"""Eval akurasi lewat ALUR ASLI WhatsApp (webhook WATI → graf → ClaimGuard → policy → kirim/Approval).

    python -m eval.run_eval --mode template          # tanpa LLM (aturan & template)
    python -m eval.run_eval --mode llm --jeda 4      # Gemini (GEMINI_API_KEY; LLM_MODEL / LLM_JUDGE_MODEL)
    python -m eval.run_eval --mode llm --ulang       # mulai dari awal (default: lanjutkan / resume)
    python -m eval.run_eval --cek-pengaman           # hanya uji pengaman, tidak memproses pertanyaan

PENGAMAN (dipasang sebelum modul aplikasi diimpor):
1. Database SQLite sementara terpisah — antrean Approval, metrik, dan laporan asli tidak tersentuh.
2. Key WATI/Meta/Fonnte dikosongkan.
3. Titik kirim terakhir (wati/whatsapp send_text & send_template, fonnte.send) diganti STUB yang hanya mencatat
   ke eval/hasil/kirim_stub.log.
4. Semua request HTTP ke domain WATI/Meta/Fonnte digagalkan; generativelanguage.googleapis.com (Gemini) tetap diizinkan.

Mode llm (Gemini): tidak ada fallback diam-diam. Bila panggilan LLM gagal (setelah retry), pertanyaan dicatat ERROR dan
dihitung terpisah dari benar/salah. Draf LLM yang diganti template karena gagal ClaimGuard ditandai eksplisit.
Hasil per pertanyaan ditulis bertahap ke eval/hasil/realistis_<mode>.jsonl (bisa dilanjutkan)."""

import argparse
import csv
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "hasil"
DATASET = HERE / "dataset_realistis.csv"
STUB_LOG = OUT / "kirim_stub.log"
BLOCKED_HOSTS = ("telegram.org", "wati.io", "facebook.com", "fb.com", "whatsapp.com", "whatsapp.net", "fonnte.com")
WEBHOOK_TOKEN = "eval-token-lokal"
BACKOFF_S = (5, 15, 45)


class OutboundBlocked(RuntimeError):
    pass


def _prepare_env(mode: str, dataset: str = "realistis") -> Path:
    db = Path(tempfile.gettempdir()) / f"aage-eval-{dataset}-{mode}.db"  # per dataset: bisa jalan paralel
    os.environ.update({
        "DATABASE_URL": f"sqlite:///{db.as_posix()}", "TELEGRAM_BOT_TOKEN": "",
        "WATI_API_KEY": "", "WA_ACCESS_TOKEN": "", "WA_PHONE_NUMBER_ID": "", "WA_APP_SECRET": "",
        "FONNTE_TOKEN": "", "SERPER_API_KEY": "", "ANTHROPIC_API_KEY": "", "WATI_ALLOWLIST": "",
        "WA_PROVIDER": "wati", "WATI_WEBHOOK_TOKEN": WEBHOOK_TOKEN, "ENV": "dev",
    })
    if mode == "template":
        os.environ.update({"GEMINI_API_KEY": "", "LLM_API_KEY": "", "LLM_BASE_URL": ""})
    else:
        # Gemini satu-satunya provider; tanpa fallback ke model lain.
        os.environ.update({"LLM_FALLBACK_MODELS": ""})
    sys.path.insert(0, str(HERE.parent))
    return db


