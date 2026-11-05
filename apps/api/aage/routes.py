"""Endpoint API (prefix /api) — PRD §7."""

import hmac
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from . import agent_status, claimguard, clock, eval_api, inbox, kpi, ledger, ledger_chain, llm
from . import approvals as approval_svc
from . import serializers as ser
from .agents.drafter import _template_source
from .agents.graph import handle_inbound
from .agents.memori import teks as teks_memori
from .agents.sales import last_order, riwayat_terakhir
from .channels import registry, sender, telegram, wati, whatsapp
from .channels.base import InboundMessage
from .config import get_settings
from .content import audit as audit_svc
from .content import studio
from .db import SessionLocal, get_db
from .kb import ingest, katalog_impor
from .kb.retriever import document_by_id
from .models import (
    Approval,
    ApprovedClaim,
    Chunk,
    Contact,
    ContentDraft,
    Conversation,
    Document,
    KatalogImpor,
    LeadDuplikat,
    LeadEvidence,
    LeadSkorRiwayat,
    LedgerEvent,
    Message,
    Product,
    Prospect,
    User,
)
from .prospects import consent, dedupe, impor, konfigurasi, mapper, penilaian, tinjauan
from .security import create_token, current_user, mask_phone, require_admin, require_izin, verify_password

log = logging.getLogger("aage.api")
settings = get_settings()
router = APIRouter(prefix="/api")
router.include_router(agent_status.router)  # /api/agents/status(+stream), /api/settings
router.include_router(eval_api.router)  # /api/eval/summary, /api/eval/run


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
        "whatsapp": {"aktif": settings.wa_enabled, "penyedia": settings.wa_channel, "kanal_cadangan": "webchat"},
        "kanal": registry.status(),
        "prospek": {"sumber": "OpenStreetMap Overpass (tanpa API key)", "timeout_s": settings.overpass_timeout_s,
                    "maks_hasil": settings.prospek_max_results},
        "anggaran": {"harian_rp": settings.budget_daily_rp, "bulanan_rp": settings.budget_monthly_rp,
                     "terpakai_hari_ini_rp": round(llm.spent_rp(days=1), 2),
                     "terpakai_bulan_ini_rp": round(llm.spent_rp(month=True), 2)},
    }


# ------------------------------------------------------------------ Webhook kanal & web chat


@router.get("/webhook/whatsapp")
def wa_verify(hub_mode: str = Query(None, alias="hub.mode"), hub_token: str = Query(None, alias="hub.verify_token"),
              hub_challenge: str = Query(None, alias="hub.challenge")):
    if hub_mode == "subscribe" and hub_token == settings.wa_verify_token:
        return PlainTextResponse(hub_challenge or "")
    raise HTTPException(403, "Token verifikasi tidak cocok")


def _process_inbound(messages: list[InboundMessage]) -> None:
    with SessionLocal() as db:
        for m in messages:
            if db.scalar(select(Message.id).where(Message.external_message_id == m.external_message_id)):
                continue  # kanal bisa mengirim ulang webhook yang sama
            registry.get(m.channel).typing(m.external_user_id)
            try:
                handle_inbound(db, channel=m.channel, external_user_id=m.external_user_id, text=m.text,
                               external_message_id=m.external_message_id, nama=m.nama, telepon=m.telepon)
            except Exception:
                log.exception("Gagal memproses pesan %s", m.external_message_id)
                db.rollback()


def _wa_inbound(m: dict) -> InboundMessage:
    return InboundMessage(channel="whatsapp", external_user_id=m["from"], external_message_id=m["id"], text=m["text"],
                          nama=m.get("name"), telepon=m["from"])


