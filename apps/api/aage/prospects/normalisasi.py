"""Validasi dan normalisasi satu lead, dipakai input manual, impor, dan ubah data."""

import re

from .mapper import wa_number

MAKS = {"nama": 200, "wilayah": 120, "alamat": 500, "website": 300, "jam_buka": 200, "telepon": 40}
_DOMAIN = re.compile(r"^https?://[a-z0-9.-]+\.[a-z]{2,}(?:[/?#]\S*)?$", re.I)
_RUMUS = ("=", "+", "-", "@", "\t", "\r")


def rapikan(teks) -> str:
    return " ".join(str(teks if teks is not None else "").split())


def _huruf(teks: str) -> str:
    return teks.title() if teks.islower() or teks.isupper() else teks


def _koordinat(teks: str, kolom: str, lo: float, hi: float, salah: list) -> float | None:
    if not teks:
        return None
    try:
        nilai = float(teks.replace(",", "."))
    except ValueError:
        salah.append({"kolom": kolom, "alasan": "Harus berupa angka desimal"})
        return None
    if not lo <= nilai <= hi:
        salah.append({"kolom": kolom, "alasan": f"Di luar wilayah Indonesia ({lo:g} sampai {hi:g})"})
        return None
    return nilai


def validasi(data: dict, segmen: list[str]) -> tuple[dict, list[dict]]:
    """Kembalikan (lead yang sudah rapi, daftar kesalahan). Tidak ada nilai yang ditebak: yang tidak sah dilaporkan."""
    salah: list[dict] = []
    nama = rapikan(data.get("nama"))
    wilayah = _huruf(rapikan(data.get("wilayah")))
    alamat = rapikan(data.get("alamat"))
    tipe_mentah = rapikan(data.get("tipe"))
    if len(nama) < 2:
        salah.append({"kolom": "nama", "alasan": "Wajib diisi, minimal 2 karakter"})
    elif nama.startswith(_RUMUS):
        salah.append({"kolom": "nama", "alasan": "Tidak boleh diawali karakter rumus (=, +, -, @)"})
    if len(wilayah) < 2:
        salah.append({"kolom": "wilayah", "alasan": "Wajib diisi, minimal 2 karakter"})
    if alamat.startswith(_RUMUS):
        salah.append({"kolom": "alamat", "alasan": "Tidak boleh diawali karakter rumus (=, +, -, @)"})
    tipe = next((s for s in segmen if s.lower() == tipe_mentah.lower()), None)
    if tipe is None:
        salah.append({"kolom": "tipe", "alasan": f"Harus salah satu dari: {', '.join(segmen)}"})

    telepon = rapikan(data.get("telepon"))
    if telepon and not wa_number(telepon):
        salah.append({"kolom": "telepon", "alasan": "Nomor tidak valid. Contoh: 0812-3456-7890 atau 024-8311234"})
    website = rapikan(data.get("website"))
    if website and not website.lower().startswith(("http://", "https://")):
        website = f"https://{website}"
    if website and not _DOMAIN.match(website):
        salah.append({"kolom": "website", "alasan": "Alamat website tidak valid"})
    lat = _koordinat(rapikan(data.get("lat")), "lat", -11.5, 6.5, salah)
    lng = _koordinat(rapikan(data.get("lng")), "lng", 94.5, 141.5, salah)
    if (lat is None) != (lng is None) and not any(s["kolom"] in ("lat", "lng") for s in salah):
        salah.append({"kolom": "lat" if lat is None else "lng", "alasan": "Lat dan lng harus diisi berpasangan"})
    jam_buka = rapikan(data.get("jam_buka"))
    bersih = {"nama": nama, "tipe": tipe, "wilayah": wilayah, "alamat": alamat, "telepon": telepon or None, "website": website or None,
              "lat": lat, "lng": lng, "jam_buka": jam_buka or None}
    for kolom, maks in MAKS.items():
        if len(bersih[kolom] or "") > maks:
            salah.append({"kolom": kolom, "alasan": f"Maksimal {maks} karakter"})
    return bersih, salah
