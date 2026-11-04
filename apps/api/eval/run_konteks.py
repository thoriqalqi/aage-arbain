"""Eval pemahaman konteks multi-giliran (dataset_konteks.csv) lewat alur asli handle_inbound.

Klausa cek memakai klausa eval/run_eval.py, klausa khusus eval/run_percakapan.py (satu_ajakan), ditambah:

    maksud=<intent>      intent giliran ini
    profil=<nama>        profil pembeli: reseller | konsumen | lama
    produk=<nama>        produk yang sedang dirujuk (produk pertama di konteks)
    langkah=<nama>       tindakan sales giliran ini (lihat agents/tindakan.py)
    ringkasan=<teks>     teks yang harus ada di ringkasan antrean staf
    permintaan=<istilah> barang yang tercatat sebagai permintaan tak terpenuhi pada giliran ini

Baris "bagian=holdout" dihitung terpisah dan tidak boleh dipakai untuk menyetel aturan. Baris "hanya_llm=ya" dilewati di
mode template. Mode LLM memakai kuota sungguhan; skenario yang LLM-nya gagal diulang pada run berikutnya.

    python -m eval.run_konteks --keluaran hasil_kerja
    python -m eval.run_konteks --dataset luar_katalog --keluaran hasil_kerja
    python -m eval.run_konteks --mode llm --keluaran hasil_fase5
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
KHUSUS = {"maksud", "profil", "produk", "langkah", "ringkasan", "permintaan", "satu_ajakan"}


def _ajakan(teks: str) -> int:
    return teks.count("?") + len(re.findall(r"^\s*Balas \*", teks, re.M))


def _nama_produk_konteks(db, konteks: dict) -> str | None:
    from aage.models import Product

    ids = konteks.get("last_product_ids") or []
    p = db.get(Product, ids[0]) if ids else None
    return p.nama if p else None


def _nilai_khusus(c: str, *, intent, konteks, produk, jawab, ringkasan, permintaan) -> str | None:
    """Alasan gagal, atau None bila lolos."""
    if c == "satu_ajakan":
        return None if _ajakan(jawab) <= 1 else f"{c} (ajakan={_ajakan(jawab)})"
    kunci, nilai = c.split("=", 1)
    if kunci == "maksud":
        return None if intent == nilai else f"{c} (dapat {intent})"
    if kunci == "profil":
        dapat = (konteks.get("sales") or {}).get("profil")
        return None if dapat == nilai else f"{c} (dapat {dapat})"
    if kunci == "produk":
        return None if produk and nilai.lower() in produk.lower() else f"{c} (dapat {produk})"
    if kunci == "langkah":
        dapat = konteks.get("langkah")
        return None if dapat == nilai else f"{c} (dapat {dapat})"
    if kunci == "ringkasan":
        return None if nilai.lower() in (ringkasan or "").lower() else f"{c} (tidak ada di ringkasan)"
    if kunci == "permintaan":
        return None if nilai.lower() in permintaan else f"{c} (tercatat {permintaan})"
    raise ValueError(f"Klausa khusus tidak dikenal: {c}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["template", "llm"], default="template")
    p.add_argument("--jeda", type=float, default=4.0)
    p.add_argument("--dataset", choices=["konteks", "luar_katalog"], default="konteks")
    p.add_argument("--keluaran", default="", help="folder di eval/ untuk hasil; skenario yang sudah dinilai dilewati")
    args = p.parse_args()

    from eval import run_eval

    run_eval._prepare_env(args.mode, args.dataset + (f"-{args.keluaran}" if args.keluaran else ""))

    from sqlalchemy import select

    from aage import llm
    from aage.agents.graph import handle_inbound
    from aage.config import get_settings
    from aage.db import SessionLocal, init_db
    from aage.models import Approval, Conversation, PermintaanTakTerpenuhi, Product
    from aage.seed import seed_base

    if args.mode == "llm" and not get_settings().llm_enabled:
        sys.exit("Mode llm butuh LLM aktif di apps/api/.env")
    run_eval.OUT.mkdir(exist_ok=True)
    run_eval._install_guards()  # selalu: tidak ada kiriman nyata dari eval
    meter = run_eval.LLMMeter(llm, args.jeda) if args.mode == "llm" else None

    init_db(drop=True)
    with SessionLocal() as s:
        seed_base(s)
        run_eval.KATALOG[:] = [n for (n,) in s.execute(select(Product.nama).where(Product.aktif.is_(True)))]

    folder = HERE / args.keluaran if args.keluaran else HERE
    folder.mkdir(exist_ok=True)
    keluaran = folder / f"hasil_{args.mode}_{args.dataset}.jsonl"
    selesai = set()
    if keluaran.exists():
        selesai = {r["skenario"] for r in map(json.loads, keluaran.read_text(encoding="utf-8").splitlines())
                   if r.get("status") != "ERROR"}
        if not args.keluaran or args.mode == "template":  # mode template selalu dihitung ulang
            keluaran.unlink()
            selesai = set()

    rows = [r for r in csv.DictReader((HERE / f"dataset_{args.dataset}.csv").open(encoding="utf-8"))
            if args.mode == "llm" or (r.get("hanya_llm") or "").strip().lower() != "ya"]
    hasil = []
    with SessionLocal() as db:
        for sid, giliran in groupby(rows, key=lambda r: r["skenario"]):
            if sid in selesai:
                continue
            if meter:
                meter.reset_question()
            bagian = []
            for row in giliran:
                kanal = row.get("kanal") or "webchat"
                pengguna = row.get("pengguna") or f"kt-{sid}"
                r = handle_inbound(db, channel=kanal, external_user_id=pengguna, text=row["pesan"],
                                   telepon=pengguna if kanal == "whatsapp" else None)
                conv = db.get(Conversation, r.conversation_id)
                konteks = conv.konteks or {}
                jawab = " ".join(m.teks for m in r.replies)
                ap = db.get(Approval, r.approval_id) if r.approval_id else None
                clauses = [c.strip() for c in row["cek"].split(";;") if c.strip()]
                khusus = [c for c in clauses if c.split("=", 1)[0] in KHUSUS]
                umum = [c for c in clauses if c not in khusus]
                rec = {"jawaban": jawab, "keputusan": r.decision, "approval": r.approval_id,
                       "teks_ai": [(m.teks, m.verdict) for m in r.replies]}
                gagal = run_eval._cek(";;".join(umum), rec) if umum else []
                produk = _nama_produk_konteks(db, konteks)
                permintaan = [x.lower() for x in db.scalars(select(PermintaanTakTerpenuhi.istilah)
                                                            .where(PermintaanTakTerpenuhi.trace_id == r.trace_id))]
                gagal += [g for c in khusus if (g := _nilai_khusus(c, intent=r.intent, konteks=konteks, produk=produk,
                                                                   jawab=jawab, ringkasan=ap.ringkasan if ap else "",
                                                                   permintaan=permintaan))]
                bagian.append({"skenario": sid, "giliran": int(row["giliran"]), "bagian": row.get("bagian") or "dev",
                               "pesan": row["pesan"], "jawaban": jawab, "intent": r.intent, "keputusan": r.decision,
                               "profil": (konteks.get("sales") or {}).get("profil"), "produk": produk,
                               "langkah": konteks.get("langkah"), "gagal": gagal, "benar": not gagal,
                               "cek": row["cek"], "catatan": row.get("catatan") or ""})
            if meter:
                err = meter.q.get("error")
                for h in bagian:
                    h["status"] = "ERROR" if err else "DINILAI"
                    h["llm"] = {"error": err} if err else {}
            hasil += bagian
            with keluaran.open("a", encoding="utf-8") as f:
                f.write("".join(json.dumps(h, ensure_ascii=False) + "\n" for h in bagian))
    _ringkas(hasil)


def _ringkas(hasil: list[dict]) -> None:
    for nama in ("dev", "holdout"):
        v = [h for h in hasil if h["bagian"] == nama]
        per = defaultdict(list)
        for h in v:
            per[h["skenario"]].append(h)
        print(f"{nama}: giliran {sum(h['benar'] for h in v)}/{len(v)} · skenario "
              f"{sum(all(x['benar'] for x in s) for s in per.values())}/{len(per)}")
    print()
    for h in hasil:
        if not h["benar"]:
            print(f"[{h['bagian']}] {h['skenario']}#{h['giliran']} {h['pesan'][:60]!r}\n    → {h['gagal']}\n"
                  f"    jawaban: {' '.join(h['jawaban'].split())[:170]}")


if __name__ == "__main__":
    main()
