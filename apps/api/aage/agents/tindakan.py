"""Peta tindakan sales per maksud dan profil pembeli. Berjalan sesudah draf dibuat, hanya menambah satu langkah berikutnya.

    profil    maksud      kondisi                 langkah
    reseller  kebijakan   kota belum ada          minta_kota
    reseller  kebijakan   kota ada                gali_volume
    reseller  harga       jumlah + produk ada     minta_identitas
    reseller  (lengkap)   nama atau toko ada      serah_staf (intent serah_sales)
    konsumen  kebijakan   -                       tawar_staf
    lama      kebijakan   -                       tawar_ulang

Semua angka berasal dari dokumen kebijakan atau tabel harga; bila kebijakannya tidak ada, kalimatnya dilewati.
"""

from sqlalchemy.orm import Session

from ..models import Conversation
from . import drafter


def _syarat_grosir(db: Session) -> list[str]:
    kalimat, _ = drafter._policy_sentences(db, [("Minimum order dan satuan", "MOQ"), ("Harga dan diskon volume", "Diskon volume")])
    return kalimat


def terapkan(db: Session, d: drafter.Draft, intent: str, conv: Conversation) -> drafter.Draft:
    if d.escalate or not d.text:
        return d
    sales = (conv.konteks or {}).get("sales") or {}
    profil = sales.get("profil")
    if d.template == "kebijakan" and intent == "kebijakan":
        return _setelah_kebijakan(db, d, profil, sales)
    if d.template == "harga_qty" and profil == "reseller" and not (sales.get("nama") or sales.get("toko")):
        penawaran = d.text.rsplit("\n\n", 1)[0]
        d.text = f"{penawaran}\n\nBoleh tahu nama Kakak dan nama tokonya? Nanti saya rangkumkan untuk staf penjualan."
        d.template = "harga_qty_sales"  # kalimat permintaan data tidak ikut ditulis ulang gaya bahasa LLM
        d.konteks = {**d.konteks, "langkah": "minta_identitas"}
    return d


def _setelah_kebijakan(db: Session, d: drafter.Draft, profil: str | None, sales: dict) -> drafter.Draft:
    if profil == "reseller":
        if not sales.get("kota"):
            d.text += "\n\nTokonya di kota mana, Kak? Supaya estimasi pengirimannya lebih tepat."
            d.konteks = {**d.konteks, "langkah": "minta_kota"}
            return d
        syarat = " ".join(_syarat_grosir(db))
        d.text += (f"\n\n{syarat}" if syarat else "") + "\n\nKira-kira mau stok produk apa dan berapa box, Kak?"
        d.konteks = {**d.konteks, "langkah": "gali_volume"}
    elif profil == "konsumen":
        syarat = _syarat_grosir(db)
        catatan = f"Perlu diketahui, penjualan kami grosir. {syarat[0]} " if syarat else ""
        d.text += f"\n\n{catatan}{drafter.TAWAR_STAF}"
        d.konteks = {**d.konteks, "tawar_staf": True, "langkah": "tawar_staf"}
    elif profil == "lama":
        d.text += "\n\nBalas *pesan ulang* bila ingin saya susunkan draf dari pesanan terakhir Kakak."
        d.konteks = {**d.konteks, "langkah": "tawar_ulang"}
    return d
