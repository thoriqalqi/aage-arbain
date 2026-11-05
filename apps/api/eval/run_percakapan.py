"""Eval percakapan multi-giliran (sales). Tiap skenario = satu kontak baru; giliran dijalankan berurutan lewat alur asli
(handle_inbound). Klausa cek memakai klausa eval/run_eval.py, ditambah klausa khusus percakapan:

Kolom opsional: kanal (default webchat), pengguna (default mt-<skenario>). Pesan "@nomor=<HP>" mensimulasikan
tombol "Bagikan nomor HP" di Telegram.

    tahap=<nama>      tahap percakapan setelah giliran ini (lihat agents/tahap.py)
    sinyal=<nama>     sinyal pembeli terdeteksi pada giliran ini
    satu_ajakan       paling banyak satu ajakan (tanda tanya + baris "Balas *")

Selalu aktif di tiap giliran: tanpa_karangan — tidak ada kelangkaan, testimoni, atau diskon khusus yang dikarang.

    python -m eval.run_percakapan
    python -m eval.run_percakapan --mode llm --keluaran hasil_fase4   # skenario yang LLM-nya gagal diulang pada run berikutnya
"""

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from itertools import groupby
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATASET = HERE / "dataset_percakapan.csv"
OUT = HERE / "hasil_percakapan.jsonl"
KHUSUS = {"tahap", "sinyal", "satu_ajakan"}
KARANGAN = re.compile(r"kehabisan|stok (?:sisa|terbatas)|buruan|diskon khusus|hari ini saja|testimoni|"
                      r"ribuan (?:apotek|pelanggan)|sudah (?:terbukti|dipakai) (?:ribuan|banyak)", re.I)


