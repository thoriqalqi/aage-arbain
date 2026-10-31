"""Growth Orchestrator: graf LangGraph terkendali untuk pesan pembeli.

    router → retriever → drafter → claimguard → policy ─┬─ kirim     (otomatis)
                                                       ├─ eskalasi  (antrean approval + pesan tunggu)
                                                       └─ tahan     (ClaimGuard: review/diblokir)

Setiap node menulis event ke Ledger dengan trace_id yang sama, sehingga satu pesan keluar
bisa ditelusuri sampai dokumen sumbernya."""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import claimguard, clock, inbox, ledger, llm, settings_store
from ..channels import sender
from ..kb.retriever import Hit, find_products, retrieve
from ..models import Approval, Contact, Conversation, Message, Product
from . import drafter, normalisasi, penjaga
from .router import INTENTS, RouteResult, jelas_jualan, route
from .sales import parse_order_lines

NO_RETRIEVAL = {"salam", "medis_personal", "minta_staf", "perlu_staf", "minta_dokumen", "identitas", "luar_topik",
                "media", "manipulasi", "perusahaan", "pembanding", "ambigu", "darurat", "sensitif", "marah", "tuduhan",
                "sara", "daftar_produk", "gratis", "basa_basi"}


class State(TypedDict, total=False):
    conv: Conversation
    contact: Contact
    text: str  # teks yang dipahami (dirapikan); teks asli ada di Message
    bahasa: str
    trace_id: str
    inbound_at: datetime
    inbound_check: claimguard.CheckResult
    intent: str
    slots: dict
    hits: list[Hit]
    draft: drafter.Draft
    check: claimguard.CheckResult
    staff_check: claimguard.CheckResult | None
    decision: str
    hold_reason: str | None  # ditahan oleh mode otonomi/jeda (bukan oleh ClaimGuard)
    sent: list[Message]
    approval_id: int | None


def _db(config) -> Session:
    return config["configurable"]["db"]


def _merge_konteks(conv: Conversation, updates: dict) -> None:
    if updates:
        conv.konteks = {**(conv.konteks or {}), **updates}


# ------------------------------------------------------------------ nodes


# Intent dari aturan yang boleh dinilai ulang penjaga topik. Aturan keras (klaim, medis, keluhan, manipulasi, minta
# staf, dll.) tidak pernah masuk sini. "tanya_produk" hanya bila tertangkap kata umum ("ada", "rekomendasi").
GERBANG = {"lainnya", "tanya_produk"}
_INGGRIS = re.compile(r"\b(how much|price|do you|is there|have you|available|please|thanks|thank you|what is|"
                      r"can i|i want|i need)\b", re.IGNORECASE)
CATATAN_BAHASA = "(Sorry, I can only reply in Indonesian for now.)"


def _rute(db: Session, text: str, inbound: claimguard.CheckResult, konteks: dict):
    mentions = bool(find_products(db, text))
    r = route(text, inbound_verdict=inbound.verdict, inbound_rules=inbound.rules_triggered, konteks=konteks,
              mentions_product=mentions, multi_item=len(parse_order_lines(db, text)) >= 2)
    return r, mentions


