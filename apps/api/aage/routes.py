"""Endpoint API (prefix /api) — PRD §7."""

import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import approvals as approval_svc
from . import claimguard, kpi, ledger, llm
from . import serializers as ser
from .agents.drafter import _template_source
from .agents.graph import handle_inbound
from .agents.sales import last_order
from .channels import sender, whatsapp
from .config import get_settings
from .content import audit as audit_svc
from .content import studio
from .db import SessionLocal, get_db
from .kb import ingest
from .kb.retriever import document_by_id
from .models import (
    Approval,
    ApprovedClaim,
    Chunk,
    Contact,
    ContentDraft,
    Conversation,
    Document,
    LedgerEvent,
    Message,
    Product,
    Prospect,
    User,
)
from .prospects import mapper
from .security import create_token, current_user, require_admin, verify_password

log = logging.getLogger("aage.api")
settings = get_settings()
router = APIRouter(prefix="/api")


# ------------------------------------------------------------------ auth & status


class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if u is None or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "Email atau kata sandi salah")
    return {"token": create_token(u), "user": ser.user(u)}


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return ser.user(user)


@router.get("/status")
def status():
    return {
        "llm": {"aktif": settings.llm_enabled, "model": settings.llm_model if settings.llm_enabled else llm.OFFLINE_MODEL,
                "judge": settings.llm_judge_model if settings.llm_enabled else None},
        "whatsapp": {"aktif": settings.wa_enabled, "kanal_cadangan": "webchat"},
        "prospek": {"sumber": "OpenStreetMap Overpass (tanpa API key)", "timeout_s": settings.overpass_timeout_s,
                    "maks_hasil": settings.prospek_max_results},
        "anggaran": {"harian_rp": settings.budget_daily_rp, "bulanan_rp": settings.budget_monthly_rp,
                     "terpakai_hari_ini_rp": round(llm.spent_rp(days=1), 2),
                     "terpakai_bulan_ini_rp": round(llm.spent_rp(month=True), 2)},
    }


# ------------------------------------------------------------------ WhatsApp webhook & web chat


@router.get("/webhook/whatsapp")
def wa_verify(hub_mode: str = Query(None, alias="hub.mode"), hub_token: str = Query(None, alias="hub.verify_token"),
              hub_challenge: str = Query(None, alias="hub.challenge")):
    if hub_mode == "subscribe" and hub_token == settings.wa_verify_token:
        return PlainTextResponse(hub_challenge or "")
    raise HTTPException(403, "Token verifikasi tidak cocok")


def _process_wa(messages: list[dict]) -> None:
    with SessionLocal() as db:
        for m in messages:
            if db.scalar(select(Message).where(Message.wa_message_id == m["id"])):
                continue  # Meta bisa mengirim ulang webhook yang sama
            try:
                handle_inbound(db, wa_number=m["from"], text=m["text"], kanal="whatsapp", wa_message_id=m["id"])
            except Exception:
                log.exception("Gagal memproses pesan WA %s", m["id"])
                db.rollback()


