"""Rantai hash Ledger (Brief §6.1): hash = sha256(prev_hash + payload kanonik event).

Segel disimpan di tabel `ledger_hashes` (append-only) — baris `ledger_events` tidak pernah diubah. Segel ditulis di
transaksi yang sama dengan event-nya (lewat `ledger.record`). Mengubah satu baris Ledger langsung di database membuat
hash baris itu (dan rantai sesudahnya) tidak cocok saat diverifikasi.
"""

import hashlib
import json
from datetime import timezone

from sqlalchemy import ForeignKey, Integer, String, event, func, select, text
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import clock
from .db import IS_POSTGRES, Base
from .models import LedgerEvent, LedgerImmutableError

GENESIS = "0" * 64
_PG_LOCK_KEY = 4_200_101  # advisory lock: satu penulis rantai pada satu waktu


class LedgerHash(Base):
    __tablename__ = "ledger_hashes"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("ledger_events.id"), unique=True, index=True)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), index=True)


@event.listens_for(LedgerHash, "before_update")
def _block_update(*_):
    raise LedgerImmutableError("ledger_hashes bersifat append-only")


@event.listens_for(LedgerHash, "before_delete")
def _block_delete(*_):
    raise LedgerImmutableError("ledger_hashes bersifat append-only")


def payload(ev: LedgerEvent) -> str:
    waktu = clock.aware(ev.waktu)
    waktu = waktu.astimezone(timezone.utc) if waktu else None  # hash tidak boleh bergantung pada zona sesi database
    body = {
        "id": ev.id, "tipe_event": ev.tipe_event, "waktu": waktu.isoformat(timespec="microseconds") if waktu else None,
        "trace_id": ev.trace_id, "conversation_id": ev.conversation_id, "product_id": ev.product_id,
        "objek_ref": ev.objek_ref, "sumber_ref": ev.sumber_ref or [], "ringkasan": ev.ringkasan or "",
        "alasan": ev.alasan or "", "verdict": ev.verdict, "aturan_terpicu": ev.aturan_terpicu or [], "model": ev.model,
        "token_in": ev.token_in or 0, "token_out": ev.token_out or 0, "biaya_rp": round(float(ev.biaya_rp or 0), 6),
        "latensi_ms": ev.latensi_ms, "aktor": ev.aktor, "outcome": ev.outcome, "data": ev.data or {},
    }
    return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def digest(prev_hash: str, ev: LedgerEvent) -> str:
    return hashlib.sha256((prev_hash + payload(ev)).encode("utf-8")).hexdigest()


def _last_hash(db: Session) -> str:
    return db.scalar(select(LedgerHash.hash).order_by(LedgerHash.seq.desc()).limit(1)) or GENESIS


def seal(db: Session, ev: LedgerEvent) -> LedgerHash:
    """Segel satu event yang baru di-flush. Dipanggil di transaksi yang sama dengan insert event."""
    if IS_POSTGRES:
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _PG_LOCK_KEY})
    prev = _last_hash(db)
    row = LedgerHash(event_id=ev.id, prev_hash=prev, hash=digest(prev, ev))
    db.add(row)
    db.flush()
    return row


def backfill(db: Session) -> int:
    """Segel event lama yang belum punya hash (sekali, saat startup). Tidak mengubah baris Ledger."""
    sealed = select(LedgerHash.event_id)
    pending = list(db.scalars(select(LedgerEvent).where(LedgerEvent.id.not_in(sealed)).order_by(LedgerEvent.id)))
    for ev in pending:
        seal(db, ev)
    db.commit()
    return len(pending)


def verify(db: Session, limit_issues: int = 5) -> dict:
    """Hitung ulang seluruh rantai. Utuh bila setiap hash cocok dan setiap event sudah tersegel."""
    issues: list[dict] = []
    prev, count = GENESIS, 0
    rows = db.execute(select(LedgerHash, LedgerEvent).join(LedgerEvent, LedgerEvent.id == LedgerHash.event_id)
                      .order_by(LedgerHash.seq)).all()
    for h, ev in rows:
        count += 1
        if h.prev_hash != prev:
            issues.append({"event_id": ev.id, "alasan": "Rantai terputus: prev_hash tidak sama dengan hash sebelumnya"})
        elif h.hash != digest(h.prev_hash, ev):
            issues.append({"event_id": ev.id, "alasan": "Isi event berubah setelah dicatat (hash tidak cocok)"})
        prev = h.hash
        if len(issues) >= limit_issues:
            break
    total = db.scalar(select(func.count()).select_from(LedgerEvent)) or 0
    sealed = db.scalar(select(func.count()).select_from(LedgerHash)) or 0
    return {
        "utuh": not issues and sealed == total,
        "jumlah_event": int(total),
        "diperiksa": count,
        "belum_disegel": int(total - sealed),
        "masalah": issues,
        "hash_terakhir": prev if count else None,
        "diperiksa_pada": clock.now().isoformat(),
    }


def hashes_for(db: Session, event_ids: list[int]) -> dict[int, str]:
    if not event_ids:
        return {}
    return dict(db.execute(select(LedgerHash.event_id, LedgerHash.hash).where(LedgerHash.event_id.in_(event_ids))).all())
