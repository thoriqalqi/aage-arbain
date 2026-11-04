"""Pindahkan isi SQLite lokal ke Postgres pada DATABASE_URL, dengan ID dan rantai hash Ledger tetap utuh.

    python scripts/pindah_ke_postgres.py --cek                     # hanya periksa sumber dan target
    python scripts/pindah_ke_postgres.py                           # pindahkan aage.db
    python scripts/pindah_ke_postgres.py --tambah-demo             # lalu tambahkan katalog, dokumen, dan akun demo

Sumber dibuka hanya-baca dan tidak diubah. Semua baris disalin dalam satu transaksi: bila jumlah baris atau rantai hash
tidak cocok, transaksi dibatalkan dan target tetap kosong. Target yang sudah berisi ditolak. Isi DATABASE_URL tidak dicetak.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import DateTime, create_engine, func, insert, select, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from aage import clock, ledger_chain, models, settings_store  # noqa: E402,F401  (registrasi tabel)
from aage.db import IS_POSTGRES, Base, SessionLocal, engine, init_db  # noqa: E402

UKURAN_BATCH = 200


def _baris(sumber, table) -> list[dict]:
    kolom_waktu = [c.name for c in table.columns if isinstance(c.type, DateTime)]
    hasil = []
    for row in sumber.execute(select(table)).mappings():
        d = dict(row)
        for k in kolom_waktu:
            d[k] = clock.aware(d[k])  # SQLite menyimpan UTC tanpa zona
        hasil.append(d)
    return hasil


def _jumlah(conn, table) -> int:
    return conn.scalar(select(func.count()).select_from(table)) or 0


def _setel_sequence(conn, table) -> None:
    pk = list(table.primary_key.columns)
    if len(pk) != 1 or pk[0].type.python_type is not int:
        return
    terbesar = conn.scalar(select(func.max(pk[0])))
    urut = conn.scalar(text("SELECT pg_get_serial_sequence(:t, :c)"), {"t": table.name, "c": pk[0].name})
    if urut and terbesar is not None:
        conn.execute(text("SELECT setval(:s, :n)"), {"s": urut, "n": terbesar})


def pindahkan(sumber_path: Path, hanya_cek: bool) -> None:
    src = create_engine(f"sqlite:///file:{sumber_path.as_posix()}?mode=ro&uri=true")
    with Session(src) as s:
        awal = ledger_chain.verify(s)
    print(f"Sumber: {sumber_path.name}, rantai utuh: {awal['utuh']}, {awal['jumlah_event']} event")
    if not awal["utuh"]:
        sys.exit(f"Rantai hash sumber tidak utuh: {awal['masalah']}")

    init_db()
    tables = Base.metadata.sorted_tables
    with engine.connect() as conn:
        terisi = {t.name: n for t in tables if (n := _jumlah(conn, t))}
    if terisi:
        sys.exit(f"Target sudah berisi data, pemindahan dibatalkan: {terisi}")
    if hanya_cek:
        print(f"Target kosong dan siap, {len(tables)} tabel.")
        return

    with src.connect() as sumber, engine.begin() as conn:
        for t in tables:
            baris = _baris(sumber, t)
            for i in range(0, len(baris), UKURAN_BATCH):
                conn.execute(insert(t), baris[i:i + UKURAN_BATCH])
            if _jumlah(conn, t) != len(baris):
                raise RuntimeError(f"Jumlah baris {t.name} tidak cocok; transaksi dibatalkan.")
            _setel_sequence(conn, t)
            if baris:
                print(f"  {t.name}: {len(baris)} baris")
        with Session(bind=conn) as s:
            akhir = ledger_chain.verify(s)
        if not akhir["utuh"] or akhir["hash_terakhir"] != awal["hash_terakhir"]:
            raise RuntimeError(f"Rantai hash di target tidak cocok; transaksi dibatalkan: {akhir['masalah']}")
    print(f"Pindah selesai, rantai hash cocok: {akhir['diperiksa']} event.")


def tambah_demo() -> None:
    from aage.seed import seed_base

    with SessionLocal() as db:
        seed_base(db)
        hasil = ledger_chain.verify(db)
    print(f"Data demo ditambahkan. Rantai utuh: {hasil['utuh']}, {hasil['jumlah_event']} event.")
    with engine.connect() as conn:
        for t in Base.metadata.sorted_tables:
            print(f"  {t.name}: {_jumlah(conn, t)}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sumber", default="aage.db")
    p.add_argument("--cek", action="store_true", help="periksa saja, tidak menyalin apa pun")
    p.add_argument("--tambah-demo", action="store_true", help="setelah pindah, tambahkan katalog, dokumen, dan akun demo")
    args = p.parse_args()
    if not IS_POSTGRES:
        sys.exit("DATABASE_URL harus mengarah ke Postgres (postgresql+psycopg://...).")
    print(f"Target: Postgres di {engine.url.host}")
    pindahkan(Path(args.sumber), args.cek)
    if args.tambah_demo and not args.cek:
        tambah_demo()


if __name__ == "__main__":
    main()
