"""Satukan draf: audit Compliance merujuk content_drafts, marketing_drafts dihapus.

Isi marketing_drafts dipindahkan ke content_drafts berstatus diarsipkan. Draf itu berasal dari sistem tanpa aturan dua
orang, jadi tidak boleh langsung bisa diajukan atau disetujui.

compliance_audits dijaga trigger append-only. Trigger dimatikan hanya untuk mengganti rujukan draft_id, di dalam
transaksi migrasi ini. Isi audit lain tidak berubah. Event Ledger lama tetap menyebut nomor draf lama karena Ledger
tidak bisa diubah; peta nomor lama ke baru ada di content_drafts.topik.

Revision ID: 0005
Revises: 0004
"""
from alembic import op

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None

NAIK = [
    "ALTER TABLE compliance_audits DROP CONSTRAINT compliance_audits_draft_id_fkey",
    # Nomor baru disiapkan dulu supaya rujukan audit bisa dipetakan.
    """
    CREATE TEMP TABLE peta_draf ON COMMIT DROP AS
    SELECT m.id AS lama, nextval(pg_get_serial_sequence('content_drafts', 'id')) AS baru, m.product_id, m.teks, m.versi, m.dibuat_pada,
           CASE (SELECT a.status FROM compliance_audits a WHERE a.draft_id = m.id ORDER BY a.id DESC LIMIT 1)
                WHEN 'BLOCKED' THEN 'blocked' WHEN 'ALLOWED' THEN 'allowed' ELSE 'review' END AS putusan
    FROM marketing_drafts m
    """,
    """
    INSERT INTO content_drafts (id, product_id, tipe, topik, target, judul, isi, faq, meta, json_ld, claim_verdict, claim_report, status, dibuat_pada)
    SELECT baru, product_id, 'deskripsi', 'Dipindahkan dari draf marketing #' || lama, 'apotek', 'Materi audit Compliance #' || lama, teks,
           '[]', '{}', '[]', putusan, '{}', 'diarsipkan', dibuat_pada
    FROM peta_draf
    """,
    """
    INSERT INTO content_versions (content_id, nomor, judul, isi, faq, meta, json_ld, claim_verdict, claim_report, perubahan, aktor, dibuat_pada)
    SELECT baru, versi, 'Materi audit Compliance #' || lama, teks, '[]', '{}', '[]', putusan, '{}', 'sebelum_riwayat', 'sistem', dibuat_pada
    FROM peta_draf
    """,
    "ALTER TABLE compliance_audits DISABLE TRIGGER compliance_audit_no_update",
    "UPDATE compliance_audits a SET draft_id = p.baru FROM peta_draf p WHERE a.draft_id = p.lama",
    "ALTER TABLE compliance_audits ENABLE TRIGGER compliance_audit_no_update",
    "ALTER TABLE compliance_audits ADD CONSTRAINT compliance_audits_draft_id_fkey FOREIGN KEY (draft_id) REFERENCES content_drafts (id)",
    "DROP TABLE marketing_drafts",
]

# Tabel kembali kosong dan rujukan audit dilepas. Draf yang dipindahkan tetap di content_drafts, tidak ada yang hilang.
TURUN = [
    "ALTER TABLE compliance_audits DROP CONSTRAINT compliance_audits_draft_id_fkey",
    "ALTER TABLE compliance_audits DISABLE TRIGGER compliance_audit_no_update",
    "UPDATE compliance_audits SET draft_id = NULL WHERE draft_id IS NOT NULL",
    "ALTER TABLE compliance_audits ENABLE TRIGGER compliance_audit_no_update",
    """
    CREATE TABLE marketing_drafts (
        id SERIAL PRIMARY KEY,
        product_id INTEGER NOT NULL REFERENCES products (id),
        teks TEXT NOT NULL,
        status VARCHAR(24) NOT NULL,
        versi INTEGER NOT NULL,
        dibuat_oleh INTEGER REFERENCES users (id),
        keputusan_oleh INTEGER REFERENCES users (id),
        keputusan_pada TIMESTAMP WITH TIME ZONE,
        catatan_keputusan TEXT,
        dibuat_pada TIMESTAMP WITH TIME ZONE NOT NULL,
        diperbarui_pada TIMESTAMP WITH TIME ZONE NOT NULL
    )
    """,
    "CREATE INDEX ix_marketing_drafts_product_id ON marketing_drafts (product_id)",
    "CREATE INDEX ix_marketing_drafts_status ON marketing_drafts (status)",
    "ALTER TABLE marketing_drafts ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE compliance_audits ADD CONSTRAINT compliance_audits_draft_id_fkey FOREIGN KEY (draft_id) REFERENCES marketing_drafts (id)",
]


def upgrade() -> None:
    for sql in NAIK:
        op.execute(sql)


def downgrade() -> None:
    for sql in TURUN:
        op.execute(sql)
