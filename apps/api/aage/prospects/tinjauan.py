"""Verifikasi manual, alasan tinjauan, dan saran langkah berikutnya.

"Perlu tinjauan" dihitung dari data saat ini, jadi hilang sendiri begitu datanya dilengkapi. Yang disimpan hanya keputusan staf."""

from sqlalchemy.orm import Session

from .. import clock, ledger
from ..models import Prospect, User
from . import penilaian

STATUS_KEPUTUSAN = ("belum", "terverifikasi", "ditolak")


def alasan_tinjauan(p: Prospect, ids_duplikat: set[int], ambang: float) -> list[str]:
    alasan = []
    if p.id in ids_duplikat:
        alasan.append("Ada calon duplikat")
    if not p.telepon:
        alasan.append("Nomor telepon kosong")
    if not p.alamat_jalan_ada:
        alasan.append("Alamat jalan kosong")
    if p.lat is None or p.lng is None:
        alasan.append("Koordinat kosong")
    if p.confidence is not None and p.confidence < ambang:
        alasan.append(f"Confidence rendah ({p.confidence:.1f})")
    return alasan


def status_tinjauan(p: Prospect, alasan: list[str]) -> str:
    if p.verifikasi in ("terverifikasi", "ditolak") and "Ada calon duplikat" not in alasan:
        return p.verifikasi
    return "perlu_tinjauan" if alasan else p.verifikasi


def langkah_berikutnya(p: Prospect, ids_duplikat: set[int], status: str) -> str:
    """Saran untuk staf, bukan izin untuk menghubungi. Pagar consent tetap berlaku di server."""
    if p.digabung_ke_id:
        return f"Lead ini sudah digabung ke lead {p.digabung_ke_id}."
    if p.verifikasi == "ditolak":
        return "Lead ditolak saat verifikasi. Tidak perlu tindak lanjut."
    if p.id in ids_duplikat:
        return "Selesaikan calon duplikat di antrean tinjauan."
    if p.consent_status == "OPTED_OUT" or p.status == "menolak":
        return "Jangan hubungi untuk promosi."
    if p.status == "pelanggan":
        return "Sudah pelanggan. Tindak lanjut lewat alur pesanan."
    if not p.telepon:
        return "Lengkapi nomor telepon, atau kunjungi langsung."
    if p.verifikasi != "terverifikasi" and status != "terverifikasi":
        return "Verifikasi data lead ini."
    if p.consent_status != "GRANTED":
        return "Minta dan catat consent sebelum promosi."
    if p.status == "baru":
        return "Buka draf di WhatsApp. Staf yang menekan kirim."
    return "Lanjutkan percakapan dan catat hasilnya."


def set_verifikasi(db: Session, p: Prospect, user: User, status: str, catatan: str | None = None) -> Prospect:
    if status not in STATUS_KEPUTUSAN:
        raise ValueError(f"Status verifikasi harus salah satu dari: {', '.join(STATUS_KEPUTUSAN)}")
    lama = p.verifikasi
    if lama == status:
        return p
    p.verifikasi = status
    p.terakhir_diverifikasi = None if status == "belum" else clock.now()
    penilaian.nilai_ulang(db, p, "verifikasi")
    ledger.record(db, "prospek_diverifikasi", objek_ref=f"prospect:{p.id}", aktor=f"staf:{user.nama}", model=None, outcome=status,
                  ringkasan=f"{p.nama}: verifikasi {lama} → {status}", alasan=catatan or "", data={"dari": lama, "ke": status})
    db.commit()
    return p
