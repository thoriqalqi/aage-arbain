"""Prospek (M7): Live Lead Scouting OSM → Opportunity Score → simpan tanpa duplikat → draf pesan pembuka (ClaimGuard).

Tidak ada data tiruan: bila Overpass penuh/tidak terjangkau, yang dikembalikan adalah hasil pindaian NYATA terakhir
dari database (ditandai `sumber="cache"` beserta waktu pindainya), atau error yang jelas bila belum pernah dipindai.
Staf yang menghubungi prospek — sistem tidak mengirim pesan massal."""

import csv
import io
import logging
import re
import threading
import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import claimguard, clock, ledger
from ..models import Contact, LeadEvidence, Prospect
from . import konfigurasi, lead_service, penilaian, scoring_service
from .lead_service import JENIS_TOKO, ScoutError, ScoutTimeout, normalize_jenis

log = logging.getLogger("aage.prospek")
BACKGROUND_BUDGET_S = 120.0
_bg_lock = threading.Lock()
_bg_running: set[tuple[str, str]] = set()

STATUSES = ["baru", "dihubungi", "merespons", "pelanggan", "menolak"]
_URUTAN = {s: i for i, s in enumerate(STATUSES[:4])}  # tahap funnel; "menolak" di luar urutan
_LEGACY_TIPE = {"Apotek": "apotek", "Toko Obat": "toko obat", "Minimarket": "minimarket"}


def opening_message(nama: str, wilayah: str, jenis: str) -> str:
    return (f"Halo {nama}, kami dari CV Arba'in, pemasok produk herbal dan suplemen dengan izin edar BPOM untuk "
            f"{jenis.lower()} di {wilayah}. Kami menyediakan harga grosir dengan diskon volume serta pengiriman dari "
            f"gudang Semarang. Bolehkah kami kirimkan katalog dan daftar harga terbaru?")


