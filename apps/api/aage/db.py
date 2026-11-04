from collections.abc import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import adalah_online, get_settings

settings = get_settings()

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

IS_POSTGRES = engine.dialect.name == "postgresql"


class DatabaseOnlineError(RuntimeError):
    """Operasi yang menghapus data ditolak pada database online."""


if engine.dialect.name == "sqlite":

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):  # pragma: no cover - konfigurasi koneksi
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


LEDGER_GUARD_SQL = """
CREATE OR REPLACE FUNCTION ledger_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION USING MESSAGE = TG_TABLE_NAME || ' bersifat append-only';
END;
$$ LANGUAGE plpgsql SET search_path = '';
DROP TRIGGER IF EXISTS ledger_no_update ON ledger_events;
CREATE TRIGGER ledger_no_update BEFORE UPDATE OR DELETE ON ledger_events
  FOR EACH ROW EXECUTE FUNCTION ledger_append_only();
DROP TRIGGER IF EXISTS ledger_hash_no_update ON ledger_hashes;
CREATE TRIGGER ledger_hash_no_update BEFORE UPDATE OR DELETE ON ledger_hashes
  FOR EACH ROW EXECUTE FUNCTION ledger_append_only();
DROP TRIGGER IF EXISTS compliance_audit_no_update ON compliance_audits;
CREATE TRIGGER compliance_audit_no_update BEFORE UPDATE OR DELETE ON compliance_audits
  FOR EACH ROW EXECUTE FUNCTION ledger_append_only();
"""


def _add_missing_columns() -> None:
    """Migrasi ringan: tambahkan kolom baru pada tabel yang sudah ada (create_all tidak mengubah tabel lama)."""
    from sqlalchemy import inspect

    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                ddl = col.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {ddl}'))


def _rebuild_sqlite_table(table) -> None:
    """SQLite tidak bisa mengubah constraint kolom: buat tabel baru → salin → hapus lama → ganti nama
    (prosedur resmi SQLite "ALTER TABLE" §7), dengan foreign key dimatikan sementara."""
    from sqlalchemy import inspect
    from sqlalchemy.schema import CreateIndex, CreateTable

    old_cols = {c["name"] for c in inspect(engine).get_columns(table.name)}
    cols = ", ".join(f'"{c.name}"' for c in table.columns if c.name in old_cols)
    tmp = f"{table.name}_baru"
    create = str(CreateTable(table).compile(engine)).strip().replace(f"CREATE TABLE {table.name} ", f"CREATE TABLE {tmp} ", 1)
    indexes = "".join(f"{str(CreateIndex(i).compile(engine)).strip()};" for i in table.indexes)
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute("PRAGMA foreign_keys=OFF")
        cur.executescript(f"BEGIN; {create}; INSERT INTO {tmp} ({cols}) SELECT {cols} FROM {table.name}; "
                          f"DROP TABLE {table.name}; ALTER TABLE {tmp} RENAME TO {table.name}; {indexes} COMMIT;")
        cur.execute("PRAGMA foreign_keys=ON")
    finally:
        raw.close()


def _migrate_channel_identity() -> None:
    """Migrasi 31 Okt 2026: kontak diidentifikasi (channel, external_user_id), bukan lagi wa_number yang wajib & unik;
    Message.wa_message_id → external_message_id. Idempoten, dijalankan setiap start setelah _add_missing_columns."""
    from sqlalchemy import inspect

    from .models import Contact

    insp = inspect(engine)
    if not insp.has_table("contacts"):
        return
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE contacts SET channel = CASE WHEN wa_number LIKE 'web:%' THEN 'webchat' ELSE 'whatsapp' END, "
            "external_user_id = CASE WHEN wa_number LIKE 'web:%' THEN substr(wa_number, 5) ELSE wa_number END "
            "WHERE external_user_id IS NULL"))
    wa = next((c for c in insp.get_columns("contacts") if c["name"] == "wa_number"), None)
    if wa is not None and not wa["nullable"]:
        if IS_POSTGRES:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE contacts ALTER COLUMN wa_number DROP NOT NULL"))
                conn.execute(text("DROP INDEX IF EXISTS ix_contacts_wa_number"))  # indeks UNIQUE lama
                conn.execute(text("CREATE INDEX ix_contacts_wa_number ON contacts (wa_number)"))
        else:
            _rebuild_sqlite_table(Contact.__table__)
    with engine.begin() as conn:
        conn.execute(text("UPDATE contacts SET wa_number = NULL WHERE channel = 'webchat' AND wa_number LIKE 'web:%'"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_contact_kanal_id ON contacts (channel, external_user_id)"))
        if insp.has_table("messages"):
            if "wa_message_id" in {c["name"] for c in insp.get_columns("messages")}:
                conn.execute(text("UPDATE messages SET external_message_id = wa_message_id "
                                  "WHERE external_message_id IS NULL AND wa_message_id IS NOT NULL"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_messages_external_message_id ON messages (external_message_id)"))


def init_db(drop: bool = False) -> None:
    from . import ledger_chain, models, settings_store  # noqa: F401  (registrasi tabel)

    if drop and adalah_online(settings.database_url):
        raise DatabaseOnlineError("Reset database ditolak: DATABASE_URL mengarah ke database online. Tidak ada data yang diubah.")
    if drop:
        Base.metadata.drop_all(engine)
    with engine.begin() as conn:
        if IS_POSTGRES:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        Base.metadata.create_all(conn)
        if IS_POSTGRES:
            # Satu transaksi dengan pembuatan tabel: Supabase membuka skema public lewat REST, jadi tabel tidak boleh
            # terlihat tanpa RLS sedetik pun. API memakai peran pemilik tabel, yang tidak terkena RLS.
            for table in Base.metadata.sorted_tables:
                conn.exec_driver_sql(f'ALTER TABLE "{table.name}" ENABLE ROW LEVEL SECURITY')
    _add_missing_columns()
    _migrate_channel_identity()
    if IS_POSTGRES:
        with engine.begin() as conn:
            conn.exec_driver_sql(LEDGER_GUARD_SQL)
    with SessionLocal() as db:  # segel event lama yang tercatat sebelum rantai hash ada
        ledger_chain.backfill(db)
