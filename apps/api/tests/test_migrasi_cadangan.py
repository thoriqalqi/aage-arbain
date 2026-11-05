"""Alembic dan skrip cadangan. Uji penuh butuh AAGE_TES_PINDAH_URL (Postgres lokal, isinya dihapus); selain itu dilewati."""
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from unittest import mock

import pytest
from sqlalchemy import create_engine, text

from aage import db as db_mod

HERE = Path(__file__).resolve().parents[1]
URL = os.environ.get("AAGE_TES_PINDAH_URL", "")
perlu_postgres = pytest.mark.skipif(not URL, reason="butuh AAGE_TES_PINDAH_URL")
ONLINE = "postgresql+psycopg://u:p@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres"


def _jalan(*perintah: str, url: str = URL) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": url, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, *perintah], cwd=HERE, env=env, capture_output=True, text=True, encoding="utf-8", timeout=300)


def _alembic(*args: str) -> subprocess.CompletedProcess:
    return _jalan("-m", "alembic", *args)


def _cadangan(*args: str) -> subprocess.CompletedProcess:
    return _jalan("scripts/cadangan_db.py", *args)


def _kosongkan(engine) -> None:
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))


def _skema_alembic_dan_data(engine) -> None:
    _kosongkan(engine)
    h = _alembic("upgrade", "head")
    assert h.returncode == 0, h.stderr
    isi = "from aage.db import SessionLocal\nfrom aage.seed import seed_base\ns = SessionLocal()\nseed_base(s)\ns.commit()\ns.close()"
    h = _jalan("-c", isi)
    assert h.returncode == 0, h.stderr


def test_riwayat_migrasi_tidak_bercabang():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    assert len(ScriptDirectory.from_config(Config(str(HERE / "alembic.ini"))).get_heads()) == 1


@pytest.mark.parametrize("versi", [None, "versi-lain"])
def test_api_berhenti_kalau_versi_skema_online_berbeda(monkeypatch, versi):
    create_all = mock.Mock()
    monkeypatch.setattr(db_mod.settings, "database_url", ONLINE)
    monkeypatch.setattr(db_mod, "versi_skema_database", lambda: versi)
    monkeypatch.setattr(db_mod.Base.metadata, "create_all", create_all)
    with pytest.raises(db_mod.DatabaseOnlineError, match="alembic upgrade head"):
        db_mod.init_db()
    create_all.assert_not_called()


def test_api_online_tidak_mengubah_skema_saat_versi_sama(monkeypatch):
    create_all = mock.Mock()
    backfill = mock.Mock()
    monkeypatch.setattr(db_mod.settings, "database_url", ONLINE)
    monkeypatch.setattr(db_mod, "versi_skema_database", db_mod.versi_skema_kode)
    monkeypatch.setattr(db_mod.Base.metadata, "create_all", create_all)
    monkeypatch.setattr(db_mod, "_add_missing_columns", create_all)
    monkeypatch.setattr(db_mod, "_migrate_channel_identity", create_all)
    monkeypatch.setattr("aage.ledger_chain.backfill", backfill)
    db_mod.init_db()
    create_all.assert_not_called()
    backfill.assert_called_once()


def test_alembic_menolak_sqlite(tmp_path):
    h = _jalan("-m", "alembic", "upgrade", "head", url=f"sqlite:///{(tmp_path / 'x.db').as_posix()}")
    assert h.returncode != 0 and "hanya untuk Postgres" in h.stderr + h.stdout
    assert not (tmp_path / "x.db").exists()


def test_cadangan_rusak_ditolak_tanpa_database(tmp_path):
    rusak = tmp_path / "rusak.zip"
    rusak.write_bytes(b"bukan zip")
    h = _jalan("scripts/cadangan_db.py", "periksa", str(rusak), url=f"sqlite:///{(tmp_path / 'x.db').as_posix()}")
    assert h.returncode != 0 and "rusak" in h.stderr


def test_pulihkan_ke_online_wajib_konfirmasi_host(tmp_path):
    berkas = tmp_path / "c.zip"
    with zipfile.ZipFile(berkas, "w") as a:
        a.writestr("manifes.json", '{"format": 1, "dibuat_pada": "x", "tabel": {}}')
    h = _jalan("scripts/cadangan_db.py", "pulihkan", str(berkas), url=ONLINE + "?sslmode=require")
    assert h.returncode != 0 and "--konfirmasi-host" in h.stderr


