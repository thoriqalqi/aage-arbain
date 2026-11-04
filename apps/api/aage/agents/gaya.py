"""Gaya bahasa LLM dengan kunci fakta: LLM hanya boleh menulis ulang draf template agar lebih luwes, tidak boleh
mengubah fakta. Hasil tulis ulang diperiksa deterministik; satu pelanggaran → draf template asli yang dipakai.

Yang dikunci: semua angka (harga, persen, jumlah, nomor izin edar, tanggal), teks *tebal* (nama produk), nama produk
katalog, frasa kejujuran/kebijakan ("belum ada", "dikonfirmasi staf", ...), jumlah pertanyaan, dan kata penekan
("buruan", "dijamin", ...) yang tidak ada di draf asli. ClaimGuard tetap memeriksa hasilnya sesudah ini.
"""

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import llm
from ..models import Product

# Cakupan: hanya balasan jualan biasa. Jalur sensitif, eskalasi, penolakan, identitas, negosiasi, kebijakan,
# dan ringkasan pesanan tetap memakai kata-kata template yang sudah disetujui.
CAKUPAN = {"salam", "basa_basi", "penutup", "tindak_lanjut", "klarifikasi", "harga_dasar", "harga_qty",
           "spesifikasi", "izin_edar", "tanya_produk"}

# Fakta angka = awalan Rp + angka + satuan. Satuan ikut dikunci agar "MOQ 10 box, diskon 5%" tidak bisa jadi
# "MOQ 5 box, diskon 10%", dan urutannya ikut dibandingkan agar dua nilai bersatuan sama tidak bisa ditukar.
_ANGKA = re.compile(r"(rp\.?\s?)?(\d+(?:[.,]\d+)*)\s*(?:/\s*|per\s+)?"
                    r"(%|(?:box|botol|sachet|saset|kapsul|tablet|pcs|karton|kardus|dus|lusin|pack|pouch|strip|kotak"
                    r"|gram|gr|g|kg|ml|liter|l|km|hari|minggu|bulan|tahun|jam|menit)\b)?", re.I)
_TEBAL = re.compile(r"\*([^*\n]+)\*")
_URL = re.compile(r"https?://\S+", re.I)
# Frasa yang, bila ada di draf asli, wajib tetap ada (kejujuran soal data & batas wewenang AI).
FRASA_KUNCI = ("belum ada", "dikonfirmasi staf", "staf", "izin edar", "diskon", "moq", "stok", "grosir", "halal",
               "bagikan nomor hp", "pesan", "tidak perlu buru-buru", "mulai", "stok belum ada", "belum ada di katalog",
               "belum ada datanya", "belum termasuk", "diskon volume", "bpom", "asisten ai")
# Kata yang tidak boleh muncul bila tidak ada di draf asli (desakan, janji, promo, klaim mutlak). Utuh per kata:
# "memastikan" bukan janji "pasti", tapi "menyembuhkan" dan "mengobati" tetap kena.
TERLARANG = re.compile(r"\b(?:buruan|segera|terbatas|kehabisan|dijamin|jaminan|pasti|promo|gratis|bonus|termurah"
                       r"|paling murah|ampuh|manjur|\w*sembuh\w*|\w*obat\w*|sumber\w*)\b|100\s?%|\[s\d", re.I)

PROMPT = (
    "Tulis ulang pesan WhatsApp dari asisten penjualan CV Arba'in di bawah ini supaya terdengar lebih luwes, hangat, "
    "dan manusiawi seperti sales yang ramah — tetap sopan, ringkas, bahasa Indonesia, sapa 'Kak'.\n"
    "ATURAN KERAS:\n"
    "- Jangan menambah, mengubah, atau menghapus fakta apa pun. Semua angka, harga, persen, jumlah box, nomor izin "
    "edar, tanggal, dan nama produk harus tertulis persis sama, dengan urutan penyebutan yang sama.\n"
    "- Pertahankan teks bertanda *tebal* persis apa adanya, dan pertahankan baris daftar (•) bila ada.\n"
    "- Jangan menambah klaim kesehatan, janji hasil, promo, bonus, atau kata yang mendesak pembeli.\n"
    "- Pertahankan kalimat yang jujur soal data yang belum ada dan soal konfirmasi oleh staf.\n"
    "- Jumlah pertanyaan harus sama dengan pesan asli (jumlah tanda tanya sama).\n"
    "- Jangan membuka dengan sapaan 'Halo' atau 'Hai' kecuali pesan asli memang salam; ini kelanjutan percakapan.\n"
    "- Jangan menyebut bahwa ini tulisan ulang. Kembalikan HANYA teks pesannya.\n\n"
    "PESAN ASLI:\n{teks}"
)


