"""Satu-satunya jalur pesan keluar ke pembeli. Wajib membawa hasil ClaimGuard berstatus Diizinkan."""

from sqlalchemy.orm import Session

from .. import clock, ledger
from ..claimguard import ALLOWED, CheckResult
from ..models import Conversation, Message
from ..config import get_settings
from . import wati, whatsapp

settings = get_settings()


class ClaimGuardRequired(RuntimeError):
    pass


def send(
    db: Session,
    conv: Conversation,
    text: str,
    *,
    check: CheckResult,
    pengirim: str,
    trace_id: str | None,
    sources: list[dict] | None = None,
    biaya_rp: float = 0.0,
    aktor: str = "AI",
    approval_id: int | None = None,
    inbound_at=None,
    template: tuple[str, list[str]] | None = None,
) -> Message:
    if check is None or check.verdict != ALLOWED:
        raise ClaimGuardRequired("Teks belum lolos ClaimGuard (harus Diizinkan) — tidak dikirim.")

    msg = Message(conversation_id=conv.id, arah="keluar", pengirim=pengirim, teks=text, status_kirim="antre",
                  verdict=check.verdict, sumber=sources or [], biaya_rp=biaya_rp, trace_id=trace_id)
    db.add(msg)
    db.flush()

    if conv.kanal == "whatsapp":
        channel = wati if settings.wa_channel == "wati" else whatsapp
        if template:
            ok, wa_id, err = channel.send_template(conv.contact.wa_number, template[0], template[1])
        else:
            ok, wa_id, err = channel.send_text(conv.contact.wa_number, text)
        simulated = err == "WhatsApp belum dikonfigurasi" or (err or "").startswith(wati.SIMULASI_PREFIX)
        msg.status_kirim = "terkirim" if ok else ("simulasi" if simulated else "gagal")
        msg.wa_message_id = wa_id
    else:
        msg.status_kirim = "terkirim"
        err = None

    now = clock.now()
    latency = int((now - clock.aware(inbound_at)).total_seconds() * 1000) if inbound_at else None
    conv.diperbarui_pada = now
    ledger.record(
        db, "pesan_keluar", trace_id=trace_id, conversation_id=conv.id, objek_ref=f"message:{msg.id}",
        sumber_ref=sources or [], ringkasan=text[:280], verdict=check.verdict,
        aturan_terpicu=check.rules_triggered, aktor=aktor, outcome=msg.status_kirim, latensi_ms=latency,
        alasan=(f"Disetujui lewat approval #{approval_id}" if approval_id else "Dikirim otomatis: lolos ClaimGuard & kebijakan")
        + (f" · Error kanal: {err}" if err and msg.status_kirim == "gagal" else ""),
        data={"kanal": conv.kanal, "approval_id": approval_id},
    )
    return msg
