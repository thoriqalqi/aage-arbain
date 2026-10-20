"""Prospek (M7): Live Lead Scouting OSM → Opportunity Score → simpan tanpa duplikat → draf pesan pembuka (ClaimGuard).

Tidak ada data tiruan: bila Overpass penuh/tidak terjangkau, yang dikembalikan adalah hasil pindaian NYATA terakhir
dari database (ditandai `sumber="cache"` beserta waktu pindainya), atau error yang jelas bila belum pernah dipindai.
Staf yang menghubungi prospek — sistem tidak mengirim pesan massal."""

import csv
import io
import logging
import threading
import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import claimguard, clock, ledger
from ..models import Contact, Prospect
from . import lead_service, scoring_service
from .lead_service import JENIS_TOKO, ScoutError, ScoutTimeout, normalize_jenis

log = logging.getLogger("aage.prospek")
BACKGROUND_BUDGET_S = 120.0
_bg_lock = threading.Lock()
_bg_running: set[tuple[str, str]] = set()

STATUSES = ["baru", "dihubungi", "merespons", "menolak"]
_LEGACY_TIPE = {"Apotek": "apotek", "Toko Obat": "toko obat", "Minimarket": "minimarket"}


def opening_message(nama: str, wilayah: str, jenis: str) -> str:
    return (f"Halo {nama}, kami dari CV Arba'in, pemasok produk herbal dan suplemen dengan izin edar BPOM untuk "
            f"{jenis.lower()} di {wilayah}. Kami menyediakan harga grosir dengan diskon volume serta pengiriman dari "
            f"gudang Semarang. Bolehkah kami kirimkan katalog dan daftar harga terbaru?")


def _cached(db: Session, wilayah: str, jenis: str) -> list[Prospect]:
    return list(db.scalars(
        select(Prospect).where(func.lower(Prospect.wilayah) == wilayah.lower(), Prospect.tipe.in_([jenis, _LEGACY_TIPE[jenis]]),
                               Prospect.sumber == "osm").order_by(Prospect.skor.desc())))


def scout_and_store(db: Session, *, wilayah: str, jenis_toko: str, aktor: str = "staf") -> dict:
    jenis = normalize_jenis(jenis_toko)
    wilayah = " ".join(wilayah.split())
    started = time.perf_counter()
    try:
        res = lead_service.scout(wilayah, jenis)
    except ScoutError as exc:
        diproses = isinstance(exc, ScoutTimeout) and start_background_scout(wilayah, jenis, aktor)
        cached = _cached(db, wilayah, jenis)
        if not cached:
            if diproses:
                return {"wilayah": wilayah, "jenis_toko": jenis, "sumber": "diproses", "jumlah": 0,
                        "durasi_ms": int((time.perf_counter() - started) * 1000), "terakhir_dipindai": None,
                        "peringatan": "Server OpenStreetMap sedang lambat. Pindaian dilanjutkan di latar (maks 2 menit); "
                                      "hasil akan muncul otomatis.", "prospects": []}
            raise ScoutError(f"{exc}. Belum ada hasil pindaian sebelumnya untuk {jenis} di {wilayah} — coba lagi sebentar.") from exc
        last = max((p.terakhir_dipindai for p in cached if p.terakhir_dipindai), default=None)
        return {"wilayah": wilayah, "jenis_toko": jenis, "sumber": "cache", "jumlah": len(cached),
                "durasi_ms": int((time.perf_counter() - started) * 1000), "terakhir_dipindai": last,
                "peringatan": f"Overpass sedang penuh/tidak terjangkau; menampilkan hasil pindaian terakhir. ({exc})",
                "prospects": cached}

    return _store(db, res, wilayah, jenis, aktor, started)


def start_background_scout(wilayah: str, jenis: str, aktor: str) -> bool:
    """Lanjutkan pindaian yang melewati batas 25 detik di thread latar (satu per wilayah+jenis)."""
    key = (wilayah.lower(), jenis)
    with _bg_lock:
        if key in _bg_running:
            return True
        _bg_running.add(key)

    def run():
        from ..db import SessionLocal

        try:
            res = lead_service.scout(wilayah, jenis, budget_s=BACKGROUND_BUDGET_S)
            with SessionLocal() as bdb:
                _store(bdb, res, wilayah, jenis, aktor, time.perf_counter())
            log.info("Pindaian latar %s/%s selesai: %d toko", wilayah, jenis, len(res.leads))
        except Exception as exc:  # pragma: no cover - jaringan
            log.warning("Pindaian latar %s/%s gagal: %s", wilayah, jenis, exc)
        finally:
            with _bg_lock:
                _bg_running.discard(key)

    threading.Thread(target=run, daemon=True).start()
    return True