@dataclass
class HasilGaya:
    teks: str | None  # None = ditolak/gagal → pakai template asli
    alasan: str
    llm_result: llm.LLMResult | None = None
    pelanggaran: list[str] = field(default_factory=list)
    teks_ditolak: str | None = None


def _angka(teks: str) -> list[str]:
    """Fakta angka berurutan, mis. ['rp45000/box', '10/box', '3/%']."""
    return [("rp" if rp else "") + re.sub(r"[.,]", "", n) + (f"/{unit.lower()}" if unit else "")
            for rp, n, unit in _ANGKA.findall(teks)]


def _nama_produk(db: Session, teks: str) -> set[str]:
    t = teks.lower()
    return {n for n in db.scalars(select(Product.nama)) if n and n.lower() in t}


def periksa_fakta(db: Session, asli: str, baru: str) -> list[str]:
    """Daftar pelanggaran kunci fakta (kosong = aman dipakai)."""
    salah: list[str] = []
    a, b = asli.lower(), baru.lower()
    if _angka(asli) != _angka(baru):
        salah.append(f"angka berubah: {_angka(asli)} → {_angka(baru)}")
    for tebal in _TEBAL.findall(asli):
        if tebal.strip().lower() not in b:
            salah.append(f"teks tebal hilang: {tebal.strip()}")
    produk_asli, produk_baru = _nama_produk(db, asli), _nama_produk(db, baru)
    if produk_asli != produk_baru:
        salah.append(f"nama produk berubah: {sorted(produk_asli ^ produk_baru)}")
    salah += [f"frasa kunci hilang: {f}" for f in FRASA_KUNCI if f in a and f not in b]
    kata_asli = {w.lower() for w in TERLARANG.findall(asli)}
    salah += [f"kata terlarang ditambahkan: {w}" for w in sorted({w.lower() for w in TERLARANG.findall(baru)} - kata_asli)]
    if set(_URL.findall(baru)) - set(_URL.findall(asli)):
        salah.append("tautan baru ditambahkan")
    if baru.count("?") != asli.count("?"):
        salah.append("pertanyaan bertambah" if baru.count("?") > asli.count("?") else "pertanyaan hilang")
    if baru[-1:].isalnum() and not asli.rstrip()[-1:].isalnum():
        salah.append("teks terpotong")
    if asli.count("•") and baru.count("•") != asli.count("•"):
        salah.append("baris daftar berubah")
    if not (0.4 * len(asli) <= len(baru) <= 1.4 * len(asli) + 80):
        salah.append("panjang tidak wajar")
    return salah


def tulis_ulang(db: Session, teks: str) -> HasilGaya:
    """LLM menulis ulang draf; gagal/mati/tidak lolos kunci fakta → teks None (template asli tetap dipakai)."""
    try:
        res = llm.complete([{"role": "user", "content": PROMPT.format(teks=teks)}], max_tokens=1200, temperature=0.5)
    except Exception as exc:  # gangguan LLM tidak boleh menggagalkan balasan
        return HasilGaya(None, f"LLM gagal ({type(exc).__name__}) — template dipakai")
    if res is None:
        return HasilGaya(None, "LLM tidak tersedia — template dipakai")
    baru = res.text.strip().strip('"').strip()
    salah = periksa_fakta(db, teks, baru)
    if res.finish_reason in ("length", "MAX_TOKENS"):
        salah.append("teks terpotong: batas token model")
    if salah:
        return HasilGaya(None, "Kunci fakta menolak tulis ulang: " + "; ".join(salah[:3]), res, salah, baru)
    return HasilGaya(baru, "Gaya bahasa LLM lolos kunci fakta", res)
