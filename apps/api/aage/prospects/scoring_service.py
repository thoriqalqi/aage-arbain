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

VERSI_SKOR = "draf-geo-data-v0"  # draf, belum disetujui CV Arba'in

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


def opportunity_score(lead: dict) -> dict:
    """Kembalikan skor total + rincian transparan untuk ditampilkan di popup/tabel."""
    jarak = haversine_km(settings.gudang_lat, settings.gudang_lng, lead["latitude"], lead["longitude"])
    geo = geographic_fit(jarak)
    data = data_completeness(lead.get("phone"), lead.get("opening_hours"), lead.get("has_street", False))
    jaringan = national_chain(lead.get("name", ""), lead.get("brand"))
    penalti = PENALTI_JARINGAN if jaringan else 0
    lo, hi = settings.skor_zona_emas_min_km, settings.skor_zona_emas_max_km
    zona = "zona emas" if lo <= jarak <= hi else ("terlalu dekat gudang" if jarak < lo else "di luar zona emas")
    alasan = [
        {"faktor": "Geographic Fit", "poin": round(geo, 1), "maks": 70,
         "keterangan": f"{jarak:.2f} km dari {settings.gudang_nama} ({zona} {lo:g}–{hi:g} km)"},
        {"faktor": "Telepon", "poin": 10 if lead.get("phone") else 0, "maks": 10,
         "keterangan": lead.get("phone") or "tidak ada di OSM"},
        {"faktor": "Jam operasional", "poin": 10 if lead.get("opening_hours") else 0, "maks": 10,
         "keterangan": lead.get("opening_hours") or "tidak ada di OSM"},
        {"faktor": "Nama jalan", "poin": 10 if lead.get("has_street") else 0, "maks": 10,
         "keterangan": lead.get("address") if lead.get("has_street") else "tidak ada di OSM"},
    ]
    if jaringan:
        alasan.append({"faktor": "Jaringan nasional", "poin": -penalti, "maks": 0,
                       "keterangan": f"{jaringan} — pembelian umumnya terpusat di kantor pusat"})
    return {"skor": max(0, int(round(geo + data - penalti))), "skor_geo": round(geo, 1), "skor_data": data,
            "jarak_km": round(jarak, 2), "alasan": alasan, "jaringan": jaringan}
