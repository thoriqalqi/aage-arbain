"""Growth Orchestrator: graf LangGraph terkendali untuk pesan pembeli.

    router → retriever → drafter → claimguard → policy ─┬─ kirim     (otomatis)
                                                       ├─ eskalasi  (antrean approval + pesan tunggu)
                                                       └─ tahan     (ClaimGuard: review/diblokir)

Setiap node menulis event ke Ledger dengan trace_id yang sama, sehingga satu pesan keluar
bisa ditelusuri sampai dokumen sumbernya."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import claimguard, clock, ledger, llm, settings_store
from ..channels import sender
from ..kb.retriever import Hit, retrieve
from ..models import Approval, Contact, Conversation, Message, Product
from . import drafter
from .router import INTENTS, route

NO_RETRIEVAL = {"salam", "medis_personal", "minta_staf"}


class State(TypedDict, total=False):
    conv: Conversation
    contact: Contact
    text: str
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


def router_node(state: State, config) -> dict:
    db = _db(config)
    conv, text, trace = state["conv"], state["text"], state["trace_id"]
    inbound = claimguard.check(db, text, use_llm=False)
    if inbound.verdict != claimguard.ALLOWED:
        ledger.record(
            db, "claimguard_inbound", trace_id=trace, conversation_id=conv.id, objek_ref=f"conversation:{conv.id}",
            ringkasan=f"Klaim yang diminta pembeli: {inbound.label}", verdict=inbound.verdict,
            aturan_terpicu=inbound.rules_triggered, alasan=" | ".join(inbound.reasons[:4]),
            model=inbound.model, latensi_ms=inbound.duration_ms,
            data={"sentences": inbound.to_dict()["sentences"], "safe_text": inbound.safe_text},
        )
    r = route(text, inbound_verdict=inbound.verdict, inbound_rules=inbound.rules_triggered, konteks=conv.konteks or {})
    ledger.record_llm(db, "intent", r.llm_result, trace_id=trace, conversation_id=conv.id,
                      objek_ref=f"conversation:{conv.id}", ringkasan=f"Intent: {INTENTS.get(r.intent, r.intent)}",
                      alasan=r.reason, data={"intent": r.intent, "slots": r.slots})
    conv.intent_terakhir = r.intent
    return {"inbound_check": inbound, "intent": r.intent, "slots": r.slots}


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
    _merge_konteks(conv, d.konteks)
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


def send_node(state: State, config) -> dict:
    db = _db(config)
    conv, d, check = state["conv"], state["draft"], state["check"]
    msg = sender.send(db, conv, d.text, check=check, pengirim="ai", trace_id=state["trace_id"], sources=d.sources,
                      biaya_rp=(d.llm_result.biaya_rp if d.llm_result else 0) + check.biaya_rp,
                      inbound_at=state["inbound_at"])
    approval_id = None
    if d.order_draft_id:
        sc = state.get("staff_check")
        ap = Approval(objek_tipe="order_draft", objek_id=d.order_draft_id, conversation_id=conv.id,
                      alasan="Draf pesanan harus dikonfirmasi staf (stok & tagihan).",
                      ringkasan=_summary(db, conv, state["intent"], d), intent=state["intent"],
                      draf=d.staff_draft or "", verdict=sc.verdict if sc else None, trace_id=state["trace_id"])
        db.add(ap)
        db.flush()
        approval_id = ap.id
        ledger.record(db, "approval_dibuat", trace_id=state["trace_id"], conversation_id=conv.id,
                      objek_ref=f"approval:{ap.id}", ringkasan="Konfirmasi draf pesanan oleh staf",
                      alasan=ap.alasan, verdict=ap.verdict, outcome="menunggu", model=llm.OFFLINE_MODEL)
    conv.status = "otomatis"
    return {"sent": [msg], "approval_id": approval_id}


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
    return "send" if state["decision"] == "kirim" else "escalate"


def build_graph():
    g = StateGraph(State)
    g.add_node("router", router_node)
    g.add_node("retriever", retriever_node)
    g.add_node("drafter", drafter_node)
    g.add_node("claimguard", claimguard_node)
    g.add_node("policy", policy_node)
    g.add_node("send", send_node)
    g.add_node("escalate", escalate_node)
    g.set_entry_point("router")
    g.add_edge("router", "retriever")
    g.add_edge("retriever", "drafter")
    g.add_edge("drafter", "claimguard")
    g.add_edge("claimguard", "policy")
    g.add_conditional_edges("policy", _after_policy, {"send": "send", "escalate": "escalate"})
    g.add_edge("send", END)
    g.add_edge("escalate", END)
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


def get_or_create_conversation(db: Session, wa_number: str, kanal: str) -> Conversation:
    contact = db.scalar(select(Contact).where(Contact.wa_number == wa_number))
    if contact is None:
        contact = Contact(wa_number=wa_number, nama_toko=None, opt_in=False)
        db.add(contact)
        db.flush()
    conv = db.scalar(select(Conversation).where(Conversation.contact_id == contact.id, Conversation.kanal == kanal)
                     .order_by(Conversation.id.desc()))
    if conv is None:
        conv = Conversation(contact_id=contact.id, kanal=kanal, status="otomatis", konteks={})
        db.add(conv)
        db.flush()
    return conv


def handle_inbound(db: Session, *, wa_number: str, text: str, kanal: str = "whatsapp",
                   wa_message_id: str | None = None, nama: str | None = None) -> PipelineResult:
    conv = get_or_create_conversation(db, wa_number, kanal)
    trace = ledger.new_trace_id()
    inbound_at = clock.now()
    msg = Message(conversation_id=conv.id, arah="masuk", pengirim="pembeli", teks=text, status_kirim="diterima",
                  wa_message_id=wa_message_id, trace_id=trace)
    db.add(msg)
    db.flush()
    conv.diperbarui_pada = inbound_at
    ledger.record(db, "pesan_masuk", trace_id=trace, conversation_id=conv.id, objek_ref=f"message:{msg.id}",
                  ringkasan=text[:280], aktor="pembeli", data={"kanal": kanal}, model=None)

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
