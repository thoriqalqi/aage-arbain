"""Skema awal: semua tabel, RLS, dan trigger append-only.

Database yang sudah berisi skema ini (Supabase AAGE, dibuat 4 Nov 2026) hanya ditandai dengan `alembic stamp 0001`.
Isi file ini sengaja tidak mengimpor models: riwayat migrasi tidak boleh berubah saat model berubah.

Revisi: 0001
Sebelumnya: -
"""
from alembic import op
from pgvector.sqlalchemy import Vector
import sqlalchemy as sa


revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


PELINDUNG_APPEND_ONLY = """
CREATE OR REPLACE FUNCTION ledger_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION USING MESSAGE = TG_TABLE_NAME || ' bersifat append-only';
END;
$$ LANGUAGE plpgsql SET search_path = '';
CREATE TRIGGER ledger_no_update BEFORE UPDATE OR DELETE ON ledger_events
  FOR EACH ROW EXECUTE FUNCTION ledger_append_only();
CREATE TRIGGER ledger_hash_no_update BEFORE UPDATE OR DELETE ON ledger_hashes
  FOR EACH ROW EXECUTE FUNCTION ledger_append_only();
CREATE TRIGGER compliance_audit_no_update BEFORE UPDATE OR DELETE ON compliance_audits
  FOR EACH ROW EXECUTE FUNCTION ledger_append_only();
"""


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table('documents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('judul', sa.String(length=200), nullable=False),
    sa.Column('tipe', sa.String(length=20), nullable=False),
    sa.Column('url', sa.String(length=500), nullable=True),
    sa.Column('file', sa.String(length=300), nullable=True),
    sa.Column('versi', sa.Integer(), nullable=False),
    sa.Column('aktif', sa.Boolean(), nullable=False),
    sa.Column('diunggah_pada', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('katalog_impor',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('token', sa.String(length=40), nullable=False),
    sa.Column('nama_file', sa.String(length=300), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('produk', sa.JSON(), nullable=False),
    sa.Column('kebijakan', sa.JSON(), nullable=False),
    sa.Column('laporan', sa.JSON(), nullable=False),
    sa.Column('dibuat_oleh', sa.String(length=120), nullable=False),
    sa.Column('dibuat_pada', sa.DateTime(timezone=True), nullable=False),
    sa.Column('diterapkan_pada', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_katalog_impor_token'), 'katalog_impor', ['token'], unique=True)
    op.create_table('laporan',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('jenis', sa.String(length=32), nullable=False),
    sa.Column('judul', sa.String(length=200), nullable=False),
    sa.Column('isi', sa.Text(), nullable=False),
    sa.Column('commit', sa.String(length=40), nullable=False),
    sa.Column('sumber', sa.String(length=255), nullable=False),
    sa.Column('catatan', sa.Text(), nullable=False),
    sa.Column('dibuat_pada', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('sumber', 'commit', name='uq_laporan_sumber_commit')
    )
    op.create_index(op.f('ix_laporan_dibuat_pada'), 'laporan', ['dibuat_pada'], unique=False)
    op.create_index(op.f('ix_laporan_jenis'), 'laporan', ['jenis'], unique=False)
    op.create_table('ledger_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('waktu', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tipe_event', sa.String(length=40), nullable=False),
    sa.Column('trace_id', sa.String(length=40), nullable=True),
    sa.Column('conversation_id', sa.Integer(), nullable=True),
    sa.Column('product_id', sa.Integer(), nullable=True),
    sa.Column('objek_ref', sa.String(length=80), nullable=True),
    sa.Column('sumber_ref', sa.JSON(), nullable=False),
    sa.Column('ringkasan', sa.Text(), nullable=False),
    sa.Column('alasan', sa.Text(), nullable=False),
    sa.Column('verdict', sa.String(length=16), nullable=True),
    sa.Column('aturan_terpicu', sa.JSON(), nullable=False),
    sa.Column('model', sa.String(length=80), nullable=True),
    sa.Column('token_in', sa.Integer(), nullable=False),
    sa.Column('token_out', sa.Integer(), nullable=False),
    sa.Column('biaya_rp', sa.Float(), nullable=False),
    sa.Column('latensi_ms', sa.Integer(), nullable=True),
    sa.Column('aktor', sa.String(length=80), nullable=False),
    sa.Column('outcome', sa.String(length=40), nullable=True),
    sa.Column('data', sa.JSON(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ledger_events_conversation_id'), 'ledger_events', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_ledger_events_objek_ref'), 'ledger_events', ['objek_ref'], unique=False)
    op.create_index(op.f('ix_ledger_events_product_id'), 'ledger_events', ['product_id'], unique=False)
    op.create_index(op.f('ix_ledger_events_tipe_event'), 'ledger_events', ['tipe_event'], unique=False)
    op.create_index(op.f('ix_ledger_events_trace_id'), 'ledger_events', ['trace_id'], unique=False)
    op.create_index(op.f('ix_ledger_events_verdict'), 'ledger_events', ['verdict'], unique=False)
    op.create_index(op.f('ix_ledger_events_waktu'), 'ledger_events', ['waktu'], unique=False)
    op.create_table('products',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('sku', sa.String(length=40), nullable=False),
    sa.Column('nama', sa.String(length=160), nullable=False),
    sa.Column('kategori', sa.String(length=80), nullable=False),
    sa.Column('komposisi', sa.Text(), nullable=False),
    sa.Column('kemasan', sa.String(length=160), nullable=False),
    sa.Column('satuan_grosir', sa.String(length=40), nullable=False),
    sa.Column('no_izin_edar', sa.String(length=60), nullable=False),
    sa.Column('harga_dasar', sa.Float(), nullable=False),
    sa.Column('moq', sa.Integer(), nullable=False),
    sa.Column('kata_kunci', sa.Text(), nullable=False),
    sa.Column('sumber_data', sa.String(length=20), nullable=False),
    sa.Column('aktif', sa.Boolean(), nullable=False),
    sa.Column('larangan', sa.JSON(), nullable=False),
    sa.Column('data_teknis', sa.JSON(), nullable=False),
    sa.Column('het_per_botol', sa.Float(), nullable=True),
    sa.Column('deskripsi', sa.Text(), nullable=False),
    sa.Column('stok', sa.Integer(), nullable=True),
    sa.Column('stok_per', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_products_sku'), 'products', ['sku'], unique=True)
    op.create_table('prospect_cache',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kunci', sa.String(length=200), nullable=False),
    sa.Column('sumber', sa.String(length=24), nullable=False),
    sa.Column('data', sa.JSON(), nullable=False),
    sa.Column('dibuat_pada', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_prospect_cache_kunci'), 'prospect_cache', ['kunci'], unique=True)
    op.create_table('prospects',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('nama', sa.String(length=200), nullable=False),
    sa.Column('alamat', sa.Text(), nullable=False),
    sa.Column('wilayah', sa.String(length=120), nullable=False),
    sa.Column('lat', sa.Float(), nullable=True),
    sa.Column('lng', sa.Float(), nullable=True),
    sa.Column('tipe', sa.String(length=24), nullable=False),
    sa.Column('telepon', sa.String(length=40), nullable=True),
    sa.Column('website', sa.String(length=300), nullable=True),
    sa.Column('rating', sa.Float(), nullable=True),
    sa.Column('jumlah_ulasan', sa.Integer(), nullable=True),
    sa.Column('jarak_km', sa.Float(), nullable=True),
    sa.Column('sudah_pelanggan', sa.Boolean(), nullable=False),
    sa.Column('skor', sa.Integer(), nullable=False),
    sa.Column('alasan_skor', sa.JSON(), nullable=False),
    sa.Column('draf_pesan', sa.Text(), nullable=False),
    sa.Column('draf_verdict', sa.String(length=16), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('catatan', sa.Text(), nullable=True),
    sa.Column('tindak_lanjut_pada', sa.DateTime(timezone=True), nullable=True),
    sa.Column('pic', sa.String(length=80), nullable=True),
    sa.Column('jaringan', sa.String(length=80), nullable=True),
    sa.Column('sumber', sa.String(length=24), nullable=False),
    sa.Column('eksternal_id', sa.String(length=120), nullable=True),
    sa.Column('jam_buka', sa.String(length=200), nullable=True),
    sa.Column('alamat_jalan_ada', sa.Boolean(), nullable=False),
    sa.Column('skor_geo', sa.Float(), nullable=False),
    sa.Column('skor_data', sa.Float(), nullable=False),
    sa.Column('terakhir_dipindai', sa.DateTime(timezone=True), nullable=True),
    sa.Column('market_analysis', sa.JSON(), nullable=True),
    sa.Column('nba', sa.JSON(), nullable=True),
    sa.Column('dibuat_pada', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_prospects_eksternal_id'), 'prospects', ['eksternal_id'], unique=False)
    op.create_index(op.f('ix_prospects_wilayah'), 'prospects', ['wilayah'], unique=False)
    op.create_table('settings',
    sa.Column('kunci', sa.String(length=40), nullable=False),
    sa.Column('nilai', sa.JSON(), nullable=False),
    sa.Column('diubah_oleh', sa.String(length=80), nullable=False),
    sa.Column('diubah_pada', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('kunci')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('nama', sa.String(length=120), nullable=False),
    sa.Column('email', sa.String(length=160), nullable=False),
    sa.Column('password_hash', sa.String(length=256), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_table('approved_claims',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=False),
    sa.Column('teks_klaim', sa.Text(), nullable=False),
    sa.Column('sumber_dokumen', sa.String(length=200), nullable=False),
    sa.Column('diverifikasi_oleh', sa.String(length=120), nullable=True),
    sa.Column('embedding', Vector(384), nullable=True),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_approved_claims_product_id'), 'approved_claims', ['product_id'], unique=False)
    op.create_table('chunks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('document_id', sa.Integer(), nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=True),
    sa.Column('teks', sa.Text(), nullable=False),
    sa.Column('halaman', sa.Integer(), nullable=True),
    sa.Column('embedding', Vector(384), nullable=True),
    sa.Column('versi', sa.Integer(), nullable=False),
    sa.Column('aktif', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_chunks_document_id'), 'chunks', ['document_id'], unique=False)
    op.create_index(op.f('ix_chunks_product_id'), 'chunks', ['product_id'], unique=False)
    op.create_table('contacts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('channel', sa.String(length=16), nullable=False),
    sa.Column('external_user_id', sa.String(length=64), nullable=False),
    sa.Column('wa_number', sa.String(length=32), nullable=True),
    sa.Column('nama_toko', sa.String(length=160), nullable=True),
    sa.Column('nama_wa', sa.String(length=120), nullable=True),
    sa.Column('tipe_toko', sa.String(length=40), nullable=True),
    sa.Column('alamat', sa.Text(), nullable=True),
    sa.Column('opt_in', sa.Boolean(), nullable=False),
    sa.Column('prospect_id', sa.Integer(), nullable=True),
    sa.Column('dibuat_pada', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['prospect_id'], ['prospects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_contacts_wa_number'), 'contacts', ['wa_number'], unique=False)
    op.create_index('uq_contact_kanal_id', 'contacts', ['channel', 'external_user_id'], unique=True)
    op.create_table('content_drafts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=True),
    sa.Column('tipe', sa.String(length=24), nullable=False),
    sa.Column('topik', sa.String(length=200), nullable=False),
    sa.Column('target', sa.String(length=24), nullable=False),
    sa.Column('judul', sa.String(length=200), nullable=False),
    sa.Column('isi', sa.Text(), nullable=False),
    sa.Column('faq', sa.JSON(), nullable=False),
    sa.Column('meta', sa.JSON(), nullable=False),
    sa.Column('json_ld', sa.JSON(), nullable=False),
    sa.Column('claim_verdict', sa.String(length=16), nullable=False),
    sa.Column('claim_report', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('dibuat_pada', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('ledger_hashes',
    sa.Column('seq', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('event_id', sa.Integer(), nullable=False),
    sa.Column('prev_hash', sa.String(length=64), nullable=False),
    sa.Column('hash', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['event_id'], ['ledger_events.id'], ),
    sa.PrimaryKeyConstraint('seq')
    )
    op.create_index(op.f('ix_ledger_hashes_event_id'), 'ledger_hashes', ['event_id'], unique=True)
    op.create_index(op.f('ix_ledger_hashes_hash'), 'ledger_hashes', ['hash'], unique=False)
    op.create_table('marketing_drafts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=False),
    sa.Column('teks', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('versi', sa.Integer(), nullable=False),
    sa.Column('dibuat_oleh', sa.Integer(), nullable=True),
    sa.Column('keputusan_oleh', sa.Integer(), nullable=True),
    sa.Column('keputusan_pada', sa.DateTime(timezone=True), nullable=True),
    sa.Column('catatan_keputusan', sa.Text(), nullable=True),
    sa.Column('dibuat_pada', sa.DateTime(timezone=True), nullable=False),
    sa.Column('diperbarui_pada', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['dibuat_oleh'], ['users.id'], ),
    sa.ForeignKeyConstraint(['keputusan_oleh'], ['users.id'], ),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_marketing_drafts_product_id'), 'marketing_drafts', ['product_id'], unique=False)
    op.create_index(op.f('ix_marketing_drafts_status'), 'marketing_drafts', ['status'], unique=False)
    op.create_table('pricing_rules',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=False),
    sa.Column('min_qty', sa.Integer(), nullable=False),
    sa.Column('diskon_maks_persen', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_pricing_rules_product_id'), 'pricing_rules', ['product_id'], unique=False)
    op.create_table('compliance_audits',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('audit_id', sa.String(length=32), nullable=False),
    sa.Column('idempotency_key', sa.String(length=80), nullable=True),
    sa.Column('product_sku', sa.String(length=40), nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=False),
    sa.Column('draft_id', sa.Integer(), nullable=True),
    sa.Column('draft_versi', sa.Integer(), nullable=True),
    sa.Column('input_text_hash', sa.String(length=64), nullable=False),
    sa.Column('text_length', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('stage', sa.String(length=16), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('violation_law', sa.Text(), nullable=True),
    sa.Column('regulatory_note', sa.Text(), nullable=True),
    sa.Column('matched_rules', sa.JSON(), nullable=False),
    sa.Column('evidence', sa.JSON(), nullable=False),
    sa.Column('references', sa.JSON(), nullable=False),
    sa.Column('recommendation', sa.Text(), nullable=True),
    sa.Column('recommendation_note', sa.Text(), nullable=True),
    sa.Column('rules_version', sa.String(length=24), nullable=False),
    sa.Column('engine_version', sa.String(length=40), nullable=False),
    sa.Column('model_provider', sa.String(length=40), nullable=True),
    sa.Column('model_name', sa.String(length=80), nullable=True),
    sa.Column('model_info', sa.JSON(), nullable=True),
    sa.Column('error_code', sa.String(length=40), nullable=True),
    sa.Column('status_draf_diperbarui', sa.Boolean(), nullable=False),
    sa.Column('duration_ms', sa.Integer(), nullable=False),
    sa.Column('actor_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['draft_id'], ['marketing_drafts.id'], ),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('idempotency_key')
    )
    op.create_index(op.f('ix_compliance_audits_audit_id'), 'compliance_audits', ['audit_id'], unique=True)
    op.create_index(op.f('ix_compliance_audits_created_at'), 'compliance_audits', ['created_at'], unique=False)
    op.create_index(op.f('ix_compliance_audits_draft_id'), 'compliance_audits', ['draft_id'], unique=False)
    op.create_index(op.f('ix_compliance_audits_product_id'), 'compliance_audits', ['product_id'], unique=False)
    op.create_index(op.f('ix_compliance_audits_product_sku'), 'compliance_audits', ['product_sku'], unique=False)
    op.create_index(op.f('ix_compliance_audits_status'), 'compliance_audits', ['status'], unique=False)
    op.create_table('conversations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('contact_id', sa.Integer(), nullable=False),
    sa.Column('kanal', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('intent_terakhir', sa.String(length=40), nullable=True),
    sa.Column('ditangani_oleh', sa.String(length=80), nullable=True),
    sa.Column('ditangani_sejak', sa.DateTime(timezone=True), nullable=True),
    sa.Column('aktivitas_staf_terakhir', sa.DateTime(timezone=True), nullable=True),
    sa.Column('konteks', sa.JSON(), nullable=False),
    sa.Column('diperbarui_pada', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_conversations_contact_id'), 'conversations', ['contact_id'], unique=False)
    op.create_table('approvals',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('objek_tipe', sa.String(length=24), nullable=False),
    sa.Column('objek_id', sa.Integer(), nullable=True),
    sa.Column('conversation_id', sa.Integer(), nullable=True),
    sa.Column('alasan', sa.Text(), nullable=False),
    sa.Column('ringkasan', sa.Text(), nullable=False),
    sa.Column('intent', sa.String(length=40), nullable=True),
    sa.Column('draf', sa.Text(), nullable=False),
    sa.Column('verdict', sa.String(length=16), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('ditinjau_oleh', sa.String(length=120), nullable=True),
    sa.Column('catatan', sa.Text(), nullable=True),
    sa.Column('trace_id', sa.String(length=40), nullable=True),
    sa.Column('dibuat_pada', sa.DateTime(timezone=True), nullable=False),
    sa.Column('diputus_pada', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_approvals_conversation_id'), 'approvals', ['conversation_id'], unique=False)
    op.create_table('messages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('conversation_id', sa.Integer(), nullable=False),
    sa.Column('arah', sa.String(length=8), nullable=False),
    sa.Column('pengirim', sa.String(length=8), nullable=False),
    sa.Column('teks', sa.Text(), nullable=False),
    sa.Column('status_kirim', sa.String(length=16), nullable=False),
    sa.Column('external_message_id', sa.String(length=120), nullable=True),
    sa.Column('verdict', sa.String(length=16), nullable=True),
    sa.Column('sumber', sa.JSON(), nullable=False),
    sa.Column('biaya_rp', sa.Float(), nullable=False),
    sa.Column('trace_id', sa.String(length=40), nullable=True),
    sa.Column('dibuat_pada', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_messages_conversation_id'), 'messages', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_messages_external_message_id'), 'messages', ['external_message_id'], unique=False)
    op.create_index(op.f('ix_messages_trace_id'), 'messages', ['trace_id'], unique=False)
    op.create_table('order_drafts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('contact_id', sa.Integer(), nullable=False),
    sa.Column('conversation_id', sa.Integer(), nullable=True),
    sa.Column('item', sa.JSON(), nullable=False),
    sa.Column('nama_toko', sa.String(length=160), nullable=True),
    sa.Column('alamat', sa.Text(), nullable=True),
    sa.Column('total', sa.Float(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('dibuat_pada', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_order_drafts_contact_id'), 'order_drafts', ['contact_id'], unique=False)
    op.create_table('permintaan_tak_terpenuhi',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('istilah', sa.String(length=160), nullable=False),
    sa.Column('pesan', sa.Text(), nullable=False),
    sa.Column('kanal', sa.String(length=16), nullable=False),
    sa.Column('contact_id', sa.Integer(), nullable=True),
    sa.Column('conversation_id', sa.Integer(), nullable=True),
    sa.Column('trace_id', sa.String(length=64), nullable=True),
    sa.Column('dibuat_pada', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_permintaan_tak_terpenuhi_conversation_id'), 'permintaan_tak_terpenuhi', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_permintaan_tak_terpenuhi_dibuat_pada'), 'permintaan_tak_terpenuhi', ['dibuat_pada'], unique=False)
    op.create_index(op.f('ix_permintaan_tak_terpenuhi_istilah'), 'permintaan_tak_terpenuhi', ['istilah'], unique=False)
    # Supabase membuka skema public lewat REST: tabel tidak boleh terlihat tanpa RLS. Pemilik tabel (API) tidak terkena RLS.
    tabel = [b[0] for b in op.get_bind().execute(sa.text(
        "SELECT tablename FROM pg_tables WHERE schemaname = current_schema() AND tablename <> 'alembic_version'"))]
    for nama in tabel:
        op.execute(f'ALTER TABLE "{nama}" ENABLE ROW LEVEL SECURITY')
    op.get_bind().exec_driver_sql(PELINDUNG_APPEND_ONLY)


def downgrade() -> None:
    raise RuntimeError("Migrasi awal tidak bisa dibatalkan: itu berarti menghapus semua tabel dan data.")
