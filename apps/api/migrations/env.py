"""Alembic untuk skema Postgres. SQLite (mode pengembangan) tetap memakai init_db."""
import logging.config

import pgvector.sqlalchemy  # noqa: F401  (mendaftarkan tipe vector agar terbaca saat membandingkan skema)
from alembic import context
from sqlalchemy import create_engine, pool, text

from aage import ledger_chain, models, settings_store  # noqa: F401  (registrasi tabel)
from aage.config import get_settings
from aage.db import Base

if context.config.config_file_name:
    logging.config.fileConfig(context.config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _bandingkan_nama(nama, jenis, _induk) -> bool:
    return not (jenis == "table" and nama == "alembic_version")


def _lindungi_tabel_versi(conn) -> None:
    """Supabase membuka skema public lewat REST, jadi tabel versi juga wajib RLS, satu transaksi dengan pembuatannya."""
    tanpa_rls = conn.scalar(text("SELECT count(*) FROM pg_tables WHERE schemaname = current_schema() "
                                 "AND tablename = 'alembic_version' AND NOT rowsecurity"))
    if tanpa_rls:
        conn.exec_driver_sql("ALTER TABLE alembic_version ENABLE ROW LEVEL SECURITY")


def jalankan() -> None:
    url = get_settings().database_url
    if not url.startswith("postgresql"):
        raise SystemExit("Alembic hanya untuk Postgres. DATABASE_URL sekarang bukan Postgres; SQLite memakai init_db.")
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, compare_type=True,
                          include_name=_bandingkan_nama)
        with context.begin_transaction():
            context.run_migrations()
            _lindungi_tabel_versi(conn)
    engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Mode offline tidak dipakai di proyek ini.")
jalankan()
