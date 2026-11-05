"""Menerapkan skor ke lead: faktor, versi, confidence, dan riwayat tersimpan bersama."""

from sqlalchemy.orm import Session

from .. import ledger
from ..models import LeadSkorRiwayat, Prospect
from . import konfigurasi, scoring_service


def data_lead(p: Prospect) -> dict:
    return {"name": p.nama, "brand": p.jaringan, "latitude": p.lat, "longitude": p.lng, "phone": p.telepon, "website": p.website,
            "opening_hours": p.jam_buka, "has_street": p.alamat_jalan_ada, "address": p.alamat, "asal": "OSM" if p.sumber == "osm" else "data"}


def rincian_confidence(p: Prospect) -> list[dict]:
    return scoring_service.rincian_confidence(data_lead(p), p.verifikasi == "terverifikasi")


def nilai_ulang(db: Session, p: Prospect, pemicu: str, cfg: dict | None = None) -> bool:
    """Hitung dan simpan skor. Riwayat hanya bertambah bila ada yang berubah. `p` harus sudah punya id."""
    cfg = cfg or konfigurasi.skor(db)
    data = data_lead(p)
    s = scoring_service.opportunity_score(data, cfg)
    conf = scoring_service.confidence(data, p.verifikasi == "terverifikasi")
    versi = konfigurasi.versi(cfg)
    berubah = (p.skor, p.skor_versi, p.confidence) != (s["skor"], versi, conf)
    p.skor, p.skor_geo, p.skor_data, p.jarak_km, p.alasan_skor = s["skor"], s["skor_geo"], s["skor_data"], s["jarak_km"], s["alasan"]
    p.jaringan, p.skor_versi, p.confidence = s["jaringan"], versi, conf
    if berubah:
        db.add(LeadSkorRiwayat(lead_id=p.id, skor=p.skor, confidence=conf, skor_versi=versi, faktor=s["alasan"], pemicu=pemicu))
    return berubah


def hitung_ulang_semua(db: Session, aktor: str) -> dict:
    from sqlalchemy import select

    cfg = konfigurasi.skor(db)
    leads = list(db.scalars(select(Prospect).where(Prospect.sumber != "sintetis", Prospect.digabung_ke_id.is_(None))))
    berubah = sum(nilai_ulang(db, p, "hitung_ulang", cfg) for p in leads)
    versi = konfigurasi.versi(cfg)
    ledger.record(db, "prospek_skor_dihitung", aktor=aktor, model=None, outcome="selesai", trace_id=ledger.new_trace_id(),
                  ringkasan=f"{len(leads)} lead dihitung ulang dengan {versi}, {berubah} berubah",
                  data={"jumlah": len(leads), "berubah": berubah, "versi": versi})
    db.commit()
    return {"jumlah": len(leads), "berubah": berubah, "versi": versi}