@perlu_postgres
def test_migrasi_dari_kosong_sama_dengan_model_dan_terlindungi():
    assert not db_mod.adalah_online(URL)
    engine = create_engine(URL)
    _kosongkan(engine)
    h = _alembic("upgrade", "head")
    assert h.returncode == 0, h.stderr
    h = _alembic("check")
    assert h.returncode == 0 and "No new upgrade operations" in h.stdout + h.stderr, h.stdout + h.stderr
    with engine.connect() as c:
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == db_mod.versi_skema_kode()
        assert c.scalar(text("SELECT count(*) FROM pg_tables WHERE schemaname='public' AND NOT rowsecurity")) == 0, "tabel versi juga wajib RLS"
        assert c.scalar(text("SELECT count(*) FROM pg_trigger WHERE tgname IN "
                             "('ledger_no_update','ledger_hash_no_update','compliance_audit_no_update') AND tgenabled <> 'D'")) == 3
    h = _alembic("downgrade", "base")
    assert h.returncode != 0 and "tidak bisa dibatalkan" in h.stderr + h.stdout
    with engine.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM pg_tables WHERE schemaname='public'")) > 20, "tabel tetap ada setelah downgrade ditolak"
    engine.dispose()


@perlu_postgres
def test_migrasi_0002_mengisi_baris_lead_lama_tanpa_menghapus():
    engine = create_engine(URL)
    _kosongkan(engine)
    h = _alembic("upgrade", "0001")
    assert h.returncode == 0, h.stderr
    isi = ("INSERT INTO prospects (nama, alamat, wilayah, tipe, sudah_pelanggan, skor, alasan_skor, draf_pesan, status, sumber, "
           "eksternal_id, alamat_jalan_ada, skor_geo, skor_data, dibuat_pada) VALUES "
           "(:nama, '', 'Kota', 'Apotek', false, 10, '[]', '', 'dihubungi', :sumber, :ext, false, 0, 0, now())")
    with engine.begin() as c:
        c.execute(text(isi), {"nama": "Asli", "sumber": "osm", "ext": "osm:node/1"})
        c.execute(text(isi), {"nama": "Demo", "sumber": "sintetis", "ext": None})
    h = _alembic("upgrade", "head")
    assert h.returncode == 0, h.stderr
    with engine.connect() as c:
        baris = c.execute(text("SELECT nama, status, consent_status, verifikasi, skor_versi, diperbarui_pada IS NOT NULL, "
                               "dikumpulkan_pada IS NOT NULL FROM prospects ORDER BY id")).all()
        bukti = c.execute(text("SELECT source_type, source_reference FROM lead_evidence ORDER BY lead_id")).all()
        riwayat = c.execute(text("SELECT lead_id, skor, skor_versi, pemicu FROM lead_skor_riwayat ORDER BY lead_id")).all()
        confidence = c.execute(text("SELECT confidence FROM prospects ORDER BY id")).scalars().all()
        rls = c.execute(text("SELECT count(*) FROM pg_class WHERE relname IN ('lead_impor', 'lead_skor_riwayat', 'lead_evidence', 'lead_duplikat') AND relrowsecurity")).scalar()
    assert [tuple(b) for b in baris] == [("Asli", "dihubungi", "UNKNOWN", "belum", "draf-geo-data-v0", True, True),
                                         ("Demo", "dihubungi", "UNKNOWN", "belum", "draf-geo-data-v0", True, True)]
    assert [tuple(b) for b in bukti] == [("osm", "osm:node/1"), ("sintetis", "prospect:2")]
    assert [tuple(r) for r in riwayat] == [(1, 10, "draf-geo-data-v0", "migrasi"), (2, 10, "draf-geo-data-v0", "migrasi")]
    assert confidence == [0, 0] and rls == 4
    engine.dispose()


