"""Logika dagang Sales Agent: tier diskon dari `pricing_rules` dan penyusunan draf pesanan."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Contact, OrderDraft, PricingRule, Product
from ..textutil import rupiah


@dataclass
class Quote:
    product: Product
    qty: int
    diskon_maks: float
    diskon: float
    harga_satuan: float
    subtotal: float
    total: float
    di_bawah_moq: bool
    tier_min: int | None


def tiers(db: Session, product_id: int) -> list[PricingRule]:
    return list(db.scalars(select(PricingRule).where(PricingRule.product_id == product_id).order_by(PricingRule.min_qty)))


def max_discount(db: Session, product: Product, qty: int) -> tuple[float, int | None]:
    best, tier_min = 0.0, None
    for r in tiers(db, product.id):
        if qty >= r.min_qty:
            best, tier_min = r.diskon_maks_persen, r.min_qty
    return best, tier_min


def quote(db: Session, product: Product, qty: int, diskon: float | None = None) -> Quote:
    maks, tier_min = max_discount(db, product, qty)
    applied = maks if diskon is None else min(diskon, maks)
    harga_satuan = product.harga_dasar * (1 - applied / 100)
    subtotal = product.harga_dasar * qty
    return Quote(product, qty, maks, applied, harga_satuan, subtotal, harga_satuan * qty, qty < product.moq, tier_min)


def tier_table(db: Session, product: Product) -> str:
    rows = tiers(db, product.id)
    if not rows:
        return "Belum ada tier diskon."
    return "; ".join(f"≥{r.min_qty} {product.satuan_grosir}: s.d. {r.diskon_maks_persen:g}%" for r in rows)


def format_quote(q: Quote) -> str:
    p = q.product
    lines = [f"Penawaran *{p.nama}* untuk {q.qty} {p.satuan_grosir}:"]
    lines.append(f"• Harga dasar {rupiah(p.harga_dasar)}/{p.satuan_grosir}")
    if q.diskon > 0:
        lines.append(f"• Diskon volume {q.diskon:g}% → {rupiah(q.harga_satuan)}/{p.satuan_grosir}")
    else:
        lines.append("• Belum masuk tier diskon (mulai 10 karton)")
    lines.append(f"• Total {rupiah(q.total)} (belum termasuk ongkos kirim)")
    if q.di_bawah_moq:
        lines.append(f"Catatan: minimum order {p.moq} {p.satuan_grosir}.")
    return "\n".join(lines)


def last_order(db: Session, contact_id: int) -> OrderDraft | None:
    return db.scalar(
        select(OrderDraft)
        .where(OrderDraft.contact_id == contact_id, OrderDraft.status != "ditolak")
        .order_by(OrderDraft.id.desc())
    )


def build_items(db: Session, lines: list[tuple[Product, int]]) -> tuple[list[dict], float]:
    items, total = [], 0.0
    for product, qty in lines:
        q = quote(db, product, qty)
        items.append({
            "product_id": product.id, "sku": product.sku, "nama": product.nama, "qty": qty,
            "satuan": product.satuan_grosir, "harga_satuan": round(q.harga_satuan), "diskon_persen": q.diskon,
            "subtotal": round(q.total),
        })
        total += q.total
    return items, round(total)


def format_order(items: list[dict], nama_toko: str | None, alamat: str | None, total: float) -> str:
    lines = [f"• {it['nama']} × {it['qty']} {it['satuan']} = {rupiah(it['subtotal'])}" for it in items]
    return (
        "\n".join(lines)
        + f"\nTotal perkiraan: {rupiah(total)} (belum termasuk ongkos kirim)"
        + (f"\nToko: {nama_toko}" if nama_toko else "")
        + (f"\nAlamat: {alamat}" if alamat else "")
    )


def ensure_contact_details(contact: Contact, slots: dict) -> None:
    if slots.get("nama_toko") and not contact.nama_toko:
        contact.nama_toko = slots["nama_toko"]
    if slots.get("alamat") and not contact.alamat:
        contact.alamat = slots["alamat"]
