"""Verifikasi knowledge: status per fakta untuk produk, klaim, dan dokumen.

Tidak ada baris yang menjadi `terverifikasi`. Data dari sumber simulasi atau bernomor SIM diberi status `simulasi`;
fakta tanpa baris dianggap belum diverifikasi oleh kode. Isi tabel lain tidak diubah.

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None

BUAT_TABEL = """
CREATE TABLE IF NOT EXISTS verifikasi_fakta (
    id SERIAL PRIMARY KEY,
    objek_tipe VARCHAR(16) NOT NULL,
    objek_id INTEGER NOT NULL,
    jenis_fakta VARCHAR(24) NOT NULL,
    status_verifikasi VARCHAR(24) NOT NULL,
    diverifikasi_oleh VARCHAR(120),
    diverifikasi_pada TIMESTAMP WITH TIME ZONE,
    sumber_bukti TEXT,
    berlaku_sampai DATE,
    nilai_hash VARCHAR(64),
    diubah_oleh VARCHAR(120) NOT NULL,
    diubah_pada TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uq_verifikasi_fakta_objek UNIQUE (objek_tipe, objek_id, jenis_fakta)
)
"""
AKTIFKAN_RLS = "ALTER TABLE verifikasi_fakta ENABLE ROW LEVEL SECURITY"
BUAT_INDEKS = "CREATE INDEX IF NOT EXISTS ix_verifikasi_fakta_status_verifikasi ON verifikasi_fakta (status_verifikasi)"
ISI_PRODUK = """
INSERT INTO verifikasi_fakta (objek_tipe, objek_id, jenis_fakta, status_verifikasi, diubah_oleh, diubah_pada)
SELECT 'produk', p.id, j.jenis, 'simulasi', 'migrasi 0003', CURRENT_TIMESTAMP
FROM products p
CROSS JOIN (SELECT 'produk' AS jenis UNION ALL SELECT 'harga' UNION ALL SELECT 'moq' UNION ALL SELECT 'tier_diskon'
            UNION ALL SELECT 'stok' UNION ALL SELECT 'izin_edar' UNION ALL SELECT 'halal' UNION ALL SELECT 'bko'
            UNION ALL SELECT 'aturan_pakai') j
WHERE p.sumber_data IN ('simulasi', 'sintetis') OR p.no_izin_edar LIKE '%SIM%'
   OR CAST(p.data_teknis AS TEXT) LIKE '%-SIM-%'
ON CONFLICT (objek_tipe, objek_id, jenis_fakta) DO NOTHING
"""
ISI_KLAIM = """
INSERT INTO verifikasi_fakta (objek_tipe, objek_id, jenis_fakta, status_verifikasi, diubah_oleh, diubah_pada)
SELECT 'klaim', c.id, 'klaim', 'simulasi', 'migrasi 0003', CURRENT_TIMESTAMP
FROM approved_claims c JOIN products p ON p.id = c.product_id
WHERE p.sumber_data IN ('simulasi', 'sintetis') OR p.no_izin_edar LIKE '%SIM%'
   OR CAST(p.data_teknis AS TEXT) LIKE '%-SIM-%'
ON CONFLICT (objek_tipe, objek_id, jenis_fakta) DO NOTHING
"""
ISI_DOKUMEN = """
INSERT INTO verifikasi_fakta (objek_tipe, objek_id, jenis_fakta, status_verifikasi, diubah_oleh, diubah_pada)
SELECT 'dokumen', d.id, 'dokumen', 'simulasi', 'migrasi 0003', CURRENT_TIMESTAMP
FROM documents d
WHERE LOWER(d.judul) LIKE '%simulasi%' OR LOWER(d.judul) LIKE '%sintetis%' OR LOWER(d.judul) LIKE '%data contoh%'
ON CONFLICT (objek_tipe, objek_id, jenis_fakta) DO NOTHING
"""
HAPUS_MODE = "DELETE FROM settings WHERE kunci = 'mode_data'"
HAPUS_TABEL = "DROP TABLE IF EXISTS verifikasi_fakta"


def upgrade() -> None:
    for sql in (BUAT_TABEL, AKTIFKAN_RLS, BUAT_INDEKS, ISI_PRODUK, ISI_KLAIM, ISI_DOKUMEN):
        op.execute(sql)


def downgrade() -> None:
    op.execute(HAPUS_MODE)
    op.execute(HAPUS_TABEL)
