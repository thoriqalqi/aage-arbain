"""Status live enam agen (Brief §3) + endpoint Pengaturan.

Status tidak disimulasikan: dihitung dari Ledger (satu sumber kebenaran). Setiap tipe event dipetakan ke agen
yang mengerjakannya, lalu agen dianggap "bekerja" bila ada event dalam 90 detik terakhir.

- GET /api/agents/status         snapshot status, tugas & biaya hari ini, antrean, mode otonomi efektif
- GET /api/agents/status/stream  Server-Sent Events: snapshot baru setiap kali ada perubahan
- GET /api/settings              pengaturan (semua role)
- PUT /api/settings              ubah mode otonomi / jeda / budget (admin), tercatat di Ledger
"""

import json
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import clock, llm, settings_store
from .db import SessionLocal, get_db
from .ledger import EVENT_TYPES
from .models import Approval, LedgerEvent, User
from .security import current_user, require_admin

router = APIRouter()

WIB = timezone(timedelta(hours=7))
ACTIVE_WINDOW_S = 90
STREAM_TICK_S = 2.0
STREAM_MAX_S = 600  # klien menyambung ulang setelah ini

AGENT_EVENTS: dict[str, tuple[str, ...]] = {
    "orchestrator": ("pesan_masuk", "intent", "kebijakan", "approval_dibuat"),
    "opportunity": ("prospek_dibuat", "prospek_status", "prospek_riset"),
    "sales": ("retrieval", "draf_jawaban", "pesan_keluar", "draf_pesanan", "pengingat_repeat_order",
              "invoice_dikirim", "agen_hitl"),
    "content": ("konten_dibuat", "konten_disetujui", "konten_diekspor", "audit_halaman"),
    "claimguard": ("claimguard", "claimguard_inbound", "agen_claimguard", "claimguard_playground",
                   "compliance_audit", "compliance_tindakan"),
    "evaluation": (),
}
IDLE_TEXT = {
    "orchestrator": "Menunggu pesan atau tugas baru",
    "opportunity": "Menunggu wilayah baru untuk dipetakan",
    "sales": "Siap menjawab pesan WhatsApp",
    "content": "Menunggu permintaan konten",
    "claimguard": "Siap memeriksa klaim",
    "evaluation": "Evaluasi dijalankan lewat skrip eval (belum terjadwal)",
}


def _start_of_day() -> datetime:
    local = clock.now().astimezone(WIB)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def compute(db: Session) -> dict:
    now = clock.now()
    today = _start_of_day()
    modes = settings_store.otonomi(db)
    paused = settings_store.jeda(db)
    pending = db.scalar(select(func.count()).select_from(Approval).where(Approval.status == "menunggu")) or 0

    agents = []
    for agent, types in AGENT_EVENTS.items():
        tugas, biaya, last = 0, 0.0, None
        if types:
            tugas, biaya = db.execute(
                select(func.count(), func.coalesce(func.sum(LedgerEvent.biaya_rp), 0))
                .where(LedgerEvent.tipe_event.in_(types), LedgerEvent.waktu >= today)
            ).one()
            last = db.scalars(select(LedgerEvent).where(LedgerEvent.tipe_event.in_(types))
                              .order_by(LedgerEvent.id.desc()).limit(1)).first()
        last_at = clock.aware(last.waktu) if last else None
        antrean = pending if agent == "sales" else 0

        if paused[agent]:
            status = "jeda"
        elif last_at and (now - last_at).total_seconds() <= ACTIVE_WINDOW_S:
            status = "bekerja"
        elif antrean:
            status = "menunggu"
        else:
            status = "idle"

        if last and last_at and last_at >= today:
            label = EVENT_TYPES.get(last.tipe_event, last.tipe_event)
            kerja = f"{label}: {' '.join((last.ringkasan or '').split())}".rstrip(": ")[:120]
        else:
            kerja = IDLE_TEXT[agent]
        mode_efektif, alasan_mode = settings_store.effective_mode(db, agent)
        agents.append({
            "id": agent, "status": status, "tugas": int(tugas), "biaya_rp": round(float(biaya), 2),
            "antrean": int(antrean), "kerja": kerja, "terakhir": last_at.isoformat() if last_at else None,
            "mode": modes[agent], "mode_efektif": mode_efektif, "alasan_mode": alasan_mode, "jeda": paused[agent],
        })

    caps = settings_store.anggaran(db)
    return {
        "agen": agents,
        "anggaran": {**caps, "terpakai_hari_ini_rp": round(llm.spent_rp(days=1), 2),
                     "terpakai_bulan_ini_rp": round(llm.spent_rp(month=True), 2),
                     "terlampaui": settings_store.budget_exceeded(db)},
        "diperbarui": now.isoformat(),
    }


@router.get("/agents/status")
def agents_status(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return compute(db)


@router.get("/agents/status/stream")
def agents_status_stream(user: User = Depends(current_user)):
    def gen():
        last_payload, started, last_sent = None, time.monotonic(), 0.0
        while time.monotonic() - started < STREAM_MAX_S:
            with SessionLocal() as db:
                data = compute(db)
            # "diperbarui" selalu berubah; bandingkan isi tanpa stempel waktu.
            body = json.dumps({k: v for k, v in data.items() if k != "diperbarui"}, sort_keys=True)
            if body != last_payload:
                last_payload, last_sent = body, time.monotonic()
                yield f"data: {json.dumps(data)}\n\n"
            elif time.monotonic() - last_sent > 15:
                last_sent = time.monotonic()
                yield ": ping\n\n"
            time.sleep(STREAM_TICK_S)
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/settings")
def get_settings_view(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return settings_store.snapshot(db)


@router.put("/settings")
def put_settings(patch: dict = Body(...), user: User = Depends(require_admin), db: Session = Depends(get_db)):
    allowed = {"otonomi", "jeda", "anggaran"}
    unknown = set(patch) - allowed
    if unknown:
        raise HTTPException(422, f"Kunci tidak dikenal: {', '.join(sorted(unknown))}")
    try:
        return settings_store.update(db, patch, aktor=f"staf:{user.nama}")
    except (settings_store.InvalidSetting, TypeError, ValueError) as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
