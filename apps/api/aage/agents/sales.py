"""Logika dagang Sales Agent: tier diskon dari `pricing_rules` dan penyusunan draf pesanan."""

import re
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
        lines.append(f"• Belum masuk tier diskon (mulai 10 {p.satuan_grosir})")
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


def riwayat_terakhir(db: Session, contact: Contact) -> OrderDraft | None:
    """Pesanan terakhir pembeli ini, termasuk dari kontak di kanal lain dengan nomor HP yang sama (mis. dulu lewat
    WhatsApp, sekarang lewat Telegram setelah nomornya dibagikan/ditautkan staf)."""
    ids = [contact.id]
    if contact.wa_number:
        ids = list(db.scalars(select(Contact.id).where(Contact.wa_number == contact.wa_number))) or ids
    return db.scalar(select(OrderDraft).where(OrderDraft.contact_id.in_(ids), OrderDraft.status != "ditolak")
                     .order_by(OrderDraft.id.desc()))


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


_SEGMEN_RE = re.compile(r"\s*(?:\+|,|;|\n|&|\bdan\b|\bserta\b)\s*", re.IGNORECASE)
_ANGKA_RE = re.compile(r"(?<![\w-])(\d{1,4})(?!\w|\s*(?:mg|ml|g|gr|gram|iu|mcg|kapsul|tablet|sachet|%|persen))", re.IGNORECASE)


def parse_order_lines(db: Session, text: str) -> list[tuple[Product, int]]:
    """"10 box jahe merah + 5 box propolis" → [(Jahe Merah…, 10), (Propolis…, 5)]. Angka yang bagian dari nama
    produk ("Habbatussauda 120", "Omega-3") tidak dianggap jumlah."""
    from ..kb.retriever import find_products
    from .router import QTY_RE

    out: list[tuple[Product, int]] = []
    for seg in _SEGMEN_RE.split(text):
        found = find_products(db, seg, limit=1) if seg.strip() else []
        if not found or any(p.id == found[0].id for p, _ in out):
            continue
        p = found[0]
        m = QTY_RE.search(seg)
        qty = int(m.group(1)) if m else None
        if qty is None:
            name_nums = set(re.findall(r"\d+", p.nama))
            qty = next((int(a.group(1)) for a in _ANGKA_RE.finditer(seg) if a.group(1) not in name_nums), None)
        if qty:
            out.append((p, qty))
    return out


def moq_note(lines: list[tuple[Product, int]], min_campuran: int | None = None) -> str | None:
    """MOQ per produk dari katalog; pembelian campuran boleh bila total ≥ min_campuran (dari kebijakan, bila diatur)."""
    total = sum(q for _, q in lines)
    kurang = [p for p, q in lines if q < p.moq]
    if not kurang:
        return None
    if len(lines) > 1 and min_campuran and total >= min_campuran:
        return None
    if len(lines) > 1 and min_campuran:
        return f"Catatan: pembelian campuran minimal total {min_campuran} box (saat ini {total} box)."
    return f"Catatan: minimum order {kurang[0].moq} {kurang[0].satuan_grosir} per produk."


def ensure_contact_details(contact: Contact, slots: dict) -> None:
    if slots.get("nama_toko") and not contact.nama_toko:
        contact.nama_toko = slots["nama_toko"]
    if slots.get("alamat") and not contact.alamat:
        contact.alamat = slots["alamat"]
