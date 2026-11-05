"""Fondasi AI Leads: asal data, consent, verifikasi, versi skor, riwayat skor, impor, dan keputusan duplikat.

Baris lama tidak dihapus. Setiap lead mendapat satu lead_evidence dari sumber dan ID yang sudah tersimpan,
dan consent-nya UNKNOWN sehingga promosi terblokir sampai consent yang sah dicatat.

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('prospects', sa.Column('diperbarui_pada', sa.DateTime(timezone=True), nullable=True))
    op.add_column('prospects', sa.Column('dikumpulkan_pada', sa.DateTime(timezone=True), nullable=True))
    op.add_column('prospects', sa.Column('confidence', sa.Float(), nullable=True))
    op.add_column('prospects', sa.Column('skor_versi', sa.String(length=32), nullable=True))
    op.add_column('prospects', sa.Column('verifikasi', sa.String(length=16), server_default='belum', nullable=False))
    op.add_column('prospects', sa.Column('terakhir_diverifikasi', sa.DateTime(timezone=True), nullable=True))
    op.add_column('prospects', sa.Column('consent_status', sa.String(length=16), server_default='UNKNOWN', nullable=False))
    op.add_column('prospects', sa.Column('consent_sumber', sa.String(length=200), nullable=True))
    op.add_column('prospects', sa.Column('consent_cakupan', sa.String(length=40), nullable=True))
    op.add_column('prospects', sa.Column('consent_pada', sa.DateTime(timezone=True), nullable=True))
    op.add_column('prospects', sa.Column('digabung_ke_id', sa.Integer(), nullable=True))
    op.create_foreign_key('prospects_digabung_ke_id_fkey', 'prospects', 'prospects', ['digabung_ke_id'], ['id'])
    op.execute("UPDATE prospects SET diperbarui_pada = dibuat_pada, dikumpulkan_pada = COALESCE(terakhir_dipindai, dibuat_pada), "
               "skor_versi = 'draf-geo-data-v0', confidence = ROUND((CASE WHEN lat IS NOT NULL AND lng IS NOT NULL THEN 1 ELSE 0 END "
               "+ CASE WHEN telepon IS NOT NULL THEN 1 ELSE 0 END + CASE WHEN alamat_jalan_ada THEN 1 ELSE 0 END "
               "+ CASE WHEN jam_buka IS NOT NULL OR website IS NOT NULL THEN 1 ELSE 0 END) * 0.2, 2)")
    op.alter_column('prospects', 'diperbarui_pada', nullable=False)
    op.create_index(op.f('ix_prospects_verifikasi'), 'prospects', ['verifikasi'], unique=False)
    op.create_index(op.f('ix_prospects_consent_status'), 'prospects', ['consent_status'], unique=False)
    op.create_index(op.f('ix_prospects_digabung_ke_id'), 'prospects', ['digabung_ke_id'], unique=False)
    op.create_index('ix_prospects_skor', 'prospects', ['skor'], unique=False)
    op.create_index('ix_prospects_status', 'prospects', ['status'], unique=False)
    op.create_index('ix_prospects_sumber', 'prospects', ['sumber'], unique=False)

    op.create_table('lead_evidence',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('lead_id', sa.Integer(), nullable=False),
    sa.Column('source_type', sa.String(length=24), nullable=False),
    sa.Column('source_reference', sa.String(length=500), nullable=False),
    sa.Column('dikumpulkan_pada', sa.DateTime(timezone=True), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('metadata_sumber', sa.JSON(), nullable=True),
    sa.Column('dibuat_pada', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['lead_id'], ['prospects.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('lead_id', 'source_type', 'source_reference', name='uq_lead_evidence_sumber')
    )
    op.execute('ALTER TABLE lead_evidence ENABLE ROW LEVEL SECURITY')
    op.create_index(op.f('ix_lead_evidence_lead_id'), 'lead_evidence', ['lead_id'], unique=False)
    op.execute("INSERT INTO lead_evidence (lead_id, source_type, source_reference, dikumpulkan_pada, dibuat_pada) "
               "SELECT id, sumber, COALESCE(eksternal_id, 'prospect:' || CAST(id AS TEXT)), dikumpulkan_pada, dikumpulkan_pada FROM prospects")

    op.create_table('lead_duplikat',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('lead_id', sa.Integer(), nullable=False),
    sa.Column('lead_cocok_id', sa.Integer(), nullable=False),
    sa.Column('tingkat', sa.String(length=8), nullable=False),
    sa.Column('alasan', sa.JSON(), nullable=False),
    sa.Column('keputusan', sa.String(length=16), nullable=False),
    sa.Column('diputuskan_oleh', sa.String(length=120), nullable=True),
    sa.Column('diputuskan_pada', sa.DateTime(timezone=True), nullable=True),
    sa.Column('dibuat_pada', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['lead_cocok_id'], ['prospects.id'], ),
    sa.ForeignKeyConstraint(['lead_id'], ['prospects.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('lead_id', 'lead_cocok_id', name='uq_lead_duplikat_pasangan')
    )
    op.execute('ALTER TABLE lead_duplikat ENABLE ROW LEVEL SECURITY')
    op.create_index(op.f('ix_lead_duplikat_keputusan'), 'lead_duplikat', ['keputusan'], unique=False)
    op.create_index(op.f('ix_lead_duplikat_lead_cocok_id'), 'lead_duplikat', ['lead_cocok_id'], unique=False)
    op.create_index(op.f('ix_lead_duplikat_lead_id'), 'lead_duplikat', ['lead_id'], unique=False)

    op.create_table('lead_skor_riwayat',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('lead_id', sa.Integer(), nullable=False),
    sa.Column('skor', sa.Integer(), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('skor_versi', sa.String(length=32), nullable=False),
    sa.Column('faktor', sa.JSON(), nullable=False),
    sa.Column('pemicu', sa.String(length=24), nullable=False),
    sa.Column('dibuat_pada', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['lead_id'], ['prospects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.execute('ALTER TABLE lead_skor_riwayat ENABLE ROW LEVEL SECURITY')
    op.create_index(op.f('ix_lead_skor_riwayat_lead_id'), 'lead_skor_riwayat', ['lead_id'], unique=False)
    op.execute("INSERT INTO lead_skor_riwayat (lead_id, skor, confidence, skor_versi, faktor, pemicu, dibuat_pada) "
               "SELECT id, skor, confidence, skor_versi, alasan_skor, 'migrasi', dikumpulkan_pada FROM prospects")

    op.create_table('lead_impor',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('token', sa.String(length=40), nullable=False),
    sa.Column('nama_file', sa.String(length=300), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('source_type', sa.String(length=24), nullable=False),
    sa.Column('source_reference', sa.String(length=300), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('baris', sa.JSON(), nullable=False),
    sa.Column('laporan', sa.JSON(), nullable=False),
    sa.Column('hasil', sa.JSON(), nullable=True),
    sa.Column('dibuat_oleh', sa.String(length=120), nullable=False),
    sa.Column('dibuat_pada', sa.DateTime(timezone=True), nullable=False),
    sa.Column('diterapkan_pada', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.execute('ALTER TABLE lead_impor ENABLE ROW LEVEL SECURITY')
    op.create_index(op.f('ix_lead_impor_sha256'), 'lead_impor', ['sha256'], unique=False)
    op.create_index(op.f('ix_lead_impor_token'), 'lead_impor', ['token'], unique=True)


def downgrade() -> None:
    raise RuntimeError("Migrasi 0002 tidak bisa dibatalkan otomatis: consent dan asal data bisa hilang. Pulihkan dari cadangan.")
