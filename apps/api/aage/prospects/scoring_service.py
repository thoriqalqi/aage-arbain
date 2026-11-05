"""Opportunity Score (0–100) deterministik — fungsi matematika murni, tanpa LLM.

    Geographic Fit (maks 70)  jarak Haversine ke Pusat Logistik (GUDANG_LAT/GUDANG_LNG di .env)
        < 2 km   naik linear dari SKOR_GEO_DI_GUDANG (35) di 0 km ke 70 di 2 km
        2–8 km   zona emas → 70 penuh
        > 8 km   turun linear dari 70 ke 0 di SKOR_JARAK_NOL_KM (30 km)
    Data Completeness (maks 30)  telepon +10 · jam operasional +10 · nama jalan (addr:street) +10
    Penyesuaian jaringan (−25)  cabang jaringan nasional (Kimia Farma, K-24, Guardian, Indomaret, …) umumnya
                                 membeli lewat kantor pusat, jadi bukan target utama sales lapangan distributor
"""

import math
import re

from ..config import get_settings

VERSI_SKOR = "draf-geo-data-v0"  # draf, belum disetujui CV Arba'in. Versi berjalan ada di konfigurasi.py
BOBOT_AWAL = {"geo_maks": 70, "telepon": 10, "jam": 10, "jalan": 10, "penalti_jaringan": 25}

settings = get_settings()
R_BUMI_KM = 6371.0088


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_BUMI_KM * math.asin(math.sqrt(a))


def geographic_fit(jarak_km: float) -> float:
    lo, hi = settings.skor_zona_emas_min_km, settings.skor_zona_emas_max_km
    nol, dekat = settings.skor_jarak_nol_km, settings.skor_geo_di_gudang
    if jarak_km < lo:
        return dekat + (70 - dekat) * (jarak_km / lo)
    if jarak_km <= hi:
        return 70.0
    if jarak_km >= nol:
        return 0.0
    return 70.0 * (1 - (jarak_km - hi) / (nol - hi))


def data_completeness(phone: str | None, opening_hours: str | None, has_street: bool) -> float:
    return (10.0 if phone else 0.0) + (10.0 if opening_hours else 0.0) + (10.0 if has_street else 0.0)


PENALTI_JARINGAN = 25
_JARINGAN = {
    r"kimia\s*farma": "Kimia Farma", r"\bk[\s-]?24\b|apotek\s*k24": "K-24", r"guardian": "Guardian",
    r"century": "Century", r"watsons": "Watsons", r"\broxy\b": "Roxy", r"indomaret": "Indomaret", r"alfa\s*(?:mart|midi|express)": "Alfamart",
    r"lawson": "Lawson", r"family\s*mart": "FamilyMart", r"circle\s*k": "Circle K", r"superindo": "Superindo",
}


def national_chain(name: str, brand: str | None = None) -> str | None:
    hay = f"{name} {brand or ''}".lower()
    return next((label for pola, label in _JARINGAN.items() if re.search(pola, hay)), None)


def opportunity_score(lead: dict, bobot: dict | None = None) -> dict:
    """Kembalikan skor total + rincian transparan untuk ditampilkan di popup/tabel. Nomor telepon tidak ikut ke rincian."""
    b = {**BOBOT_AWAL, **(bobot or {})}
    asal = lead.get("asal", "OSM")
    lat, lng = lead.get("latitude"), lead.get("longitude")
    lo, hi = settings.skor_zona_emas_min_km, settings.skor_zona_emas_max_km
    if lat is None or lng is None:
        jarak, geo = None, 0.0
        ket_geo = "Koordinat belum ada, jarak tidak bisa dihitung"
    else:
        jarak = haversine_km(settings.gudang_lat, settings.gudang_lng, lat, lng)
        geo = geographic_fit(jarak) * b["geo_maks"] / 70
        zona = "zona emas" if lo <= jarak <= hi else ("terlalu dekat gudang" if jarak < lo else "di luar zona emas")
        ket_geo = f"{jarak:.2f} km dari {settings.gudang_nama} ({zona} {lo:g}–{hi:g} km)"
    data = (b["telepon"] if lead.get("phone") else 0.0) + (b["jam"] if lead.get("opening_hours") else 0.0) + (b["jalan"] if lead.get("has_street") else 0.0)
    jaringan = national_chain(lead.get("name", ""), lead.get("brand"))
    penalti = b["penalti_jaringan"] if jaringan else 0
    alasan = [
        {"faktor": "Geographic Fit", "poin": round(geo, 1), "maks": b["geo_maks"], "keterangan": ket_geo},
        {"faktor": "Telepon", "poin": b["telepon"] if lead.get("phone") else 0, "maks": b["telepon"],
         "keterangan": "Tersedia" if lead.get("phone") else f"tidak ada di {asal}"},
        {"faktor": "Jam operasional", "poin": b["jam"] if lead.get("opening_hours") else 0, "maks": b["jam"],
         "keterangan": lead.get("opening_hours") or f"tidak ada di {asal}"},
        {"faktor": "Nama jalan", "poin": b["jalan"] if lead.get("has_street") else 0, "maks": b["jalan"],
         "keterangan": lead.get("address") if lead.get("has_street") else f"tidak ada di {asal}"},
    ]
    if jaringan:
        alasan.append({"faktor": "Jaringan nasional", "poin": -penalti, "maks": 0,
                       "keterangan": f"{jaringan} — pembelian umumnya terpusat di kantor pusat"})
    return {"skor": max(0, min(100, int(round(geo + data - penalti)))), "skor_geo": round(geo, 1), "skor_data": data,
            "jarak_km": round(jarak, 2) if jarak is not None else None, "alasan": alasan, "jaringan": jaringan}


def rincian_confidence(lead: dict, terverifikasi: bool) -> list[dict]:
    """Seberapa lengkap dan terperiksa datanya, bukan peluang lead membeli. Draf: tiap butir bernilai 0,2."""
    return [
        {"faktor": "Koordinat", "ada": lead.get("latitude") is not None and lead.get("longitude") is not None},
        {"faktor": "Nomor telepon", "ada": bool(lead.get("phone"))},
        {"faktor": "Alamat jalan", "ada": bool(lead.get("has_street"))},
        {"faktor": "Jam buka atau website", "ada": bool(lead.get("opening_hours") or lead.get("website"))},
        {"faktor": "Diverifikasi staf", "ada": terverifikasi},
    ]


def confidence(lead: dict, terverifikasi: bool) -> float:
    return round(sum(0.2 for r in rincian_confidence(lead, terverifikasi) if r["ada"]), 2)