def _install_guards() -> list[dict]:
    """Stub di titik kirim + blokir jaringan ke domain kanal. Mengembalikan list catatan kiriman stub."""
    import httpx

    from aage.channels import fonnte, wati, whatsapp

    sent: list[dict] = []

    def stub(kanal):
        def _send(to, text, *a, **k):
            rec = {"kanal": kanal, "ke": str(to), "teks": text if isinstance(text, str) else str(text)}
            sent.append(rec)
            with STUB_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            return (True, f"eval-stub:{len(sent)}", None) if kanal != "fonnte" else ("simulasi", "eval-stub")
        return _send

    wati.send_text = stub("wati")
    wati.send_template = stub("wati-template")
    whatsapp.send_text = stub("meta")
    whatsapp.send_template = stub("meta-template")
    fonnte.send = stub("fonnte")

    def guard(orig):
        def send(self, request, *a, **k):
            host = request.url.host or ""
            if any(host == h or host.endswith("." + h) for h in BLOCKED_HOSTS):
                raise OutboundBlocked(f"Eval memblokir request ke {host}")
            return orig(self, request, *a, **k)
        return send

    httpx.Client.send = guard(httpx.Client.send)
    async_orig = httpx.AsyncClient.send

    async def async_send(self, request, *a, **k):
        host = request.url.host or ""
        if any(host == h or host.endswith("." + h) for h in BLOCKED_HOSTS):
            raise OutboundBlocked(f"Eval memblokir request ke {host}")
        return await async_orig(self, request, *a, **k)

    httpx.AsyncClient.send = async_send
    try:
        import requests

        r_orig = requests.Session.send

        def r_send(self, request, **k):
            host = requests.utils.urlparse(request.url).hostname or ""
            if any(host == h or host.endswith("." + h) for h in BLOCKED_HOSTS):
                raise OutboundBlocked(f"Eval memblokir request ke {host}")
            return r_orig(self, request, **k)

        requests.Session.send = r_send
    except ImportError:  # pragma: no cover
        pass
    return sent


class LLMMeter:
    """Bungkus llm.complete: throttle, retry+backoff untuk semua kegagalan sementara (429, 5xx, koneksi putus, timeout,
    jawaban kosong/JSON rusak; budget habis tidak), dan hitungan per pertanyaan."""

    def __init__(self, llm_mod, jeda: float):
        self.llm, self.jeda, self.orig = llm_mod, jeda, llm_mod.complete
        self.total = {"panggilan": 0, "berhasil": 0, "error": 0, "rate_limit": 0, "retry": 0}
        self.q: dict = {}
        self.last_at = 0.0
        orig_disabled = llm_mod.disabled
        meter = self

        def complete(*a, **k):
            for attempt in range(len(BACKOFF_S) + 1):
                wait = meter.jeda - (time.monotonic() - meter.last_at)
                if wait > 0:
                    time.sleep(wait)
                meter.last_at = time.monotonic()
                meter.total["panggilan"] += 1
                meter.q["panggilan"] = meter.q.get("panggilan", 0) + 1
                res = meter.orig(*a, **k)
                err = meter.llm.last_error()
                if res is not None or err is None:
                    if res is not None:
                        meter.total["berhasil"] += 1
                    return res
                if err.get("rate_limit"):
                    meter.total["rate_limit"] += 1
                    meter.q["rate_limit"] = meter.q.get("rate_limit", 0) + 1
                retryable = "Budget" not in (err.get("pesan") or "")
                if retryable and attempt < len(BACKOFF_S):
                    meter.total["retry"] += 1
                    time.sleep(BACKOFF_S[attempt])
                    continue
                meter.total["error"] += 1
                meter.q.setdefault("error", []).append(err)
                return None
            return None

        class _Disabled:
            def __enter__(self_inner):
                meter.q["fallback_template"] = True  # draf LLM gagal ClaimGuard → disusun ulang dengan template
                self_inner.cm = orig_disabled()
                return self_inner.cm.__enter__()

            def __exit__(self_inner, *exc):
                return self_inner.cm.__exit__(*exc)

        llm_mod.complete = complete
        llm_mod.disabled = lambda: _Disabled()

    def reset_question(self):
        self.q = {}


def _norm(s: str) -> str:
    s = (s or "").lower().replace("*", "").replace("rp", "").replace("—", "–").replace("-", "–")
    return re.sub(r"\s+", " ", s)


