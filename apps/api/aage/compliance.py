"""Repository Compliance Check: simpan audit, perketat putusan draf konten, dan catat Ledger.

Prinsip:
- Setiap audit yang selesai (termasuk ALLOWED dan ERROR) → satu baris compliance_audits + satu event Ledger.
- Retry dengan idempotency key yang sama → audit lama dikembalikan, tidak ada duplikasi.
- Draf hanya ada satu jenis: content_drafts milik Studio Konten. Audit tanpa draf tidak membuat draf.
- Audit draf memeriksa isi draf itu sendiri. Mengubah, menyetujui, dan mengarsipkan draf hanya lewat Studio Konten,
  supaya aturan dua orang dan riwayat versi tidak punya jalan pintas.
- AI tidak pernah menghapus, menerbitkan, atau menyetujui draf. Audit hanya bisa memperketat putusan, tidak melonggarkan."""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.compliance import AuditResult, ClaimGuardEngine, ContextReviewer
from src.compliance.claim_guard import text_hash

from . import clock, ledger
from .content import studio
from .models import ComplianceAudit, ContentDraft, Product, User
from .security import punya_izin


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


def serialize_draft(db: Session, d: ContentDraft) -> dict:
    p = db.get(Product, d.product_id) if d.product_id else None
    return {"id": d.id, "product_id": p.sku if p else None, "product_name": p.nama if p else None, "tipe": d.tipe, "judul": d.judul,
            "isi": d.isi, "status": d.status, "claim_verdict": d.claim_verdict, "versi": studio.nomor_versi(db, d.id)}


def _draf_untuk_audit(db: Session, draft_id: int, product_id: str, user: User) -> ContentDraft:
    if not punya_izin(user, "konten"):
        raise ComplianceError(403, "Audit draf konten hanya untuk peran yang memegang izin konten")
    draft = db.get(ContentDraft, draft_id)
    if draft is None:
        raise ComplianceError(404, f"Draf #{draft_id} tidak ditemukan")
    produk = db.get(Product, draft.product_id) if draft.product_id else None
    if produk is None or produk.sku != product_id.strip():
        raise ComplianceError(422, f"Draf #{draft_id} bukan milik produk {product_id}")
    if draft.status == "diarsipkan":
        raise ComplianceError(409, f"Draf #{draft_id} sudah diarsipkan")
    return draft