def _penjaga_topik(db: Session, text: str, r: RouteResult, inbound: claimguard.CheckResult,
                   konteks: dict) -> tuple[RouteResult, str]:
    """LLM menilai pesan yang tidak jelas-jelas soal jualan. Gagal/mati → hasil aturan dipakai apa adanya."""
    put = penjaga.periksa(text)
    if put is None:
        return r, text
    alasan = f"LLM: penjaga topik → {put.kategori}"
    # Semua belokan ini menuju jalur aman (tolak sopan, jujur, empati, atau staf) — tidak ada yang melonggarkan.
    if put.kategori in ("luar_topik", "identitas", "perusahaan", "marah", "sensitif", "darurat"):
        return RouteResult(put.kategori, alasan, r.slots, put.llm_result.model, put.llm_result), text
    if put.kategori == "jualan" and r.intent == "lainnya":
        teks = put.teks_rapi or text
        r2, _ = _rute(db, teks, inbound, konteks) if teks != text else (r, None)
        if r2.intent == "lainnya" and put.intent:
            r2 = RouteResult(put.intent, alasan + f" ({put.intent})", r2.slots)
        return RouteResult(r2.intent, f"{alasan}; {r2.reason}", r2.slots, put.llm_result.model, put.llm_result), teks
    # "tidak_jelas", atau "jualan" untuk pesan yang sudah dirutekan aturan → aturan tetap dipakai.
    return RouteResult(r.intent, f"{r.reason} ({alasan})", r.slots, put.llm_result.model, put.llm_result), text


def router_node(state: State, config) -> dict:
    db = _db(config)
    conv, asli, trace = state["conv"], state["text"], state["trace_id"]
    text = normalisasi.rapikan(asli)  # "brp hrg" → "berapa harga"; teks asli tetap tersimpan di pesan & Ledger
    inbound = claimguard.check(db, text, use_llm=False)
    if inbound.verdict != claimguard.ALLOWED:
        ledger.record(
            db, "claimguard_inbound", trace_id=trace, conversation_id=conv.id, objek_ref=f"conversation:{conv.id}",
            ringkasan=f"Klaim yang diminta pembeli: {inbound.label}", verdict=inbound.verdict,
            aturan_terpicu=inbound.rules_triggered, alasan=" | ".join(inbound.reasons[:4]),
            model=inbound.model, latensi_ms=inbound.duration_ms,
            data={"sentences": inbound.to_dict()["sentences"], "safe_text": inbound.safe_text},
        )
    konteks = conv.konteks or {}
    r, mentions = _rute(db, text, inbound, konteks)
    if r.intent in GERBANG and not jelas_jualan(text, mentions_product=mentions, konteks=konteks):
        r, text = _penjaga_topik(db, text, r, inbound, konteks)
    ledger.record_llm(db, "intent", r.llm_result, trace_id=trace, conversation_id=conv.id,
                      objek_ref=f"conversation:{conv.id}", ringkasan=f"Intent: {INTENTS.get(r.intent, r.intent)}",
                      alasan=r.reason, data={"intent": r.intent, "slots": r.slots,
                                             **({"teks_dipahami": text} if text != asli else {})})
    conv.intent_terakhir = r.intent
    return {"inbound_check": inbound, "intent": r.intent, "slots": r.slots, "text": text,
            "bahasa": "en" if _INGGRIS.search(asli) else "id"}


def retriever_node(state: State, config) -> dict:
    db = _db(config)
    if state["intent"] in NO_RETRIEVAL:
        return {"hits": []}
    conv = state["conv"]
    hits = retrieve(db, state["text"], k=4)
    ledger.record(db, "retrieval", trace_id=state["trace_id"], conversation_id=conv.id,
                  objek_ref=f"conversation:{conv.id}", sumber_ref=[h.source() for h in hits],
                  ringkasan=f"{len(hits)} potongan sumber ditemukan",
                  alasan="Retrieval hibrida (embedding + kata kunci) atas chunks aktif", model=llm.OFFLINE_MODEL)
    return {"hits": hits}


def _run_handler(db: Session, state: State) -> drafter.Draft:
    handler = drafter.HANDLERS.get(state["intent"], drafter.draft_dokumen)
    return handler(db=db, text=state["text"], conv=state["conv"], contact=state["contact"],
                   slots=state.get("slots", {}), hits=state.get("hits", []))


