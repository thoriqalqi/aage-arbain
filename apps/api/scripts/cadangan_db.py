"""Cadangkan dan pulihkan database Postgres tanpa pg_dump.

Paket gratis Supabase tidak punya backup otomatis, jadi cadangan ini wajib dibuat sendiri. Isi cadangan: semua baris
semua tabel public dalam satu file .zip. Skema tidak ikut; skema dibuat oleh `alembic upgrade head`.

    python scripts/cadangan_db.py buat
    python scripts/cadangan_db.py periksa cadangan/db-....zip
    python scripts/cadangan_db.py pulihkan cadangan/db-....zip            (Postgres lokal)
    python scripts/cadangan_db.py pulihkan cadangan/db-....zip --konfirmasi-host <host>   (database online)

Pemulihan hanya mau mengisi tabel yang kosong. Data yang ada tidak pernah ditimpa, dan semua isi dimasukkan dalam satu
transaksi yang dibatalkan kalau hasilnya tidak sama persis dengan cadangan.

File cadangan memuat data pelanggan dan hash sandi, dan tidak terenkripsi. Jangan di-commit atau dibagikan.
"""
import argparse
import hashlib
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from aage import ledger_chain, models, settings_store  # noqa: E402,F401
from aage.config import adalah_online  # noqa: E402
from aage.db import IS_POSTGRES, Base, engine  # noqa: E402

FORMAT = 1
SSL_AMAN = {"require", "verify-ca", "verify-full"}
# Teks waktu harus sama di semua komputer. Bentuk INTERVAL tidak butuh data zona waktu di server.
ZONA_TETAP = "SET LOCAL TIME ZONE INTERVAL '+00:00' HOUR TO MINUTE"


def _kutip(nama: str) -> str:
    return '"' + nama.replace('"', '""') + '"'


def _urutan_tabel(cur) -> dict[str, list[str]]:
    """Tabel public beserta kolomnya, induk lebih dulu agar foreign key terpenuhi saat dipulihkan."""
    baris = cur.execute("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public' "
                        "AND table_name <> 'alembic_version' ORDER BY table_name, ordinal_position").fetchall()
    kolom: dict[str, list[str]] = {}
    for tabel, nama in baris:
        kolom.setdefault(tabel, []).append(nama)
    dikenal = [t.name for t in Base.metadata.sorted_tables if t.name in kolom]
    return {t: kolom[t] for t in dikenal + sorted(set(kolom) - set(dikenal))}


def _kunci_urut(cur, tabel: str, kolom: list[str]) -> str:
    pk = cur.execute("SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
                     "WHERE i.indrelid = %s::regclass AND i.indisprimary ORDER BY a.attnum", (f"public.{_kutip(tabel)}",)).fetchall()
    return ", ".join(_kutip(b[0]) for b in pk) or ", ".join(_kutip(k) for k in kolom)


def _salin_keluar(cur, tabel: str, kolom: list[str], tulis) -> tuple[int, str]:
    """Tulis isi tabel apa adanya. Baris baru di dalam nilai di-escape oleh COPY, jadi satu baris file = satu baris tabel."""
    sidik, jumlah = hashlib.sha256(), 0
    daftar = ", ".join(_kutip(k) for k in kolom)
    sql = f"COPY (SELECT {daftar} FROM public.{_kutip(tabel)} ORDER BY {_kunci_urut(cur, tabel, kolom)}) TO STDOUT"
    with cur.copy(sql) as salin:
        for potongan in salin:
            data = bytes(potongan)
            sidik.update(data)
            jumlah += data.count(b"\n")
            tulis(data)
    return jumlah, sidik.hexdigest()


def _versi_alembic(cur) -> str | None:
    if cur.execute("SELECT to_regclass('public.alembic_version')").fetchone()[0] is None:
        return None
    baris = cur.execute("SELECT version_num FROM public.alembic_version").fetchone()
    return baris[0] if baris else None


def _pesan_aman(e: Exception) -> str:
    """Pesan galat Postgres bisa memuat isi baris, jadi yang dicetak hanya jenis dan kodenya."""
    return f"{type(e).__name__} {getattr(e, 'sqlstate', '') or ''}".strip()


