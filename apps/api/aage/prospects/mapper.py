"""Prospect Mapper (M7): cari apotek/toko obat/minimarket per wilayah, skor 0–100 yang bisa
dijelaskan, dan draf pesan pembuka yang lolos ClaimGuard. Staf yang mengirim — tidak ada pesan massal."""

import csv
import io
import logging
import math
import random
import time

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import claimguard, ledger, llm
from ..config import get_settings
from ..models import Contact, Prospect, ProspectCache

log = logging.getLogger("aage.prospek")
settings = get_settings()

TIPE = {
    "apotek": {"label": "Apotek", "places": "apotek", "osm": ['"amenity"="pharmacy"'], "poin": 30},
    "toko obat": {"label": "Toko Obat", "places": "toko obat", "osm": ['"shop"="chemist"', '"healthcare"="pharmacy"'], "poin": 25},
    "minimarket": {"label": "Minimarket", "places": "minimarket", "osm": ['"shop"="convenience"', '"shop"="supermarket"'], "poin": 15},
}
STATUSES = ["baru", "dihubungi", "merespons", "menolak"]
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

# Titik pusat beberapa kota (cadangan bila geocoding tidak tersedia)
CITY_CENTERS = {
    "kota semarang": (-6.9932, 110.4203), "semarang": (-6.9932, 110.4203), "kabupaten semarang": (-7.1394, 110.4040),
    "ungaran": (-7.1394, 110.4040), "surakarta": (-7.5695, 110.8290), "solo": (-7.5695, 110.8290),
    "kota surakarta": (-7.5695, 110.8290), "yogyakarta": (-7.7956, 110.3695), "kudus": (-6.8048, 110.8405),
    "salatiga": (-7.3305, 110.5084), "demak": (-6.8909, 110.6396), "kendal": (-6.9196, 110.2033),
    "magelang": (-7.4797, 110.2177), "pekalongan": (-6.8898, 109.6746), "jakarta": (-6.2088, 106.8456),
}


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ------------------------------------------------------------------ sumber data


def _google_places(wilayah: str, tipe: str) -> list[dict]:
    out: list[dict] = []
    token = None
    for _ in range(3):
        body = {"textQuery": f"{TIPE[tipe]['places']} di {wilayah}", "languageCode": "id", "regionCode": "ID",
                "pageSize": 20}
        if token:
            body["pageToken"] = token
        resp = httpx.post(
            "https://places.googleapis.com/v1/places:searchText", json=body, timeout=12,
            headers={"X-Goog-Api-Key": settings.google_places_api_key,
                     "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.location,"
                                         "places.rating,places.userRatingCount,places.nationalPhoneNumber,"
                                         "places.websiteUri,nextPageToken"},
        )
        resp.raise_for_status()
        data = resp.json()
        for p in data.get("places", []):
            out.append({
                "eksternal_id": p["id"], "nama": p.get("displayName", {}).get("text", "-"),
                "alamat": p.get("formattedAddress", ""), "lat": p.get("location", {}).get("latitude"),
                "lng": p.get("location", {}).get("longitude"), "rating": p.get("rating"),
                "jumlah_ulasan": p.get("userRatingCount"), "telepon": p.get("nationalPhoneNumber"),
                "website": p.get("websiteUri"),
            })
        token = data.get("nextPageToken")
        if not token:
            break
        time.sleep(1.5)
    return out


def _geocode(wilayah: str) -> tuple[float, float, list[float]] | None:
    resp = httpx.get("https://nominatim.openstreetmap.org/search",
                     params={"q": f"{wilayah}, Indonesia", "format": "json", "limit": 1},
                     headers={"User-Agent": "AAGE-hackathon/0.1"}, timeout=10)
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        return None
    r = rows[0]
    bbox = [float(x) for x in r["boundingbox"]]  # south, north, west, east
    return float(r["lat"]), float(r["lon"]), bbox


