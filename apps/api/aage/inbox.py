"""Kendali staf atas percakapan. Selama diambil alih, AI tidak mengirim apa pun ke pembeli — AI hanya menyiapkan
saran balasan untuk staf. Tanpa aktivitas staf selama AMBIL_ALIH_JAM, percakapan kembali ke AI."""

from datetime import timedelta

from sqlalchemy.orm import Session

from . import clock, ledger
from .config import get_settings
from .models import Conversation

settings = get_settings()
DITANGANI_STAF = "ditangani_staf"


def staff_active(conv: Conversation) -> bool:
    if conv.status != DITANGANI_STAF:
        return False
    last = conv.aktivitas_staf_terakhir or conv.ditangani_sejak
    return last is not None and clock.now() - clock.aware(last) < timedelta(hours=settings.ambil_alih_jam)


def take_over(db: Session, conv: Conversation, nama: str, *, alasan: str = "Staf mengambil alih percakapan") -> None:
    now = clock.now()
    if conv.status != DITANGANI_STAF:
        conv.ditangani_sejak = now
        ledger.record(db, "ambil_alih", conversation_id=conv.id, objek_ref=f"conversation:{conv.id}",
                      aktor=f"staf:{nama}", ringkasan=f"Percakapan diambil alih {nama}", alasan=alasan,
                      outcome=DITANGANI_STAF, model=None)
    conv.status = DITANGANI_STAF
    conv.ditangani_oleh = nama
    conv.aktivitas_staf_terakhir = now


def release(db: Session, conv: Conversation, *, aktor: str, alasan: str) -> None:
    oleh = conv.ditangani_oleh
    conv.status = "otomatis"
    conv.ditangani_oleh = conv.ditangani_sejak = conv.aktivitas_staf_terakhir = None
    conv.konteks = {k: v for k, v in (conv.konteks or {}).items() if k != "saran_ai"}
    ledger.record(db, "ambil_alih_selesai", conversation_id=conv.id, objek_ref=f"conversation:{conv.id}", aktor=aktor,
                  ringkasan=f"Percakapan dikembalikan ke AI{f' (sebelumnya {oleh})' if oleh else ''}", alasan=alasan,
                  outcome="otomatis", model=None)


def expire_if_idle(db: Session, conv: Conversation) -> bool:
    if conv.status == DITANGANI_STAF and not staff_active(conv):
        release(db, conv, aktor="sistem",
                alasan=f"Tidak ada aktivitas staf selama {settings.ambil_alih_jam:g} jam — AI kembali menjawab.")
        return True
    return False
