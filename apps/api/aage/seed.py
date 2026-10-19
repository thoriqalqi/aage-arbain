"""Seed / reset data demo dengan satu perintah:  python -m aage.seed  (tambahkan --tanpa-riwayat untuk DB kosong).

Katalog: config/mock_products.json (50 produk SIMULASI). Ganti dengan data resmi mitra saat tersedia."""

import argparse
import json
import random
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from . import clock
from .db import SessionLocal, init_db
from .kb.ingest import import_catalog, import_pricing, ingest_document, rows_from_products_json
from .models import Contact, OrderDraft, Product, User
from .security import hash_password

DATA = Path(__file__).resolve().parent.parent / "data"
PRODUCTS_JSON = Path(__file__).resolve().parent.parent / "config" / "mock_products.json"

DEMO_USERS = [
    ("Admin AAGE", "admin@aage.local", "admin123", "admin"),
    ("Staf Sales", "staf@aage.local", "staf123", "staf"),
]

DEMO_CONTACTS = [
    ("6281200000001", "Apotek Sehat Sentosa", "apotek", "Jl. Pandanaran No. 12, Semarang", True,
     [("ARB-002", 20), ("ARB-006", 10)]),
    ("6281200000002", "Toko Obat Barokah", "toko obat", "Jl. Majapahit No. 88, Semarang", True,
     [("ARB-001", 15), ("ARB-005", 10)]),
    ("6281200000003", "Minimarket Mitra Jaya", "minimarket", "Jl. Setiabudi No. 5, Semarang", False, []),
    ("6281200000004", "Apotek Keluarga Ungaran", "apotek", "Jl. Diponegoro No. 40, Ungaran", True,
     [("ARB-017", 12)]),
]

# Percakapan historis (dijalankan lewat pipeline yang sama, dengan jam digeser ke masa lalu)
HISTORY = [
    ["Halo kak", "ada produk untuk daya tahan tubuh?", "harga 30 karton berapa?"],
    ["ada madu buat anak susah makan?", "izin edarnya apa?"],
    ["bisa sembuhkan diabetes?"],
    ["harga 50 karton propolis tetes berapa?", "bisa diskon 25%?"],
    ["pesan ulang seperti bulan lalu"],
    ["produk untuk stamina apa saja?", "harga 100 karton madu stamina?", "bisa diskon 10%?"],
    ["paket kemarin datang tapi 2 botol pecah"],
    ["pengiriman ke Solo berapa hari?"],
    ["ada minyak untuk pegal linu?", "MOQ nya berapa?"],
    ["saya sedang hamil, boleh minum kapsul habbatussauda?"],
    ["ada yang bisa obati asam urat?"],
    ["pembayaran bisa tempo?"],
    ["ada jahe merah instan?", "pesan 20 karton jahe merah instan"],
    ["temulawak ada kak?", "harga 10 karton?"],
    ["ada produk untuk tidur nyenyak?"],
]


def seed_base(db) -> None:
    for nama, email, pw, role in DEMO_USERS:
        if db.scalar(select(User).where(User.email == email)) is None:
            db.add(User(nama=nama, email=email, password_hash=hash_password(pw), role=role))
    db.commit()

    data = json.loads(PRODUCTS_JSON.read_text(encoding="utf-8"))
    rows, tiers = rows_from_products_json(data)
    import_catalog(db, rows, judul="Katalog Produk (data simulasi)", aktor="seed", verifikator="Tim Djuaraumm (simulasi)")
    import_pricing(db, tiers)
    for path in sorted((DATA / "dokumen").glob("*.md")):
        title = path.read_text(encoding="utf-8").splitlines()[0].lstrip("# ").strip()
        ingest_document(db, judul=title, text=path.read_text(encoding="utf-8"), tipe="teks", aktor="seed")

    for wa, toko, tipe, alamat, opt_in, orders in DEMO_CONTACTS:
        c = Contact(wa_number=wa, nama_toko=toko, tipe_toko=tipe, alamat=alamat, opt_in=opt_in)
        db.add(c)
        db.flush()
        if orders:
            from .agents.sales import build_items

            lines = [(db.scalar(select(Product).where(Product.sku == sku)), q) for sku, q in orders]
            items, total = build_items(db, lines)
            with clock.frozen_at(clock.now() - timedelta(days=32)):
                db.add(OrderDraft(contact_id=c.id, item=items, nama_toko=toko, alamat=alamat, total=total,
                                  status="selesai", dibuat_pada=clock.now()))
    db.commit()


def seed_history(db, days: int = 14) -> None:
    """Jalankan percakapan contoh melalui pipeline asli agar KPI & Ledger berisi data nyata dari sistem."""
    from .agents.graph import handle_inbound
    from .approvals import decide
    from .models import Approval

    rng = random.Random(42)
    staf = db.scalar(select(User).where(User.role == "staf"))
    base = clock.now().replace(hour=8, minute=0, second=0, microsecond=0) - timedelta(days=days)
    n = 0
    for day in range(days):
        for _ in range(rng.randint(1, 3)):
            script = HISTORY[n % len(HISTORY)]
            n += 1
            wa = f"62813{rng.randint(10_000_000, 99_999_999)}"
            if "pesan ulang" in script[0]:
                wa = DEMO_CONTACTS[n % 2][0]
            t = base + timedelta(days=day, hours=rng.randint(0, 13), minutes=rng.randint(0, 59))
            last = None
            for text in script:
                with clock.frozen_at(t):
                    last = handle_inbound(db, wa_number=wa, text=text, kanal="whatsapp")
                t += timedelta(minutes=rng.randint(1, 6))
            # Sebagian besar approval diputus staf (agar funnel/KPI realistis), sisanya tetap menunggu.
            if last and last.approval_id and day < days - 1:
                ap = db.get(Approval, last.approval_id)
                if ap and ap.status == "menunggu" and ap.draf:
                    with clock.frozen_at(t + timedelta(minutes=rng.randint(5, 40))):
                        try:
                            decide(db, ap.id, aksi="setujui", user=staf)
                        except Exception:
                            db.rollback()


def seed_prospect_funnel(db, prospects) -> None:
    """Simulasi tindak lanjut staf atas prospek teratas (dicatat di Ledger sebagai aktor seed-demo)."""
    from .prospects.mapper import update_status

    for i, p in enumerate(prospects[:18]):
        update_status(db, p.id, "dihubungi", "staf:seed-demo")
        if i < 10:
            update_status(db, p.id, "merespons", "staf:seed-demo")
        elif i < 12:
            update_status(db, p.id, "menolak", "staf:seed-demo")


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset & seed data demo AAGE")
    parser.add_argument("--tanpa-riwayat", action="store_true", help="hanya data dasar, tanpa percakapan historis")
    args = parser.parse_args()
    init_db(drop=True)
    with SessionLocal() as db:
        seed_base(db)
        if not args.tanpa_riwayat:
            seed_history(db)
            from .prospects.mapper import search_prospects

            res = search_prospects(db, wilayah="Kota Semarang", tipe="apotek", aktor="seed", allow_network=False)
            seed_prospect_funnel(db, res["prospects"])
    print("Seed selesai. Login: admin@aage.local / admin123 · staf@aage.local / staf123")


if __name__ == "__main__":
    main()