def _overpass(wilayah: str, tipe: str) -> list[dict]:
    geo = _geocode(wilayah)
    if geo is None:
        return []
    _, _, (s, n, w, e) = geo
    filters = "".join(f"node[{f}]({s},{w},{n},{e});way[{f}]({s},{w},{n},{e});" for f in TIPE[tipe]["osm"])
    query = f"[out:json][timeout:25];({filters});out center 150;"
    elements, last_error = None, None
    deadline = time.monotonic() + 25  # AC: satu kota ≤30 detik
    for mirror in OVERPASS_MIRRORS:
        for attempt in range(3):
            if time.monotonic() > deadline:
                break
            try:
                resp = httpx.post(mirror, data={"data": query}, timeout=20, headers={"User-Agent": "AAGE-hackathon/0.1"})
                if resp.status_code in {429, 502, 503, 504} and attempt < 2:
                    time.sleep(2 * (attempt + 1))  # server penuh → backoff lalu coba lagi
                    continue
                resp.raise_for_status()
                elements = resp.json().get("elements", [])
                break
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                log.warning("Overpass %s gagal: %s", mirror, exc)
                break
        if elements is not None:
            break
    if elements is None:
        raise RuntimeError(f"Semua mirror Overpass gagal: {last_error}")
    out = []
    for el in elements:
        tags = el.get("tags", {})
        if not tags.get("name"):
            continue
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lng = el.get("lon") or el.get("center", {}).get("lon")
        alamat = " ".join(filter(None, [tags.get("addr:street"), tags.get("addr:housenumber"), tags.get("addr:city")]))
        out.append({"eksternal_id": f"osm:{el['type']}/{el['id']}", "nama": tags["name"], "alamat": alamat or wilayah,
                    "lat": lat, "lng": lng, "rating": None, "jumlah_ulasan": None,
                    "telepon": tags.get("phone") or tags.get("contact:phone"),
                    "website": tags.get("website") or tags.get("contact:website")})
    return out


_SYN_NAMES = ["Sehat", "Sentosa", "Kimia Farma", "Barokah", "Medika", "Waras", "Prima", "Sumber Sehat", "Mitra",
              "Keluarga", "Bunda", "Amanah", "Sejahtera", "Harapan", "Tunas", "Farma Jaya", "Rahayu", "Lestari",
              "Abadi", "Nusantara", "Pelita", "Cahaya", "Insan", "Al-Falah", "Mulia", "Makmur", "Asri", "Bakti",
              "Merdeka", "Pandanaran", "Candi", "Tembalang", "Banyumanik", "Gajahmungkur", "Ngaliyan", "Pedurungan"]
_SYN_STREETS = ["Jl. Pandanaran", "Jl. Pemuda", "Jl. MT Haryono", "Jl. Majapahit", "Jl. Setiabudi", "Jl. Ngesrep Timur",
                "Jl. Prof. Sudarto", "Jl. Fatmawati", "Jl. Kaligawe", "Jl. Siliwangi", "Jl. Sriwijaya", "Jl. Dr. Cipto",
                "Jl. Gajah Mada", "Jl. Imam Bonjol", "Jl. Wolter Monginsidi", "Jl. Brigjen Sudiarto"]


def _synthetic(wilayah: str, tipe: str, n: int = 36) -> list[dict]:
    """Data SINTETIS berlabel (dipakai bila Places & OSM tidak terjangkau, mis. demo offline)."""
    rng = random.Random(f"{wilayah.lower()}|{tipe}")
    lat0, lng0 = CITY_CENTERS.get(wilayah.lower().strip(), (settings.gudang_lat, settings.gudang_lng))
    label = TIPE[tipe]["label"]
    names = rng.sample(_SYN_NAMES, k=min(n, len(_SYN_NAMES)))
    out = []
    for i, nm in enumerate(names):
        has_rating = rng.random() > 0.2
        out.append({
            "eksternal_id": f"sintetis:{wilayah.lower()}:{tipe}:{i}",
            "nama": f"{label} {nm} (sintetis)",
            "alamat": f"{rng.choice(_SYN_STREETS)} No. {rng.randint(1, 220)}, {wilayah}",
            "lat": lat0 + rng.uniform(-0.09, 0.09), "lng": lng0 + rng.uniform(-0.09, 0.09),
            "rating": round(rng.uniform(3.6, 4.9), 1) if has_rating else None,
            "jumlah_ulasan": rng.randint(3, 420) if has_rating else None,
            "telepon": f"024-{rng.randint(7000000, 8999999)}" if rng.random() > 0.25 else None,
            "website": f"https://{nm.lower().replace(' ', '')}.contoh.id" if rng.random() > 0.7 else None,
        })
    return out