def drafter_node(state: State, config) -> dict:
    db = _db(config)
    conv = state["conv"]
    d = _run_handler(db, state)
    if state.get("bahasa") == "en" and d.text:
        d.text = f"{d.text}\n\n{CATATAN_BAHASA}"  # sebelum ClaimGuard, jadi tetap ikut diperiksa
    # Tawaran "balas ya untuk staf" hanya berlaku untuk pesan berikutnya, bukan "ya" kapan pun sesudahnya.
    _merge_konteks(conv, {"tawar_staf": False, **d.konteks})
    ledger.record_llm(
        db, "draf_jawaban", d.llm_result, trace_id=state["trace_id"], conversation_id=conv.id,
        product_id=(d.product_ids or [None])[0], objek_ref=f"conversation:{conv.id}", sumber_ref=d.sources,
        ringkasan=(d.text or "(tidak ada jawaban otomatis)")[:280],
        alasan=f"Template '{d.template}'" + (f"; eskalasi: {d.escalate_reason}" if d.escalate else ""),
        data={"template": d.template, "staff_draft": d.staff_draft, "escalate": d.escalate},
    )
    if d.order_draft_id:
        ledger.record(db, "draf_pesanan", trace_id=state["trace_id"], conversation_id=conv.id,
                      objek_ref=f"order_draft:{d.order_draft_id}", sumber_ref=d.sources,
                      ringkasan=f"Draf pesanan #{d.order_draft_id} menunggu konfirmasi staf", aktor="AI",
                      outcome="menunggu konfirmasi staf", model=llm.OFFLINE_MODEL)
    return {"draft": d}


def claimguard_node(state: State, config) -> dict:
    db = _db(config)
    conv, d = state["conv"], state["draft"]
    check = claimguard.check(db, d.text, product_ids=d.product_ids or None) if d.text else None
    if check is not None and check.verdict != claimguard.ALLOWED and d.template == "llm":
        # Draf LLM tidak lolos → susun ulang dengan template deterministik bersumber.
        with llm.disabled():
            d = _run_handler(db, state)
        check = claimguard.check(db, d.text, product_ids=d.product_ids or None) if d.text else None
    staff_check = claimguard.check(db, d.staff_draft, product_ids=d.product_ids or None) if d.staff_draft else None
    if check is not None:
        ledger.record(
            db, "claimguard", trace_id=state["trace_id"], conversation_id=conv.id,
            product_id=(d.product_ids or [None])[0], objek_ref=f"conversation:{conv.id}",
            ringkasan=f"ClaimGuard: {check.label} ({check.summary})", verdict=check.verdict,
            aturan_terpicu=check.rules_triggered, alasan=" | ".join(check.reasons[:5]), model=check.model,
            token_in=check.token_in, token_out=check.token_out, biaya_rp=check.biaya_rp, latensi_ms=check.duration_ms,
            data={"sentences": check.to_dict()["sentences"], "safe_text": check.safe_text},
        )
    return {"draft": d, "check": check, "staff_check": staff_check}


def _apply_autonomy(db: Session, reason: str) -> tuple[str, str]:
    """Mode otonomi Sales Assistant (diatur di dashboard) hanya bisa MENAHAN kiriman, tidak pernah melonggarkan."""
    if settings_store.jeda(db)["sales"]:
        return "tahan", "Sales Assistant dijeda staf — draf menunggu staf."
    mode, why = settings_store.effective_mode(db, "sales")
    if mode == "saran":
        return "tahan", "Mode Saran saja: draf AI hanya usulan, staf yang mengirim."
    if mode == "setujui":
        return "tahan", why or "Mode Setujui dulu: staf menyetujui sebelum terkirim."
    return "kirim", reason