def _cached(db: Session, wilayah: str, jenis: str) -> list[Prospect]:
    return list(db.scalars(
        select(Prospect).where(func.lower(Prospect.wilayah) == wilayah.lower(), Prospect.tipe.in_([jenis, _LEGACY_TIPE[jenis]]),
                               Prospect.sumber == "osm", Prospect.digabung_ke_id.is_(None)).order_by(Prospect.skor.desc())))


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
    contacts = list(db.scalars(select(Contact)))
    customers = {(c.nama_toko or "").strip().lower() for c in contacts if c.nama_toko}
    customer_phones = {c.wa_number for c in contacts if c.wa_number}
    linked = {c.prospect_id for c in contacts if c.prospect_id}
    from . import dedupe

    trace = ledger.new_trace_id()
    stored: list[Prospect] = []
    baru = 0
    cfg = konfigurasi.skor(db)
    indeks = dedupe.indeks_aktif(db)
    for lead in res.leads:
        ext = f"osm:{lead['osm_id']}"
        p = db.scalar(select(Prospect).where(Prospect.eksternal_id == ext))
        if p is not None and p.digabung_ke_id:
            continue  # sudah digabung staf: tidak dimunculkan lagi oleh pindai ulang
        is_new = p is None
        if is_new:
            p = Prospect(eksternal_id=ext, status="baru")
            db.add(p)
            baru += 1
        consent_batal = _isi_dari_osm(db, p, lead, wilayah, jenis)
        p.rating, p.jumlah_ulasan = None, None  # OSM tidak menyediakan rating — tidak dikarang
        p.jaringan = scoring_service.national_chain(lead["name"], lead.get("brand"))
        p.sudah_pelanggan = (lead["name"].strip().lower() in customers or p.id in linked
                             or (wa_number(p.telepon) or "-") in customer_phones)
        p.sumber = "osm"
        p.terakhir_dipindai = p.dikumpulkan_pada = lead["last_scanned_at"]
        if is_new or not p.draf_pesan:
            msg = opening_message(p.nama, wilayah, jenis)
            chk = claimguard.check(db, msg, use_llm=False)
            p.draf_pesan, p.draf_verdict = (msg if chk.verdict == claimguard.ALLOWED else chk.safe_text), chk.verdict
        db.flush()
        penilaian.nilai_ulang(db, p, "pindai", cfg)
        catat_bukti(db, p.id, "osm", ext, {"server": res.server, "area": res.area_dipakai}, p.dikumpulkan_pada)
        if consent_batal:
            ledger.record(db, "prospek_diperbarui", trace_id=trace, objek_ref=f"prospect:{p.id}", aktor=aktor, model=None,
                          ringkasan=f"{p.nama}: consent dibatalkan karena nomor berubah saat pindai ulang", data={"consent_dibatalkan": True})
        if is_new:
            k = dedupe.dari_prospek(p)
            for c in indeks.cari(k):
                dedupe.rekam_calon(db, p.id, c["id"], c["tingkat"], c["alasan"])
            indeks.tambah(k)
            ledger.record(db, "prospek_dibuat", trace_id=trace, objek_ref=f"prospect:{p.id}", aktor=aktor,
                          ringkasan=f"{p.nama} · skor {p.skor}", alasan="; ".join(f"{r['faktor']} +{r['poin']}" for r in p.alasan_skor),
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


def _isi_dari_osm(db: Session, p: Prospect, lead: dict, wilayah: str, jenis: str) -> bool:
    """Nilai OSM yang kosong tidak mengosongkan data, dan alamat jalan tidak diganti teks "Alamat tidak spesifik".
    Lead yang sudah punya data dari staf atau sumber lain hanya diisi bagian yang kosong. True bila consent batal karena nomornya berganti."""
    dijaga = p.id is not None and db.scalar(select(LeadEvidence.id).where(LeadEvidence.lead_id == p.id, LeadEvidence.source_type != "osm").limit(1)) is not None
    consent_batal = False
    for kolom, nilai in (("nama", lead["name"]), ("wilayah", wilayah), ("tipe", jenis), ("lat", lead["latitude"]), ("lng", lead["longitude"]),
                         ("telepon", lead["phone"]), ("website", lead["website"]), ("jam_buka", lead["opening_hours"])):
        if nilai in (None, "") or (dijaga and getattr(p, kolom) not in (None, "")):
            continue
        if kolom == "telepon":
            consent_batal = setel_nomor(p, nilai)
        else:
            setattr(p, kolom, nilai)
    if lead["has_street"]:
        if not (dijaga and p.alamat_jalan_ada):
            p.alamat, p.alamat_jalan_ada = lead["address"], True
    elif not p.alamat:
        p.alamat, p.alamat_jalan_ada = lead["address"], False
    return consent_batal


def catat_bukti(db: Session, lead_id: int, source_type: str, reference: str, metadata: dict | None = None, dikumpulkan_pada=None) -> None:
    """Satu bukti per lead, sumber, dan referensi. Di-flush karena autoflush mati, agar pencarian berikutnya dalam transaksi yang sama menemukannya."""
    reference = reference[:500]
    bukti = db.scalar(select(LeadEvidence).where(LeadEvidence.lead_id == lead_id, LeadEvidence.source_type == source_type,
                                                 LeadEvidence.source_reference == reference))
    if bukti is None:
        bukti = LeadEvidence(lead_id=lead_id, source_type=source_type, source_reference=reference)
        db.add(bukti)
    bukti.dikumpulkan_pada, bukti.metadata_sumber = dikumpulkan_pada or clock.now(), metadata
    db.flush()


def wa_number(phone: str | None) -> str | None:
    """Nomor OSM ("+62 812-…", "0812 …", "024 …") → format WhatsApp 62xxxxxxxxxx. None bila tidak masuk akal."""
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone.split(";")[0])
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    elif digits.startswith("8"):
        digits = "62" + digits
    return digits if digits.startswith("62") and 10 <= len(digits) <= 15 else None


def setel_nomor(p: Prospect, nomor: str | None) -> bool:
    """Consent melekat pada nomor: nomor yang berganti, termasuk dari kosong, membatalkan consent GRANTED. True bila dibatalkan."""
    berganti = wa_number(p.telepon) != wa_number(nomor)
    p.telepon = nomor
    if berganti and p.consent_status == "GRANTED":
        p.consent_status, p.consent_sumber, p.consent_cakupan, p.consent_pada = "UNKNOWN", None, None, None
        return True
    return False


def _set_status(db: Session, p: Prospect, status: str, aktor: str, alasan: str | None = None) -> None:
    if status not in STATUSES:
        raise ValueError(f"Status harus salah satu dari: {', '.join(STATUSES)}")
    if status == p.status:
        return
    old = p.status
    p.status = status
    if status == "pelanggan":
        p.sudah_pelanggan = True
    ledger.record(db, "prospek_status", objek_ref=f"prospect:{p.id}", aktor=aktor, alasan=alasan or "",
                  ringkasan=f"{p.nama}: {old} → {status}", outcome=status, model=None,
                  data={"dari": old, "ke": status, "wilayah": p.wilayah})


def update_status(db: Session, prospect_id: int, status: str, aktor: str) -> Prospect:
    return update(db, prospect_id, aktor, status=status)


