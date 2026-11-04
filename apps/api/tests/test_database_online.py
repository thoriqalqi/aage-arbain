"""Pengaman database online: seed, tes, dan eval tidak boleh bisa menghapus atau menyentuh data Supabase."""

import os
from unittest import mock

import pytest

from aage import db as db_mod

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

    with mock.patch.dict(os.environ, {"DATABASE_URL": ONLINE}):
        run_eval._prepare_env(mode, "uji-pengaman")
        assert os.environ["DATABASE_URL"].startswith("sqlite:///")


def test_tes_berjalan_di_sqlite():
    assert db_mod.engine.dialect.name == "sqlite" and not db_mod.adalah_online(str(db_mod.engine.url))
