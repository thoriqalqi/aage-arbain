"""Pindahkan isi SQLite lokal dan laporan penting ke Postgres pada DATABASE_URL, dengan ID dan rantai hash Ledger tetap utuh.

    python scripts/pindah_ke_postgres.py --cek                     # simulasi: hanya membaca, target tidak diubah
    python scripts/pindah_ke_postgres.py                           # pindahkan ke Postgres lokal
    python scripts/pindah_ke_postgres.py --konfirmasi-host <host>  # pindahkan ke database online

Sumber tidak pernah diubah: yang dibaca adalah salinan buatan API backup SQLite, disimpan di --cadangan. Semua baris disalin
dalam satu transaksi. Aman diulang: baris yang sudah ada dilewati, dan bila isinya berbeda dari sumber, atau jumlah baris dan
rantai hash tidak cocok, transaksi dibatalkan tanpa menimpa apa pun. Di database online sandi pengguna diganti acak dan ditulis
ke berkas di --cadangan, tidak pernah dicetak. Isi DATABASE_URL tidak dicetak.
"""

import argparse
import json
import secrets
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import (  # noqa: E402
    JSON,
    Boolean,
    DateTime,
    Float,
    Integer,
    Numeric,
    String,
    Text,
    create_engine,
    func,
    inspect,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import insert  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from aage import clock, ledger_chain, models, settings_store  # noqa: E402,F401  (registrasi tabel)
from aage.config import adalah_online  # noqa: E402
from aage.db import IS_POSTGRES, Base, engine, init_db  # noqa: E402
from aage.security import hash_password  # noqa: E402

UKURAN_BATCH = 200
AKAR_REPO = Path(__file__).resolve().parents[3]
SSL_AMAN = {"require", "verify-ca", "verify-full"}
# Tidak dibandingkan dengan sumber: sandi di database online sengaja diganti.
KOLOM_TAK_DIBANDINGKAN = {"users": {"password_hash"}, "laporan": {"id", "dibuat_pada"}}
LAPORAN = (
    {"jenis": "regresi_llm", "judul": "Regresi LLM fase 4b", "sumber": "apps/api/eval/hasil_fase4b/laporan.txt", "commit": "145b4d7",
     "catatan": "Hanya berlaku untuk commit ini. Kode sesudahnya belum diuji di mode LLM."},
    {"jenis": "audit", "judul": "Audit koneksi seluruh proyek", "sumber": "docs/AUDIT_KONEKSI.md", "commit": "0b83092",
     "catatan": "Ditulis sebelum regresi 4b selesai; status emosi dan catatan LLM di dalamnya sudah usang."},
    {"jenis": "evaluasi", "judul": "Laporan perbaikan eval", "sumber": "apps/api/eval/laporan_perbaikan.md", "commit": "7717312",
     "catatan": "Hanya sampai tahap emosi dengan 268 tes; belum mencakup fase 4 dan konteks."},
)


def _salin_sumber(sumber: Path, tujuan: Path) -> None:
    """Salinan konsisten lewat API backup: salin file biasa bisa kehilangan isi WAL."""
    asal = sqlite3.connect(f"file:{sumber.as_posix()}?mode=ro", uri=True)
    hasil = sqlite3.connect(tujuan)
    try:
        asal.backup(hasil)
        cek = hasil.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        hasil.close()
        asal.close()
    if cek != "ok":
        sys.exit(f"Sumber rusak menurut integrity_check: {cek}")


def _isi_wajib(kolom):
    """Nilai pengganti NULL di kolom wajib: bawaan model, atau nilai kosong sesuai tipe."""
    bawaan = kolom.default
    if bawaan is not None and bawaan.is_scalar:
        return bawaan.arg
    if isinstance(kolom.type, (String, Text)):
        return ""
    if isinstance(kolom.type, Boolean):
        return False
    if isinstance(kolom.type, (Integer, Float, Numeric)):
        return 0
    if isinstance(kolom.type, JSON):
        return {}
    return None


def _baca_sumber(sumber, inspektor, tabel) -> dict:
    """Baris sumber yang sudah dirapikan, plus catatan transformasinya."""
    hasil = {"baris": [], "diisi": {}, "kolom_lama": [], "ada": inspektor.has_table(tabel.name)}
    if not hasil["ada"]:
        return hasil
    nama_sumber = {k["name"] for k in inspektor.get_columns(tabel.name)}
    kolom = [k for k in tabel.columns if k.name in nama_sumber]
    hasil["kolom_lama"] = sorted(nama_sumber - {k.name for k in tabel.columns})
    wajib = [k for k in tabel.columns if not k.nullable and not k.primary_key]
    waktu = [k.name for k in tabel.columns if isinstance(k.type, DateTime)]
    for row in sumber.execute(select(*kolom)).mappings():
        d = dict(row)
        for k in waktu:
            d[k] = clock.aware(d.get(k))  # SQLite menyimpan UTC tanpa zona
        for k in wajib:
            if d.get(k.name) is None:
                d[k.name] = _isi_wajib(k)
                hasil["diisi"][k.name] = hasil["diisi"].get(k.name, 0) + 1
        hasil["baris"].append(d)
    return hasil


def _normal(nilai):
    """Bentuk pembanding yang sama di SQLite dan Postgres."""
    if isinstance(nilai, datetime):
        return clock.aware(nilai).astimezone(timezone.utc).isoformat()
    if isinstance(nilai, bool) or nilai is None:
        return nilai
    if isinstance(nilai, (float, Decimal)):
        return round(float(nilai), 6)
    if isinstance(nilai, dict):
        return json.dumps(nilai, sort_keys=True, ensure_ascii=False, default=str)
    if hasattr(nilai, "tolist") or (isinstance(nilai, (list, tuple)) and nilai and isinstance(nilai[0], float)):
        return [round(float(x), 4) for x in nilai]  # vektor: pgvector menyimpan float 32-bit
    if isinstance(nilai, (list, tuple)):
        return json.dumps(nilai, sort_keys=True, ensure_ascii=False, default=str)
    return nilai


def _kunci(tabel, baris: dict) -> tuple:
    return tuple(baris[k.name] for k in tabel.primary_key.columns)


def _cetak(baris: dict, tabel) -> dict:
    lewati = KOLOM_TAK_DIBANDINGKAN.get(tabel.name, set())
    return {k: _normal(v) for k, v in baris.items() if k not in lewati}


def _terlalu_panjang(tabel, baris: list[dict]) -> dict:
    hasil = {}
    for k in tabel.columns:
        batas = getattr(k.type, "length", None)
        if batas and (n := sum(isinstance(b.get(k.name), str) and len(b[k.name]) > batas for b in baris)):
            hasil[k.name] = n
    return hasil


def _isi_target(conn, tabel) -> dict:
    return {_kunci(tabel, dict(r)): dict(r) for r in conn.execute(select(tabel)).mappings()}


def _berbeda(tabel, baris: list[dict], target: dict) -> list:
    """Kunci baris yang ada di target tetapi isinya tidak sama dengan sumber."""
    beda = []
    for b in baris:
        ada = target.get(_kunci(tabel, b))
        if ada is None:
            continue
        banding, hasil = _cetak(b, tabel), _cetak(ada, tabel)
        if any(banding[k] != hasil.get(k) for k in banding):
            beda.append(_kunci(tabel, b))
    return beda


def _setel_sequence(conn, tabel) -> None:
    pk = list(tabel.primary_key.columns)
    if len(pk) != 1 or pk[0].type.python_type is not int:
        return
    terbesar = conn.scalar(select(func.max(pk[0])))
    urut = conn.scalar(text("SELECT pg_get_serial_sequence(:t, :c)"), {"t": f'public."{tabel.name}"', "c": pk[0].name})
    if urut and terbesar is not None:
        conn.execute(text("SELECT setval(:s, :n)"), {"s": urut, "n": terbesar})


def _baris_laporan() -> list[dict]:
    hasil = []
    for item in LAPORAN:
        berkas = AKAR_REPO / item["sumber"]
        if not berkas.exists():
            sys.exit(f"Laporan tidak ditemukan: {item['sumber']}")
        hasil.append({**item, "isi": berkas.read_text(encoding="utf-8")})
    return hasil


def _peringatan(rencana: dict) -> None:
    for nama, r in rencana.items():
        if r["diisi"]:
            print(f"  ! {nama}: NULL di kolom wajib diisi nilai kosong: {r['diisi']}")
        if r["kolom_lama"]:
            print(f"  ! {nama}: kolom lama di sumber tidak dipindah: {r['kolom_lama']}")
        if r["panjang"]:
            print(f"  ! {nama}: nilai melebihi batas kolom: {r['panjang']}")


def cek(sumber_engine, awal: dict) -> int:
    """Simulasi: laporan per tabel. Transaksi target hanya-baca, jadi target pasti tidak berubah."""
    inspektor = inspect(sumber_engine)
    rencana, masalah = {}, 0
    with sumber_engine.connect() as sumber, engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        ada_target = inspect(conn)
        vektor = conn.scalar(text("SELECT count(*) FROM pg_available_extensions WHERE name = 'vector'"))
        print(f"pgvector tersedia di target: {'ya' if vektor else 'TIDAK'}")
        print(f"{'tabel':28s} {'sumber':>7s} {'target':>7s} {'ditambah':>9s} {'berbeda':>8s}")
        for t in Base.metadata.sorted_tables:
            r = _baca_sumber(sumber, inspektor, t)
            target = _isi_target(conn, t) if ada_target.has_table(t.name) else None
            beda = _berbeda(t, r["baris"], target) if target else []
            tambah = len(r["baris"]) if target is None else sum(_kunci(t, b) not in target for b in r["baris"])
            r["panjang"] = _terlalu_panjang(t, r["baris"])
            rencana[t.name] = r
            masalah += len(beda) + len(r["panjang"])
            jumlah = "belum ada" if target is None else str(len(target))
            print(f"{t.name:28s} {len(r['baris']):>7d} {jumlah:>7s} {tambah:>9d} {len(beda):>8d}{'' if r['ada'] else '  (tidak ada di sumber)'}")
    _peringatan(rencana)
    laporan = _baris_laporan()
    print(f"Laporan yang akan disimpan: {len(laporan)} ({', '.join(x['commit'] for x in laporan)})")
    print(f"Rantai hash sumber: {'utuh' if awal['utuh'] else 'RUSAK'}, {awal['jumlah_event']} event")
    print(f"Simulasi selesai, target tidak diubah. Masalah yang menggagalkan pemindahan: {masalah}")
    return masalah


def pindahkan(sumber_engine, awal: dict, folder: Path, sandi_acak: bool) -> None:
    init_db()
    inspektor = inspect(sumber_engine)
    terakhir = None
    with Session(sumber_engine) as s:
        terakhir = s.scalar(select(func.max(ledger_chain.LedgerHash.event_id)))
    berkas_sandi = folder / f"sandi-baru-{datetime.now():%Y%m%d-%H%M%S}.txt"
    sandi: dict[str, str] = {}
    rencana = {}
    try:
        with sumber_engine.connect() as sumber, engine.begin() as conn:
            for t in Base.metadata.sorted_tables:
                r = _baca_sumber(sumber, inspektor, t)
                r["panjang"] = _terlalu_panjang(t, r["baris"])
                rencana[t.name] = r
                baris = r["baris"]
                sebelum = _isi_target(conn, t)
                beda = _berbeda(t, baris, sebelum)
                if beda:
                    raise RuntimeError(f"{t.name}: {len(beda)} baris di target berbeda dari sumber, contoh id {beda[0]}.")
                if t.name == "users" and sandi_acak:
                    for b in baris:
                        if _kunci(t, b) not in sebelum:
                            sandi[b["email"]] = secrets.token_urlsafe(18)
                            b["password_hash"] = hash_password(sandi[b["email"]])
                for i in range(0, len(baris), UKURAN_BATCH):
                    conn.execute(insert(t).on_conflict_do_nothing(), baris[i:i + UKURAN_BATCH])
                sesudah = _isi_target(conn, t)
                hilang = [_kunci(t, b) for b in baris if _kunci(t, b) not in sesudah]
                beda = _berbeda(t, baris, sesudah)
                if hilang or beda:
                    raise RuntimeError(f"{t.name}: {len(hilang)} baris tidak masuk dan {len(beda)} berbeda setelah disalin.")
                _setel_sequence(conn, t)
                print(f"  {t.name}: sumber {len(baris)}, ditambah {len(sesudah) - len(sebelum)}, total target {len(sesudah)}")

            t = models.Laporan.__table__
            laporan = _baris_laporan()
            conn.execute(insert(t).on_conflict_do_nothing(), laporan)
            for item in laporan:
                isi = conn.scalar(select(t.c.isi).where(t.c.sumber == item["sumber"], t.c.commit == item["commit"]))
                if isi != item["isi"]:
                    raise RuntimeError(f"Laporan {item['sumber']} di target berbeda dari file.")
            print(f"  laporan: {len(laporan)} tersimpan, total target {conn.scalar(select(func.count()).select_from(t))}")

            with Session(bind=conn) as s:
                akhir = ledger_chain.verify(s)
                hash_target = s.scalar(select(ledger_chain.LedgerHash.hash).where(ledger_chain.LedgerHash.event_id == terakhir))
            if not akhir["utuh"] or (terakhir is not None and hash_target != awal["hash_terakhir"]):
                raise RuntimeError(f"Rantai hash di target tidak cocok: {akhir['masalah'][:3]}")
            if sandi:  # ditulis sebelum commit: bila gagal, sandi di target tidak pernah berlaku
                berkas_sandi.write_text("".join(f"{e}\t{p}\n" for e, p in sandi.items()), encoding="utf-8")
    except Exception:
        berkas_sandi.unlink(missing_ok=True)
        raise
    _peringatan(rencana)
    print(f"Pindah selesai, rantai hash cocok: {akhir['diperiksa']} event, hash terakhir sumber sama dengan target.")
    if sandi:
        print(f"Sandi baru {len(sandi)} pengguna ditulis ke {berkas_sandi} (nilainya tidak dicetak).")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sumber", default="aage.db")
    p.add_argument("--cek", action="store_true", help="simulasi: laporkan jumlah baris per tabel tanpa mengubah target")
    p.add_argument("--konfirmasi-host", default="", help="wajib untuk database online: nama host target, persis")
    p.add_argument("--cadangan", default="cadangan", help="folder salinan aage.db dan berkas sandi baru")
    p.add_argument("--sandi-acak", action="store_true", help="ganti sandi pengguna; selalu aktif di database online")
    args = p.parse_args()
    if not IS_POSTGRES:
        sys.exit("DATABASE_URL harus mengarah ke Postgres (postgresql+psycopg://...).")
    sumber = Path(args.sumber).resolve()
    if not sumber.exists():
        sys.exit(f"Sumber tidak ditemukan: {sumber}")
    online = adalah_online(engine.url.render_as_string(hide_password=True))
    host = engine.url.host
    print(f"Target: Postgres di {host} ({'online' if online else 'lokal'})")
    if online and engine.url.query.get("sslmode") not in SSL_AMAN:
        sys.exit("Database online wajib memakai SSL: tambahkan ?sslmode=require pada DATABASE_URL.")
    if online and not args.cek and args.konfirmasi_host != host:
        sys.exit(f"Ini database online. Jalankan --cek dulu, lalu ulangi dengan --konfirmasi-host {host}.")

    if args.cek:
        folder_tmp = tempfile.TemporaryDirectory()
        folder = Path(folder_tmp.name)
    else:
        folder = Path(args.cadangan).resolve()
        folder.mkdir(parents=True, exist_ok=True)
    salinan = folder / f"aage-{datetime.now():%Y%m%d-%H%M%S}.db"
    _salin_sumber(sumber, salinan)
    sumber_engine = create_engine(f"sqlite:///{salinan.as_posix()}")
    print(f"Sumber: {sumber.name}" + ("" if args.cek else f", cadangan di {salinan}"))
    with Session(sumber_engine) as s:
        awal = ledger_chain.verify(s)
    if not awal["utuh"]:
        sys.exit(f"Rantai hash sumber tidak utuh: {awal['masalah'][:3]}")
    try:
        if args.cek:
            sys.exit(1 if cek(sumber_engine, awal) else 0)
        pindahkan(sumber_engine, awal, folder, args.sandi_acak or online)
    finally:
        sumber_engine.dispose()
        if args.cek:
            folder_tmp.cleanup()


if __name__ == "__main__":
    main()
