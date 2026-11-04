"""Skrip pindah ke Postgres. Uji penuh butuh AAGE_TES_PINDAH_URL (Postgres lokal, isinya dihapus); selain itu dilewati."""

import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from aage import models

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "scripts"))

import pindah_ke_postgres as pindah  # noqa: E402

URL = os.environ.get("AAGE_TES_PINDAH_URL", "")
perlu_postgres = pytest.mark.skipif(not URL, reason="butuh AAGE_TES_PINDAH_URL")


def test_null_di_kolom_wajib_diisi_nilai_kosong():
    kolom = models.Prospect.__table__.c
    assert pindah._isi_wajib(models.Product.__table__.c.deskripsi) == ""
    assert pindah._isi_wajib(kolom.skor_geo) == 0 and pindah._isi_wajib(kolom.alamat_jalan_ada) is False


def test_pembanding_tidak_bergantung_zona_dan_presisi_vektor():
    utc = datetime(2026, 11, 4, 5, 0, tzinfo=timezone.utc)
    assert pindah._normal(utc) == pindah._normal(utc.astimezone(timezone(timedelta(hours=7))))
    assert pindah._normal([0.123456789, 0.5]) == pindah._normal((0.12345678, 0.5))


def test_baris_berbeda_terdeteksi():
    t = models.Product.__table__
    assert pindah._berbeda(t, [{"id": 1, "nama": "a"}], {(1,): {"id": 1, "nama": "b"}}) == [(1,)]
    assert pindah._berbeda(t, [{"id": 1, "nama": "a"}], {(1,): {"id": 1, "nama": "a"}}) == []


def _jalan(sumber, cadangan, *arg):
    env = {**os.environ, "DATABASE_URL": URL, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, "scripts/pindah_ke_postgres.py", "--sumber", str(sumber), "--cadangan", str(cadangan), *arg],
                          cwd=HERE, env=env, capture_output=True, text=True, encoding="utf-8", timeout=300)


@perlu_postgres
def test_pindah_cek_ulang_dan_tolak_perbedaan(tmp_path):
    assert not pindah.adalah_online(URL)
    target = create_engine(URL)
    with target.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))

    sumber = tmp_path / "sumber.db"
    siapkan = ("from aage.db import SessionLocal, init_db\nfrom aage.seed import seed_base\n"
               "init_db(drop=True)\ns = SessionLocal()\nseed_base(s)\ns.close()")
    subprocess.run([sys.executable, "-c", siapkan], cwd=HERE, env={**os.environ, "DATABASE_URL": f"sqlite:///{sumber.as_posix()}"}, check=True)
    con = sqlite3.connect(sumber)  # bentuk lama: NULL di kolom wajib dan tabel yang belum ada di aage.db lama
    con.execute("ALTER TABLE products RENAME COLUMN deskripsi TO deskripsi_lama")
    con.execute("ALTER TABLE products ADD COLUMN deskripsi TEXT")
    con.execute("DROP TABLE permintaan_tak_terpenuhi")
    con.execute("DROP TABLE laporan")
    con.commit()
    jumlah_produk = con.execute("SELECT count(*) FROM products").fetchone()[0]
    con.close()

    hasil = _jalan(sumber, tmp_path, "--cek")
    assert hasil.returncode == 0, hasil.stdout + hasil.stderr
    assert "belum ada" in hasil.stdout and not inspect(target).get_table_names(), "simulasi tidak boleh mengubah target"

    hasil = _jalan(sumber, tmp_path, "--sandi-acak")
    assert hasil.returncode == 0, hasil.stdout + hasil.stderr
    assert "rantai hash cocok" in hasil.stdout and "deskripsi" in hasil.stdout
    assert list(tmp_path.glob("aage-*.db")), "cadangan wajib dibuat"
    berkas_sandi = list(tmp_path.glob("sandi-baru-*.txt"))
    assert len(berkas_sandi) == 1
    sandi = berkas_sandi[0].read_text(encoding="utf-8")
    assert "aage.local" in sandi and sandi.split("\t")[1].split("\n")[0] not in hasil.stdout

    with target.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM products")) == jumlah_produk
        assert c.scalar(text("SELECT count(*) FROM products WHERE deskripsi IS NULL")) == 0
        assert c.scalar(text("SELECT count(*) FROM laporan")) == len(pindah.LAPORAN)
        assert c.scalar(text("SELECT count(*) FROM pg_tables WHERE schemaname='public' AND NOT rowsecurity")) == 0
        ledger = c.scalar(text("SELECT count(*) FROM ledger_events"))
        id_baru = c.scalar(text("SELECT nextval(pg_get_serial_sequence('public.ledger_events','id'))"))
        assert id_baru > c.scalar(text("SELECT max(id) FROM ledger_events")), "sequence harus sudah melewati ID lama"

    hasil = _jalan(sumber, tmp_path, "--sandi-acak")
    assert hasil.returncode == 0, hasil.stdout + hasil.stderr
    assert "ditambah 0" in hasil.stdout and len(list(tmp_path.glob("sandi-baru-*.txt"))) == 1
    with target.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM ledger_events")) == ledger, "diulang tidak boleh menggandakan"

    with target.begin() as c:
        c.execute(text("UPDATE products SET nama = 'Diubah di target' WHERE id = (SELECT min(id) FROM products)"))
    hasil = _jalan(sumber, tmp_path, "--sandi-acak")
    assert hasil.returncode != 0 and "berbeda dari sumber" in hasil.stderr
    with target.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM products WHERE nama = 'Diubah di target'")) == 1, "tidak boleh menimpa"
    target.dispose()