def buat(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    waktu = datetime.now(timezone.utc)
    tujuan = folder / f"db-{waktu:%Y%m%d-%H%M%S}.zip"
    sementara = tujuan.with_suffix(".tmp")
    manifes = {"format": FORMAT, "dibuat_pada": waktu.isoformat(timespec="seconds"), "host": engine.url.host, "tabel": {}}
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:  # satu potret data yang konsisten
        conn.exec_driver_sql("SET TRANSACTION READ ONLY")
        conn.exec_driver_sql(ZONA_TETAP)
        cur = conn.connection.driver_connection.cursor()
        manifes["alembic"] = _versi_alembic(cur)
        manifes["postgres"] = cur.execute("SHOW server_version").fetchone()[0]
        with zipfile.ZipFile(sementara, "w", zipfile.ZIP_DEFLATED) as arsip:
            for tabel, kolom in _urutan_tabel(cur).items():
                with arsip.open(f"tabel/{tabel}.copy", "w", force_zip64=True) as berkas:
                    jumlah, sidik = _salin_keluar(cur, tabel, kolom, berkas.write)
                terhitung = cur.execute(f"SELECT count(*) FROM public.{_kutip(tabel)}").fetchone()[0]
                if terhitung != jumlah:
                    sys.exit(f"{tabel}: tersalin {jumlah} baris, di database {terhitung}. Cadangan dibatalkan.")
                manifes["tabel"][tabel] = {"kolom": kolom, "baris": jumlah, "sha256": sidik}
                print(f"  {tabel}: {jumlah} baris")
            if "ledger_hashes" in manifes["tabel"]:
                terakhir = cur.execute("SELECT hash FROM public.ledger_hashes ORDER BY seq DESC LIMIT 1").fetchone()
                manifes["hash_ledger_terakhir"] = terakhir[0] if terakhir else None
            arsip.writestr("manifes.json", json.dumps(manifes, ensure_ascii=False, indent=1))
        conn.rollback()
    periksa(sementara, diam=True)
    sementara.replace(tujuan)
    print(f"Cadangan dibuat: {tujuan} ({tujuan.stat().st_size / 1024:.0f} KB), {sum(t['baris'] for t in manifes['tabel'].values())} baris.")
    print("File ini memuat data pelanggan dan hash sandi, tidak terenkripsi. Simpan di tempat aman, jangan di-commit.")
    return tujuan


def periksa(berkas: Path, diam: bool = False) -> dict:
    """Pastikan file utuh tanpa menyentuh database."""
    try:
        with zipfile.ZipFile(berkas) as arsip:
            manifes = json.loads(arsip.read("manifes.json"))
            if manifes.get("format") != FORMAT:
                sys.exit(f"Format cadangan {manifes.get('format')} tidak dikenal.")
            for tabel, info in manifes["tabel"].items():
                sidik, jumlah = hashlib.sha256(), 0
                with arsip.open(f"tabel/{tabel}.copy") as isi:
                    while potongan := isi.read(1 << 20):
                        sidik.update(potongan)
                        jumlah += potongan.count(b"\n")
                if sidik.hexdigest() != info["sha256"] or jumlah != info["baris"]:
                    sys.exit(f"Cadangan rusak: isi tabel {tabel} tidak cocok dengan manifes.")
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as e:
        sys.exit(f"Cadangan rusak: {type(e).__name__}.")
    if not diam:
        print(f"Cadangan utuh: {berkas.name}, dibuat {manifes['dibuat_pada']}, versi skema {manifes.get('alembic') or '-'}, "
              f"{len(manifes['tabel'])} tabel, {sum(t['baris'] for t in manifes['tabel'].values())} baris.")
    return manifes


def pulihkan(berkas: Path, konfirmasi_host: str) -> None:
    manifes = periksa(berkas)
    host = engine.url.host
    online = adalah_online(engine.url.render_as_string(hide_password=True))
    print(f"Target: Postgres di {host} ({'online' if online else 'lokal'})")
    if online and engine.url.query.get("sslmode") not in SSL_AMAN:
        sys.exit("Database online wajib memakai SSL: tambahkan ?sslmode=require pada DATABASE_URL.")
    if online and konfirmasi_host != host:
        sys.exit(f"Ini database online. Ulangi dengan --konfirmasi-host {host} kalau target ini memang benar.")

    with engine.connect() as conn:
        raw = conn.connection.driver_connection
        cur = raw.cursor()
        conn.exec_driver_sql(ZONA_TETAP)
        versi = _versi_alembic(cur)
        if manifes.get("alembic") and versi != manifes["alembic"]:
            sys.exit(f"Versi skema target ({versi or 'belum ada'}) berbeda dengan cadangan ({manifes['alembic']}). "
                     f"Jalankan dulu: python -m alembic upgrade {manifes['alembic']}. Tidak ada data yang diubah.")
        ada = _urutan_tabel(cur)
        beda = [t for t, info in manifes["tabel"].items() if ada.get(t) != info["kolom"]]
        if beda:
            sys.exit(f"Tabel atau kolom target berbeda dengan cadangan: {beda[:5]}. Tidak ada data yang diubah.")
        berisi = [t for t in ada if cur.execute(f"SELECT EXISTS (SELECT 1 FROM public.{_kutip(t)})").fetchone()[0]]
        if berisi:
            sys.exit(f"Target tidak kosong ({len(berisi)} tabel berisi, mis. {berisi[0]}). Pemulihan hanya mengisi database kosong. "
                     "Tidak ada data yang diubah.")

        try:
            with zipfile.ZipFile(berkas) as arsip:
                for tabel, info in manifes["tabel"].items():
                    daftar = ", ".join(_kutip(k) for k in info["kolom"])
                    with cur.copy(f"COPY public.{_kutip(tabel)} ({daftar}) FROM STDIN") as salin, arsip.open(f"tabel/{tabel}.copy") as isi:
                        while potongan := isi.read(1 << 20):
                            salin.write(potongan)
                    _setel_sequence(cur, tabel, info["kolom"])
                    jumlah, sidik = _salin_keluar(cur, tabel, info["kolom"], lambda _: None)
                    if jumlah != info["baris"] or sidik != info["sha256"]:
                        raise ValueError(f"isi tabel {tabel} setelah dipulihkan berbeda dengan cadangan")
                    print(f"  {tabel}: {jumlah} baris, sama dengan cadangan")
        except Exception as e:  # noqa: BLE001  (apa pun yang gagal: batalkan semuanya)
            conn.rollback()
            sys.exit(f"Pemulihan dibatalkan, tidak ada data yang berubah: {e if isinstance(e, ValueError) else _pesan_aman(e)}.")
        conn.commit()

    with Session(engine) as s:
        hasil = ledger_chain.verify(s)
    if not hasil["utuh"]:
        sys.exit(f"Data sudah masuk, tetapi rantai hash Ledger tidak utuh: {hasil['masalah'][:3]}")
    if manifes.get("hash_ledger_terakhir") not in (None, hasil["hash_terakhir"]):
        sys.exit("Data sudah masuk, tetapi hash Ledger terakhir berbeda dengan cadangan.")
    print(f"Pemulihan selesai. Rantai hash utuh: {hasil['jumlah_event']} event.")


def _setel_sequence(cur, tabel: str, kolom: list[str]) -> None:
    """Tanpa ini, baris baru sesudah pemulihan bentrok dengan ID lama."""
    for nama in kolom:
        urut = cur.execute("SELECT pg_get_serial_sequence(%s, %s)", (f"public.{_kutip(tabel)}", nama)).fetchone()[0]
        if urut:
            terbesar = cur.execute(f"SELECT max({_kutip(nama)}) FROM public.{_kutip(tabel)}").fetchone()[0]
            if terbesar is not None:
                cur.execute("SELECT setval(%s, %s)", (urut, terbesar))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="perintah", required=True)
    b = sub.add_parser("buat", help="buat file cadangan dari database di DATABASE_URL")
    b.add_argument("--folder", default="cadangan")
    k = sub.add_parser("periksa", help="pastikan file cadangan utuh, tanpa menyentuh database")
    k.add_argument("berkas", type=Path)
    u = sub.add_parser("pulihkan", help="isi database kosong dari file cadangan")
    u.add_argument("berkas", type=Path)
    u.add_argument("--konfirmasi-host", default="", help="wajib untuk database online: nama host target, persis")
    args = p.parse_args()

    if args.perintah == "periksa":
        periksa(args.berkas)
        return
    if not IS_POSTGRES:
        sys.exit("Skrip ini untuk Postgres. Untuk SQLite, salin file aage.db saat API berhenti.")
    if args.perintah == "buat":
        buat(Path(args.folder))
    else:
        pulihkan(args.berkas, args.konfirmasi_host)


if __name__ == "__main__":
    main()