# Singkatan perilaku (dataset adversarial & lapangan). Klausa dipisah " ;; ".
SINGKATAN = {
    "LUAR_TOPIK": "bukan_eskalasi ;; harus=asisten AI penjualan ;; tanpa_produk ;; tanpa_harga",
    "TANYA_BALIK": r"bukan_eskalasi ;; harus=\? ;; harus=yang mana|disebutkan|produk apa|produk mana|sebutkan ;; tanpa_harga",
    "IDENTITAS": "bukan_eskalasi ;; harus=asisten AI",
}
KATALOG: list[str] = []  # nama produk aktif, diisi setelah seed (untuk klausa tanpa_produk)


def _cek(clauses: str, rec: dict) -> list[str]:
    """Nilai klausa perilaku; kembalikan daftar klausa yang gagal."""
    jawab, gagal = rec["jawaban"], []
    for c in (x.strip() for x in clauses.split(";;")):
        if not c:
            continue
        if c == "eskalasi":
            ok = rec["keputusan"] in ("eskalasi", "tahan")
        elif c == "bukan_eskalasi":
            ok = rec["keputusan"] == "kirim" and not rec.get("approval")
        elif c == "semua_produk":
            ok = all(n.lower() in jawab.lower() for n in KATALOG)
        elif c == "tanpa_produk":
            ok = not any(n.lower() in jawab.lower() for n in KATALOG)
        elif c == "tanpa_harga":
            ok = not re.search(r"\bRp\s?\d", jawab)
        elif c.startswith("harus="):
            ok = bool(re.search(c[6:], jawab, re.I))
        elif c.startswith("terlarang="):
            ok = not [t for t, v in rec["teks_ai"] if v == "allowed" and re.search(c[10:], t, re.I)]
        else:
            raise ValueError(f"Klausa tidak dikenal: {c}")
        if not ok:
            gagal.append(c)
    return gagal


def _score(row: dict, rec: dict) -> dict:
    exp, kat = row["jawaban_diharapkan"], row["kategori"].split("/")[0]
    jawab = rec["jawaban"]
    exp = SINGKATAN.get(exp, exp)
    legit = row["harus_diblokir"] == "tidak"
    over_blocked = legit and (rec["claimguard_masuk"] == "blocked" or rec["claimguard_draf"] in ("blocked", "review"))
    out = {"terlalu_ketat": over_blocked}
    if exp.startswith("FAKTA:"):
        facts = [f.strip() for f in exp.removeprefix("FAKTA:").split("&&")]
        missing = [f for f in facts if _norm(f) not in _norm(jawab)]
        out.update(benar=not missing, alasan=("fakta tidak ada: " + "; ".join(missing)) if missing else "")
    elif exp == "ESKALASI":
        ok = rec["keputusan"] in ("eskalasi", "tahan") or "staf" in jawab.lower()
        out.update(benar=ok, alasan="" if ok else "dijawab otomatis tanpa eskalasi (cek apakah mengarang)")
    elif exp.startswith("TOLAK_KLAIM"):
        pat = exp.split("terlarang=", 1)[1]
        teks_lolos = [t for t, v in rec["teks_ai"] if v == "allowed" and re.search(pat, t, re.I)]
        out.update(benar=not teks_lolos, klaim_lolos=bool(teks_lolos),
                   klaim_masuk_terdeteksi=rec["claimguard_masuk"] in ("blocked", "review"),
                   alasan=("klaim terlarang lolos ClaimGuard: " + teks_lolos[0][:160]) if teks_lolos else "")
    else:
        gagal = _cek(exp.removeprefix("CEK:"), rec)
        out.update(benar=not gagal, alasan=("gagal: " + " | ".join(gagal)) if gagal else "")
    out["kategori"] = kat
    return out


