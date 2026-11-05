"""Endpoint ClaimGuard & Compliance Check (prefix /api/compliance). Semua endpoint butuh login (JWT).

- POST /api/compliance/audit                          audit teks (+ draft_id opsional, Idempotency-Key opsional)
- GET  /api/compliance/latest-audit                   audit terbaru per product_id/draft_id (tanpa memanggil LLM)
- GET  /api/compliance/audits?draft_id=               riwayat audit draf
- GET  /api/compliance/drafts[?product_id=]           daftar draf
- GET  /api/compliance/drafts/{id}                    draf + audit terbaru
- POST /api/compliance/drafts/{id}/apply-recommendation   terapkan rekomendasi (confirm=true) → audit ulang otomatis
- POST /api/compliance/drafts/{id}/discard            buang draf (confirm=true, soft delete)
- POST /api/compliance/drafts/{id}/approve            setujui draf (confirm=true; NEED_REVIEW hanya admin + catatan)
- GET  /api/compliance/registry                       rujukan regulasi & aturan yang dipakai

Batasan: otorisasi per produk belum ada — setiap pengguna login dapat melihat semua draf/audit. Endpoint ini tidak
boleh dibuka publik di produksi tanpa kontrol akses tambahan."""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.compliance import ClaimGuardEngine, ClaimGuardInputError, JalurUtamaReviewer, UnknownProductError

from . import compliance as svc
from .config import get_settings
from .db import get_db
from .models import User
from .security import current_user

log = logging.getLogger("aage.compliance")
router = APIRouter(prefix="/api/compliance")


def get_engine(db: Session = Depends(get_db)) -> ClaimGuardEngine:
    return ClaimGuardEngine(db, JalurUtamaReviewer())


class AuditIn(BaseModel):
    product_id: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=200_000)  # batas sebenarnya CLAIMGUARD_MAX_TEXT_LENGTH (dicek engine)
    draft_id: int | None = None
    request_id: str | None = Field(None, min_length=8, max_length=80, description="Idempotency key alternatif header")


class ConfirmIn(BaseModel):
    confirm: bool = False
    catatan: str | None = Field(None, max_length=2000)


class ApplyIn(ConfirmIn):
    audit_id: str = Field(min_length=8, max_length=32)


def _raise(exc: svc.ComplianceError):
    raise HTTPException(exc.status_code, str(exc)) from None


def _input_error(exc: ClaimGuardInputError):
    status = 404 if isinstance(exc, UnknownProductError) else 422
    raise HTTPException(status, {"pesan": str(exc), "kode": exc.code}) from None


@router.post("/audit")
def audit(body: AuditIn, idempotency_key: str | None = Header(None, alias="Idempotency-Key", max_length=80),
          user: User = Depends(current_user), db: Session = Depends(get_db), engine: ClaimGuardEngine = Depends(get_engine)):
    try:
        a, d, replayed = svc.run_audit(db, engine=engine, product_id=body.product_id, text=body.text, user=user,
                                       draft_id=body.draft_id, idempotency_key=idempotency_key or body.request_id)
    except ClaimGuardInputError as exc:
        _input_error(exc)
    except svc.ComplianceError as exc:
        _raise(exc)
    except Exception:  # infrastruktur (DB, dsb.) — detail tidak dikirim ke client
        log.exception("Compliance audit gagal")
        db.rollback()
        raise HTTPException(503, "Audit tidak dapat diproses saat ini; coba lagi") from None
    return {"audit": svc.serialize_audit(a), "draft": svc.serialize_draft(d), "replayed": replayed}


@router.get("/latest-audit")
def latest_audit(product_id: str | None = None, draft_id: int | None = None,
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not product_id and draft_id is None:
        raise HTTPException(422, "Sertakan product_id dan/atau draft_id")
    a, d = svc.latest_audit(db, product_id, draft_id)
    return {"state": "ada" if a else "kosong", "audit": svc.serialize_audit(a) if a else None,
            "draft": svc.serialize_draft(d) if d else None}


@router.get("/audits")
def audits(draft_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"items": [svc.serialize_audit(a) for a in svc.history(db, draft_id)]}


@router.get("/drafts")
def drafts(product_id: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"items": [svc.serialize_draft(d) for d in svc.list_drafts(db, product_id)]}


@router.get("/drafts/{draft_id}")
def draft_get(draft_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a, d = svc.latest_audit(db, None, draft_id)
    if d is None:
        raise HTTPException(404, f"Draf #{draft_id} tidak ditemukan")
    return {"draft": svc.serialize_draft(d), "audit": svc.serialize_audit(a) if a else None}


@router.post("/drafts/{draft_id}/apply-recommendation")
def apply_recommendation(draft_id: int, body: ApplyIn, user: User = Depends(current_user), db: Session = Depends(get_db),
                         engine: ClaimGuardEngine = Depends(get_engine)):
    try:
        a, d = svc.apply_recommendation(db, engine=engine, draft_id=draft_id, audit_id=body.audit_id, confirm=body.confirm, user=user)
    except ClaimGuardInputError as exc:
        _input_error(exc)
    except svc.ComplianceError as exc:
        _raise(exc)
    return {"audit": svc.serialize_audit(a), "draft": svc.serialize_draft(d)}


@router.post("/drafts/{draft_id}/discard")
def discard(draft_id: int, body: ConfirmIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        d = svc.discard(db, draft_id=draft_id, confirm=body.confirm, alasan=body.catatan, user=user)
    except svc.ComplianceError as exc:
        _raise(exc)
    return {"draft": svc.serialize_draft(d)}


@router.post("/drafts/{draft_id}/approve")
def approve(draft_id: int, body: ConfirmIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        d = svc.approve(db, draft_id=draft_id, confirm=body.confirm, catatan=body.catatan, user=user)
    except svc.ComplianceError as exc:
        _raise(exc)
    return {"draft": svc.serialize_draft(d)}


@router.get("/registry")
def registry(user: User = Depends(current_user)):
    s = get_settings()
    return {**svc.registry_view(), "llm": {"provider": s.llm_provider, "model": s.llm_judge_model,
                                          "dikonfigurasi": s.llm_enabled,
                                          "status_bila_gagal": s.claimguard_llm_failure_status.upper()},
            "batas_teks": s.claimguard_max_text_length}