def run_audit(db: Session, *, engine: ClaimGuardEngine, product_id: str, text: str | None, user: User,
              draft_id: int | None = None, idempotency_key: str | None = None) -> tuple[ComplianceAudit, ContentDraft | None, bool]:
    """Jalankan audit dan simpan. Return (audit, draft, replayed). Dengan `draft_id`, yang diperiksa adalah isi draf."""
    if draft_id is not None and text:
        raise ComplianceError(422, "Audit draf memeriksa isi draf itu sendiri; jangan kirim teks. Ubah teks lewat Studio Konten.")
    if draft_id is None and not text:
        raise ComplianceError(422, "Sertakan teks atau draft_id")
    draft = _draf_untuk_audit(db, draft_id, product_id, user) if draft_id is not None else None
    text = studio.full_text(draft) if draft else text

    if idempotency_key:
        prev = db.scalar(select(ComplianceAudit).where(ComplianceAudit.idempotency_key == idempotency_key))
        if prev is not None:
            if prev.input_text_hash != text_hash(text) or prev.product_sku != product_id.strip() or prev.draft_id != draft_id:
                raise ComplianceError(409, "Idempotency key sudah dipakai untuk permintaan audit yang berbeda")
            return prev, draft, True

    result: AuditResult = engine.verify_content(product_id, text)  # validasi input terjadi sebelum LLM dipanggil

    now = clock.now()
    product = db.scalar(select(Product).where(Product.sku == result.product_id))
    perbarui, putusan_baru = False, None
    if draft is not None:
        db.refresh(draft)
        if studio.full_text(draft) != text:  # LLM bisa makan waktu semenit, dan staf bisa menyimpan selama itu
            raise ComplianceError(409, "Draf berubah saat audit berjalan; muat ulang lalu audit kembali")
        putusan_baru = studio.lebih_ketat(draft.claim_verdict, studio.PUTUSAN_AUDIT.get(result.status))
        perbarui = putusan_baru != draft.claim_verdict
    versi = studio.nomor_versi(db, draft.id) if draft else None

    audit = ComplianceAudit(
        audit_id=uuid.uuid4().hex, idempotency_key=idempotency_key, product_sku=result.product_id, product_id=product.id,
        draft_id=draft_id, draft_versi=versi, input_text_hash=result.input_text_hash, text_length=result.text_length,
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
    if perbarui:
        draft.claim_verdict = putusan_baru
    sasaran = f"draf #{draft_id} v{versi}" if draft else "tanpa draf"
    ledger.record(
        db, "compliance_audit", objek_ref=f"audit:{audit.audit_id}", product_id=product.id, aktor=_aktor(user),
        ringkasan=f"Compliance Check {result.status} · {product.nama} · {sasaran}"[:280],
        alasan=result.reason[:1000], verdict={"BLOCKED": "blocked", "NEED_REVIEW": "review", "ALLOWED": "allowed"}.get(result.status),
        aturan_terpicu=sorted({m.rule_id for m in result.matched_rules}), model=audit.model_name,
        token_in=result.model_info.input_tokens if result.model_info else 0,
        token_out=result.model_info.output_tokens if result.model_info else 0, latensi_ms=result.duration_ms,
        biaya_rp=result.model_info.biaya_rp if result.model_info else 0.0,
        outcome=result.status,
        sumber_ref=[{"jenis": "regulasi", "judul": r["singkat"], "kutipan": r["article_reference"]} for r in result.references[:8]],
        data={k: v for k, v in serialize_audit(audit).items() if k not in {"references", "matched_rules"}}
        | {"matched_rules": sorted({m.rule_id for m in result.matched_rules})},
    )
    try:
        db.commit()
    except IntegrityError:  # retry paralel dengan idempotency key yang sama
        db.rollback()
        prev = db.scalar(select(ComplianceAudit).where(ComplianceAudit.idempotency_key == idempotency_key)) if idempotency_key else None
        if prev is None:
            raise
        return prev, draft, True
    return audit, draft, False


def latest_audit(db: Session, product_id: str | None, draft_id: int | None) -> tuple[ComplianceAudit | None, ContentDraft | None]:
    q = select(ComplianceAudit)
    if draft_id is not None:
        q = q.where(ComplianceAudit.draft_id == draft_id)
    if product_id:
        q = q.where(ComplianceAudit.product_sku == product_id.strip())
    audit = db.scalar(q.order_by(ComplianceAudit.id.desc()).limit(1))
    terkait = draft_id if draft_id is not None else (audit.draft_id if audit else None)
    return audit, db.get(ContentDraft, terkait) if terkait is not None else None


def history(db: Session, draft_id: int) -> list[ComplianceAudit]:
    return list(db.scalars(select(ComplianceAudit).where(ComplianceAudit.draft_id == draft_id).order_by(ComplianceAudit.id.desc())))


def registry_view() -> dict:
    from .claimguard import registry

    reg = registry.load()
    return {
        "rules_version": reg["rules_version"],
        "regulations": [{"id": k, **v} for k, v in reg["regulations"].items()],
        "rules": [{"rule_id": rid, **{k: v for k, v in r.items() if k != "frasa"}, "frasa": r.get("frasa", []),
                   "references": registry.references_for(rid)} for rid, r in reg["rules"].items()],
    }


__all__ = ["ComplianceError", "ContextReviewer", "history", "latest_audit", "registry_view", "run_audit", "serialize_audit",
           "serialize_draft"]
