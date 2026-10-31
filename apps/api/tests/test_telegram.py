"""Adapter Telegram + lapisan kanal netral — semua panggilan HTTP dipalsukan; tidak ada pesan sungguhan yang terkirim."""

import httpx
import pytest
from sqlalchemy import select

from aage.agents.graph import handle_inbound
from aage.channels import registry, telegram
from aage.config import get_settings
from aage.db import SessionLocal
from aage.models import Contact, Conversation, Message

settings = get_settings()
TOKEN = "123456:token-rahasia-uji"


def _update(text="halo, harga madu?", chat_id=555001, message_id=1, **extra):
    msg = {"message_id": message_id, "chat": {"id": chat_id, "type": "private"},
           "from": {"id": chat_id, "is_bot": False, "first_name": "Rina", "last_name": "Apotek"}, "date": 1764238453}
    if text is not None:
        msg["text"] = text
    msg.update(extra)
    return {"update_id": 9000 + message_id, "message": msg}


class FakeTelegram:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def __call__(self, url, json, timeout):
        method = url.rsplit("/", 1)[-1]
        self.calls.append({"url": url, "method": method, "json": json})
        if method != "sendMessage":
            return _resp(200, {"ok": True, "result": True})
        r = self.responses.pop(0) if self.responses else _resp(200, {"ok": True, "result": {"message_id": len(self.calls)}})
        if isinstance(r, Exception):
            raise r
        return r

    def sent(self):
        return [c["json"] for c in self.calls if c["method"] == "sendMessage"]


def _resp(status, body):
    return httpx.Response(status, json=body, request=httpx.Request("POST", "https://api.telegram.org/x"))