def background_running(wilayah: str, jenis: str) -> bool:
    with _bg_lock:
        return (wilayah.lower(), jenis) in _bg_running


def _store(db: Session, res: "lead_service.ScoutResult", wilayah: str, jenis: str, aktor: str, started: float) -> dict:
    customers = {(c.nama_toko or "").strip().lower() for c in db.scalars(select(Contact)) if c.nama_toko}
    trace = ledger.new_trace_id()
    stored: list[Prospect] = []
    baru = 0
    for lead in res.leads:
        s = scoring_service.opportunity_score(lead)
        ext = f"osm:{lead['osm_id']}"
        p = db.scalar(select(Prospect).where(Prospect.eksternal_id == ext))
        is_new = p is None
        if is_new:
            p = Prospect(eksternal_id=ext, status="baru")
            db.add(p)
            baru += 1
        p.nama, p.alamat, p.wilayah, p.tipe = lead["name"], lead["address"], wilayah, jenis
        p.lat, p.lng = lead["latitude"], lead["longitude"]
        p.telepon, p.website, p.jam_buka = lead["phone"], lead["website"], lead["opening_hours"]
        p.alamat_jalan_ada = lead["has_street"]
        p.rating, p.jumlah_ulasan = None, None  # OSM tidak menyediakan rating — tidak dikarang
        p.jarak_km, p.skor, p.skor_geo, p.skor_data = s["jarak_km"], s["skor"], s["skor_geo"], s["skor_data"]
        p.alasan_skor = s["alasan"]
        p.sudah_pelanggan = lead["name"].strip().lower() in customers
        p.sumber = "osm"
        p.terakhir_dipindai = lead["last_scanned_at"]
        if is_new or not p.draf_pesan:
            msg = opening_message(p.nama, wilayah, jenis)
            chk = claimguard.check(db, msg, use_llm=False)
            p.draf_pesan, p.draf_verdict = (msg if chk.verdict == claimguard.ALLOWED else chk.safe_text), chk.verdict
        db.flush()
        if is_new:
            ledger.record(db, "prospek_dibuat", trace_id=trace, objek_ref=f"prospect:{p.id}", aktor=aktor,
                          ringkasan=f"{p.nama} · skor {p.skor}", alasan="; ".join(f"{r['faktor']} +{r['poin']}" for r in s["alasan"]),
                          sumber_ref=[{"jenis": "osm", "eksternal_id": ext, "server": res.server}], verdict=p.draf_verdict,
                          outcome="baru", data={"wilayah": wilayah, "tipe": jenis, "skor": p.skor})
        stored.append(p)
    db.commit()
    stored.sort(key=lambda x: x.skor, reverse=True)
    return {"wilayah": wilayah, "jenis_toko": jenis, "sumber": "osm_live", "area_osm": res.area_dipakai,
            "jumlah": len(stored), "baru": baru, "dilewati_tanpa_nama": res.dilewati_tanpa_nama,
            "durasi_ms": int((time.perf_counter() - started) * 1000), "terakhir_dipindai": clock.now(),
            "server": res.server, "peringatan": None if stored else f"Tidak ada {jenis.lower()} bernama di area OSM \"{wilayah}\".",
            "prospects": stored}


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
    w.writerow(["skor", "skor_geo", "skor_data", "nama", "jenis", "alamat", "lat", "lng", "jarak_km", "telepon",
                "jam_buka", "status", "osm_id", "terakhir_dipindai", "draf_pesan"])
    for p in prospects:
        w.writerow([p.skor, p.skor_geo, p.skor_data, p.nama, p.tipe, p.alamat, p.lat, p.lng, p.jarak_km or "",
                    p.telepon or "", p.jam_buka or "", p.status, p.eksternal_id or "",
                    p.terakhir_dipindai.isoformat() if p.terakhir_dipindai else "", p.draf_pesan])
    return buf.getvalue()


__all__ = ["JENIS_TOKO", "STATUSES", "ScoutError", "scout_and_store", "to_csv", "update_status"]