def _ajakan(teks: str) -> int:
    return teks.count("?") + len(re.findall(r"^\s*Balas \*", teks, re.M))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["template", "llm"], default="template")
    p.add_argument("--jeda", type=float, default=4.0, help="jeda minimal antar panggilan LLM (detik)")
    p.add_argument("--keluaran", default="", help="folder di eval/ untuk hasil terpisah; skenario yang sudah dinilai dilewati")
    args = p.parse_args()

    from eval import run_eval

    # DB sementara terpisah, tanpa kiriman nyata; mode template mematikan LLM.
    run_eval._prepare_env(args.mode, "percakapan" + (f"-{args.keluaran}" if args.keluaran else ""))

    from sqlalchemy import select

    from aage import llm
    from aage.agents.graph import handle_inbound
    from aage.channels.base import TEKS_NOMOR_DIBAGIKAN
    from aage.config import get_settings
    from aage.db import SessionLocal, init_db
    from aage.models import Conversation, LedgerEvent, Product
    from aage import settings_store
    from aage.seed import seed_base

    meter = None
    if args.mode == "llm":
        if not get_settings().llm_enabled:
            sys.exit("Mode llm butuh LLM aktif di apps/api/.env")
        run_eval.OUT.mkdir(exist_ok=True)
        run_eval._install_guards()
        meter = run_eval.LLMMeter(llm, args.jeda)

    init_db(drop=True)
    with SessionLocal() as s:
        seed_base(s)
        settings_store.pasang_mode_data(s, "demo", "eval")  # dataset bergantung pada katalog simulasi
        run_eval.KATALOG[:] = [n for (n,) in s.execute(select(Product.nama).where(Product.aktif.is_(True)))]

    keluaran = HERE / args.keluaran / "hasil_llm_percakapan.jsonl" if args.keluaran else None
    selesai = set()
    if keluaran:
        keluaran.parent.mkdir(exist_ok=True)
        if keluaran.exists():
            selesai = {r["skenario"] for r in map(json.loads, keluaran.read_text(encoding="utf-8").splitlines())
                       if r.get("status") != "ERROR"}

    rows = list(csv.DictReader(DATASET.open(encoding="utf-8")))
    hasil = []
    total = {"panggilan": 0, "berhasil": 0, "error": 0, "rate_limit": 0, "retry": 0}
    with SessionLocal() as db:
        for sid, giliran in groupby(rows, key=lambda r: r["skenario"]):
            if sid in selesai:
                continue
            if meter:
                meter.reset_question()
            bagian = []
            for row in giliran:
                kanal = row.get("kanal") or "webchat"
                pengguna = row.get("pengguna") or f"mt-{sid}"
                pesan, telepon = row["pesan"], pengguna if kanal == "whatsapp" else None
                if pesan.startswith("@nomor="):  # simulasi tombol "Bagikan nomor HP" Telegram (nomor milik pengirim)
                    pesan, telepon = TEKS_NOMOR_DIBAGIKAN, pesan.split("=", 1)[1]
                r = handle_inbound(db, channel=kanal, external_user_id=pengguna, text=pesan, telepon=telepon)
                conv = db.get(Conversation, r.conversation_id)
                jawab = " ".join(m.teks for m in r.replies)
                tahap, sinyal = conv.konteks.get("tahap"), conv.konteks.get("sinyal") or []

                clauses = [c.strip() for c in row["cek"].split(";;") if c.strip()]
                khusus = [c for c in clauses if c.split("=", 1)[0] in KHUSUS]
                umum = [c for c in clauses if c not in khusus]
                rec = {"jawaban": jawab, "keputusan": r.decision, "approval": r.approval_id,
                       "teks_ai": [(m.teks, m.verdict) for m in r.replies]}
                gagal = run_eval._cek(";;".join(umum), rec) if umum else []
                for c in khusus:
                    if c == "satu_ajakan":
                        ok = _ajakan(jawab) <= 1
                    elif c.startswith("tahap="):
                        ok = tahap == c[len("tahap="):]
                    elif c.startswith("sinyal="):
                        ok = c[len("sinyal="):] in sinyal
                    else:
                        raise ValueError(f"Klausa khusus tidak dikenal: {c}")
                    if not ok:
                        gagal.append(f"{c} (tahap={tahap}, sinyal={sinyal})")
                karangan = KARANGAN.search(jawab)
                if karangan:
                    gagal.append(f"tanpa_karangan: '{karangan.group(0)}'")

                ev = db.scalar(select(LedgerEvent).where(LedgerEvent.trace_id == r.trace_id, LedgerEvent.tipe_event == "gaya_bahasa")
                               .order_by(LedgerEvent.id.desc()))
                bagian.append({"skenario": sid, "giliran": int(row["giliran"]), "pesan": row["pesan"], "jawaban": jawab,
                               "intent": r.intent, "keputusan": r.decision, "tahap": tahap, "sinyal": sinyal,
                               "ajakan": _ajakan(jawab), "karangan": bool(karangan), "gagal": gagal,
                               "benar": not gagal, "cek": row["cek"], "catatan": row["catatan"],
                               "gaya": (ev.data or {}) if ev else None})
            if meter:  # LLM gagal di giliran mana pun → satu skenario tidak dinilai; diulang utuh pada run berikutnya
                err = meter.q.get("error")
                for h in bagian:
                    h["status"] = "ERROR" if err else "DINILAI"
                    h["llm"] = {"error": err} if err else {}
            hasil += bagian
            if keluaran:
                with keluaran.open("a", encoding="utf-8") as f:
                    f.write("".join(json.dumps(h, ensure_ascii=False) + "\n" for h in bagian))

    if keluaran:
        with (keluaran.parent / "hasil_llm_percakapan_ringkas.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"mode": args.mode, "llm": meter.total if meter else total}) + "\n")
    else:
        OUT.write_text("".join(json.dumps(h, ensure_ascii=False) + "\n" for h in hasil), encoding="utf-8")
    _ringkas(hasil)


def _ringkas(hasil: list[dict]) -> None:
    per = defaultdict(list)
    for h in hasil:
        per[h["skenario"]].append(h)
    lolos_skenario = sum(all(x["benar"] for x in v) for v in per.values())
    print(f"Skenario lolos: {lolos_skenario}/{len(per)} · giliran lolos: {sum(h['benar'] for h in hasil)}/{len(hasil)}")
    menuju_order = [v for v in per.values() if any("tahap=closing" in x["cek"] for x in v)]
    print(f"Bergerak ke closing: {sum(all(x['benar'] for x in v) for v in menuju_order)}/{len(menuju_order)} skenario")
    print(f"Tanpa karangan: {sum(not h['karangan'] for h in hasil)}/{len(hasil)} giliran")
    ajakan = [h for h in hasil if "satu_ajakan" in h["cek"]]
    print(f"Satu ajakan: {sum(h['ajakan'] <= 1 for h in ajakan)}/{len(ajakan)} giliran yang dicek")
    print()
    for sid, v in per.items():
        status = "LOLOS" if all(x["benar"] for x in v) else "GAGAL"
        print(f"{sid} {status}")
        for x in v:
            if not x["benar"]:
                print(f"   giliran {x['giliran']} {x['pesan'][:55]!r} → {x['gagal']}")


if __name__ == "__main__":
    main()