def policy_node(state: State, config) -> dict:
    db = _db(config)
    d, check = state["draft"], state.get("check")
    if inbox.staff_active(state["conv"]):
        conv = state["conv"]
        reason = f"Percakapan sedang ditangani {conv.ditangani_oleh or 'staf'} — AI hanya menyiapkan saran."
        ledger.record(db, "kebijakan", trace_id=state["trace_id"], conversation_id=conv.id,
                      objek_ref=f"conversation:{conv.id}", ringkasan="Keputusan: staf", alasan=reason, outcome="staf",
                      verdict=check.verdict if check else None, model=llm.OFFLINE_MODEL)
        return {"decision": "staf", "hold_reason": reason}
    if d.escalate:
        decision, reason = "eskalasi", d.escalate_reason
    elif check is None:
        decision, reason = "eskalasi", "Tidak ada jawaban bersumber."
    elif check.verdict == claimguard.BLOCKED:
        decision, reason = "tahan", "ClaimGuard memblokir draf; tidak dikirim, diteruskan ke staf."
    elif check.verdict == claimguard.REVIEW:
        decision, reason = "tahan", "ClaimGuard: perlu review staf sebelum dikirim."
    elif not d.sources:
        decision, reason = "eskalasi", "Jawaban tanpa sumber tidak dikirim otomatis."
    elif d.order_draft_id:
        decision, reason = "kirim", "Draf pesanan dibuat — ringkasan dikirim otomatis, konfirmasi oleh staf."
    else:
        decision, reason = "kirim", "Lolos ClaimGuard, bersumber, dan dalam wewenang otomatis."
    hold_reason = None
    if decision == "kirim":
        decision, reason = _apply_autonomy(db, reason)
        hold_reason = reason if decision == "tahan" else None
    ledger.record(db, "kebijakan", trace_id=state["trace_id"], conversation_id=state["conv"].id,
                  objek_ref=f"conversation:{state['conv'].id}", ringkasan=f"Keputusan: {decision}", alasan=reason,
                  outcome=decision, verdict=check.verdict if check else None, model=llm.OFFLINE_MODEL)
    return {"decision": decision, "hold_reason": hold_reason}


def _summary(db: Session, conv: Conversation, intent: str, d: drafter.Draft) -> str:
    recent = db.scalars(select(Message).where(Message.conversation_id == conv.id).order_by(Message.id.desc()).limit(4))
    lines = [f"{'Pembeli' if m.arah == 'masuk' else 'AAGE'}: {' '.join(m.teks.split())[:140]}" for m in reversed(list(recent))]
    names = [p.nama for pid in d.product_ids if (p := db.get(Product, pid))]
    head = f"Intent {INTENTS.get(intent, intent)}" + (f" · produk: {', '.join(names)}" if names else "")
    return head + "\n" + "\n".join(lines)


def _order_approval(db: Session, state: State) -> int:
    conv, d, sc = state["conv"], state["draft"], state.get("staff_check")
    ap = Approval(objek_tipe="order_draft", objek_id=d.order_draft_id, conversation_id=conv.id,
                  alasan="Draf pesanan harus dikonfirmasi staf (stok & tagihan).",
                  ringkasan=_summary(db, conv, state["intent"], d), intent=state["intent"],
                  draf=d.staff_draft or "", verdict=sc.verdict if sc else None, trace_id=state["trace_id"])
    db.add(ap)
    db.flush()
    ledger.record(db, "approval_dibuat", trace_id=state["trace_id"], conversation_id=conv.id,
                  objek_ref=f"approval:{ap.id}", ringkasan="Konfirmasi draf pesanan oleh staf",
                  alasan=ap.alasan, verdict=ap.verdict, outcome="menunggu", model=llm.OFFLINE_MODEL)
    return ap.id


def send_node(state: State, config) -> dict:
    db = _db(config)
    conv, d, check = state["conv"], state["draft"], state["check"]
    msg = sender.send(db, conv, d.text, check=check, pengirim="ai", trace_id=state["trace_id"], sources=d.sources,
                      biaya_rp=(d.llm_result.biaya_rp if d.llm_result else 0) + check.biaya_rp,
                      inbound_at=state["inbound_at"])
    approval_id = _order_approval(db, state) if d.order_draft_id else None
    conv.status = "otomatis"
    return {"sent": [msg], "approval_id": approval_id}