@pytest.fixture
def tg_on(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", TOKEN)
    monkeypatch.setattr(settings, "telegram_allowlist", "")
    monkeypatch.setattr(settings, "telegram_webhook_secret", "rahasia-tg")
    monkeypatch.setattr(telegram.time, "sleep", lambda s: None)
    fake = FakeTelegram()
    monkeypatch.setattr(telegram.httpx, "post", fake)
    return fake


# ------------------------------------------------------------------ parsing


def test_parse_private_text_message(tg_on):
    m = telegram.parse_update(_update())
    assert (m.channel, m.external_user_id, m.external_message_id) == ("telegram", "555001", "tg:555001:1")
    assert m.text == "halo, harga madu?" and m.nama == "Rina Apotek" and m.telepon is None


@pytest.mark.parametrize("update", [
    {"update_id": 1, "edited_message": _update()["message"]},
    _update(chat={"id": -100, "type": "group"}),
    _update(**{"from": {"id": 1, "is_bot": True, "first_name": "Bot"}}),
    _update(text=None),
    {"update_id": 2, "callback_query": {"id": "x"}},
])
def test_parse_ignores_irrelevant_updates(tg_on, update):
    assert telegram.parse_update(update) is None


def test_parse_start_command_and_media(tg_on):
    assert telegram.parse_update(_update("/start promo")).text == "Halo"
    assert telegram.parse_update(_update(text=None, photo=[{"file_id": "x"}])).text == "[photo tidak didukung]"
    assert telegram.parse_update(_update(text=None, photo=[{"file_id": "x"}], caption="ini kemasannya")).text == "ini kemasannya"


def test_allowlist_filters_inbound_and_outbound(tg_on, monkeypatch):
    monkeypatch.setattr(settings, "telegram_allowlist", "555001, 777")
    assert telegram.parse_update(_update(chat_id=555001)) is not None
    assert telegram.parse_update(_update(chat_id=999)) is None
    res = telegram.TelegramAdapter().send_text("999", "Halo")
    assert res.status == "simulasi" and tg_on.sent() == []


# ------------------------------------------------------------------ kirim


def test_send_text_plain_and_returns_id(tg_on):
    res = telegram.TelegramAdapter().send_text("555001", "Harga *madu* Rp 2.340.000")
    assert res.status == "terkirim" and res.external_message_id == "tg:555001:1"
    body = tg_on.sent()[0]
    assert body == {"chat_id": "555001", "text": "Harga *madu* Rp 2.340.000", "disable_web_page_preview": True}
    assert "parse_mode" not in body  # teks polos: tanda * dari draf tidak ditafsirkan


def test_send_retries_rate_limit_then_succeeds(tg_on):
    tg_on.responses = [_resp(429, {"ok": False, "parameters": {"retry_after": 3}}),
                       _resp(200, {"ok": True, "result": {"message_id": 42}})]
    res = telegram.TelegramAdapter().send_text("555001", "Halo")
    assert res.status == "terkirim" and res.external_message_id == "tg:555001:42" and len(tg_on.sent()) == 2


def test_send_errors_never_leak_token(tg_on):
    tg_on.responses = [_resp(403, {"ok": False, "description": "Forbidden: bot was blocked by the user"})]
    res = telegram.TelegramAdapter().send_text("555001", "Halo")
    assert res.status == "gagal" and "blocked" in res.error and TOKEN not in res.error
    tg_on.responses = [httpx.ReadTimeout(f"timeout ke https://api.telegram.org/bot{TOKEN}/sendMessage")]
    res = telegram.TelegramAdapter().send_text("555001", "Halo")
    assert res.status == "gagal" and TOKEN not in res.error


def test_not_configured_is_simulation(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    assert telegram.TelegramAdapter().send_text("555001", "Halo").status == "simulasi"
    assert registry.status()["telegram"]["aktif"] is False


# ------------------------------------------------------------------ webhook → pipeline


def test_webhook_requires_secret(client, tg_on):
    assert client.post("/api/webhook/telegram", json=_update()).status_code == 401
    assert client.post("/api/webhook/telegram", json=_update(),
                       headers={"X-Telegram-Bot-Api-Secret-Token": "salah"}).status_code == 401


def test_webhook_runs_ai_pipeline_once_and_replies(client, tg_on):
    h = {"X-Telegram-Bot-Api-Secret-Token": "rahasia-tg"}
    upd = _update("ada produk untuk stamina?", chat_id=555002, message_id=7)
    r = client.post("/api/webhook/telegram", json=upd, headers=h)
    assert r.status_code == 200 and r.json()["diterima"] == 1
    client.post("/api/webhook/telegram", json=upd, headers=h)  # Telegram mengirim ulang update yang sama
    assert client.post("/api/webhook/telegram", json={"update_id": 1, "edited_message": {}}, headers=h).json()["diterima"] == 0

    with SessionLocal() as db:
        c = db.scalar(select(Contact).where(Contact.channel == "telegram", Contact.external_user_id == "555002"))
        assert c is not None and c.wa_number is None and c.nama_wa == "Rina Apotek"
        conv = db.scalar(select(Conversation).where(Conversation.contact_id == c.id))
        msgs = list(db.scalars(select(Message).where(Message.conversation_id == conv.id).order_by(Message.id)))
    assert conv.kanal == "telegram"
    assert [m.arah for m in msgs].count("masuk") == 1
    keluar = [m for m in msgs if m.arah == "keluar"]
    assert keluar and keluar[0].status_kirim == "terkirim" and keluar[0].external_message_id.startswith("tg:555002:")
    assert tg_on.sent()[0]["chat_id"] == "555002" and "Madu Stamina" in tg_on.sent()[0]["text"]
    assert any(c["method"] == "sendChatAction" for c in tg_on.calls)


def test_staff_take_over_is_channel_neutral(client, auth, tg_on):
    with SessionLocal() as db:
        cid = handle_inbound(db, channel="telegram", external_user_id="555003", text="harga propolis tetes?").conversation_id
    n = len(tg_on.sent())
    assert client.post(f"/api/conversations/{cid}/ambil-alih", headers=auth).json()["status"] == "ditangani_staf"
    with SessionLocal() as db:
        res = handle_inbound(db, channel="telegram", external_user_id="555003", text="kalau 30 box berapa?")
    assert res.decision == "staf" and res.replies == [] and len(tg_on.sent()) == n  # AI diam

    d = client.get(f"/api/conversations/{cid}", headers=auth).json()
    assert d["kanal"] == "telegram" and d["saran_ai"]["teks"] and d["jendela"]["berlaku"] is False
    r = client.post(f"/api/conversations/{cid}/reply", headers=auth, json={"text": "Halo Kak, saya bantu hitungkan ya."})
    assert r.status_code == 200 and tg_on.sent()[-1] == {"chat_id": "555003", "text": "Halo Kak, saya bantu hitungkan ya.",
                                                         "disable_web_page_preview": True}


def test_identity_is_channel_plus_external_id(db):
    a = handle_inbound(db, channel="telegram", external_user_id="6287711112222", text="halo")
    b = handle_inbound(db, channel="whatsapp", external_user_id="6287711112222", text="halo", telepon="6287711112222")
    assert a.conversation_id != b.conversation_id
    ids = {(c.channel, c.external_user_id) for c in db.scalars(select(Contact).where(Contact.external_user_id == "6287711112222"))}
    assert ids == {("telegram", "6287711112222"), ("whatsapp", "6287711112222")}


def test_unknown_channel_rejected():
    with pytest.raises(ValueError):
        registry.get("sms")
