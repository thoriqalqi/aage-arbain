"""Migrasi DB lama (kontak = wa_number wajib & unik) ke identitas (channel, external_user_id), tanpa kehilangan data."""

from sqlalchemy import create_engine, inspect, text

from aage import db as db_module
from aage import models  # noqa: F401  (registrasi tabel untuk _add_missing_columns)

OLD_SCHEMA = """
CREATE TABLE contacts (id INTEGER PRIMARY KEY, wa_number VARCHAR(32) NOT NULL, nama_toko VARCHAR(160), nama_wa VARCHAR(120),
  tipe_toko VARCHAR(40), alamat TEXT, opt_in BOOLEAN, prospect_id INTEGER, dibuat_pada DATETIME);
CREATE UNIQUE INDEX ix_contacts_wa_number ON contacts (wa_number);
CREATE TABLE conversations (id INTEGER PRIMARY KEY, contact_id INTEGER NOT NULL REFERENCES contacts(id), kanal VARCHAR(16),
  status VARCHAR(16), konteks JSON, diperbarui_pada DATETIME);
CREATE TABLE messages (id INTEGER PRIMARY KEY, conversation_id INTEGER NOT NULL REFERENCES conversations(id), arah VARCHAR(8),
  pengirim VARCHAR(8), teks TEXT, status_kirim VARCHAR(16), wa_message_id VARCHAR(120), dibuat_pada DATETIME);
INSERT INTO contacts (id, wa_number, nama_toko, opt_in, dibuat_pada) VALUES (1, '6281200000001', 'Apotek Lama', 1, '2026-10-01 08:00:00'),
  (2, 'web:abc123', NULL, 0, '2026-10-02 08:00:00');
INSERT INTO conversations (id, contact_id, kanal, status) VALUES (10, 1, 'whatsapp', 'otomatis'), (11, 2, 'webchat', 'otomatis');
INSERT INTO messages (id, conversation_id, arah, pengirim, teks, status_kirim, wa_message_id)
  VALUES (100, 10, 'masuk', 'pembeli', 'halo', 'diterima', 'wati:lama-1');
"""


def test_old_sqlite_db_migrates_to_channel_identity(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{(tmp_path / 'lama.db').as_posix()}")
    raw = eng.raw_connection()
    raw.cursor().executescript(OLD_SCHEMA)
    raw.close()
    monkeypatch.setattr(db_module, "engine", eng)
    monkeypatch.setattr(db_module, "IS_POSTGRES", False)  # DB lama ini selalu SQLite, di mana pun tes dijalankan

    for _ in range(2):  # idempoten: start kedua tidak mengubah apa pun
        db_module._add_missing_columns()
        db_module._migrate_channel_identity()

    with eng.connect() as conn:
        rows = conn.execute(text("SELECT id, channel, external_user_id, wa_number, nama_toko FROM contacts ORDER BY id")).all()
        assert [tuple(r) for r in rows] == [(1, "whatsapp", "6281200000001", "6281200000001", "Apotek Lama"),
                                            (2, "webchat", "abc123", None, None)]
        assert conn.execute(text("SELECT external_message_id FROM messages WHERE id = 100")).scalar() == "wati:lama-1"
        assert conn.execute(text("SELECT COUNT(*) FROM conversations")).scalar() == 2
        # Kontak Telegram tanpa nomor telepon kini bisa disimpan; pasangan (channel, external_user_id) tetap unik.
        conn.execute(text("INSERT INTO contacts (channel, external_user_id, opt_in, dibuat_pada) VALUES ('telegram', '555', 0, '2026-10-31')"))
        try:
            conn.execute(text("INSERT INTO contacts (channel, external_user_id, opt_in, dibuat_pada) VALUES ('telegram', '555', 0, '2026-10-31')"))
            raise AssertionError("duplikat (channel, external_user_id) seharusnya ditolak")
        except Exception as exc:  # noqa: BLE001
            assert "UNIQUE" in str(exc)
        fk = conn.execute(text("PRAGMA foreign_key_list(conversations)")).all()
        assert fk and fk[0][2] == "contacts"  # FK tetap menunjuk tabel contacts yang baru

    idx = {i["name"]: i["unique"] for i in inspect(eng).get_indexes("contacts")}
    assert idx["uq_contact_kanal_id"] and not idx["ix_contacts_wa_number"]