@perlu_postgres
def test_migrasi_0003_status_simulasi_rls_bisa_diulang_dan_rollback():
    engine = create_engine(URL)
    _kosongkan(engine)
    h = _alembic("upgrade", "0002")
    assert h.returncode == 0, h.stderr
    produk = ("INSERT INTO products (sku, nama, kategori, komposisi, kemasan, satuan_grosir, no_izin_edar, harga_dasar, moq, kata_kunci, "
              "sumber_data, aktif, larangan, data_teknis, deskripsi) VALUES (:sku, :nama, '', '', '', 'box', :izin, 1000, 1, '', :sumber, true, "
              "'[]', '{}', '')")
    with engine.begin() as c:
        c.execute(text(produk), {"sku": "A", "nama": "Simulasi", "izin": "POM SD SIM1", "sumber": "impor"})
        c.execute(text(produk), {"sku": "B", "nama": "Sintetis", "izin": "POM TR 1", "sumber": "sintetis"})
        c.execute(text(produk), {"sku": "C", "nama": "Impor mitra", "izin": "POM TR 2", "sumber": "impor"})
        ids = dict(c.execute(text("SELECT sku, id FROM products")).all())
        c.execute(text("INSERT INTO approved_claims (product_id, teks_klaim, sumber_dokumen, diverifikasi_oleh) VALUES "
                       "(:a, 'klaim a', '', 'Tim (simulasi)'), (:c, 'klaim c', '', 'Tim')"), {"a": ids["A"], "c": ids["C"]})
        c.execute(text("INSERT INTO documents (judul, tipe, versi, aktif, diunggah_pada) VALUES "
                       "('Kebijakan (data contoh/sintetis)', 'teks', 1, true, now()), ('Panduan mitra', 'teks', 1, true, now())"))
        c.execute(text("INSERT INTO settings (kunci, nilai, diubah_oleh, diubah_pada) VALUES ('otonomi', '{}', 'tes', now())"))

    def isi():
        with engine.connect() as c:
            return {
                "status": [tuple(b) for b in c.execute(text(
                    "SELECT objek_tipe, status_verifikasi, count(*) FROM verifikasi_fakta GROUP BY 1, 2 ORDER BY 1, 2"))],
                "produk_c": c.scalar(text("SELECT count(*) FROM verifikasi_fakta WHERE objek_tipe='produk' AND objek_id=:i"), {"i": ids["C"]}),
                "rls": c.scalar(text("SELECT relrowsecurity FROM pg_class WHERE relname='verifikasi_fakta'")),
                "terverifikasi": c.scalar(text("SELECT count(*) FROM verifikasi_fakta WHERE status_verifikasi='terverifikasi' OR diverifikasi_oleh IS NOT NULL")),
                "klaim_lama": c.scalar(text("SELECT count(*) FROM approved_claims WHERE diverifikasi_oleh IS NOT NULL")),
                "produk": c.scalar(text("SELECT count(*) FROM products")),
            }

    h = _alembic("upgrade", "0003")
    assert h.returncode == 0, h.stderr
    pertama = isi()
    # 9 jenis fakta untuk 2 produk simulasi, 1 klaim, 1 dokumen. Impor mitra tanpa pola simulasi tetap tanpa baris = belum diverifikasi.
    assert pertama["status"] == [("dokumen", "simulasi", 1), ("klaim", "simulasi", 1), ("produk", "simulasi", 18)]
    assert pertama["produk_c"] == 0 and pertama["rls"] is True and pertama["terverifikasi"] == 0
    assert pertama["klaim_lama"] == 2 and pertama["produk"] == 3, "kolom dan tabel lain tidak boleh diubah"

    # Diulang: isi yang sudah ada tidak berubah dan tidak ganda. Baris buatan admin tidak tertimpa.
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    modul = ScriptDirectory.from_config(Config(str(HERE / "alembic.ini"))).get_revision("0003").module
    with engine.begin() as c:
        for sql in (modul.BUAT_TABEL, modul.AKTIFKAN_RLS, modul.BUAT_INDEKS, modul.ISI_PRODUK, modul.ISI_KLAIM, modul.ISI_DOKUMEN):
            c.exec_driver_sql(sql.replace("%", "%%"))
    assert isi() == pertama

    with engine.begin() as c:
        c.execute(text("INSERT INTO settings (kunci, nilai, diubah_oleh, diubah_pada) VALUES ('mode_data', '{\"mode\": \"demo\"}', 'tes', now())"))
    h = _alembic("downgrade", "0002")
    assert h.returncode == 0, h.stderr
    with engine.connect() as c:
        assert c.scalar(text("SELECT to_regclass('public.verifikasi_fakta')")) is None
        assert c.scalar(text("SELECT count(*) FROM settings WHERE kunci='mode_data'")) == 0
        assert c.scalar(text("SELECT count(*) FROM settings WHERE kunci='otonomi'")) == 1
        assert c.scalar(text("SELECT count(*) FROM products")) == 3
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == "0002"
    h = _alembic("upgrade", "head")
    assert h.returncode == 0, h.stderr
    assert isi() == pertama
    h = _alembic("check")
    assert h.returncode == 0 and "No new upgrade operations" in h.stdout + h.stderr, h.stdout + h.stderr
    engine.dispose()