def staff_node(state: State, config) -> dict:
    """Staf sedang memegang percakapan: tidak ada pesan keluar. Draf AI (hanya yang lolos ClaimGuard) disimpan
    sebagai saran yang bisa dipakai staf dengan satu klik."""
    db = _db(config)
    conv, d, check = state["conv"], state["draft"], state.get("check")
    if check is not None and check.verdict == claimguard.ALLOWED and not d.escalate:
        saran, verdict = d.text, check.verdict
    else:
        sc = state.get("staff_check")
        saran = d.staff_draft if sc is not None and sc.verdict == claimguard.ALLOWED else None
        verdict = sc.verdict if saran else None
    _merge_konteks(conv, {"saran_ai": {"teks": saran, "verdict": verdict, "intent": state["intent"],
                                       "trace_id": state["trace_id"], "catatan": d.escalate_reason or None,
                                       "waktu": clock.now().isoformat()}})
    ledger.record(db, "saran_ai", trace_id=state["trace_id"], conversation_id=conv.id, objek_ref=f"conversation:{conv.id}",
                  ringkasan=(saran or "(tidak ada saran yang lolos ClaimGuard)")[:280], verdict=verdict,
                  alasan=state.get("hold_reason"), sumber_ref=d.sources, model=llm.OFFLINE_MODEL)
    approval_id = _order_approval(db, state) if d.order_draft_id else None
    return {"sent": [], "approval_id": approval_id}


def escalate_node(state: State, config) -> dict:
    db = _db(config)
    conv, d, check = state["conv"], state["draft"], state.get("check")
    decision = state["decision"]
    staff_check = state.get("staff_check")
    if state.get("hold_reason"):
        # Draf sudah lolos ClaimGuard; hanya mode otonomi yang menahannya → staf tinggal menyetujui.
        staff_text, verdict, reason = d.text, check.verdict, state["hold_reason"]
    elif decision == "tahan" and check is not None:
        staff_text, verdict = check.safe_text, None
        reason = f"ClaimGuard {check.label}: " + "; ".join(sorted(check.rules_triggered) or ["klaim tidak cocok daftar disetujui"])
    else:
        staff_text = d.staff_draft or ""
        verdict = staff_check.verdict if staff_check else None
        reason = d.escalate_reason or "Perlu ditangani staf."
    if staff_text and verdict is None:
        verdict = claimguard.check(db, staff_text, product_ids=d.product_ids or None).verdict

    ap = Approval(objek_tipe="balasan", conversation_id=conv.id, alasan=reason,
                  ringkasan=_summary(db, conv, state["intent"], d), intent=state["intent"], draf=staff_text,
                  verdict=verdict, trace_id=state["trace_id"])
    db.add(ap)
    db.flush()
    ledger.record(db, "approval_dibuat", trace_id=state["trace_id"], conversation_id=conv.id,
                  objek_ref=f"approval:{ap.id}", ringkasan=f"Masuk antrean approval: {reason}"[:280], alasan=reason,
                  verdict=verdict, outcome="menunggu", model=llm.OFFLINE_MODEL)

    # Pembeli diberi tahu bahwa staf akan menghubungi (pesan tunggu juga lewat ClaimGuard).
    hold_text = d.text if (decision == "eskalasi" and d.text and check and check.verdict == claimguard.ALLOWED) \
        else "Terima kasih, Kak. " + drafter.HOLD_STAF
    hold_check = check if hold_text == d.text else claimguard.check(db, hold_text, use_llm=False)
    sent = []
    if hold_check.verdict == claimguard.ALLOWED:
        sent.append(sender.send(db, conv, hold_text, check=hold_check, pengirim="ai", trace_id=state["trace_id"],
                                sources=d.sources if hold_text == d.text else [drafter._template_source("pesan tunggu")],
                                inbound_at=state["inbound_at"]))
    conv.status = "eskalasi" if decision == "eskalasi" else "ditahan"
    return {"sent": sent, "approval_id": ap.id}


