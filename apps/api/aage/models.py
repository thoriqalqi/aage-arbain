"""Model data AAGE (PRD §7). Satu database; `ledger_events` = sumber tunggal KPI dan audit."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from . import clock
from .config import get_settings
from .db import Base, IS_POSTGRES


class Embedding(TypeDecorator):
    """pgvector di Postgres, JSON array di SQLite."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(get_settings().embedding_dim))
        return dialect.type_descriptor(JSON())

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return [float(v) for v in value]


def _now() -> datetime:
    return clock.now()


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    nama: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16), default="staf")  # admin | staf


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    nama: Mapped[str] = mapped_column(String(160))
    kategori: Mapped[str] = mapped_column(String(80), default="")
    komposisi: Mapped[str] = mapped_column(Text, default="")
    kemasan: Mapped[str] = mapped_column(String(160), default="")
    satuan_grosir: Mapped[str] = mapped_column(String(40), default="karton")
    no_izin_edar: Mapped[str] = mapped_column(String(60), default="")
    harga_dasar: Mapped[float] = mapped_column(Float, default=0)  # per satuan grosir
    moq: Mapped[int] = mapped_column(Integer, default=1)
    kata_kunci: Mapped[str] = mapped_column(Text, default="")
    sumber_data: Mapped[str] = mapped_column(String(20), default="sintetis")
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)

    claims: Mapped[list["ApprovedClaim"]] = relationship(back_populates="product")
    pricing: Mapped[list["PricingRule"]] = relationship(back_populates="product", order_by="PricingRule.min_qty")


class ApprovedClaim(Base):
    __tablename__ = "approved_claims"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    teks_klaim: Mapped[str] = mapped_column(Text)
    sumber_dokumen: Mapped[str] = mapped_column(String(200), default="")
    diverifikasi_oleh: Mapped[str | None] = mapped_column(String(120), nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Embedding, nullable=True)

    product: Mapped[Product] = relationship(back_populates="claims")


class PricingRule(Base):
    __tablename__ = "pricing_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    min_qty: Mapped[int] = mapped_column(Integer)
    diskon_maks_persen: Mapped[float] = mapped_column(Float)

    product: Mapped[Product] = relationship(back_populates="pricing")


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    judul: Mapped[str] = mapped_column(String(200))
    tipe: Mapped[str] = mapped_column(String(20))  # katalog | pdf | docx | url | teks
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file: Mapped[str | None] = mapped_column(String(300), nullable=True)
    versi: Mapped[int] = mapped_column(Integer, default=1)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)
    diunggah_pada: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True, index=True)
    teks: Mapped[str] = mapped_column(Text)
    halaman: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Embedding, nullable=True)
    versi: Mapped[int] = mapped_column(Integer, default=1)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)

    document: Mapped[Document] = relationship()


