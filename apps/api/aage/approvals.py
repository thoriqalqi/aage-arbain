"""Inbox & Approval (M5): staf menyetujui, mengedit, atau menolak draf. Teks yang dikirim tetap
diperiksa ClaimGuard — staf pun tidak bisa mengirim klaim yang diblokir."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import claimguard, clock, inbox, ledger
from .channels import sender
from .models import Approval, ContentDraft, Conversation, LedgerEvent, OrderDraft, User


class ApprovalError(Exception):
    def __init__(self, message: str, check: claimguard.CheckResult | None = None):
        super().__init__(message)
        self.check = check


def _decide_content(db: Session, ap: Approval, *, aksi: str, actor: str) -> None:
    """Konten pemasaran: disetujui/ditolak di sini, diedit di Studio Konten. Aturan dua orang berlaku."""
    from .content import studio

    d = db.get(ContentDraft, ap.objek_id) if ap.objek_id else None
    if d is None:
        raise ApprovalError("Draf konten tidak ditemukan")
    if aksi == "tolak":
        ap.status = "ditolak"
        d.status = "ditolak"
        return
    if aksi != "setujui":
        raise ApprovalError("Konten diedit di Studio Konten; di sini hanya Setujui atau Tolak.")
    submitter = db.scalar(select(LedgerEvent.aktor).where(LedgerEvent.tipe_event == "approval_dibuat",
                                                          LedgerEvent.objek_ref == f"approval:{ap.id}"))
    if actor == submitter:
        raise ApprovalError("Aturan dua orang: pengaju draf tidak boleh menyetujui drafnya sendiri.")
    try:
        studio.approve(db, d, actor, commit=False)
    except studio.ContentError as exc:
        raise ApprovalError(str(exc)) from None
    ap.status = "disetujui"
    ap.verdict = d.claim_verdict


def decide(db: Session, approval_id: int, *, aksi: str, user: User, teks: str | None = None,
           catatan: str | None = None) -> Approval:
    ap = db.get(Approval, approval_id)
    if ap is None:
        raise ApprovalError("Approval tidak ditemukan")
    if ap.status != "menunggu":
        raise ApprovalError(f"Approval sudah {ap.status}")
    conv = db.get(Conversation, ap.conversation_id) if ap.conversation_id else None
    actor = f"staf:{user.nama}"

    if ap.objek_tipe == "konten":
        _decide_content(db, ap, aksi=aksi, actor=actor)
    elif aksi == "tolak":
        ap.status = "ditolak"
        if ap.objek_tipe == "order_draft" and ap.objek_id:
            od = db.get(OrderDraft, ap.objek_id)
            if od:
                od.status = "ditolak"
    elif aksi in {"setujui", "edit"}:
        text = (teks if aksi == "edit" and teks else ap.draf or "").strip()
        if not text:
            raise ApprovalError("Draf kosong — tulis balasan terlebih dahulu (aksi edit).")
        product_ids = (conv.konteks or {}).get("last_product_ids") if conv else None
        check = claimguard.check(db, text, product_ids=product_ids or None)
        ledger.record(db, "claimguard", trace_id=ap.trace_id, conversation_id=ap.conversation_id,
                      objek_ref=f"approval:{ap.id}", ringkasan=f"ClaimGuard atas teks staf: {check.label}",
                      verdict=check.verdict, aturan_terpicu=check.rules_triggered,
                      alasan=" | ".join(check.reasons[:5]), model=check.model, biaya_rp=check.biaya_rp,
                      aktor=actor, latensi_ms=check.duration_ms,
                      data={"sentences": check.to_dict()["sentences"], "safe_text": check.safe_text})
        if check.verdict != claimguard.ALLOWED:
            db.commit()
            raise ApprovalError(f"ClaimGuard: {check.label}. Perbaiki teks sebelum dikirim.", check)
        if conv is not None:
            sender.send(db, conv, text, check=check, pengirim="staf", trace_id=ap.trace_id, aktor=actor,
                        approval_id=ap.id, sources=[{"jenis": "approval", "approval_id": ap.id}],
                        inbound_at=ap.dibuat_pada)
            if conv.status == inbox.DITANGANI_STAF:
                conv.aktivitas_staf_terakhir = clock.now()
            else:
                conv.status = "otomatis"
        if ap.objek_tipe == "order_draft" and ap.objek_id:
            od = db.get(OrderDraft, ap.objek_id)
            if od:
                od.status = "dikonfirmasi staf"
                if conv is not None:
                    from .prospects.mapper import mark_customer

                    mark_customer(db, conv.contact, actor)
        ap.status = "disetujui"
        if aksi == "edit":
            ap.draf = text
    else:
        raise ApprovalError("Aksi harus setujui, edit, atau tolak")

    ap.ditinjau_oleh = user.nama
    ap.catatan = catatan
    ap.diputus_pada = clock.now()
    ledger.record(db, "approval_diputus", trace_id=ap.trace_id, conversation_id=ap.conversation_id,
                  objek_ref=f"approval:{ap.id}", ringkasan=f"Approval #{ap.id} {ap.status} oleh {user.nama}",
                  alasan=catatan or f"Aksi: {aksi}", aktor=actor, outcome=ap.status, verdict=ap.verdict,
                  data={"aksi": aksi, "objek_tipe": ap.objek_tipe, "objek_id": ap.objek_id})
    db.commit()
    return ap