def _after_policy(state: State) -> str:
    return {"kirim": "send", "staf": "staff"}.get(state["decision"], "escalate")


def build_graph():
    g = StateGraph(State)
    g.add_node("router", router_node)
    g.add_node("retriever", retriever_node)
    g.add_node("drafter", drafter_node)
    g.add_node("claimguard", claimguard_node)
    g.add_node("policy", policy_node)
    g.add_node("send", send_node)
    g.add_node("escalate", escalate_node)
    g.add_node("staff", staff_node)
    g.set_entry_point("router")
    g.add_edge("router", "retriever")
    g.add_edge("retriever", "drafter")
    g.add_edge("drafter", "claimguard")
    g.add_edge("claimguard", "policy")
    g.add_conditional_edges("policy", _after_policy, {"send": "send", "escalate": "escalate", "staff": "staff"})
    g.add_edge("send", END)
    g.add_edge("escalate", END)
    g.add_edge("staff", END)
    return g.compile()


GRAPH = build_graph()


@dataclass
class PipelineResult:
    trace_id: str
    conversation_id: int
    intent: str
    decision: str
    replies: list[Message] = field(default_factory=list)
    approval_id: int | None = None
    verdict: str | None = None
    inbound_verdict: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def get_or_create_conversation(db: Session, channel: str, external_user_id: str,
                               telepon: str | None = None) -> Conversation:
    contact = db.scalar(select(Contact).where(Contact.channel == channel, Contact.external_user_id == external_user_id))
    if contact is None:
        contact = Contact(channel=channel, external_user_id=external_user_id, wa_number=telepon, nama_toko=None, opt_in=False)
        db.add(contact)
        db.flush()
    elif telepon and not contact.wa_number:
        contact.wa_number = telepon
    conv = db.scalar(select(Conversation).where(Conversation.contact_id == contact.id).order_by(Conversation.id.desc()))
    if conv is None:
        conv = Conversation(contact_id=contact.id, kanal=channel, status="otomatis", konteks={})
        db.add(conv)
        db.flush()
    return conv


def handle_inbound(db: Session, *, channel: str, external_user_id: str, text: str,
                   external_message_id: str | None = None, nama: str | None = None,
                   telepon: str | None = None) -> PipelineResult:
    """Titik masuk netral kanal: adapter (WhatsApp, Telegram, web chat) cukup menormalisasi pesan ke parameter ini."""
    conv = get_or_create_conversation(db, channel, external_user_id, telepon)
    if nama and not conv.contact.nama_wa:
        conv.contact.nama_wa = nama[:120]
    if conv.contact.wa_number:
        from ..prospects.mapper import link_contact

        link_contact(db, conv.contact)
    inbox.expire_if_idle(db, conv)
    trace = ledger.new_trace_id()
    inbound_at = clock.now()
    msg = Message(conversation_id=conv.id, arah="masuk", pengirim="pembeli", teks=text, status_kirim="diterima",
                  external_message_id=external_message_id, trace_id=trace)
    db.add(msg)
    db.flush()
    conv.diperbarui_pada = inbound_at
    ledger.record(db, "pesan_masuk", trace_id=trace, conversation_id=conv.id, objek_ref=f"message:{msg.id}",
                  ringkasan=text[:280], aktor="pembeli", data={"kanal": channel}, model=None)

    state = GRAPH.invoke(
        {"conv": conv, "contact": conv.contact, "text": text, "trace_id": trace, "inbound_at": inbound_at},
        config={"configurable": {"db": db}},
    )
    db.commit()
    check = state.get("check")
    inbound = state.get("inbound_check")
    return PipelineResult(
        trace_id=trace, conversation_id=conv.id, intent=state["intent"], decision=state["decision"],
        replies=state.get("sent", []), approval_id=state.get("approval_id"),
        verdict=check.verdict if check else None, inbound_verdict=inbound.verdict if inbound else None,
    )
