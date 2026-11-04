"""Pelacak tahap percakapan sales dan deteksi sinyal pembeli. Murni aturan (deterministik): LLM tidak menentukan tahap.

Tahap giliran terakhir disimpan di konteks percakapan sebagai "tahap", sinyal giliran terakhir sebagai "sinyal".
Dipakai untuk mencatat & mengukur percakapan (eval/run_percakapan.py); aturan balasannya ada di router & drafter.
"""

import re

from .router import PESAN_ULANG, TINDAK_LANJUT

TAHAP = ("sapa", "gali_kebutuhan", "rekomendasi", "keberatan", "closing", "tindak_lanjut", "layanan")
SINYAL = ("niat_tinggi", "membandingkan", "penasaran", "repeat")

# Niat membeli: "mau pesan", "order 5", "ambil 2 box", "checkout". "min order" (tanya syarat) bukan niat.
_NIAT = re.compile(r"\b(?:mau|mo|ingin|pengen)\s+(?:pesan|pesen|order|ambil|beli)\b|\b(?:pesan|pesen|order|beli|ambil)\s+\d+\b"
                   r"|\bcheckout\b|\bpesan\b|\bpesen\b", re.I)
_MIN_ORDER = re.compile(r"\bmin(?:imal|imum)?\s+order\b", re.I)
_BANDING = re.compile(r"\bvs\b|\bmana yang\b|\bbedanya\b|\bbeda antara\b|\blebih (?:bagus|cocok|baik)\b|\bdibanding\w*", re.I)
_PENASARAN = re.compile(r"\b(?:cuma nanya|cuma tanya|sekadar|sekedar|penasaran|iseng|lihat-lihat|kira-kira|kira kira)\b", re.I)
_KEBERATAN = re.compile(r"\b(?:mahal\w*|kemahalan|keberatan|terlalu (?:mahal|tinggi)|diskon|potongan|nego|kurangi)\b", re.I)
_TINDAK = TINDAK_LANJUT

_SAPA = {"salam", "identitas", "luar_topik", "basa_basi", "sara", "manipulasi", "perusahaan", "media", "pembanding"}
_LAYANAN = {"darurat", "sensitif", "marah", "medis_personal", "keluhan", "tuduhan", "agama", "klaim_kesehatan",
            "minta_staf", "perlu_staf", "tunda_closing", "lokasi_cabang"}
_PRODUK = {"harga_moq", "tanya_produk", "spesifikasi", "izin_edar", "aturan_pakai"}


def _niat(text: str) -> bool:
    return bool(_NIAT.search(text)) and not _MIN_ORDER.search(text)


def tahap_baru(sebelumnya: str | None, intent: str, text: str, konteks: dict) -> str:
    """Tahap setelah giliran ini. Urutan prioritas: layanan sensitif > tindak lanjut > closing > keberatan > produk."""
    if intent in _LAYANAN:
        return "layanan"
    if intent in _SAPA:
        return sebelumnya or "sapa"
    niat = _niat(text) or intent in ("pesan", "pesan_ulang", "serah_sales")
    if _TINDAK.search(text) and not niat:
        return "tindak_lanjut"
    if niat:
        return "closing"
    if intent == "negosiasi" or _KEBERATAN.search(text):
        return "keberatan"
    if intent in _PRODUK:
        return "rekomendasi" if konteks.get("last_product_ids") else "gali_kebutuhan"
    return sebelumnya or "gali_kebutuhan"


def sinyal_baru(text: str, intent: str) -> list[str]:
    out = []
    if intent == "pesan_ulang" or PESAN_ULANG.search(text):
        out.append("repeat")
    if _niat(text):
        out.append("niat_tinggi")
    if _BANDING.search(text):
        out.append("membandingkan")
    if _PENASARAN.search(text):
        out.append("penasaran")
    return out
