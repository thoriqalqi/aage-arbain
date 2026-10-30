"""Repository ClaimGuard & Compliance Check: simpan audit, perbarui status draf, catat Ledger, dan tindakan manusia.

Prinsip:
- Setiap audit yang selesai (termasuk ALLOWED dan ERROR) → satu baris compliance_audits + satu event Ledger.
- Retry dengan idempotency key yang sama → audit lama dikembalikan, tidak ada duplikasi.
- Status draf hanya diperbarui untuk draf & versi teks yang diaudit; keputusan manusia final (disetujui/dibuang)
  pada versi yang sama tidak ditimpa audit.
- AI tidak pernah menghapus, menerbitkan, atau menyetujui draf; semua itu tindakan manusia yang tercatat."""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.compliance import AuditResult, ClaimGuardEngine, ContextReviewer
from src.compliance.claim_guard import text_hash

from . import clock, ledger
from .models import ComplianceAudit, MarketingDraft, Product, User

STATUS_DRAF = {"BLOCKED": "diblokir", "NEED_REVIEW": "perlu_review", "ALLOWED": "lolos_pemeriksaan", "ERROR": "audit_gagal"}
HUMAN_FINAL = {"disetujui", "dibuang"}


class ComplianceError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def _aktor(user: User) -> str:
    return f"staf:{user.nama}"


