"""Pengaman database online: seed, tes, dan eval tidak boleh bisa menghapus atau menyentuh data Supabase."""

import os
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from aage import db as db_mod
from aage import ledger_chain
from aage.models import LedgerEvent

ONLINE = "postgresql+psycopg://u:p@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres"


@pytest.mark.parametrize("url,online", [
    (ONLINE, True),
    ("postgresql+psycopg://aage:aage@db:5432/aage", False),
    ("postgresql+psycopg://aage:aage@localhost:5432/aage", False),
    ("sqlite:///./aage.db", False),
])
def test_adalah_online(url, online):
    assert db_mod.adalah_online(url) is online


def test_reset_ditolak_pada_database_online(monkeypatch):
    drop = mock.Mock()
    monkeypatch.setattr(db_mod.settings, "database_url", ONLINE)
    monkeypatch.setattr(db_mod.Base.metadata, "drop_all", drop)
    with pytest.raises(db_mod.DatabaseOnlineError):
        db_mod.init_db(drop=True)
    drop.assert_not_called()


def test_seed_memakai_init_db_yang_dijaga(monkeypatch):
    from aage import seed

    monkeypatch.setattr(db_mod.settings, "database_url", ONLINE)
    monkeypatch.setattr("sys.argv", ["seed"])
    with pytest.raises(db_mod.DatabaseOnlineError):
        seed.main()


@pytest.mark.parametrize("mode", ["template", "llm"])
def test_eval_selalu_memakai_sqlite_sementara(mode):
    from eval import run_eval

    with mock.patch.dict(os.environ, {"DATABASE_URL": ONLINE, "AAGE_EVAL_DATABASE_URL": ""}):
        run_eval._prepare_env(mode, "uji-pengaman")
        assert os.environ["DATABASE_URL"].startswith("sqlite:///")


def test_eval_menolak_database_online_lewat_url_uji():
    from eval import run_eval

    with mock.patch.dict(os.environ, {"AAGE_EVAL_DATABASE_URL": ONLINE}), pytest.raises(SystemExit):
        run_eval._prepare_env("template", "uji-pengaman")


def test_tes_tidak_berjalan_di_database_online():
    assert not db_mod.adalah_online(str(db_mod.engine.url))


def test_hash_ledger_tidak_bergantung_zona_sesi():
    utc = datetime(2026, 11, 4, 5, 0, tzinfo=timezone.utc)
    a = LedgerEvent(id=1, tipe_event="x", waktu=utc, data={})
    b = LedgerEvent(id=1, tipe_event="x", waktu=utc.astimezone(timezone(timedelta(hours=7))), data={})
    assert ledger_chain.payload(a) == ledger_chain.payload(b)


hanya_postgres = pytest.mark.skipif(not db_mod.IS_POSTGRES, reason="khusus Postgres")


@hanya_postgres
def test_rls_aktif_dan_peran_publik_tidak_melihat_apa_pun(db, seeded):
    tanpa_rls = db.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND NOT rowsecurity")).all()
    assert tanpa_rls == []
    db.execute(text("DO $$ BEGIN CREATE ROLE anon_uji NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$"))
    db.execute(text("GRANT USAGE ON SCHEMA public TO anon_uji"))
    db.execute(text("GRANT SELECT ON ALL TABLES IN SCHEMA public TO anon_uji"))  # seperti hak bawaan Supabase untuk anon
    assert db.scalar(text("SELECT count(*) FROM products")) > 0
    db.execute(text("SET LOCAL ROLE anon_uji"))
    for tabel in ("products", "users", "contacts", "messages", "ledger_events", "laporan"):
        assert db.scalar(text(f"SELECT count(*) FROM {tabel}")) == 0
    db.rollback()


@hanya_postgres
@pytest.mark.parametrize("sql,nama", [
    ("UPDATE ledger_hashes SET hash = 'x'", "ledger_hashes"),
    ("DELETE FROM ledger_events", "ledger_events"),
    ("UPDATE compliance_audits SET status = 'x'", "compliance_audits"),
])
def test_trigger_append_only_menolak_sql_langsung(db, seeded, sql, nama):
    # compliance_audits bisa kosong: trigger FOR EACH ROW hanya jalan bila ada baris, jadi pastikan lewat katalog juga.
    pemicu = db.scalar(text("SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                            "WHERE c.relname = :n AND NOT t.tgisinternal AND t.tgenabled <> 'D'"), {"n": nama})
    assert pemicu == 1
    if db.scalar(text(f"SELECT count(*) FROM {nama}")):
        with pytest.raises(DBAPIError, match="append-only"):
            db.execute(text(sql))
    db.rollback()


@hanya_postgres
def test_pencarian_memakai_pgvector(db, seeded):
    assert db.scalar(text("SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                          "WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'")) == "vector(384)"
    from aage.kb import retriever

    hasil = retriever.retrieve(db, "kebijakan pembayaran transfer bank")
    assert hasil


@hanya_postgres
def test_panjang_status_konten_muat_di_postgres(db, seeded):
    from aage.models import ContentDraft

    assert ContentDraft.__table__.c.status.type.length >= len("menunggu_approval")
