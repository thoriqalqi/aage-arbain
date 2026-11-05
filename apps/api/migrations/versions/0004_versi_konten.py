"""Riwayat versi draf konten.

Hanya menambah satu tabel kosong. Tidak ada baris di tabel lain yang diubah: draf lama mendapat versi pertamanya saat
pertama kali diedit.

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None

BUAT_TABEL = """
CREATE TABLE IF NOT EXISTS content_versions (
    id SERIAL PRIMARY KEY,
    content_id INTEGER NOT NULL REFERENCES content_drafts (id),
    nomor INTEGER NOT NULL,
    judul VARCHAR(200) NOT NULL,
    isi TEXT NOT NULL,
    faq JSON NOT NULL,
    meta JSON NOT NULL,
    json_ld JSON NOT NULL,
    claim_verdict VARCHAR(16) NOT NULL,
    claim_report JSON NOT NULL,
    perubahan VARCHAR(24) NOT NULL,
    aktor VARCHAR(120) NOT NULL,
    dibuat_pada TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uq_content_versions_nomor UNIQUE (content_id, nomor)
)
"""
AKTIFKAN_RLS = "ALTER TABLE content_versions ENABLE ROW LEVEL SECURITY"
HAPUS_TABEL = "DROP TABLE IF EXISTS content_versions"


def upgrade() -> None:
    op.execute(BUAT_TABEL)
    op.execute(AKTIFKAN_RLS)


def downgrade() -> None:
    op.execute(HAPUS_TABEL)