def serialize_audit(a: ComplianceAudit) -> dict:
    return {
        "audit_id": a.audit_id, "product_id": a.product_sku, "draft_id": a.draft_id, "draft_versi": a.draft_versi,
        "status": a.status, "stage": a.stage, "reason": a.reason, "violation_law": a.violation_law,
        "regulatory_note": a.regulatory_note, "matched_rules": a.matched_rules, "evidence": a.evidence,
        "references": a.references, "recommendation": a.recommendation, "recommendation_note": a.recommendation_note,
        "rules_version": a.rules_version, "engine_version": a.engine_version, "model_provider": a.model_provider,
        "model_name": a.model_name, "model_info": a.model_info, "error_code": a.error_code,
        "input_text_hash": a.input_text_hash, "text_length": a.text_length, "status_draf_diperbarui": a.status_draf_diperbarui,
        "duration_ms": a.duration_ms, "actor_id": a.actor_id, "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def serialize_draft(d: MarketingDraft) -> dict:
    return {
        "id": d.id, "product_id": d.product.sku if d.product else None, "product_name": d.product.nama if d.product else None,
        "teks": d.teks, "status": d.status, "versi": d.versi, "catatan_keputusan": d.catatan_keputusan,
        "keputusan_oleh": d.keputusan_oleh, "keputusan_pada": d.keputusan_pada.isoformat() if d.keputusan_pada else None,
        "dibuat_pada": d.dibuat_pada.isoformat(), "diperbarui_pada": d.diperbarui_pada.isoformat(),
    }


def _latest_for(db: Session, draft: MarketingDraft) -> ComplianceAudit | None:
    return db.scalar(select(ComplianceAudit).where(ComplianceAudit.draft_id == draft.id)
                     .order_by(ComplianceAudit.id.desc()).limit(1))


def _get_draft(db: Session, draft_id: int) -> MarketingDraft:
    d = db.get(MarketingDraft, draft_id)
    if d is None:
        raise ComplianceError(404, f"Draf #{draft_id} tidak ditemukan")
    return d


def _record_action(db: Session, draft: MarketingDraft, user: User, aksi: str, ringkasan: str, **data) -> None:
    ledger.record(db, "compliance_tindakan", objek_ref=f"marketing_draft:{draft.id}", product_id=draft.product_id,
                  aktor=_aktor(user), ringkasan=ringkasan[:280], alasan=(data.get("catatan") or "")[:500], outcome=aksi,
                  data={"aksi": aksi, "draft_id": draft.id, "versi": draft.versi, "actor_id": user.id, **data})


def run_audit(db: Session, *, engine: ClaimGuardEngine, product_id: str, text: str, user: User,
              draft_id: int | None = None, idempotency_key: str | None = None) -> tuple[ComplianceAudit, MarketingDraft, bool]:
    """Jalankan audit dan simpan. Return (audit, draft, replayed)."""
    if idempotency_key:
        prev = db.scalar(select(ComplianceAudit).where(ComplianceAudit.idempotency_key == idempotency_key))
        if prev is not None:
            if prev.input_text_hash != text_hash(text) or prev.product_sku != product_id.strip():
                raise ComplianceError(409, "Idempotency key sudah dipakai untuk permintaan audit yang berbeda")
            return prev, db.get(MarketingDraft, prev.draft_id), True

    draft = None
    if draft_id is not None:
        draft = _get_draft(db, draft_id)
        if draft.product is None or draft.product.sku != product_id.strip():
            raise ComplianceError(422, f"Draf #{draft_id} bukan milik produk {product_id}")
        if draft.status == "dibuang":
            raise ComplianceError(409, f"Draf #{draft_id} sudah dibuang")
    versi_awal = draft.versi if draft else None

    result: AuditResult = engine.verify_content(product_id, text)  # validasi input terjadi sebelum LLM dipanggil

    now = clock.now()
    product = db.scalar(select(Product).where(Product.sku == result.product_id))
    if draft is None:
        draft = MarketingDraft(product_id=product.id, teks=text, status="draf", versi=1, dibuat_oleh=user.id,
                               dibuat_pada=now, diperbarui_pada=now)
        db.add(draft)
        db.flush()
        _record_action(db, draft, user, "draf_dibuat", f"Draf #{draft.id} dibuat untuk {product.nama}", sesudah=text)
    else:
        db.refresh(draft)
        if draft.versi != versi_awal:
            raise ComplianceError(409, "Draf berubah saat audit berjalan; muat ulang lalu audit kembali")
        if draft.teks != text:
            sebelum = draft.teks
            draft.teks, draft.versi, draft.diperbarui_pada = text, draft.versi + 1, now
            _record_action(db, draft, user, "teks_diubah", f"Teks draf #{draft.id} diubah manusia (versi {draft.versi})",
                           sebelum=sebelum, sesudah=text)

    perbarui = not (draft.status in HUMAN_FINAL and draft.teks == text and versi_awal == draft.versi)
    if perbarui:
        draft.status = STATUS_DRAF[result.status]
        draft.diperbarui_pada = now

    audit = ComplianceAudit(
        audit_id=uuid.uuid4().hex, idempotency_key=idempotency_key, product_sku=result.product_id, product_id=product.id,
        draft_id=draft.id, draft_versi=draft.versi, input_text_hash=result.input_text_hash, text_length=result.text_length,
        status=result.status, stage=result.stage, reason=result.reason, violation_law=result.violation_law,
        regulatory_note=result.regulatory_note, matched_rules=[m.model_dump() for m in result.matched_rules],
        evidence=[e.model_dump() for e in result.evidence], references=result.references,
        recommendation=result.recommendation, recommendation_note=result.recommendation_note,
        rules_version=result.rules_version, engine_version=result.engine_version,
        model_provider=result.model_info.provider if result.model_info else None,
        model_name=result.model_info.model if result.model_info else None,
        model_info=result.model_info.model_dump() if result.model_info else None, error_code=result.error_code,
        status_draf_diperbarui=perbarui, duration_ms=result.duration_ms, actor_id=user.id, created_at=now,
    )
    db.add(audit)
    ledger.record(
        db, "compliance_audit", objek_ref=f"audit:{audit.audit_id}", product_id=product.id, aktor=_aktor(user),
        ringkasan=f"Compliance Check {result.status} · {product.nama} · draf #{draft.id} v{draft.versi}"[:280],
        alasan=result.reason[:1000], verdict={"BLOCKED": "blocked", "NEED_REVIEW": "review", "ALLOWED": "allowed"}.get(result.status),
        aturan_terpicu=sorted({m.rule_id for m in result.matched_rules}), model=audit.model_name,
        token_in=result.model_info.input_tokens if result.model_info else 0,
        token_out=result.model_info.output_tokens if result.model_info else 0, latensi_ms=result.duration_ms,
        outcome=result.status,
        sumber_ref=[{"jenis": "regulasi", "judul": r["singkat"], "kutipan": r["article_reference"]} for r in result.references[:8]],
        data={k: v for k, v in serialize_audit(audit).items() if k not in {"references", "matched_rules"}}
        | {"matched_rules": sorted({m.rule_id for m in result.matched_rules}), "draft_id": draft.id},
    )
    try:
        db.commit()
    except IntegrityError:  # retry paralel dengan idempotency key yang sama
        db.rollback()
        prev = db.scalar(select(ComplianceAudit).where(ComplianceAudit.idempotency_key == idempotency_key)) if idempotency_key else None
        if prev is None:
            raise
        return prev, db.get(MarketingDraft, prev.draft_id), True
    db.refresh(draft)
    return audit, draft, False


def latest_audit(db: Session, product_id: str | None, draft_id: int | None) -> tuple[ComplianceAudit | None, MarketingDraft | None]:
    q = select(ComplianceAudit)
    if draft_id is not None:
        q = q.where(ComplianceAudit.draft_id == draft_id)
    if product_id:
        q = q.where(ComplianceAudit.product_sku == product_id.strip())
    audit = db.scalar(q.order_by(ComplianceAudit.id.desc()).limit(1))
    draft = db.get(MarketingDraft, draft_id) if draft_id is not None else (db.get(MarketingDraft, audit.draft_id) if audit and audit.draft_id else None)
    return audit, draft


def history(db: Session, draft_id: int) -> list[ComplianceAudit]:
    return list(db.scalars(select(ComplianceAudit).where(ComplianceAudit.draft_id == draft_id).order_by(ComplianceAudit.id.desc())))


def apply_recommendation(db: Session, *, engine: ClaimGuardEngine, draft_id: int, audit_id: str, confirm: bool,
                         user: User) -> tuple[ComplianceAudit, MarketingDraft]:
    """Terapkan rekomendasi hanya dengan persetujuan eksplisit, lalu audit ulang teks revisi (audit baru, riwayat tetap)."""
    if not confirm:
        raise ComplianceError(422, "Penerapan rekomendasi memerlukan persetujuan eksplisit (confirm=true)")
    draft = _get_draft(db, draft_id)
    if draft.status == "dibuang":
        raise ComplianceError(409, "Draf sudah dibuang")
    audit = db.scalar(select(ComplianceAudit).where(ComplianceAudit.audit_id == audit_id))
    if audit is None or audit.draft_id != draft.id:
        raise ComplianceError(404, "Audit tidak ditemukan untuk draf ini")
    latest = _latest_for(db, draft)
    if latest is None or latest.audit_id != audit.audit_id or audit.draft_versi != draft.versi:
        raise ComplianceError(409, "Rekomendasi sudah usang — draf telah berubah atau ada audit yang lebih baru")
    if not audit.recommendation:
        raise ComplianceError(422, "Audit ini tidak memiliki rekomendasi yang dapat diterapkan")
    sebelum = draft.teks
    draft.teks, draft.versi, draft.status, draft.diperbarui_pada = audit.recommendation, draft.versi + 1, "menunggu_audit_ulang", clock.now()
    _record_action(db, draft, user, "rekomendasi_diterapkan",
                   f"Rekomendasi aman audit {audit.audit_id[:8]} diterapkan ke draf #{draft.id} (versi {draft.versi})",
                   sebelum=sebelum, sesudah=draft.teks, audit_id=audit.audit_id)
    db.commit()
    new_audit, draft, _ = run_audit(db, engine=engine, product_id=draft.product.sku, text=draft.teks, user=user, draft_id=draft.id)
    return new_audit, draft


def discard(db: Session, *, draft_id: int, confirm: bool, alasan: str | None, user: User) -> MarketingDraft:
    """Buang draf (soft delete: status dibuang). Teks & riwayat audit tetap untuk jejak audit."""
    if not confirm:
        raise ComplianceError(422, "Membuang draf memerlukan konfirmasi eksplisit (confirm=true)")
    draft = _get_draft(db, draft_id)
    if draft.status == "dibuang":
        return draft
    status_lama = draft.status
    draft.status, draft.keputusan_oleh, draft.keputusan_pada = "dibuang", user.id, clock.now()
    draft.catatan_keputusan, draft.diperbarui_pada = alasan, draft.keputusan_pada
    _record_action(db, draft, user, "draf_dibuang", f"Draf #{draft.id} dibuang ({status_lama})", catatan=alasan,
                   status_sebelum=status_lama)
    db.commit()
    return draft


def approve(db: Session, *, draft_id: int, confirm: bool, catatan: str | None, user: User) -> MarketingDraft:
    """Persetujuan manusia. ALLOWED: staf; NEED_REVIEW: hanya admin dengan catatan. BLOCKED/ERROR tidak bisa disetujui."""
    if not confirm:
        raise ComplianceError(422, "Persetujuan memerlukan konfirmasi eksplisit (confirm=true)")
    draft = _get_draft(db, draft_id)
    if draft.status == "dibuang":
        raise ComplianceError(409, "Draf sudah dibuang")
    latest = _latest_for(db, draft)
    if latest is None or latest.draft_versi != draft.versi:
        raise ComplianceError(409, "Versi teks terbaru belum diaudit")
    if latest.status in ("BLOCKED", "ERROR"):
        raise ComplianceError(409, f"Draf dengan audit {latest.status} tidak dapat disetujui; terapkan rekomendasi atau revisi teks")
    if latest.status == "NEED_REVIEW":
        if user.role != "admin":
            raise ComplianceError(403, "Hanya admin yang dapat menyetujui draf berstatus NEED_REVIEW")
        if not catatan or len(catatan.strip()) < 10:
            raise ComplianceError(422, "Tulis catatan peninjauan (min. 10 karakter) untuk menyetujui draf NEED_REVIEW")
    status_lama = draft.status
    draft.status, draft.keputusan_oleh, draft.keputusan_pada = "disetujui", user.id, clock.now()
    draft.catatan_keputusan, draft.diperbarui_pada = catatan, draft.keputusan_pada
    _record_action(db, draft, user, "draf_disetujui", f"Draf #{draft.id} disetujui manusia (audit {latest.status})",
                   catatan=catatan, audit_id=latest.audit_id, status_sebelum=status_lama)
    db.commit()
    return draft


def list_drafts(db: Session, product_id: str | None, limit: int = 30) -> list[MarketingDraft]:
    q = select(MarketingDraft).join(Product)
    if product_id:
        q = q.where(Product.sku == product_id.strip())
    return list(db.scalars(q.order_by(MarketingDraft.diperbarui_pada.desc()).limit(limit)))


def registry_view() -> dict:
    from .claimguard import registry

    reg = registry.load()
    return {
        "rules_version": reg["rules_version"],
        "regulations": [{"id": k, **v} for k, v in reg["regulations"].items()],
        "rules": [{"rule_id": rid, **{k: v for k, v in r.items() if k != "frasa"}, "frasa": r.get("frasa", []),
                   "references": registry.references_for(rid)} for rid, r in reg["rules"].items()],
    }


__all__ = ["ComplianceError", "ContextReviewer", "apply_recommendation", "approve", "discard", "history",
           "latest_audit", "list_drafts", "registry_view", "run_audit", "serialize_audit", "serialize_draft"]