@perlu_postgres
def test_cadangkan_hapus_pulihkan_kembali_sama(tmp_path):
    engine = create_engine(URL)
    _skema_alembic_dan_data(engine)
    with engine.connect() as c:
        tabel = ("products", "users", "chunks", "ledger_events", "ledger_hashes", "approved_claims")
        awal = {t: c.scalar(text(f"SELECT count(*) FROM {t}")) for t in tabel}
    assert awal["products"] > 0 and awal["ledger_events"] > 0

    h = _cadangan("buat", "--folder", str(tmp_path))
    assert h.returncode == 0, h.stderr
    berkas = next(tmp_path.glob("db-*.zip"))
    assert not list(tmp_path.glob("*.tmp"))
    assert _cadangan("periksa", str(berkas)).returncode == 0

    h = _cadangan("pulihkan", str(berkas))
    assert h.returncode != 0 and "tidak kosong" in h.stderr, "tidak boleh menimpa data yang ada"

    _kosongkan(engine)
    h = _cadangan("pulihkan", str(berkas))
    assert h.returncode != 0 and f"alembic upgrade {db_mod.versi_skema_kode()}" in h.stderr, "skema harus dibuat dulu"

    assert _alembic("upgrade", "head").returncode == 0
    h = _cadangan("pulihkan", str(berkas))
    assert h.returncode == 0, h.stderr
    assert "Rantai hash utuh" in h.stdout
    with engine.begin() as c:
        assert {t: c.scalar(text(f"SELECT count(*) FROM {t}")) for t in tabel} == awal
        terbesar = c.scalar(text("SELECT max(id) FROM products"))
        baru = c.scalar(text("SELECT nextval(pg_get_serial_sequence('public.products','id'))"))
        assert baru > terbesar, "sequence harus melewati ID lama"
    engine.dispose()


@perlu_postgres
def test_cadangan_yang_diubah_ditolak_dan_target_tetap_kosong(tmp_path):
    engine = create_engine(URL)
    _skema_alembic_dan_data(engine)
    assert _cadangan("buat", "--folder", str(tmp_path)).returncode == 0
    asli = next(tmp_path.glob("db-*.zip"))
    ubah = tmp_path / "ubah.zip"
    with zipfile.ZipFile(asli) as a, zipfile.ZipFile(ubah, "w") as b:
        for nama in a.namelist():
            isi = a.read(nama)
            b.writestr(nama, isi.replace(b"Madu", b"Mada") if nama == "tabel/products.copy" else isi)
    _kosongkan(engine)
    assert _alembic("upgrade", "head").returncode == 0
    h = _cadangan("pulihkan", str(ubah))
    assert h.returncode != 0 and "rusak" in h.stderr
    with engine.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM products")) == 0
    engine.dispose()


@perlu_postgres
def test_pemulihan_gagal_di_tengah_dibatalkan_semua(tmp_path):
    """Isi yang lolos sidik file tetapi ditolak database: semua tabel harus kembali kosong, dan isi baris tidak tercetak."""
    import hashlib
    import json

    engine = create_engine(URL)
    _skema_alembic_dan_data(engine)
    assert _cadangan("buat", "--folder", str(tmp_path)).returncode == 0
    asli = next(tmp_path.glob("db-*.zip"))
    ubah = tmp_path / "gagal.zip"
    with zipfile.ZipFile(asli) as a, zipfile.ZipFile(ubah, "w") as b:
        manifes = json.loads(a.read("manifes.json"))
        isi_produk = a.read("tabel/products.copy")
        rusak = isi_produk + isi_produk.split(b"\n")[0] + b"\n"  # baris kembar: melanggar primary key
        manifes["tabel"]["products"].update(baris=rusak.count(b"\n"), sha256=hashlib.sha256(rusak).hexdigest())
        for nama in a.namelist():
            if nama == "manifes.json":
                b.writestr(nama, json.dumps(manifes))
            else:
                b.writestr(nama, rusak if nama == "tabel/products.copy" else a.read(nama))
    _kosongkan(engine)
    assert _alembic("upgrade", "head").returncode == 0
    h = _cadangan("pulihkan", str(ubah))
    assert h.returncode != 0 and "dibatalkan" in h.stderr
    assert "Madu" not in h.stderr + h.stdout.split("products")[0], "pesan galat tidak boleh memuat isi baris"
    with engine.connect() as c:
        for t in ("documents", "products", "ledger_events", "users"):
            assert c.scalar(text(f"SELECT count(*) FROM {t}")) == 0, t
    engine.dispose()