def _fetch(db: Session, wilayah: str, tipe: str, allow_network: bool) -> tuple[str, list[dict], bool]:
    attempts = []
    if allow_network and settings.prospect_allow_network:
        if settings.google_places_api_key:
            attempts.append(("google_places", _google_places))
        attempts.append(("osm", _overpass))
    for source, fn in attempts:
        key = f"{wilayah.lower().strip()}|{tipe}|{source}"
        cached = db.scalar(select(ProspectCache).where(ProspectCache.kunci == key))
        if cached and cached.data:
            return source, cached.data, True
        try:
            rows = fn(wilayah, tipe)
        except Exception as exc:  # jaringan / kuota habis → sumber berikutnya
            log.warning("Sumber prospek %s gagal: %s", source, exc)
            continue
        if rows:
            db.add(ProspectCache(kunci=key, sumber=source, data=rows))
            db.flush()
            return source, rows, False
    return "sintetis", _synthetic(wilayah, tipe), False


# ------------------------------------------------------------------ skor


def score(row: dict, tipe: str, customer_names: set[str]) -> tuple[int, list[dict], float | None, bool]:
    reasons = []
    poin_tipe = TIPE[tipe]["poin"]
    reasons.append({"faktor": "Jenis toko", "poin": poin_tipe, "maks": 30, "keterangan": TIPE[tipe]["label"]})

    jarak = None
    if row.get("lat") is not None and row.get("lng") is not None:
        jarak = haversine_km(settings.gudang_lat, settings.gudang_lng, row["lat"], row["lng"])
        p = 25 if jarak <= 5 else 20 if jarak <= 15 else 14 if jarak <= 30 else 8 if jarak <= 60 else 3
        reasons.append({"faktor": "Jarak ke gudang", "poin": p, "maks": 25, "keterangan": f"{jarak:.1f} km dari {settings.gudang_nama}"})
    else:
        reasons.append({"faktor": "Jarak ke gudang", "poin": 5, "maks": 25, "keterangan": "Lokasi tidak diketahui"})

    rating, ulasan = row.get("rating"), row.get("jumlah_ulasan") or 0
    if rating is None:
        p, ket = 4, "Belum ada rating"
    elif rating >= 4.5 and ulasan >= 50:
        p, ket = 20, f"Rating {rating} dari {ulasan} ulasan"
    elif rating >= 4.0:
        p, ket = 14, f"Rating {rating} dari {ulasan} ulasan"
    else:
        p, ket = 8, f"Rating {rating} dari {ulasan} ulasan"
    reasons.append({"faktor": "Rating & ulasan", "poin": p, "maks": 20, "keterangan": ket})

    kontak = (10 if row.get("telepon") else 0) + (5 if row.get("website") else 0)
    ket = ", ".join(filter(None, ["telepon" if row.get("telepon") else "", "website" if row.get("website") else ""])) or "tidak ada"
    reasons.append({"faktor": "Kelengkapan kontak", "poin": kontak, "maks": 15, "keterangan": f"Kontak: {ket}"})

    pelanggan = row["nama"].lower().replace(" (sintetis)", "") in customer_names
    reasons.append({"faktor": "Status pelanggan", "poin": 0 if pelanggan else 10, "maks": 10,
                    "keterangan": "Sudah pelanggan" if pelanggan else "Belum pelanggan — peluang baru"})
    total = sum(r["poin"] for r in reasons)
    return min(100, total), reasons, jarak, pelanggan


def opening_message(nama: str, wilayah: str) -> str:
    return (f"Halo {nama.replace(' (sintetis)', '')}, kami dari CV Arba'in, pemasok produk herbal dan suplemen "
            f"dengan izin edar BPOM untuk apotek, toko obat, dan minimarket di {wilayah}. Kami menyediakan harga "
            f"grosir dengan diskon volume serta pengiriman dari gudang Semarang. Bolehkah kami kirimkan katalog "
            f"dan daftar harga terbaru?")


