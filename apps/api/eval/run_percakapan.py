"""Eval percakapan multi-giliran (sales). Tiap skenario = satu kontak baru; giliran dijalankan berurutan lewat alur asli
(handle_inbound). Klausa cek memakai klausa eval/run_eval.py, ditambah klausa khusus percakapan:

Kolom opsional: kanal (default webchat), pengguna (default mt-<skenario>). Pesan "@nomor=<HP>" mensimulasikan
tombol "Bagikan nomor HP" di Telegram.

    tahap=<nama>      tahap percakapan setelah giliran ini (lihat agents/tahap.py)
    sinyal=<nama>     sinyal pembeli terdeteksi pada giliran ini
    satu_ajakan       paling banyak satu ajakan (tanda tanya + baris "Balas *")

Selalu aktif di tiap giliran: tanpa_karangan — tidak ada kelangkaan, testimoni, atau diskon khusus yang dikarang.

    python -m eval.run_percakapan
"""

import csv
import json
import re
from collections import defaultdict
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
    from eval import run_eval

    run_eval._prepare_env("template", "percakapan")  # DB sementara terpisah, LLM dimatikan, tanpa kiriman nyata

    from sqlalchemy import select

    from aage.agents.graph import handle_inbound
    from aage.channels.base import TEKS_NOMOR_DIBAGIKAN
    from aage.db import SessionLocal, init_db
    from aage.models import Conversation, Product
    from aage.seed import seed_base

    init_db(drop=True)
    with SessionLocal() as s:
        seed_base(s)
        run_eval.KATALOG[:] = [n for (n,) in s.execute(select(Product.nama).where(Product.aktif.is_(True)))]

    rows = list(csv.DictReader(DATASET.open(encoding="utf-8")))
    hasil = []
    with SessionLocal() as db:
        for row in rows:
            sid = row["skenario"]
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

            hasil.append({"skenario": sid, "giliran": int(row["giliran"]), "pesan": row["pesan"], "jawaban": jawab,
                          "intent": r.intent, "keputusan": r.decision, "tahap": tahap, "sinyal": sinyal,
                          "ajakan": _ajakan(jawab), "karangan": bool(karangan), "gagal": gagal,
                          "benar": not gagal, "cek": row["cek"], "catatan": row["catatan"]})

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
