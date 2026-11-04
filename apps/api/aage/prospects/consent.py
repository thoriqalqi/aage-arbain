"""Pagar consent Leads: promosi hanya boleh dibuka untuk lead dengan consent yang sah, dan ditegakkan di server.

Lead yang menghubungi lebih dulu atau skor yang tinggi bukan consent. Fitur ini hanya membuka WhatsApp staf;
tidak ada pesan yang dikirim sistem."""

from datetime import datetime, timezone
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import claimguard, clock, ledger
from ..models import Prospect, User
from . import mapper

UNKNOWN, GRANTED, OPTED_OUT = "UNKNOWN", "GRANTED", "OPTED_OUT"
STATUSES = (UNKNOWN, GRANTED, OPTED_OUT)
CAKUPAN_PROMO_WA = "promosi_whatsapp"
CAKUPAN = (CAKUPAN_PROMO_WA,)


class KontakDitolak(Exception):
    def __init__(self, kode: str, pesan: str):
        super().__init__(pesan)
        self.kode, self.pesan = kode, pesan


def _nomor_diblokir(db: Session, p: Prospect) -> bool:
    """Opt-out berlaku pada nomornya, jadi lead lain dengan nomor yang sama ikut terblokir."""
    nomor = mapper.wa_number(p.telepon)
    if not nomor:
        return False
    lain = db.scalars(select(Prospect.telepon).where(Prospect.consent_status == OPTED_OUT, Prospect.id != p.id, Prospect.telepon.is_not(None)))
    return any(mapper.wa_number(t) == nomor for t in lain)


def alasan_blokir(db: Session, p: Prospect) -> tuple[str, str] | None:
    if p.consent_status == OPTED_OUT:
        return "OPTED_OUT", "Lead ini sudah menolak dihubungi untuk promosi."
    if p.status == "menolak":
        return "OPTED_OUT", "Lead ini berstatus menolak."
    if _nomor_diblokir(db, p):
        return "OPTED_OUT", "Nomor ini sudah menolak dihubungi lewat lead lain."
    if p.consent_status != GRANTED or not p.consent_sumber or not p.consent_pada or p.consent_cakupan != CAKUPAN_PROMO_WA:
        return "CONSENT_REQUIRED", "Belum ada consent promosi WhatsApp yang sah untuk lead ini."
    return None


def set_consent(db: Session, p: Prospect, user: User, *, status: str, sumber: str | None = None, cakupan: str | None = None,
                pada: datetime | None = None) -> Prospect:
    if status not in STATUSES:
        raise ValueError(f"Status consent harus salah satu dari: {', '.join(STATUSES)}")
    if p.consent_status == OPTED_OUT and status != OPTED_OUT and user.role != "admin":
        raise PermissionError("Opt-out hanya bisa diubah oleh admin")
    sumber = " ".join((sumber or "").split()) or None
    if pada is not None:  # disimpan dalam UTC: SQLite membuang zona waktu tanpa mengonversi
        pada = clock.aware(pada).astimezone(timezone.utc)
    if pada is not None and pada > clock.now():
        raise ValueError("Waktu consent tidak boleh di masa depan")
    if status == GRANTED:
        if not sumber or pada is None:
            raise ValueError("Consent wajib menyertakan sumber dan waktu")
        if cakupan not in CAKUPAN:
            raise ValueError(f"Cakupan consent harus salah satu dari: {', '.join(CAKUPAN)}")
    elif status == UNKNOWN:
        sumber, cakupan, pada = None, None, None
    else:
        pada = pada or clock.now()
    lama = p.consent_status
    if (lama, p.consent_sumber, p.consent_cakupan) == (status, sumber, cakupan) and (status != GRANTED or clock.aware(p.consent_pada) == pada):
        return p
    p.consent_status, p.consent_sumber, p.consent_cakupan, p.consent_pada = status, sumber, cakupan, pada
    ledger.record(db, "prospek_consent", objek_ref=f"prospect:{p.id}", aktor=f"staf:{user.nama}", model=None, outcome=status,
                  ringkasan=f"{p.nama}: consent {lama} → {status}",
                  data={"dari": lama, "ke": status, "sumber": sumber, "cakupan": cakupan, "pada": pada.isoformat() if pada else None})
    db.commit()
    return p


def buka_kontak_promo(db: Session, p: Prospect, user: User) -> str:
    """Satu-satunya jalan ke tautan wa.me berisi draf promosi. Menaikkan status baru → dihubungi."""
    aktor = f"staf:{user.nama}"
    alasan = alasan_blokir(db, p)
    nomor = mapper.wa_number(p.telepon)
    if alasan is None and not nomor:
        alasan = ("TANPA_NOMOR", "Lead ini tidak punya nomor WhatsApp yang valid.")
    if alasan is None and claimguard.check(db, p.draf_pesan, use_llm=False).verdict != claimguard.ALLOWED:
        alasan = ("KLAIM_DITOLAK", "Draf pesan tidak lolos ClaimGuard.")
    if alasan is not None:
        ledger.record(db, "prospek_kontak_ditolak", objek_ref=f"prospect:{p.id}", aktor=aktor, model=None, outcome=alasan[0],
                      ringkasan=f"{p.nama}: {alasan[0]}", alasan=alasan[1], data={"kode": alasan[0]})
        db.commit()
        raise KontakDitolak(*alasan)
    ledger.record(db, "prospek_kontak_dibuka", objek_ref=f"prospect:{p.id}", aktor=aktor, model=None, outcome="dibuka",
                  ringkasan=f"{p.nama}: WhatsApp staf dibuka dengan draf promosi",
                  data={"cakupan": p.consent_cakupan, "consent_sumber": p.consent_sumber})
    if p.status == "baru":
        mapper.update_status(db, p.id, "dihubungi", aktor)
    db.commit()
    return f"https://wa.me/{nomor}?text={quote(p.draf_pesan)}"