@router.post("/webhook/whatsapp")
async def wa_webhook(request: Request, background: BackgroundTasks):
    raw = await request.body()
    if not whatsapp.verify_signature(raw, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(401, "Signature webhook tidak valid")
    payload = await request.json()
    msgs = [_wa_inbound(m) for m in whatsapp.parse_messages(payload)]
    if msgs:
        background.add_task(_process_inbound, msgs)
    return {"diterima": len(msgs)}


@router.post("/webhook/wati")
async def wati_webhook(request: Request, background: BackgroundTasks, token: str = Query("")):
    # WATI tidak menandatangani webhook → lindungi dengan token rahasia di URL.
    if settings.wati_webhook_token:
        if not hmac.compare_digest(token, settings.wati_webhook_token):
            raise HTTPException(401, "Token webhook WATI tidak valid")
    elif settings.env != "dev":
        raise HTTPException(403, "WATI_WEBHOOK_TOKEN wajib diisi di luar mode dev")
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(400, "Body webhook bukan JSON")
    items = payload if isinstance(payload, list) else [payload]
    msgs = [_wa_inbound(m) for m in (wati.parse_message(p) for p in items if isinstance(p, dict)) if m]
    if msgs:
        background.add_task(_process_inbound, msgs)
    # Selalu 200 untuk event yang tidak relevan, agar WATI tidak mengulang hingga 144x.
    return {"diterima": len(msgs)}


@router.post("/webhook/telegram")
async def telegram_webhook(request: Request, background: BackgroundTasks):
    # Secret dari setWebhook(secret_token=...) dikirim Telegram di header ini pada setiap update.
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if settings.telegram_webhook_secret:
        if not hmac.compare_digest(secret.encode(), settings.telegram_webhook_secret.encode()):
            raise HTTPException(401, "Secret webhook Telegram tidak valid")
    elif settings.env != "dev":
        raise HTTPException(403, "TELEGRAM_WEBHOOK_SECRET wajib diisi di luar mode dev")
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(400, "Body webhook bukan JSON")
    m = telegram.parse_update(payload) if isinstance(payload, dict) else None
    if m:
        background.add_task(_process_inbound, [m])
    # Selalu 200 untuk update yang tidak relevan, agar Telegram tidak mengulang.
    return {"diterima": int(m is not None)}


class SimulateIn(BaseModel):
    session: str = Field(..., min_length=3, max_length=32, description="ID sesi web chat (dipakai sebagai nomor)")
    text: str = Field(..., min_length=1, max_length=2000)


@router.post("/chat/simulate")
def chat_simulate(body: SimulateIn, db: Session = Depends(get_db)):
    r = handle_inbound(db, channel="webchat", external_user_id=body.session, text=body.text)
    return {"trace_id": r.trace_id, "conversation_id": r.conversation_id, "intent": r.intent, "keputusan": r.decision,
            "verdict": r.verdict, "verdict_masuk": r.inbound_verdict, "approval_id": r.approval_id,
            "balasan": [ser.message(m) for m in r.replies]}


@router.get("/chat/simulate/{session}/messages")
def chat_messages(session: str, after_id: int = 0, db: Session = Depends(get_db)):
    contact = db.scalar(select(Contact).where(Contact.channel == "webchat", Contact.external_user_id == session))
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
    pending = {cid: (n, oldest) for cid, n, oldest in db.execute(
        select(Approval.conversation_id, func.count(), func.min(Approval.dibuat_pada))
        .where(Approval.status == "menunggu").group_by(Approval.conversation_id)).all()}
    out = []
    for c in convs:
        last = db.scalar(select(Message).where(Message.conversation_id == c.id).order_by(Message.id.desc()))
        if q and q.lower() not in f"{c.contact.nama_toko or ''} {c.contact.nama_wa or ''} {last.teks if last else ''}".lower():
            continue
        n, oldest = pending.get(c.id, (0, None))
        out.append(ser.conversation(c, user, last, n, menunggu_sejak=oldest))
    counts = dict(db.execute(select(Conversation.status, func.count()).group_by(Conversation.status)).all())
    return {"items": out, "jumlah_per_status": counts}


def _get_conv(db: Session, conv_id: int) -> Conversation:
    c = db.get(Conversation, conv_id)
    if c is None:
        raise HTTPException(404, "Percakapan tidak ditemukan")
    if inbox.expire_if_idle(db, c):
        db.commit()
    return c


def _jendela(db: Session, c: Conversation) -> dict:
    """Batas balas teks bebas kanal (WhatsApp: 24 jam sejak pesan terakhir pembeli; di luar itu wajib template)."""
    window = registry.get(c.kanal).reply_window_h
    if window is None:
        return {"berlaku": False, "terbuka": True, "berakhir": None, "jam": None}
    last_in = db.scalar(select(func.max(Message.dibuat_pada)).where(Message.conversation_id == c.id, Message.arah == "masuk"))
    berakhir = clock.aware(last_in) + timedelta(hours=window) if last_in else None
    return {"berlaku": True, "terbuka": bool(berakhir and clock.now() < berakhir), "berakhir": ser.ts(berakhir),
            "jam": window}


@router.get("/conversations/{conv_id}")
def conversation_detail(conv_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _get_conv(db, conv_id)
    events = list(db.scalars(select(LedgerEvent).where(LedgerEvent.conversation_id == c.id).order_by(LedgerEvent.id)))
    lo = riwayat_terakhir(db, c.contact)
    aps = list(db.scalars(select(Approval).where(Approval.conversation_id == c.id).order_by(Approval.id.desc())))
    waiting = [a.dibuat_pada for a in aps if a.status == "menunggu"]
    prospect = db.get(Prospect, c.contact.prospect_id) if c.contact.prospect_id else None
    return {
        **ser.conversation(c, user, pending=len(waiting), menunggu_sejak=min(waiting) if waiting else None),
        "pesan": [ser.message(m) for m in c.messages],
        "ledger": [ser.ledger_event(e) for e in events],
        "biaya_total_rp": round(sum(e.biaya_rp or 0 for e in events), 2),
        "pesanan_terakhir": ser.order(lo) if lo else None,
        "approvals": [ser.approval(a, c, user) for a in aps],
        "konteks": c.konteks,
        "memori": teks_memori((c.konteks or {}).get("memori")),
        "saran_ai": (c.konteks or {}).get("saran_ai") if c.status == inbox.DITANGANI_STAF else None,
        "jendela": _jendela(db, c),
        "prospek": {"id": prospect.id, "nama": prospect.nama, "status": prospect.status, "skor": prospect.skor}
        if prospect else None,
    }


@router.post("/conversations/{conv_id}/ambil-alih")
def conversation_take_over(conv_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _get_conv(db, conv_id)
    inbox.take_over(db, c, user.nama)
    db.commit()
    return ser.conversation(c, user)


@router.post("/conversations/{conv_id}/kembalikan")
def conversation_release(conv_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _get_conv(db, conv_id)
    if c.status == inbox.DITANGANI_STAF:
        inbox.release(db, c, aktor=f"staf:{user.nama}", alasan="Staf mengembalikan percakapan ke AI")
        db.commit()
    return ser.conversation(c, user)


class ContactPatch(BaseModel):
    telepon: str | None = Field(None, max_length=40)  # tautkan kontak (mis. Telegram) ke pembeli lama lewat nomor HP
    nama_toko: str | None = Field(None, max_length=160)
    tipe_toko: str | None = Field(None, max_length=40)
    alamat: str | None = Field(None, max_length=500)


@router.patch("/contacts/{contact_id}")
def contact_patch(contact_id: int, body: ContactPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = db.get(Contact, contact_id)
    if c is None:
        raise HTTPException(404, "Kontak tidak ditemukan")
    data = body.model_dump(exclude_unset=True)
    telepon = data.pop("telepon", None)
    changes = {k: v.strip() or None for k, v in data.items() if v is not None}
    if telepon is not None:
        nomor = mapper.wa_number(telepon) if telepon.strip() else None
        if telepon.strip() and nomor is None:
            raise HTTPException(422, "Nomor HP tidak valid (contoh: 0812xxxxxxx atau 62812xxxxxxx)")
        changes["wa_number"] = nomor
    before = {k: getattr(c, k) for k in changes}
    for k, v in changes.items():
        setattr(c, k, v)
    if changes:
        ledger.record(db, "kontak_diubah", objek_ref=f"contact:{c.id}", aktor=f"staf:{user.nama}", model=None,
                      ringkasan=f"Profil {c.nama_toko or c.wa_number or c.external_user_id} diubah: {', '.join(changes)}",
                      data={"sebelum": {k: ("(disembunyikan)" if k == "wa_number" and v else v) for k, v in before.items()},
                            "sesudah": {k: ("(disembunyikan)" if k == "wa_number" and v else v) for k, v in changes.items()}})
    if changes.get("wa_number"):
        mapper.link_contact(db, c)
    db.commit()
    return ser.contact(c, user)


class ReplyIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


@router.post("/conversations/{conv_id}/reply")
def conversation_reply(conv_id: int, body: ReplyIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _get_conv(db, conv_id)
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
    # Staf yang membalas otomatis memegang percakapan, agar AI tidak menyela.
    inbox.take_over(db, c, user.nama, alasan="Staf membalas manual")
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
    rows = list(db.scalars(stmt.order_by(LedgerEvent.id.desc()).limit(limit).offset(offset)))
    hashes = ledger_chain.hashes_for(db, [e.id for e in rows])
    return {"total": total, "items": [{**ser.ledger_event(e), "hash": hashes.get(e.id)} for e in rows],
            "tipe": ledger.EVENT_TYPES}


@router.get("/ledger/verify")
def ledger_verify(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Hitung ulang rantai hash seluruh Ledger: sha256(prev_hash + payload)."""
    return ledger_chain.verify(db)


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


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _unduh(isi: bytes, nama: str, tipe: str) -> Response:
    return Response(isi, media_type=tipe, headers={"Content-Disposition": f'attachment; filename="{nama}"'})


@router.get("/katalog/template.xlsx")
def katalog_template_xlsx():
    return _unduh(katalog_impor.template_xlsx(), "template_katalog_aage.xlsx", XLSX)


@router.get("/katalog/template.csv")
def katalog_template_csv():
    return _unduh(katalog_impor.template_csv(), "template_katalog_produk.csv", "text/csv; charset=utf-8")


@router.get("/katalog/template-kebijakan.csv")
def katalog_template_kebijakan_csv():
    return _unduh(katalog_impor.template_kebijakan_csv(), "template_katalog_kebijakan.csv", "text/csv; charset=utf-8")


@router.get("/katalog/ekspor.xlsx")
def katalog_ekspor(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return _unduh(katalog_impor.ekspor_xlsx(db), "katalog_aktif_aage.xlsx", XLSX)


def _impor_json(imp) -> dict:
    return {"token": imp.token, "nama_file": imp.nama_file, "status": imp.status, "laporan": imp.laporan,
            "dibuat_pada": ser.ts(imp.dibuat_pada)}


@router.post("/katalog/impor")
async def katalog_impor_pratinjau(file: UploadFile = File(...), user: User = Depends(require_admin),
                                  db: Session = Depends(get_db)):
    """Langkah 1: validasi & pratinjau. Katalog BELUM berubah sampai pratinjau dikonfirmasi."""
    try:
        imp = katalog_impor.buat_pratinjau(db, file.filename or "katalog", await file.read(), f"staf:{user.nama}")
    except katalog_impor.FileTidakValid as exc:
        raise HTTPException(400, str(exc)) from None
    return _impor_json(imp)


class TerapkanIn(BaseModel):
    lewati_error: bool = False


@router.post("/katalog/impor/{token}/terapkan")
def katalog_impor_terapkan(token: str, body: TerapkanIn, user: User = Depends(require_admin),
                           db: Session = Depends(get_db)):
    """Langkah 2: terapkan dalam satu transaksi (gagal → katalog lama tetap utuh)."""
    try:
        return katalog_impor.terapkan(db, token, f"staf:{user.nama}", lewati_error=body.lewati_error)
    except katalog_impor.ImporDitolak as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/katalog/impor/{token}/batal")
def katalog_impor_batal(token: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    imp = db.scalar(select(KatalogImpor).where(KatalogImpor.token == token))
    if imp is None:
        raise HTTPException(404, "Pratinjau tidak ditemukan")
    if imp.status == "pratinjau":
        imp.status = "dibatalkan"
        db.commit()
    return _impor_json(imp)


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
    tipe: str = Field("artikel", pattern="^(artikel|deskripsi|caption_ig|broadcast_wa|marketplace|brosur)$")


@router.post("/content/generate")
def content_generate(body: GenerateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        d = studio.generate(db, product_id=body.product_id, topik=body.topik, target=body.target, tipe=body.tipe,
                            aktor=f"staf:{user.nama}")
    except studio.ContentError as exc:
        raise HTTPException(400, str(exc)) from None
    return ser.content(d)


@router.get("/content")
def content_list(arsip: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(ContentDraft).order_by(ContentDraft.id.desc())
    if not arsip:
        stmt = stmt.where(ContentDraft.status != "diarsipkan")
    formats = {k: {"label": v["label"], "web": v["web"]} for k, v in studio.FORMATS.items()}
    return {"items": [ser.content(d, full=False) for d in db.scalars(stmt)], "format": formats}


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
    try:
        studio.edit(db, d, body.model_dump(), f"staf:{user.nama}")
    except studio.ContentError as exc:
        raise HTTPException(409, str(exc)) from None
    return ser.content(d)


class RecheckIn(BaseModel):
    teks: str = Field(..., max_length=20000)
    product_id: int | None = None


@router.post("/content/recheck")
def content_recheck_text(body: RecheckIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """ClaimGuard langsung saat staf mengetik (tanpa menyimpan). Jalur deterministik agar cepat dan gratis."""
    check = claimguard.check(db, body.teks, product_ids=[body.product_id] if body.product_id else None, use_llm=False)
    return check.to_dict()


@router.post("/content/{content_id}/submit")
def content_submit(content_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = db.get(ContentDraft, content_id)
    if d is None:
        raise HTTPException(404, "Konten tidak ditemukan")
    try:
        ap = studio.submit(db, d, f"staf:{user.nama}")
    except studio.ContentError as exc:
        raise HTTPException(422, str(exc)) from None
    return {**ser.content(d), "approval_id": ap.id}


@router.post("/content/{content_id}/arsip")
def content_archive(content_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = db.get(ContentDraft, content_id)
    if d is None:
        raise HTTPException(404, "Konten tidak ditemukan")
    studio.archive(db, d, f"staf:{user.nama}")
    return ser.content(d)


@router.post("/content/{content_id}/approve")
def content_approve(content_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Setujui langsung (tetap aturan dua orang). Alur utama: /submit → antrean Approval."""
    d = db.get(ContentDraft, content_id)
    if d is None:
        raise HTTPException(404, "Konten tidak ditemukan")
    ap = studio.pending_approval(db, d)
    if ap is not None:
        try:
            approval_svc.decide(db, ap.id, aksi="setujui", user=user)
        except approval_svc.ApprovalError as exc:
            raise HTTPException(422, str(exc)) from None
        return ser.content(d)
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


def _scout_response(res: dict, user: User) -> dict:
    meta = {k: (ser.ts(v) if k == "terakhir_dipindai" else v) for k, v in res.items() if k != "prospects"}
    return {**meta, "gudang": {"nama": settings.gudang_nama, "lat": settings.gudang_lat, "lng": settings.gudang_lng},
            "items": [ser.prospect(p, user) for p in res["prospects"]]}


@router.post("/prospek/scout")
def prospek_scout(body: ScoutIn, user: User = Depends(require_izin("leads.ubah")), db: Session = Depends(get_db)):
    """Live Lead Scouting OSM Overpass → Opportunity Score → simpan ke database tanpa duplikat."""
    try:
        res = mapper.scout_and_store(db, wilayah=body.wilayah, jenis_toko=body.jenis_toko, aktor=f"staf:{user.nama}")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except mapper.ScoutError as exc:
        raise HTTPException(503, str(exc)) from None
    return _scout_response(res, user)


class ProspectSearchIn(BaseModel):
    wilayah: str = Field(..., min_length=2)
    tipe: str = "Apotek"


@router.post("/prospects/search")
def prospects_search(body: ProspectSearchIn, user: User = Depends(require_izin("leads.ubah")), db: Session = Depends(get_db)):
    """Alias lama — memakai mesin scouting yang sama dengan /api/prospek/scout."""
    return prospek_scout(ScoutIn(wilayah=body.wilayah, jenis_toko=body.tipe), user, db)


def _prospect_query(wilayah: str | None = None, tipe: str | None = None, status: str | None = None, *, q: str | None = None, sumber: str | None = None,
                    consent_status: str | None = None, skor_min: int | None = None, skor_maks: int | None = None):
    """Data demo dan lead yang sudah digabung tidak pernah tampil di daftar."""
    stmt = select(Prospect).where(Prospect.sumber != "sintetis", Prospect.digabung_ke_id.is_(None)).order_by(Prospect.skor.desc(), Prospect.id)
    if wilayah:
        stmt = stmt.where(func.lower(Prospect.wilayah) == wilayah.lower())
    if tipe:
        stmt = stmt.where(func.lower(Prospect.tipe) == tipe.lower())
    if status:
        stmt = stmt.where(Prospect.status == status)
    if q and q.strip():
        pola = "%" + q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        stmt = stmt.where(or_(func.lower(Prospect.nama).like(pola, escape="\\"), func.lower(Prospect.alamat).like(pola, escape="\\")))
    if sumber:
        stmt = stmt.where(Prospect.sumber == sumber)
    if consent_status:
        stmt = stmt.where(Prospect.consent_status == consent_status)
    if skor_min is not None:
        stmt = stmt.where(Prospect.skor >= skor_min)
    if skor_maks is not None:
        stmt = stmt.where(Prospect.skor <= skor_maks)
    return stmt


def _konteks_lead(db: Session) -> dict:
    return {"ids_duplikat": dedupe.ids_menunggu(db), "ambang": konfigurasi.skor(db)["ambang_confidence"]}


def _lead_json(db: Session, p: Prospect, user: User) -> dict:
    return ser.prospect(p, user, _prospect_conversations(db).get(p.id), **_konteks_lead(db))


@router.get("/prospects")
def prospects_list(wilayah: str | None = None, tipe: str | None = None, status: str | None = None, q: str | None = None, sumber: str | None = None,
                   consent_status: str | None = None, verifikasi: str | None = None, skor_min: int | None = Query(None, ge=0, le=100),
                   skor_maks: int | None = Query(None, ge=0, le=100), limit: int = Query(500, ge=1, le=2000),
                   user: User = Depends(require_izin("leads.lihat")), db: Session = Depends(get_db)):
    prospects = list(db.scalars(_prospect_query(wilayah, tipe, None, q=q, sumber=sumber, consent_status=consent_status, skor_min=skor_min, skor_maks=skor_maks)))
    convs = _prospect_conversations(db)
    konteks = _konteks_lead(db)
    semua = [ser.prospect(p, user, convs.get(p.id), **konteks) for p in prospects if not status or p.status == status]
    if verifikasi:
        semua = [i for i in semua if i["status_verifikasi"] == verifikasi]
    sedang = bool(wilayah and tipe and tipe in mapper.JENIS_TOKO and mapper.background_running(" ".join(wilayah.split()), tipe))
    aktif = (Prospect.sumber != "sintetis", Prospect.digabung_ke_id.is_(None))
    wilayah_list = sorted(w for (w,) in db.execute(select(Prospect.wilayah).where(*aktif).distinct()))
    now = clock.now()
    jatuh_tempo = sum(1 for p in prospects if p.tindak_lanjut_pada and clock.aware(p.tindak_lanjut_pada) <= now
                      and p.status not in ("pelanggan", "menolak"))
    return {"items": semua[:limit], "total": len(semua), "wilayah": wilayah_list, "jenis_toko": list(mapper.JENIS_TOKO), "segmen": konfigurasi.segmen(db),
            "sumber_opsi": impor.LABEL_SUMBER, "pindaian_latar": sedang, "funnel": {**mapper.funnel(prospects), "tindak_lanjut_jatuh_tempo": jatuh_tempo},
            "gudang": {"nama": settings.gudang_nama, "lat": settings.gudang_lat, "lng": settings.gudang_lng}}


def _prospect_conversations(db: Session) -> dict[int, int]:
    """prospect_id → percakapan terbaru dari kontak yang tertaut ke prospek tersebut."""
    rows = db.execute(select(Contact.prospect_id, func.max(Conversation.id)).join(Conversation, Conversation.contact_id == Contact.id)
                      .where(Contact.prospect_id.is_not(None)).group_by(Contact.prospect_id)).all()
    return {pid: cid for pid, cid in rows}


class ProspectPatch(BaseModel):
    status: str | None = None
    catatan: str | None = Field(None, max_length=2000)
    tindak_lanjut_pada: datetime | None = None
    pic: str | None = Field(None, max_length=80)


@router.patch("/prospects/{prospect_id}")
def prospects_patch(prospect_id: int, body: ProspectPatch, user: User = Depends(require_izin("leads.ubah")), db: Session = Depends(get_db)):
    fields = body.model_fields_set - {"status"}
    try:
        p = mapper.update(db, prospect_id, f"staf:{user.nama}", status=body.status, catatan=body.catatan,
                          tindak_lanjut_pada=body.tindak_lanjut_pada, pic=body.pic, fields=fields)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
    return _lead_json(db, p, user)


class ConsentIn(BaseModel):
    status: str
    sumber: str | None = Field(None, max_length=200)
    cakupan: str | None = None
    pada: datetime | None = None


def _ambil_prospek(db: Session, prospect_id: int) -> Prospect:
    p = db.get(Prospect, prospect_id)
    if p is None:
        raise HTTPException(404, "Prospek tidak ditemukan")
    return p


@router.put("/prospects/{prospect_id}/consent")
def prospects_consent(prospect_id: int, body: ConsentIn, user: User = Depends(require_izin("leads.ubah")), db: Session = Depends(get_db)):
    """Catat consent atau opt-out beserta sumber, cakupan, dan waktunya. Setiap perubahan masuk Ledger."""
    p = _ambil_prospek(db, prospect_id)
    try:
        consent.set_consent(db, p, user, status=body.status, sumber=body.sumber, cakupan=body.cakupan, pada=body.pada)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from None
    return _lead_json(db, p, user)


@router.post("/prospects/{prospect_id}/kontak-promo")
def prospects_kontak_promo(prospect_id: int, user: User = Depends(require_izin("leads.kontak")), db: Session = Depends(get_db)):
    """Tautan WhatsApp berisi draf promosi, hanya bila consent sah. Tidak ada pesan yang dikirim sistem; staf yang menekan Kirim."""
    p = _ambil_prospek(db, prospect_id)
    try:
        tautan = consent.buka_kontak_promo(db, p, user)
    except consent.KontakDitolak as exc:
        raise HTTPException(409, {"kode": exc.kode, "pesan": exc.pesan}) from None
    return {"tautan": tautan, "prospek": _lead_json(db, p, user)}


@router.post("/prospects/{prospect_id}/riset")
def prospects_research(prospect_id: int, user: User = Depends(require_izin("leads.ubah")), db: Session = Depends(get_db)):
    """Live AI Search Audit (Serper/Google News) + Next Best Action untuk satu prospek."""
    from .prospects import market_service

    p = _ambil_prospek(db, prospect_id)
    return _lead_json(db, market_service.research(db, p, f"staf:{user.nama}"), user)


@router.get("/prospects/export.csv")
def prospects_export(wilayah: str | None = None, tipe: str | None = None, user: User = Depends(require_izin("leads.ekspor")),
                     db: Session = Depends(get_db)):
    prospects = list(db.scalars(_prospect_query(wilayah, tipe, None)))
    data = mapper.to_csv(prospects)
    ledger.record(db, "prospek_diekspor", aktor=f"staf:{user.nama}", model=None, outcome="diekspor",
                  ringkasan=f"{len(prospects)} prospek diekspor ke CSV", data={"jumlah": len(prospects), "wilayah": wilayah, "tipe": tipe})
    db.commit()
    return Response(content="﻿" + data, media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="prospek-{(wilayah or "semua").replace(" ", "-")}.csv"'})


class ProspectBaru(BaseModel):
    nama: str = Field(..., max_length=300)
    tipe: str = Field(..., max_length=60)
    wilayah: str = Field(..., max_length=200)
    alamat: str | None = Field(None, max_length=600)
    telepon: str | None = Field(None, max_length=60)
    website: str | None = Field(None, max_length=400)
    lat: float | None = None
    lng: float | None = None
    jam_buka: str | None = Field(None, max_length=300)
    referensi: str | None = Field(None, max_length=300)


class ProspectData(BaseModel):
    nama: str | None = Field(None, max_length=300)
    tipe: str | None = Field(None, max_length=60)
    wilayah: str | None = Field(None, max_length=200)
    alamat: str | None = Field(None, max_length=600)
    telepon: str | None = Field(None, max_length=60)
    website: str | None = Field(None, max_length=400)
    lat: float | None = None
    lng: float | None = None
    jam_buka: str | None = Field(None, max_length=300)


def _galat_validasi(salah: list[dict]) -> HTTPException:
    return HTTPException(400, {"kode": "VALIDASI", "pesan": "; ".join(f"{s['kolom']}: {s['alasan']}" for s in salah), "kesalahan": salah})


@router.post("/prospects", status_code=201)
def prospects_create(body: ProspectBaru, user: User = Depends(require_izin("leads.ubah")), db: Session = Depends(get_db)):
    """Input manual. Duplikat pasti ditolak; calon duplikat tetap dibuat dan masuk antrean tinjauan. Consent mulai dari UNKNOWN."""
    try:
        p, cocok = impor.buat_manual(db, body.model_dump(exclude={"referensi"}), reference=body.referensi, aktor=f"staf:{user.nama}")
    except impor.DataTidakValid as exc:
        raise _galat_validasi(exc.kesalahan) from None
    except impor.DuplikatPasti as exc:
        c = exc.cocok
        raise HTTPException(409, {"kode": "DUPLIKAT", "pesan": f"Lead ini sudah ada: {c['nama']}", "lead_id": c["id"], "alasan": c["alasan"]}) from None
    return {**_lead_json(db, p, user), "calon_duplikat": [{"id": c["id"], "nama": c["nama"], "alasan": c["alasan"]} for c in cocok]}


def _ambil_aktif(db: Session, prospect_id: int) -> Prospect:
    """Untuk perubahan data: baris yang sudah digabung adalah arsip. Pencatatan consent tetap terbuka agar opt-out selalu bisa masuk."""
    p = _ambil_prospek(db, prospect_id)
    if p.digabung_ke_id:
        raise HTTPException(409, {"kode": "DIGABUNG", "pesan": f"Lead ini sudah digabung ke lead {p.digabung_ke_id}. Ubah lead utamanya.", "lead_id": p.digabung_ke_id})
    return p


@router.patch("/prospects/{prospect_id}/data")
def prospects_data(prospect_id: int, body: ProspectData, user: User = Depends(require_izin("leads.ubah")), db: Session = Depends(get_db)):
    p = _ambil_aktif(db, prospect_id)
    try:
        impor.ubah_data(db, p, body.model_dump(exclude_unset=True), f"staf:{user.nama}")
    except impor.DataTidakValid as exc:
        raise _galat_validasi(exc.kesalahan) from None
    return _lead_json(db, p, user)


class VerifikasiIn(BaseModel):
    status: str
    catatan: str | None = Field(None, max_length=500)


@router.put("/prospects/{prospect_id}/verifikasi")
def prospects_verifikasi(prospect_id: int, body: VerifikasiIn, user: User = Depends(require_izin("leads.ubah")), db: Session = Depends(get_db)):
    p = _ambil_aktif(db, prospect_id)
    try:
        tinjauan.set_verifikasi(db, p, user, body.status, body.catatan)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return _lead_json(db, p, user)


def _lead_ringkas(p: Prospect, user: User) -> dict:
    return {"id": p.id, "nama": p.nama, "alamat": p.alamat, "wilayah": p.wilayah, "tipe": p.tipe, "telepon": mask_phone(p.telepon, user), "skor": p.skor,
            "sumber": p.sumber, "status": p.status, "consent_status": p.consent_status, "website": p.website}


@router.get("/prospects/tinjauan")
def prospects_tinjauan(user: User = Depends(require_izin("leads.lihat")), db: Session = Depends(get_db)):
    """Antrean: calon duplikat yang menunggu keputusan, dan lead yang datanya kurang atau confidence-nya rendah."""
    konteks = _konteks_lead(db)
    leads = {p.id: p for p in db.scalars(_prospect_query())}
    duplikat = []
    for d in db.scalars(select(LeadDuplikat).where(LeadDuplikat.keputusan == "menunggu").order_by(LeadDuplikat.tingkat.desc(), LeadDuplikat.id)):
        a, b = leads.get(d.lead_id), leads.get(d.lead_cocok_id)
        if a and b:
            duplikat.append({"id": d.id, "tingkat": d.tingkat, "alasan": d.alasan, "lead": _lead_ringkas(a, user), "cocok": _lead_ringkas(b, user), "dibuat_pada": ser.ts(d.dibuat_pada)})
    perlu = []
    for p in leads.values():
        alasan = tinjauan.alasan_tinjauan(p, konteks["ids_duplikat"], konteks["ambang"])
        if tinjauan.status_tinjauan(p, alasan) == "perlu_tinjauan":
            perlu.append({**_lead_ringkas(p, user), "alasan": alasan, "confidence": p.confidence})
    return {"duplikat": duplikat, "perlu_tinjauan": perlu[:300], "jumlah_duplikat": len(duplikat), "jumlah_perlu_tinjauan": len(perlu)}


@router.post("/prospects/dedupe/pindai")
def prospects_dedupe_pindai(user: User = Depends(require_izin("leads.ubah")), db: Session = Depends(get_db)):
    return dedupe.pindai_semua(db, f"staf:{user.nama}")


class PutusanDuplikatIn(BaseModel):
    keputusan: str
    utama_id: int | None = None


@router.post("/prospects/duplikat/{duplikat_id}/putuskan")
def prospects_duplikat_putuskan(duplikat_id: int, body: PutusanDuplikatIn, user: User = Depends(require_izin("leads.ubah")), db: Session = Depends(get_db)):
    try:
        d = dedupe.putuskan(db, duplikat_id, body.keputusan, body.utama_id, f"staf:{user.nama}")
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"id": d.id, "keputusan": d.keputusan, "utama_id": body.utama_id}


def _impor_lead_json(imp) -> dict:
    return {"token": imp.token, "nama_file": imp.nama_file, "status": imp.status, "source_type": imp.source_type, "source_reference": imp.source_reference,
            "laporan": imp.laporan, "hasil": imp.hasil, "dibuat_pada": ser.ts(imp.dibuat_pada), "diterapkan_pada": ser.ts(imp.diterapkan_pada)}


@router.get("/prospects/impor/sumber")
def prospects_impor_sumber(user: User = Depends(require_izin("leads.impor"))):
    return {"sumber": impor.SUMBER_IMPOR, "kolom": list(impor.KOLOM), "kolom_wajib": list(impor.KOLOM_WAJIB), "maks_baris": impor.MAKS_BARIS}


@router.get("/prospects/impor/template.csv")
def prospects_impor_template(user: User = Depends(require_izin("leads.impor"))):
    return Response(content=impor.template_csv(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="template_impor_leads.csv"'})


@router.post("/prospects/impor")
def prospects_impor_pratinjau(file: UploadFile = File(...), source_type: str = Form(...), source_reference: str = Form(...),
                              user: User = Depends(require_izin("leads.impor")), db: Session = Depends(get_db)):
    """Langkah 1: validasi dan pratinjau. Belum ada lead yang masuk sampai dikonfirmasi.
    Sengaja bukan async: query dan pencocokan nama berjalan di threadpool, jadi webhook tetap dilayani."""
    try:
        imp = impor.buat_pratinjau(db, file.filename or "leads", file.file.read(impor.MAKS_UKURAN + 1), source_type, source_reference, f"staf:{user.nama}")
    except impor.ImporDitolak as exc:
        raise HTTPException(400, str(exc)) from None
    return _impor_lead_json(imp)


class ImporTerapkanIn(BaseModel):
    lewati_error: bool = False


@router.post("/prospects/impor/{token}/terapkan")
def prospects_impor_terapkan(token: str, body: ImporTerapkanIn, user: User = Depends(require_izin("leads.impor")), db: Session = Depends(get_db)):
    """Langkah 2: terapkan dalam satu transaksi. Permintaan yang diulang mengembalikan hasil yang sama."""
    try:
        return _impor_lead_json(impor.terapkan(db, token, f"staf:{user.nama}", lewati_error=body.lewati_error))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
    except impor.ImporDitolak as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/prospects/impor/{token}/batal")
def prospects_impor_batal(token: str, user: User = Depends(require_izin("leads.impor")), db: Session = Depends(get_db)):
    try:
        return _impor_lead_json(impor.batal(db, token))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None


@router.get("/prospects/konfigurasi")
def prospects_konfigurasi(user: User = Depends(require_izin("leads.lihat")), db: Session = Depends(get_db)):
    return konfigurasi.snapshot(db)


class KonfigurasiIn(BaseModel):
    bobot: dict | None = None
    ambang_confidence: float | None = None
    segmen: list[str] | None = None


@router.put("/prospects/konfigurasi")
def prospects_konfigurasi_ubah(body: KonfigurasiIn, user: User = Depends(require_izin("leads.atur")), db: Session = Depends(get_db)):
    """Versi skor naik setiap bobot berubah. Skor lama tidak berubah sampai dihitung ulang."""
    try:
        return konfigurasi.ubah(db, f"staf:{user.nama}", bobot=body.bobot, ambang_confidence=body.ambang_confidence, daftar_segmen=body.segmen)
    except konfigurasi.KonfigurasiTidakValid as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/prospects/skor/hitung-ulang")
def prospects_hitung_ulang(user: User = Depends(require_izin("leads.atur")), db: Session = Depends(get_db)):
    return penilaian.hitung_ulang_semua(db, f"staf:{user.nama}")


@router.get("/prospects/{prospect_id:int}")
def prospects_detail(prospect_id: int, user: User = Depends(require_izin("leads.lihat")), db: Session = Depends(get_db)):
    """Detail lead: asal data, riwayat skor, rincian confidence, aktivitas, dan calon duplikat."""
    p = _ambil_prospek(db, prospect_id)
    bukti = db.scalars(select(LeadEvidence).where(LeadEvidence.lead_id == p.id).order_by(LeadEvidence.dikumpulkan_pada.desc()))
    riwayat = db.scalars(select(LeadSkorRiwayat).where(LeadSkorRiwayat.lead_id == p.id).order_by(LeadSkorRiwayat.id.desc()).limit(20))
    aktivitas = db.scalars(select(LedgerEvent).where(LedgerEvent.objek_ref == f"prospect:{p.id}").order_by(LedgerEvent.id.desc()).limit(50))
    duplikat = []
    for d in db.scalars(select(LeadDuplikat).where(LeadDuplikat.keputusan == "menunggu", or_(LeadDuplikat.lead_id == p.id, LeadDuplikat.lead_cocok_id == p.id))):
        lain = db.get(Prospect, d.lead_cocok_id if d.lead_id == p.id else d.lead_id)
        duplikat.append({"id": d.id, "tingkat": d.tingkat, "alasan": d.alasan, "lead": _lead_ringkas(lain, user)})
    return {**_lead_json(db, p, user), "rincian_confidence": penilaian.rincian_confidence(p),
            "bukti": [{"id": b.id, "source_type": b.source_type, "label": impor.LABEL_SUMBER.get(b.source_type, b.source_type), "source_reference": b.source_reference,
                       "dikumpulkan_pada": ser.ts(b.dikumpulkan_pada)} for b in bukti],
            "riwayat_skor": [{"skor": r.skor, "confidence": r.confidence, "skor_versi": r.skor_versi, "pemicu": r.pemicu, "dibuat_pada": ser.ts(r.dibuat_pada)} for r in riwayat],
            "aktivitas": [{"id": e.id, "tipe": e.tipe_event, "label": ledger.EVENT_TYPES.get(e.tipe_event, e.tipe_event), "ringkasan": e.ringkasan, "aktor": e.aktor, "pada": ser.ts(e.waktu)} for e in aktivitas],
            "duplikat": duplikat}


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
            conv = Conversation(contact_id=c.id, kanal=c.channel, status="otomatis", konteks={})
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
