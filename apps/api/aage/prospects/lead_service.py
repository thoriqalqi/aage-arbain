"""Live Lead Scouting: toko retail fisik nyata dari OpenStreetMap Overpass API (gratis, tanpa API key).

Pencarian dibatasi ke batas wilayah administratif (`area["name"=…]["boundary"="administrative"]`), bukan radius.
Data yang tidak ada di OSM tidak dikarang: alamat kosong → "Alamat tidak spesifik", telepon/jam buka → None."""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from ..config import get_settings

log = logging.getLogger("aage.prospek.osm")
settings = get_settings()

ALAMAT_TIDAK_SPESIFIK = "Alamat tidak spesifik"

# Opsi dropdown UI → filter tag OSM
JENIS_TOKO: dict[str, list[tuple[str, str]]] = {
    "Apotek": [("amenity", "pharmacy")],
    "Toko Obat": [("shop", "chemist")],
    "Minimarket": [("shop", "convenience")],
}
_ALIAS = {"apotek": "Apotek", "toko obat": "Toko Obat", "minimarket": "Minimarket"}


class ScoutError(RuntimeError):
    """Overpass tidak bisa dijangkau / penuh / query gagal."""


class ScoutTimeout(ScoutError):
    """Batas waktu habis sebelum Overpass menjawab (server lambat)."""


@dataclass
class ScoutResult:
    wilayah: str
    jenis_toko: str
    area_dipakai: str
    leads: list[dict] = field(default_factory=list)
    dilewati_tanpa_nama: int = 0
    server: str = ""
    durasi_ms: int = 0


def normalize_jenis(jenis_toko: str) -> str:
    j = _ALIAS.get(jenis_toko.strip().lower(), jenis_toko.strip())
    if j not in JENIS_TOKO:
        raise ValueError(f"jenis_toko harus salah satu dari: {', '.join(JENIS_TOKO)}")
    return j


def build_query(area_name: str, jenis_toko: str, limit: int, timeout_s: int) -> str:
    safe = area_name.replace('"', "").replace("\\", "")
    filters = "".join(
        f'node["{k}"="{v}"](area.a);way["{k}"="{v}"](area.a);' for k, v in JENIS_TOKO[jenis_toko]
    )
    return f'[out:json][timeout:{timeout_s}];area["name"="{safe}"]["boundary"="administrative"]->.a;({filters});out center {limit};'


def _area_candidates(wilayah: str) -> list[str]:
    """Nama di OSM bisa "Kota Semarang" atau "Semarang"; coba yang diketik dulu, lalu varian tanpa/ dengan awalan."""
    w = " ".join(wilayah.split())
    out = [w]
    low = w.lower()
    for prefix in ("kota ", "kabupaten ", "kab. "):
        if low.startswith(prefix):
            out.append(w[len(prefix):])
    if not any(low.startswith(p) for p in ("kota ", "kabupaten ", "kab. ")):
        out.append(f"Kota {w}")
    return list(dict.fromkeys(out))


def parse_elements(elements: list[dict], scanned_at: datetime) -> tuple[list[dict], int]:
    leads, skipped = [], 0
    for el in elements:
        tags = el.get("tags") or {}
        name = (tags.get("name") or "").strip()
        if not name:
            skipped += 1  # toko tanpa nama tidak bisa didekati sales → tidak dimasukkan, tidak diberi nama karangan
            continue
        lat = el.get("lat", (el.get("center") or {}).get("lat"))
        lon = el.get("lon", (el.get("center") or {}).get("lon"))
        if lat is None or lon is None:
            skipped += 1
            continue
        street = (tags.get("addr:street") or "").strip()
        number = (tags.get("addr:housenumber") or "").strip()
        address = " ".join(p for p in (street, f"No. {number}" if number else "") if p) or ALAMAT_TIDAK_SPESIFIK
        leads.append({
            "osm_id": f"{el['type']}/{el['id']}",
            "name": name,
            "address": address,
            "has_street": bool(street),
            "latitude": float(lat),
            "longitude": float(lon),
            "phone": (tags.get("phone") or tags.get("contact:phone") or "").strip() or None,
            "opening_hours": (tags.get("opening_hours") or "").strip() or None,
            "website": (tags.get("website") or tags.get("contact:website") or "").strip() or None,
            "brand": (tags.get("brand") or tags.get("operator") or "").strip() or None,
            "last_scanned_at": scanned_at,
        })
    return leads, skipped


def _post(url: str, query: str, timeout_s: float) -> dict:
    resp = httpx.post(url, data={"data": query}, timeout=timeout_s, headers={"User-Agent": "AAGE-ArbainGrowthOS/0.2"})
    if resp.status_code in (429, 502, 503, 504):
        raise ScoutError(f"Overpass penuh ({resp.status_code}) di {url}")
    resp.raise_for_status()
    try:
        data = resp.json()
    except ValueError as exc:
        raise ScoutError(f"Respons Overpass bukan JSON ({url})") from exc
    if data.get("remark") and "runtime error" in data["remark"]:
        raise ScoutError(f"Query Overpass gagal: {data['remark'][:160]}")
    return data


def scout(wilayah: str, jenis_toko: str, budget_s: float | None = None) -> ScoutResult:
    """Pindai toko nyata. Total waktu dibatasi OVERPASS_TIMEOUT_S (default 25 detik) lintas mirror & varian nama;
    `budget_s` dipakai pindaian latar yang boleh menunggu server Overpass yang sedang lambat.

    Per varian nama area: tiap mirror dicoba hingga 2× (server penuh sering menjawab 429/502 seketika)."""
    jenis = normalize_jenis(jenis_toko)
    limit = max(1, min(settings.prospek_max_results, 100))
    budget = budget_s or settings.overpass_timeout_s
    started = time.monotonic()
    deadline = started + budget
    urls = [u.strip() for u in settings.overpass_urls.split(",") if u.strip()]
    errors: list[str] = []
    for area_name in _area_candidates(wilayah):
        answered_empty = False
        for url in [u for u in urls for _ in range(2)]:
            remaining = deadline - time.monotonic()
            if remaining < 2:
                raise ScoutTimeout(f"Batas waktu {budget:g} detik habis. " + " | ".join(errors[-3:]))
            try:
                data = _post(url, build_query(area_name, jenis, limit, max(5, int(remaining))), timeout_s=remaining)
            except httpx.TimeoutException:
                errors.append(f"timeout {url}")
                continue
            except (httpx.HTTPError, ScoutError) as exc:
                errors.append(str(exc)[:160])
                log.warning("Overpass %s gagal: %s", url, exc)
                time.sleep(min(2.0, max(0.0, deadline - time.monotonic() - 2)))  # backoff singkat
                continue
            elements = data.get("elements", [])
            if not elements:
                answered_empty = True  # server menjawab, tapi area ini kosong → coba varian nama berikutnya
                break
            leads, skipped = parse_elements(elements, datetime.now(timezone.utc))
            return ScoutResult(wilayah=wilayah, jenis_toko=jenis, area_dipakai=area_name, leads=leads[:limit],
                               dilewati_tanpa_nama=skipped, server=url, durasi_ms=int((time.monotonic() - started) * 1000))
        if not answered_empty:
            raise ScoutError("Overpass tidak dapat dijangkau: " + " | ".join(errors[-3:]))
    return ScoutResult(wilayah=wilayah, jenis_toko=jenis, area_dipakai=wilayah, server=urls[0] if urls else "",
                       durasi_ms=int((time.monotonic() - started) * 1000))
