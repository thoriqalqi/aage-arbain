"""Memori ringkasan percakapan: catatan singkat yang disusun aturan (bukan LLM), disimpan di konteks["memori"].

Isi: produk yang dibahas, jumlah yang ditanyakan, kebutuhan, keberatan, nama toko, tahap, dan penanda bahwa ada
pertanyaan kesehatan (tanpa rinciannya). Dipakai sebagai konteks LLM (bukan sumber fakta) dan ringkasan untuk staf.
Kedaluwarsa setelah `memori_retensi_hari` tanpa aktivitas — percakapan baru mulai dari catatan kosong.
"""

import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..config import get_settings
from ..models import Product

MAKS_PRODUK = 5
_KEBUTUHAN = re.compile(r"\b(?:untuk|buat|bwt|utk)\s+([a-z][a-z\s-]{2,40}?)\s*\??$", re.I)
_KEBERATAN_HARGA = re.compile(r"\b(?:mahal\w*|kemahalan|terlalu (?:mahal|tinggi)|diskon|potongan|nego\w*|kurangi)\b",
                              re.I)
_KESEHATAN = {"medis_personal", "darurat", "sensitif"}


def kedaluwarsa(memori: dict | None, now: datetime | None = None) -> bool:
    if not memori or not memori.get("diperbarui"):
        return False
    try:
        terakhir = datetime.fromisoformat(memori["diperbarui"])
    except ValueError:
        return True
    now = now or clock.now()
    if terakhir.tzinfo is None and now.tzinfo is not None:
        terakhir = terakhir.replace(tzinfo=now.tzinfo)
    return now - terakhir > timedelta(days=get_settings().memori_retensi_hari)


def produk_usang(db: Session, konteks: dict) -> dict:
    """Bagian konteks yang masih menunjuk produk yang sudah nonaktif atau terhapus, sudah dibersihkan.

    Katalog bisa diganti di tengah percakapan. Membersihkan di satu pintu masuk ini berarti semua langkah agent sesudahnya
    hanya melihat produk yang masih ada. Kosong bila tidak ada yang usang.
    """
    pending, kutipan = konteks.get("order_pending") or {}, konteks.get("last_quote") or {}
    baris, baris_pending = konteks.get("last_lines") or [], pending.get("lines") or []
    ids = {*(konteks.get("last_product_ids") or []), *(pending.get("product_ids") or []), kutipan.get("product_id"),
           *(b[0] for b in baris), *(b[0] for b in baris_pending)} - {None}
    m, sales = konteks.get("memori") or {}, konteks.get("sales") or {}
    nama = {*(m.get("produk") or []), *(m.get("jumlah") or {}), sales.get("produk")} - {None}
    if not ids and not nama:
        return {}
    ada_id = set(db.scalars(select(Product.id).where(Product.id.in_(ids), Product.aktif.is_(True)))) if ids else set()
    ada_nama = set(db.scalars(select(Product.nama).where(Product.nama.in_(nama), Product.aktif.is_(True)))) if nama else set()
    if ids <= ada_id and nama <= ada_nama:
        return {}

    out = {}
    if "last_product_ids" in konteks:
        out["last_product_ids"] = [i for i in konteks["last_product_ids"] or [] if i in ada_id]
    if kutipan.get("product_id") not in ada_id:
        out["last_quote"] = None
    if any(b[0] not in ada_id for b in baris):
        out["last_lines"] = None
    if pending:
        sisa = [i for i in pending.get("product_ids") or [] if i in ada_id]
        lines = [b for b in baris_pending if b[0] in ada_id]
        out["order_pending"] = {**pending, "product_ids": sisa, "lines": lines} if sisa else None
        if out["order_pending"] and not lines:
            out["order_pending"].pop("lines")
    if m:
        out["memori"] = {**m, "produk": [n for n in m.get("produk") or [] if n in ada_nama],
                         "jumlah": {n: q for n, q in (m.get("jumlah") or {}).items() if n in ada_nama}}
    if sales.get("produk") and sales["produk"] not in ada_nama:
        out["sales"] = {k: v for k, v in sales.items() if k != "produk"}
    return out


def _tambah(daftar: list[str], item: str, maks: int) -> list[str]:
    return ([x for x in daftar if x != item] + [item])[-maks:]


def perbarui(db: Session, memori: dict | None, *, text: str, intent: str, slots: dict, product_ids: list[int],
             tahap: str | None, order_draft_id: int | None = None) -> dict:
    m = {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v)
         for k, v in (memori or {}).items()}
    nama = [p.nama for pid in product_ids if (p := db.get(Product, pid)) is not None]
    for n in nama:
        m["produk"] = _tambah(m.get("produk", []), n, MAKS_PRODUK)
    if (qty := slots.get("qty")) and len(nama) == 1:
        m["jumlah"] = {**m.get("jumlah", {}), nama[0]: int(qty)}
    if intent == "tanya_produk" and (k := _KEBUTUHAN.search(text.strip())):
        m["kebutuhan"] = _tambah(m.get("kebutuhan", []), k.group(1).strip().lower(), 3)
    if intent == "negosiasi" or _KEBERATAN_HARGA.search(text):
        m["keberatan"] = _tambah(m.get("keberatan", []), "harga", 3)
    if intent == "tindak_lanjut":
        m["keberatan"] = _tambah(m.get("keberatan", []), "ingin menimbang dulu", 3)
    if slots.get("nama_toko"):
        m["toko"] = str(slots["nama_toko"])[:80]
    if intent in _KESEHATAN:
        m["kesehatan"] = True  # hanya penanda; isi pertanyaannya tidak disimpan di memori
    if order_draft_id:
        m["pesanan"] = f"draf #{order_draft_id} menunggu konfirmasi staf"
    if tahap:
        m["tahap"] = tahap
    m["diperbarui"] = clock.now().isoformat()
    return m


def teks(memori: dict | None) -> str:
    """Satu baris ringkas untuk prompt LLM & ringkasan approval. Kosong bila belum ada isi."""
    if not memori:
        return ""
    bagian = []
    if memori.get("produk"):
        bagian.append("produk dibahas: " + ", ".join(memori["produk"]))
    if memori.get("jumlah"):
        bagian.append("jumlah ditanyakan: " + ", ".join(f"{n} {q}" for n, q in memori["jumlah"].items()))
    if memori.get("kebutuhan"):
        bagian.append("kebutuhan: " + ", ".join(memori["kebutuhan"]))
    if memori.get("keberatan"):
        bagian.append("keberatan: " + ", ".join(memori["keberatan"]))
    if memori.get("toko"):
        bagian.append(f"toko: {memori['toko']}")
    if memori.get("kesehatan"):
        bagian.append("ada pertanyaan kesehatan (ditangani staf)")
    if memori.get("pesanan"):
        bagian.append(f"pesanan: {memori['pesanan']}")
    if memori.get("tahap"):
        bagian.append(f"tahap: {memori['tahap'].replace('_', ' ')}")
    return " · ".join(bagian)