class Contact(Base):
    __tablename__ = "contacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    wa_number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    nama_toko: Mapped[str | None] = mapped_column(String(160), nullable=True)
    tipe_toko: Mapped[str | None] = mapped_column(String(40), nullable=True)
    alamat: Mapped[str | None] = mapped_column(Text, nullable=True)
    opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    prospect_id: Mapped[int | None] = mapped_column(ForeignKey("prospects.id"), nullable=True)
    dibuat_pada: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    kanal: Mapped[str] = mapped_column(String(16), default="whatsapp")  # whatsapp | webchat
    status: Mapped[str] = mapped_column(String(16), default="otomatis")  # otomatis | eskalasi | ditahan
    intent_terakhir: Mapped[str | None] = mapped_column(String(40), nullable=True)
    konteks: Mapped[dict] = mapped_column(JSON, default=dict)
    diperbarui_pada: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    contact: Mapped[Contact] = relationship()
    messages: Mapped[list["Message"]] = relationship(order_by="Message.id", back_populates="conversation")


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    arah: Mapped[str] = mapped_column(String(8))  # masuk | keluar
    pengirim: Mapped[str] = mapped_column(String(8), default="pembeli")  # pembeli | ai | staf
    teks: Mapped[str] = mapped_column(Text)
    status_kirim: Mapped[str] = mapped_column(String(16), default="diterima")
    wa_message_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sumber: Mapped[list] = mapped_column(JSON, default=list)
    biaya_rp: Mapped[float] = mapped_column(Float, default=0)
    trace_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    dibuat_pada: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(primary_key=True)
    objek_tipe: Mapped[str] = mapped_column(String(24))  # balasan | order_draft | konten
    objek_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"), nullable=True, index=True)
    alasan: Mapped[str] = mapped_column(Text, default="")
    ringkasan: Mapped[str] = mapped_column(Text, default="")
    intent: Mapped[str | None] = mapped_column(String(40), nullable=True)
    draf: Mapped[str] = mapped_column(Text, default="")
    verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="menunggu")  # menunggu | disetujui | ditolak
    ditinjau_oleh: Mapped[str | None] = mapped_column(String(120), nullable=True)
    catatan: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    dibuat_pada: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    diputus_pada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OrderDraft(Base):
    __tablename__ = "order_drafts"
    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    item: Mapped[list] = mapped_column(JSON, default=list)
    nama_toko: Mapped[str | None] = mapped_column(String(160), nullable=True)
    alamat: Mapped[str | None] = mapped_column(Text, nullable=True)
    total: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(32), default="menunggu konfirmasi staf")
    dibuat_pada: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ContentDraft(Base):
    __tablename__ = "content_drafts"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    tipe: Mapped[str] = mapped_column(String(24))  # artikel | deskripsi
    topik: Mapped[str] = mapped_column(String(200), default="")
    target: Mapped[str] = mapped_column(String(24), default="apotek")
    judul: Mapped[str] = mapped_column(String(200), default="")
    isi: Mapped[str] = mapped_column(Text, default="")
    faq: Mapped[list] = mapped_column(JSON, default=list)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    json_ld: Mapped[list] = mapped_column(JSON, default=list)
    claim_verdict: Mapped[str] = mapped_column(String(16), default="review")
    claim_report: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="draf")  # draf | disetujui | ditolak
    dibuat_pada: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Prospect(Base):
    __tablename__ = "prospects"
    id: Mapped[int] = mapped_column(primary_key=True)
    nama: Mapped[str] = mapped_column(String(200))
    alamat: Mapped[str] = mapped_column(Text, default="")
    wilayah: Mapped[str] = mapped_column(String(120), index=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    tipe: Mapped[str] = mapped_column(String(24))
    telepon: Mapped[str | None] = mapped_column(String(40), nullable=True)
    website: Mapped[str | None] = mapped_column(String(300), nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    jumlah_ulasan: Mapped[int | None] = mapped_column(Integer, nullable=True)
    jarak_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    sudah_pelanggan: Mapped[bool] = mapped_column(Boolean, default=False)
    skor: Mapped[int] = mapped_column(Integer, default=0)
    alasan_skor: Mapped[list] = mapped_column(JSON, default=list)
    draf_pesan: Mapped[str] = mapped_column(Text, default="")
    draf_verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="baru")  # baru | dihubungi | merespons | menolak
    sumber: Mapped[str] = mapped_column(String(24))  # google_places | osm | sintetis
    eksternal_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    dibuat_pada: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ProspectCache(Base):
    __tablename__ = "prospect_cache"
    id: Mapped[int] = mapped_column(primary_key=True)
    kunci: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    sumber: Mapped[str] = mapped_column(String(24))
    data: Mapped[list] = mapped_column(JSON, default=list)
    dibuat_pada: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class LedgerEvent(Base):
    """Append-only. Dijaga di ORM (listener di bawah) dan di Postgres (trigger, lihat db.py)."""

    __tablename__ = "ledger_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    waktu: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    tipe_event: Mapped[str] = mapped_column(String(40), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    conversation_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    objek_ref: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    sumber_ref: Mapped[list] = mapped_column(JSON, default=list)
    ringkasan: Mapped[str] = mapped_column(Text, default="")
    alasan: Mapped[str] = mapped_column(Text, default="")
    verdict: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    aturan_terpicu: Mapped[list] = mapped_column(JSON, default=list)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    token_in: Mapped[int] = mapped_column(Integer, default=0)
    token_out: Mapped[int] = mapped_column(Integer, default=0)
    biaya_rp: Mapped[float] = mapped_column(Float, default=0)
    latensi_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    aktor: Mapped[str] = mapped_column(String(80), default="AI")
    outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class LedgerImmutableError(RuntimeError):
    pass


@event.listens_for(LedgerEvent, "before_update")
def _block_update(*_):
    raise LedgerImmutableError("ledger_events bersifat append-only: event tidak boleh diubah")


@event.listens_for(LedgerEvent, "before_delete")
def _block_delete(*_):
    raise LedgerImmutableError("ledger_events bersifat append-only: event tidak boleh dihapus")