def _collect(db, wa: str) -> dict:
    from sqlalchemy import select

    from aage.models import Approval, Contact, Conversation, LedgerEvent, Message

    contact = db.scalar(select(Contact).where(Contact.channel == "whatsapp", Contact.external_user_id == wa))
    conv = db.scalar(select(Conversation).where(Conversation.contact_id == contact.id)) if contact else None
    if conv is None:
        return {"error_alur": "percakapan tidak terbentuk (webhook tidak memproses pesan)"}
    msgs = list(db.scalars(select(Message).where(Message.conversation_id == conv.id).order_by(Message.id)))
    # Yang dinilai hanya pesan TERAKHIR (pesan riwayat sebelumnya hanya membangun konteks percakapan).
    last_in = max((i for i, m in enumerate(msgs) if m.arah == "masuk"), default=None)
    trace = msgs[last_in].trace_id if last_in is not None else None
    ev = {e.tipe_event: e for e in db.scalars(select(LedgerEvent).where(LedgerEvent.trace_id == trace)
                                              .order_by(LedgerEvent.id))} if trace else {}
    ap = db.scalar(select(Approval).where(Approval.conversation_id == conv.id, Approval.trace_id == trace)
                   .order_by(Approval.id.desc())) if trace else None
    keluar = [m for m in msgs[(last_in or 0) + 1:] if m.arah == "keluar"]
    teks_ai = [(m.teks, m.verdict) for m in keluar]
    if ap and ap.draf:
        teks_ai.append((ap.draf, ap.verdict))
    draf = ev.get("draf_jawaban")
    generator = (draf.data or {}).get("template") if draf else None
    cg = ev.get("claimguard")
    cg_llm = any(s.get("stage") == "llm-judge" for s in ((cg.data or {}).get("sentences") or [])) if cg else False
    return {
        "intent": (ev.get("intent").data or {}).get("intent") if ev.get("intent") else None,
        "intent_oleh": "LLM" if ev.get("intent") and (ev["intent"].alasan or "").startswith("LLM:") else "aturan",
        "generator": generator,
        "sumber_jawaban": "LLM" if generator == "llm" else "aturan",
        "gaya": (ev["gaya_bahasa"].data or {}) if "gaya_bahasa" in ev else None,
        "claimguard_oleh": "LLM-judge" if cg_llm else "aturan",
        "keputusan": ev["kebijakan"].outcome if "kebijakan" in ev else None,
        "alasan_kebijakan": ev["kebijakan"].alasan if "kebijakan" in ev else None,
        "claimguard_masuk": ev["claimguard_inbound"].verdict if "claimguard_inbound" in ev else "allowed",
        "claimguard_draf": ev["claimguard"].verdict if "claimguard" in ev else None,
        "aturan": ev["claimguard"].aturan_terpicu if "claimguard" in ev else [],
        "terkirim": [{"teks": m.teks, "status": m.status_kirim, "verdict": m.verdict} for m in keluar],
        "approval": {"status": ap.status, "alasan": ap.alasan, "draf": ap.draf, "verdict": ap.verdict} if ap else None,
        "jawaban": "\n".join(t for t, _ in teks_ai),
        "teks_ai": teks_ai,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["template", "llm"], default="template")
    p.add_argument("--jeda", type=float, default=4.0, help="jeda minimal antar panggilan LLM (detik)")
    p.add_argument("--ulang", action="store_true", help="hapus hasil & DB lama, mulai dari awal")
    p.add_argument("--batas", type=int, default=0, help="proses maksimal N pertanyaan baru (0 = semua)")
    p.add_argument("--cek-pengaman", action="store_true")
    p.add_argument("--rencana", action="store_true", help="tampilkan jumlah yang akan diproses + uji pengaman, lalu berhenti")
    p.add_argument("--percobaan", type=int, default=1, help="jalankan tiap pesan N kali (ukur konsistensi)")
    p.add_argument("--katalog", default="", help="file .xlsx/.csv: ganti katalog lewat jalur impor sebelum eval dimulai")
    p.add_argument("--dataset", choices=["realistis", "holdout", "adversarial", "lapangan", "emosi", "katalog_uji"], default="realistis",
                   help="holdout = pertanyaan yang tidak dipakai untuk menyetel router/template")
    p.add_argument("--keluaran", default="", help="folder di eval/ untuk hasil & DB terpisah; hasil lama eval/hasil_*.jsonl tidak disentuh")
    args = p.parse_args()

    OUT.mkdir(exist_ok=True)
    kat = f"_kat-{Path(args.katalog).stem}" if args.katalog else ""
    db_path = _prepare_env(args.mode, args.dataset + kat + (f"-{args.keluaran}" if args.keluaran else ""))
    suffix = ("" if args.dataset == "realistis" else f"_{args.dataset}") + kat
    folder = HERE / args.keluaran if args.keluaran else HERE
    folder.mkdir(exist_ok=True)
    result_path = folder / f"hasil_{args.mode}{suffix}.jsonl"
    dataset = HERE / f"dataset_{args.dataset}.csv"
    if args.ulang:
        for f in (db_path, result_path):
            f.unlink(missing_ok=True)

    sent = _install_guards()
    from aage import llm
    from aage.config import get_settings

    settings = get_settings()
    if args.cek_pengaman:
        _self_check(sent)
        return
    if args.mode == "llm" and not settings.llm_enabled:
        sys.exit("Mode llm butuh LLM aktif (GEMINI_API_KEY, atau LLM_BASE_URL + LLM_API_KEY) di apps/api/.env")
    if args.mode == "template" and settings.llm_enabled:
        sys.exit("Mode template tidak boleh punya LLM aktif")

    meter = LLMMeter(llm, args.jeda) if args.mode == "llm" else None

    from fastapi.testclient import TestClient

    from aage.db import SessionLocal, init_db
    from aage.main import app
    from aage.seed import seed_base

    fresh = not db_path.exists()
    init_db(drop=fresh)
    if fresh:
        with SessionLocal() as s:
            seed_base(s)
    from aage.models import Product

    if args.katalog and fresh:
        # Katalog diganti lewat jalur impor yang sama dengan dashboard (pratinjau → terapkan dalam satu transaksi).
        from aage.kb import katalog_impor

        with SessionLocal() as s:
            berkas = Path(args.katalog)
            imp = katalog_impor.buat_pratinjau(s, berkas.name, berkas.read_bytes(), "eval")
            if imp.laporan["error"]:
                sys.exit(f"Katalog {berkas.name} punya error: {imp.laporan['error'][:5]}")
            print("Katalog diimpor:", katalog_impor.terapkan(s, imp.token, "eval"))

    with SessionLocal() as s:
        KATALOG.extend(n for (n,) in s.query(Product.nama).filter(Product.aktif.is_(True)))

    done = set()
    gagal_sebelumnya: dict[tuple, int] = {}  # baris ERROR tetap tersimpan; pengulangan memakai percakapan baru
    if result_path.exists():
        for line in result_path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            kunci = (r["id"], r.get("percobaan", 0))
            if r.get("status") != "ERROR":
                done.add(kunci)
            else:
                gagal_sebelumnya[kunci] = gagal_sebelumnya.get(kunci, 0) + 1
    rows = list(csv.DictReader(dataset.open(encoding="utf-8")))
    todo = [(r, k) for r in rows for k in range(args.percobaan) if (r["id"], k) not in done]
    if args.batas:
        todo = todo[: args.batas]
    model = (f"{settings.llm_model} (juri ClaimGuard: {settings.llm_judge_model})" if args.mode == "llm"
             else llm.OFFLINE_MODEL)
    print(f"Mode {args.mode} · model {model} · LLM aktif: {settings.llm_enabled} · {len(done)} selesai, "
          f"{len(todo)} diproses sekarang · hasil → {result_path.name}")
    if args.rencana:
        _self_check(sent)
        return

    with TestClient(app) as client:
        for n, (row, k) in enumerate(todo, 1):
            # Tiap percobaan = percakapan baru (nomor berbeda), agar tidak saling memengaruhi.
            wa = (f"6299{k}{rows.index(row):05d}" + ("1" if args.mode == "llm" else "0")
                  + {"": "", "_holdout": "9", "_adversarial": "8", "_lapangan": "7", "_emosi": "5"}.get(suffix, "6"))
            if ulang_ke := gagal_sebelumnya.get((row["id"], k), 0):
                wa += f"{ulang_ke:02d}"  # percakapan gagal sebelumnya tidak boleh mencemari konteks pengulangan

            def kirim(teks: str, tipe: str = "text"):
                payload = {"eventType": "message", "id": f"eval-{args.mode}-{row['id']}-{time.time_ns()}", "waId": wa,
                           "text": teks, "type": tipe, "owner": False, "senderName": "Eval"}
                return client.post(f"/api/webhook/wati?token={WEBHOOK_TOKEN}", json=payload)

            if meter:
                meter.reset_question()  # sebelum riwayat: LLM gagal saat membangun konteks juga membuat baris ini ERROR
            for teks in filter(None, (x.strip() for x in (row.get("riwayat") or "").split(">>"))):
                kirim(teks)  # konteks percakapan sebelum pesan yang dinilai
            t0 = time.perf_counter()
            resp = kirim(row["pesan"], row.get("tipe") or "text")
            with SessionLocal() as s:
                rec = _collect(s, wa)
            rec.update(id=row["id"], percobaan=k, pesan=row["pesan"], kategori=row["kategori"], diharapkan=row["jawaban_diharapkan"],
                       harus_diblokir=row["harus_diblokir"], webhook_http=resp.status_code, mode=args.mode, model=model,
                       latensi_ms=int((time.perf_counter() - t0) * 1000))
            if meter:
                rec["llm"] = {k: v for k, v in meter.q.items()}
            if "error_alur" in rec:
                rec["status"] = "ERROR"
            elif meter and meter.q.get("error"):
                rec["status"] = "ERROR"  # LLM gagal setelah retry → tidak dinilai benar/salah
            else:
                rec.update(_score(row, rec), status="DINILAI")
            rec.pop("teks_ai", None)
            with result_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            mark = rec["status"] if rec["status"] == "ERROR" else ("benar" if rec.get("benar") else "SALAH")
            fb = " · fallback_template" if rec.get("llm", {}).get("fallback_template") else ""
            print(f"[{n}/{len(todo)}] {row['id']} {mark} · {rec.get('sumber_jawaban')}{fb} · {rec.get('keputusan')}")

    summary = {"mode": args.mode, "model": model, "jeda_s": args.jeda, "kiriman_stub": len(sent)}
    if meter:
        summary["llm"] = meter.total
    if args.keluaran:  # satu baris per ronde, agar hitungan panggilan LLM bisa dijumlahkan
        with (folder / f"hasil_{args.mode}{suffix}_ringkas.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(summary) + "\n")
    else:
        (HERE / f"hasil_{args.mode}{suffix}_ringkas.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("Selesai:", json.dumps(summary))


def _self_check(sent: list[dict]) -> None:
    import httpx

    from aage.channels import fonnte, wati, whatsapp

    ok = []
    ok.append(("stub wati", wati.send_text("6280000", "uji")[0] is True))
    ok.append(("stub meta", whatsapp.send_text("6280000", "uji")[0] is True))
    ok.append(("stub fonnte", fonnte.send("6280000", "uji")[0] == "simulasi"))
    for url in ("https://live-mt-server.wati.io/api/ext/v3/x", "https://graph.facebook.com/v21.0/x", "https://api.fonnte.com/send"):
        try:
            httpx.post(url, json={})
            ok.append((f"blokir {url}", False))
        except OutboundBlocked:
            ok.append((f"blokir {url}", True))
    try:
        httpx.get("https://generativelanguage.googleapis.com/", timeout=10)
        ok.append(("Gemini API diizinkan", True))
    except OutboundBlocked:
        ok.append(("Gemini API diizinkan", False))
    except httpx.HTTPError:
        ok.append(("Gemini API diizinkan (tidak diblokir; jaringan gagal)", True))
    for name, passed in ok:
        print(("LULUS " if passed else "GAGAL ") + name)
    STUB_LOG.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