@router.post("/webhook/whatsapp")
async def wa_webhook(request: Request, background: BackgroundTasks):
    raw = await request.body()
    if not whatsapp.verify_signature(raw, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(401, "Signature webhook tidak valid")
    payload = await request.json()
    msgs = whatsapp.parse_messages(payload)
    if msgs:
        background.add_task(_process_wa, msgs)
    return {"diterima": len(msgs)}


class SimulateIn(BaseModel):
    session: str = Field(..., min_length=3, max_length=32, description="ID sesi web chat (dipakai sebagai nomor)")
    text: str = Field(..., min_length=1, max_length=2000)


@router.post("/chat/simulate")
def chat_simulate(body: SimulateIn, db: Session = Depends(get_db)):
    r = handle_inbound(db, wa_number=f"web:{body.session}", text=body.text, kanal="webchat")
    return {"trace_id": r.trace_id, "conversation_id": r.conversation_id, "intent": r.intent, "keputusan": r.decision,
            "verdict": r.verdict, "verdict_masuk": r.inbound_verdict, "approval_id": r.approval_id,
            "balasan": [ser.message(m) for m in r.replies]}


@router.get("/chat/simulate/{session}/messages")
def chat_messages(session: str, after_id: int = 0, db: Session = Depends(get_db)):
    contact = db.scalar(select(Contact).where(Contact.wa_number == f"web:{session}"))
    if contact is None:
        return {"pesan": []}
    conv_ids = select(Conversation.id).where(Conversation.contact_id == contact.id)
    msgs = db.scalars(select(Message).where(Message.conversation_id.in_(conv_ids), Message.id > after_id).order_by(Message.id))
    return {"pesan": [ser.message(m) for m in msgs]}


# ------------------------------------------------------------------ Inbox


@router.get("/conversations")
def conversations(status: str | None = None, q: str | None = None, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    stmt = select(Conversation).order_by(Conversation.diperbarui_pada.desc()).limit(200)
    if status:
        stmt = stmt.where(Conversation.status == status)
    convs = list(db.scalars(stmt))
    pending = dict(db.execute(select(Approval.conversation_id, func.count()).where(Approval.status == "menunggu")
                              .group_by(Approval.conversation_id)).all())
    out = []
    for c in convs:
        last = db.scalar(select(Message).where(Message.conversation_id == c.id).order_by(Message.id.desc()))
        if q and q.lower() not in f"{c.contact.nama_toko or ''} {last.teks if last else ''}".lower():
            continue
        out.append(ser.conversation(c, user, last, pending.get(c.id, 0)))
    counts = dict(db.execute(select(Conversation.status, func.count()).group_by(Conversation.status)).all())
    return {"items": out, "jumlah_per_status": counts}


@router.get("/conversations/{conv_id}")
def conversation_detail(conv_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = db.get(Conversation, conv_id)
    if c is None:
        raise HTTPException(404, "Percakapan tidak ditemukan")
    events = list(db.scalars(select(LedgerEvent).where(LedgerEvent.conversation_id == c.id).order_by(LedgerEvent.id)))
    lo = last_order(db, c.contact_id)
    aps = list(db.scalars(select(Approval).where(Approval.conversation_id == c.id).order_by(Approval.id.desc())))
    return {
        **ser.conversation(c, user),
        "pesan": [ser.message(m) for m in c.messages],
        "ledger": [ser.ledger_event(e) for e in events],
        "biaya_total_rp": round(sum(e.biaya_rp or 0 for e in events), 2),
        "pesanan_terakhir": ser.order(lo) if lo else None,
        "approvals": [ser.approval(a, c, user) for a in aps],
        "konteks": c.konteks,
    }


class ReplyIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


@router.post("/conversations/{conv_id}/reply")
def conversation_reply(conv_id: int, body: ReplyIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = db.get(Conversation, conv_id)
    if c is None:
        raise HTTPException(404, "Percakapan tidak ditemukan")
    check = claimguard.check(db, body.text, product_ids=(c.konteks or {}).get("last_product_ids") or None)
    trace = ledger.new_trace_id()
    ledger.record(db, "claimguard", trace_id=trace, conversation_id=c.id, objek_ref=f"conversation:{c.id}",
                  ringkasan=f"ClaimGuard atas balasan manual staf: {check.label}", verdict=check.verdict,
                  aturan_terpicu=check.rules_triggered, alasan=" | ".join(check.reasons[:5]), aktor=f"staf:{user.nama}",
                  model=check.model, biaya_rp=check.biaya_rp,
                  data={"sentences": check.to_dict()["sentences"], "safe_text": check.safe_text})
    if check.verdict != claimguard.ALLOWED:
        db.commit()
        raise HTTPException(422, {"pesan": f"ClaimGuard: {check.label}. Balasan tidak dikirim.", "claimguard": check.to_dict()})
    m = sender.send(db, c, body.text, check=check, pengirim="staf", trace_id=trace, aktor=f"staf:{user.nama}",
                    sources=[_template_source("balasan manual staf")])
    db.commit()
    return ser.message(m)


# ------------------------------------------------------------------ Approval


class DecideIn(BaseModel):
    aksi: str = Field(..., pattern="^(setujui|edit|tolak)$")
    teks: str | None = None
    catatan: str | None = None


@router.get("/approvals")
def approvals(status: str = "menunggu", user: User = Depends(current_user), db: Session = Depends(get_db)):
    status = {"pending": "menunggu", "approved": "disetujui", "rejected": "ditolak"}.get(status, status)
    stmt = select(Approval).order_by(Approval.dibuat_pada.asc() if status == "menunggu" else Approval.id.desc())
    if status != "semua":
        stmt = stmt.where(Approval.status == status)
    items = []
    for a in db.scalars(stmt.limit(200)):
        conv = db.get(Conversation, a.conversation_id) if a.conversation_id else None
        items.append(ser.approval(a, conv, user))
    return {"items": items}


@router.post("/approvals/{approval_id}/decide")
def decide(approval_id: int, body: DecideIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        ap = approval_svc.decide(db, approval_id, aksi=body.aksi, user=user, teks=body.teks, catatan=body.catatan)
    except approval_svc.ApprovalError as exc:
        detail = {"pesan": str(exc)}
        if exc.check is not None:
            detail["claimguard"] = exc.check.to_dict()
        raise HTTPException(422, detail) from None
    conv = db.get(Conversation, ap.conversation_id) if ap.conversation_id else None
    return ser.approval(ap, conv, user)


# ------------------------------------------------------------------ Ledger


@router.get("/ledger")
def ledger_list(conversation_id: int | None = None, product_id: int | None = None, verdict: str | None = None,
                tipe: str | None = None, aktor: str | None = None, trace_id: str | None = None,
                dari: datetime | None = None, sampai: datetime | None = None, limit: int = Query(100, le=500),
                offset: int = 0, user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(LedgerEvent)
    if conversation_id:
        stmt = stmt.where(LedgerEvent.conversation_id == conversation_id)
    if product_id:
        stmt = stmt.where(LedgerEvent.product_id == product_id)
    if verdict:
        stmt = stmt.where(LedgerEvent.verdict == verdict)
    if tipe:
        stmt = stmt.where(LedgerEvent.tipe_event == tipe)
    if trace_id:
        stmt = stmt.where(LedgerEvent.trace_id == trace_id)
    if aktor == "AI":
        stmt = stmt.where(LedgerEvent.aktor == "AI")
    elif aktor == "staf":
        stmt = stmt.where(LedgerEvent.aktor.like("staf%"))
    elif aktor:
        stmt = stmt.where(LedgerEvent.aktor == aktor)
    if dari:
        stmt = stmt.where(LedgerEvent.waktu >= dari)
    if sampai:
        stmt = stmt.where(LedgerEvent.waktu <= sampai)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(LedgerEvent.id.desc()).limit(limit).offset(offset))
    return {"total": total, "items": [ser.ledger_event(e) for e in rows], "tipe": ledger.EVENT_TYPES}


@router.get("/ledger/{event_id}/trace")
def ledger_trace(event_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ev = db.get(LedgerEvent, event_id)
    if ev is None:
        raise HTTPException(404, "Event tidak ditemukan")
    chain = [ev] if not ev.trace_id else list(
        db.scalars(select(LedgerEvent).where(LedgerEvent.trace_id == ev.trace_id).order_by(LedgerEvent.id)))
    chunk_ids = {s.get("chunk_id") for e in chain for s in (e.sumber_ref or []) if isinstance(s, dict) and s.get("chunk_id")}
    sources = []
    for cid in sorted(chunk_ids):
        ch = db.get(Chunk, cid)
        if ch is None:
            continue
        doc = document_by_id(db, ch.document_id)
        sources.append({"chunk_id": ch.id, "teks": ch.teks, "versi": ch.versi, "aktif": ch.aktif, "halaman": ch.halaman,
                        "dokumen": {"id": doc.id, "judul": doc.judul, "tipe": doc.tipe, "versi": doc.versi,
                                    "url": doc.url, "diunggah_pada": ser.ts(doc.diunggah_pada), "aktif": doc.aktif}})
    approver = next((e.aktor for e in chain if e.tipe_event == "approval_diputus"), None)
    return {"event": ser.ledger_event(ev), "rantai": [ser.ledger_event(e) for e in chain], "sumber": sources,
            "biaya_total_rp": round(sum(e.biaya_rp or 0 for e in chain), 2),
            "model": sorted({e.model for e in chain if e.model}), "disetujui_oleh": approver}


# ------------------------------------------------------------------ KPI


@router.get("/kpi")
def kpi_endpoint(from_: datetime | None = Query(None, alias="from"), to: datetime | None = None,
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    return kpi.compute(db, from_, to)


# ------------------------------------------------------------------ Knowledge Base


@router.get("/kb/products")
def kb_products(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"items": [ser.product(p) for p in db.scalars(select(Product).order_by(Product.sku))]}


@router.post("/kb/products/import")
async def kb_import(file: UploadFile = File(...), judul: str = Form("Katalog Produk"), user: User = Depends(require_admin),
                    db: Session = Depends(get_db)):
    content = await file.read()
    try:
        rows = ingest._rows_from_upload(file.filename or "katalog.csv", content)
        res = ingest.import_catalog(db, rows, judul=judul, aktor=f"staf:{user.nama}")
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, f"Gagal impor: {exc}") from None
    return res.__dict__


@router.get("/kb/documents")
def kb_documents(user: User = Depends(current_user), db: Session = Depends(get_db)):
    docs = db.scalars(select(Document).order_by(Document.id.desc()))
    counts = dict(db.execute(select(Chunk.document_id, func.count()).group_by(Chunk.document_id)).all())
    return {"items": [{"id": d.id, "judul": d.judul, "tipe": d.tipe, "url": d.url, "versi": d.versi, "aktif": d.aktif,
                       "diunggah_pada": ser.ts(d.diunggah_pada), "potongan": counts.get(d.id, 0)} for d in docs]}


@router.post("/kb/documents")
async def kb_upload(judul: str = Form(...), url: str | None = Form(None), file: UploadFile | None = File(None),
                    user: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        if url:
            text, tipe = ingest.extract_text(None, None, url)
        elif file is not None:
            text, tipe = ingest.extract_text(file.filename, await file.read(), None)
        else:
            raise HTTPException(400, "Unggah file atau isi URL")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"Gagal membaca dokumen: {exc}") from None
    doc = ingest.ingest_document(db, judul=judul, text=text, tipe=tipe, url=url, aktor=f"staf:{user.nama}")
    return {"id": doc.id, "judul": doc.judul, "versi": doc.versi}


@router.get("/kb/chunks/{chunk_id}")
def kb_chunk(chunk_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ch = db.get(Chunk, chunk_id)
    if ch is None:
        raise HTTPException(404, "Potongan tidak ditemukan")
    d = ch.document
    return {"id": ch.id, "teks": ch.teks, "versi": ch.versi, "aktif": ch.aktif, "halaman": ch.halaman,
            "dokumen": {"id": d.id, "judul": d.judul, "versi": d.versi, "tipe": d.tipe, "url": d.url,
                        "diunggah_pada": ser.ts(d.diunggah_pada)}}


class ClaimIn(BaseModel):
    product_id: int
    teks: str = Field(..., min_length=5)
    sumber_dokumen: str = "Input manual"


@router.post("/kb/claims")
def kb_add_claim(body: ClaimIn, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    chk = claimguard.check(db, body.teks, use_llm=False)
    if chk.verdict == claimguard.BLOCKED:
        raise HTTPException(422, {"pesan": "Klaim ini sendiri melanggar aturan ClaimGuard.", "claimguard": chk.to_dict()})
    c = ApprovedClaim(product_id=body.product_id, teks_klaim=body.teks, sumber_dokumen=body.sumber_dokumen,
                      diverifikasi_oleh=None, embedding=llm.embed(body.teks))
    db.add(c)
    db.commit()
    return {"id": c.id}


@router.post("/kb/claims/{claim_id}/verify")
def kb_verify_claim(claim_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = db.get(ApprovedClaim, claim_id)
    if c is None:
        raise HTTPException(404, "Klaim tidak ditemukan")
    c.diverifikasi_oleh = user.nama
    db.commit()
    return {"id": c.id, "diverifikasi_oleh": c.diverifikasi_oleh}


# ------------------------------------------------------------------ ClaimGuard


class CheckIn(BaseModel):
    text: str | None = None
    url: str | None = None
    product_ids: list[int] | None = None
    use_llm: bool = True


@router.post("/claimguard/check")
def claimguard_check(body: CheckIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    text = body.text or ""
    if body.url:
        try:
            text, _ = ingest.extract_text(None, None, body.url)
        except Exception as exc:
            raise HTTPException(400, f"Gagal membuka URL: {exc}") from None
    if not text.strip():
        raise HTTPException(400, "Isi teks atau URL")
    res = claimguard.check(db, text[:20000], product_ids=body.product_ids, use_llm=body.use_llm)
    ledger.record(db, "claimguard_playground", aktor=f"staf:{user.nama}", ringkasan=f"Playground: {res.label}",
                  verdict=res.verdict, aturan_terpicu=res.rules_triggered, model=res.model, biaya_rp=res.biaya_rp,
                  token_in=res.token_in, token_out=res.token_out, latensi_ms=res.duration_ms,
                  data={"summary": res.summary})
    db.commit()
    return {**res.to_dict(), "text": text[:20000]}


# ------------------------------------------------------------------ Content & GEO Studio


class GenerateIn(BaseModel):
    product_id: int
    topik: str = ""
    target: str = Field("apotek", pattern="^(apotek|konsumen)$")
    tipe: str = Field("artikel", pattern="^(artikel|deskripsi)$")


@router.post("/content/generate")
def content_generate(body: GenerateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        d = studio.generate(db, product_id=body.product_id, topik=body.topik, target=body.target, tipe=body.tipe,
                            aktor=f"staf:{user.nama}")
    except studio.ContentError as exc:
        raise HTTPException(400, str(exc)) from None
    return ser.content(d)


@router.get("/content")
def content_list(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"items": [ser.content(d, full=False) for d in db.scalars(select(ContentDraft).order_by(ContentDraft.id.desc()))]}


@router.get("/content/sample-page", response_class=HTMLResponse)
def content_sample_page():
    return audit_svc.SAMPLE_PAGE


@router.get("/content/{content_id}")
def content_get(content_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = db.get(ContentDraft, content_id)
    if d is None:
        raise HTTPException(404, "Konten tidak ditemukan")
    return ser.content(d)


class ContentPatch(BaseModel):
    judul: str | None = None
    isi: str | None = None
    faq: list[dict] | None = None
    meta: dict | None = None


@router.patch("/content/{content_id}")
def content_patch(content_id: int, body: ContentPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = db.get(ContentDraft, content_id)
    if d is None:
        raise HTTPException(404, "Konten tidak ditemukan")
    for field_name in ("judul", "isi", "faq", "meta"):
        value = getattr(body, field_name)
        if value is not None:
            setattr(d, field_name, value)
    if d.product_id:
        d.json_ld = studio.build_json_ld(db.get(Product, d.product_id), d.faq, d.meta)
    d.status = "draf"
    studio.recheck(db, d)
    db.commit()
    return ser.content(d)


@router.post("/content/{content_id}/approve")
def content_approve(content_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = db.get(ContentDraft, content_id)
    if d is None:
        raise HTTPException(404, "Konten tidak ditemukan")
    try:
        studio.approve(db, d, f"staf:{user.nama}")
    except studio.ContentError as exc:
        raise HTTPException(422, str(exc)) from None
    return ser.content(d)


@router.get("/content/{content_id}/export")
def content_export(content_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = db.get(ContentDraft, content_id)
    if d is None:
        raise HTTPException(404, "Konten tidak ditemukan")
    try:
        return studio.export(db, d, f"staf:{user.nama}")
    except studio.ContentError as exc:
        raise HTTPException(422, str(exc)) from None


class AuditIn(BaseModel):
    url: str | None = None
    text: str | None = None
    contoh: bool = False


@router.post("/content/audit")
def content_audit(body: AuditIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        if body.contoh:
            return audit_svc.audit(db, html_doc=audit_svc.SAMPLE_PAGE, aktor=f"staf:{user.nama}")
        if not body.url and not body.text:
            raise HTTPException(400, "Isi URL atau teks")
        return audit_svc.audit(db, url=body.url, text=body.text, aktor=f"staf:{user.nama}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"Audit gagal: {exc}") from None


# ------------------------------------------------------------------ Prospek


class ScoutIn(BaseModel):
    wilayah: str = Field(..., min_length=2, max_length=120, description="Nama area administratif OSM, mis. Kota Semarang")
    jenis_toko: str = Field("Apotek", description="Apotek | Toko Obat | Minimarket")


def _scout_response(res: dict) -> dict:
    meta = {k: (ser.ts(v) if k == "terakhir_dipindai" else v) for k, v in res.items() if k != "prospects"}
    return {**meta, "gudang": {"nama": settings.gudang_nama, "lat": settings.gudang_lat, "lng": settings.gudang_lng},
            "items": [ser.prospect(p) for p in res["prospects"]]}


@router.post("/prospek/scout")
def prospek_scout(body: ScoutIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Live Lead Scouting OSM Overpass → Opportunity Score → simpan ke database tanpa duplikat."""
    try:
        res = mapper.scout_and_store(db, wilayah=body.wilayah, jenis_toko=body.jenis_toko, aktor=f"staf:{user.nama}")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except mapper.ScoutError as exc:
        raise HTTPException(503, str(exc)) from None
    return _scout_response(res)


class ProspectSearchIn(BaseModel):
    wilayah: str = Field(..., min_length=2)
    tipe: str = "Apotek"


@router.post("/prospects/search")
def prospects_search(body: ProspectSearchIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Alias lama — memakai mesin scouting yang sama dengan /api/prospek/scout."""
    return prospek_scout(ScoutIn(wilayah=body.wilayah, jenis_toko=body.tipe), user, db)


def _prospect_query(wilayah: str | None, tipe: str | None, status: str | None):
    stmt = select(Prospect).where(Prospect.sumber == "osm").order_by(Prospect.skor.desc())
    if wilayah:
        stmt = stmt.where(func.lower(Prospect.wilayah) == wilayah.lower())
    if tipe:
        stmt = stmt.where(Prospect.tipe == tipe)
    if status:
        stmt = stmt.where(Prospect.status == status)
    return stmt


@router.get("/prospects")
def prospects_list(wilayah: str | None = None, tipe: str | None = None, status: str | None = None,
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    items = [ser.prospect(p) for p in db.scalars(_prospect_query(wilayah, tipe, status))]
    sedang = bool(wilayah and tipe and tipe in mapper.JENIS_TOKO and mapper.background_running(" ".join(wilayah.split()), tipe))
    wilayah_list = [w for (w,) in db.execute(select(Prospect.wilayah).where(Prospect.sumber == "osm").distinct())]
    return {"items": items, "wilayah": wilayah_list, "jenis_toko": list(mapper.JENIS_TOKO), "pindaian_latar": sedang,
            "gudang": {"nama": settings.gudang_nama, "lat": settings.gudang_lat, "lng": settings.gudang_lng}}


class ProspectPatch(BaseModel):
    status: str


@router.patch("/prospects/{prospect_id}")
def prospects_patch(prospect_id: int, body: ProspectPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        p = mapper.update_status(db, prospect_id, body.status, f"staf:{user.nama}")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
    return ser.prospect(p)


@router.get("/prospects/export.csv")
def prospects_export(wilayah: str | None = None, tipe: str | None = None, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    data = mapper.to_csv(list(db.scalars(_prospect_query(wilayah, tipe, None))))
    return Response(content="﻿" + data, media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="prospek-{(wilayah or "semua").replace(" ", "-")}.csv"'})


# ------------------------------------------------------------------ Repeat order reminder


class ReminderIn(BaseModel):
    contact_ids: list[int] | None = None


@router.post("/reminders/repeat-order")
def reminders(body: ReminderIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(Contact).where(Contact.opt_in.is_(True))
    if body.contact_ids:
        stmt = stmt.where(Contact.id.in_(body.contact_ids))
    sent, skipped = [], []
    for c in db.scalars(stmt):
        lo = last_order(db, c.id)
        if lo is None:
            skipped.append({"contact_id": c.id, "alasan": "Belum ada pesanan sebelumnya"})
            continue
        ringkas = ", ".join(f"{it['nama']} {it['qty']} {it['satuan']}" for it in lo.item)
        text = (f"Halo {c.nama_toko or 'Kak'}, pengingat dari CV Arba'in 🙏 Pesanan terakhir: {ringkas}. "
                "Balas *pesan ulang* bila ingin kami siapkan draf pesanan yang sama.")
        check = claimguard.check(db, text, use_llm=False)
        if check.verdict != claimguard.ALLOWED:
            skipped.append({"contact_id": c.id, "alasan": f"ClaimGuard {check.label}"})
            continue
        conv = db.scalar(select(Conversation).where(Conversation.contact_id == c.id).order_by(Conversation.id.desc()))
        if conv is None:
            conv = Conversation(contact_id=c.id, kanal="whatsapp", status="otomatis", konteks={})
            db.add(conv)
            db.flush()
        trace = ledger.new_trace_id()
        tpl = (settings.wa_reminder_template, [c.nama_toko or "Kak", ringkas]) if settings.wa_reminder_template else None
        m = sender.send(db, conv, text, check=check, pengirim="ai", trace_id=trace, aktor=f"staf:{user.nama}",
                        sources=[{"jenis": "order_draft", "order_draft_id": lo.id, "judul": f"Pesanan terakhir #{lo.id}"}],
                        template=tpl)
        ledger.record(db, "pengingat_repeat_order", trace_id=trace, conversation_id=conv.id, objek_ref=f"contact:{c.id}",
                      ringkasan=f"Pengingat ke {c.nama_toko}", aktor=f"staf:{user.nama}", outcome=m.status_kirim,
                      verdict=check.verdict, alasan="Kontak opt-in dengan riwayat pesanan")
        sent.append({"contact_id": c.id, "nama_toko": c.nama_toko, "status": m.status_kirim})
    db.commit()
    return {"terkirim": sent, "dilewati": skipped}


@router.get("/ledger-types")
def ledger_types():
    return ledger.EVENT_TYPES