def update(db: Session, prospect_id: int, aktor: str, *, status: str | None = None, catatan: str | None = None,
           tindak_lanjut_pada=None, pic: str | None = None, fields: set[str] | None = None) -> Prospect:
    """Perbarui status/catatan/tindak lanjut/PIC. `fields` = kolom yang dikirim (agar bisa dikosongkan)."""
    p = db.get(Prospect, prospect_id)
    if p is None:
        raise LookupError("Prospek tidak ditemukan")
    if status is not None:
        _set_status(db, p, status, aktor)
    fields = fields or set()
    changed = {}
    for key, val in (("catatan", catatan), ("tindak_lanjut_pada", tindak_lanjut_pada), ("pic", pic)):
        if key in fields and getattr(p, key) != val:
            setattr(p, key, val)
            changed[key] = val.isoformat() if hasattr(val, "isoformat") else val
    if changed:
        ledger.record(db, "prospek_diperbarui", objek_ref=f"prospect:{p.id}", aktor=aktor, model=None,
                      ringkasan=f"{p.nama}: {', '.join(changed)} diperbarui", data=changed)
    db.commit()
    return p


def link_contact(db: Session, contact: Contact) -> Prospect | None:
    """Pesan WA dari nomor prospek → tautkan kontak ke prospek dan naikkan status ke "merespons"."""
    if contact.prospect_id or not contact.wa_number.isdigit():
        return None
    for p in db.scalars(select(Prospect).where(Prospect.telepon.is_not(None), Prospect.digabung_ke_id.is_(None))):
        if wa_number(p.telepon) == contact.wa_number:
            contact.prospect_id = p.id
            contact.nama_toko = contact.nama_toko or p.nama
            contact.tipe_toko = contact.tipe_toko or p.tipe
            ledger.record(db, "prospek_ditautkan", objek_ref=f"prospect:{p.id}", aktor="sistem", model=None,
                          ringkasan=f"{p.nama} menghubungi lewat WhatsApp", outcome=p.status,
                          data={"contact_id": contact.id})
            if _URUTAN.get(p.status, 99) < _URUTAN["merespons"]:
                _set_status(db, p, "merespons", "sistem", "Prospek mengirim pesan WhatsApp")
            return p
    return None


def mark_customer(db: Session, contact: Contact, aktor: str) -> None:
    """Draf pesanan prospek dikonfirmasi staf → prospek menjadi pelanggan."""
    p = db.get(Prospect, contact.prospect_id) if contact.prospect_id else None
    if p is not None and p.status != "pelanggan":
        _set_status(db, p, "pelanggan", aktor, "Pesanan pertama dikonfirmasi staf")


def funnel(prospects: list[Prospect]) -> dict:
    tahap = {"dipindai": len(prospects), "dihubungi": 0, "merespons": 0, "pelanggan": 0}
    for p in prospects:
        u = _URUTAN.get(p.status, -1)
        tahap["dihubungi"] += u >= _URUTAN["dihubungi"]
        tahap["merespons"] += u >= _URUTAN["merespons"]
        tahap["pelanggan"] += u >= _URUTAN["pelanggan"]
    tahap["menolak"] = sum(p.status == "menolak" for p in prospects)
    return tahap


def _aman_csv(nilai) -> str:
    """Isi dari sumber luar bisa dibaca Excel sebagai rumus. Diberi tanda kutip agar tetap jadi teks."""
    teks = "" if nilai is None else str(nilai)
    return f"'{teks}" if teks.startswith(("=", "+", "-", "@", "\t", "\r")) else teks


def to_csv(prospects: list[Prospect]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["skor", "skor_geo", "skor_data", "nama", "jenis", "alamat", "lat", "lng", "jarak_km", "telepon",
                "jam_buka", "status", "osm_id", "terakhir_dipindai", "draf_pesan", "sumber", "consent_status", "verifikasi", "confidence", "skor_versi"])
    for p in prospects:
        w.writerow([p.skor, p.skor_geo, p.skor_data, _aman_csv(p.nama), _aman_csv(p.tipe), _aman_csv(p.alamat), p.lat, p.lng, p.jarak_km or "",
                    _aman_csv(p.telepon), _aman_csv(p.jam_buka), p.status, _aman_csv(p.eksternal_id),
                    p.terakhir_dipindai.isoformat() if p.terakhir_dipindai else "", _aman_csv(p.draf_pesan), p.sumber, p.consent_status, p.verifikasi,
                    p.confidence if p.confidence is not None else "", p.skor_versi or ""])
    return buf.getvalue()


__all__ = ["JENIS_TOKO", "STATUSES", "ScoutError", "funnel", "link_contact", "mark_customer", "scout_and_store",
           "to_csv", "update", "update_status", "wa_number"]