def search_prospects(db: Session, *, wilayah: str, tipe: str, aktor: str = "staf", allow_network: bool = True) -> dict:
    if tipe not in TIPE:
        raise ValueError(f"Jenis toko harus salah satu dari: {', '.join(TIPE)}")
    started = time.perf_counter()
    source, rows, cached = _fetch(db, wilayah, tipe, allow_network)
    customers = {(c.nama_toko or "").lower() for c in db.scalars(select(Contact)) if c.nama_toko}
    trace = ledger.new_trace_id()
    results = []
    for row in rows:
        s, reasons, jarak, pelanggan = score(row, tipe, customers)
        p = db.scalar(select(Prospect).where(Prospect.eksternal_id == row["eksternal_id"]))
        is_new = p is None
        if is_new:
            p = Prospect(eksternal_id=row["eksternal_id"], status="baru")
            db.add(p)
        p.nama, p.alamat, p.wilayah, p.tipe = row["nama"], row.get("alamat", ""), wilayah, tipe
        p.lat, p.lng, p.rating, p.jumlah_ulasan = row.get("lat"), row.get("lng"), row.get("rating"), row.get("jumlah_ulasan")
        p.telepon, p.website, p.jarak_km = row.get("telepon"), row.get("website"), round(jarak, 2) if jarak else None
        p.sudah_pelanggan, p.skor, p.alasan_skor, p.sumber = pelanggan, s, reasons, source
        if is_new or not p.draf_pesan:
            msg = opening_message(p.nama, wilayah)
            chk = claimguard.check(db, msg, use_llm=False)
            p.draf_pesan, p.draf_verdict = (msg if chk.verdict == claimguard.ALLOWED else chk.safe_text), chk.verdict
        db.flush()
        if is_new:
            ledger.record(db, "prospek_dibuat", trace_id=trace, objek_ref=f"prospect:{p.id}", aktor=aktor,
                          ringkasan=f"{p.nama} · skor {s}", alasan="; ".join(f"{r['faktor']} +{r['poin']}" for r in reasons),
                          sumber_ref=[{"jenis": source, "eksternal_id": p.eksternal_id}], verdict=p.draf_verdict,
                          outcome="baru", model=llm.OFFLINE_MODEL, data={"wilayah": wilayah, "tipe": tipe, "skor": s})
        results.append(p)
    db.commit()
    results.sort(key=lambda x: x.skor, reverse=True)
    return {"sumber": source, "cache": cached, "jumlah": len(results), "durasi_ms": int((time.perf_counter() - started) * 1000),
            "prospects": results}


def update_status(db: Session, prospect_id: int, status: str, aktor: str) -> Prospect:
    if status not in STATUSES:
        raise ValueError(f"Status harus salah satu dari: {', '.join(STATUSES)}")
    p = db.get(Prospect, prospect_id)
    if p is None:
        raise LookupError("Prospek tidak ditemukan")
    old = p.status
    p.status = status
    ledger.record(db, "prospek_status", objek_ref=f"prospect:{p.id}", aktor=aktor,
                  ringkasan=f"{p.nama}: {old} → {status}", outcome=status, model=None,
                  data={"dari": old, "ke": status, "wilayah": p.wilayah})
    db.commit()
    return p


def to_csv(prospects: list[Prospect]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["skor", "nama", "tipe", "alamat", "telepon", "website", "rating", "ulasan", "jarak_km", "status",
                "sumber", "alasan_skor", "draf_pesan"])
    for p in prospects:
        w.writerow([p.skor, p.nama, p.tipe, p.alamat, p.telepon or "", p.website or "", p.rating or "",
                    p.jumlah_ulasan or "", p.jarak_km or "", p.status, p.sumber,
                    "; ".join(f"{r['faktor']} +{r['poin']} ({r['keterangan']})" for r in p.alasan_skor), p.draf_pesan])
    return buf.getvalue()
