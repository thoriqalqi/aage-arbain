"""Adapter WATI v3 — semua panggilan HTTP dipalsukan; tidak ada pesan sungguhan yang terkirim."""

import httpx
import pytest

from aage.channels import wati
from aage.config import get_settings

settings = get_settings()

PESAN = {"eventType": "message", "id": "69282478274a880fe782b2d9", "waId": "6281234567890", "text": "halo, harga madu?",
         "type": "text", "owner": False, "timestamp": "1764238453", "senderName": "Toko Sehat"}


@pytest.fixture
def wati_on(monkeypatch):
    monkeypatch.setattr(settings, "wati_api_key", "kunci-rahasia-uji")
    monkeypatch.setattr(settings, "wati_allowlist", "")
    monkeypatch.setattr(settings, "wati_channel_number", "")
    monkeypatch.setattr(wati.time, "sleep", lambda s: None)
    return settings


class FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, json, headers, timeout):
        self.calls.append({"url": url, "json": json, "headers": headers})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _resp(status, body=None, headers=None):
    return httpx.Response(status, json=body if body is not None else {}, headers=headers,
                          request=httpx.Request("POST", "https://x"))


def test_parse_message_customer_text():
    assert wati.parse_message(PESAN) == {"from": "6281234567890", "id": "wati:69282478274a880fe782b2d9",
                                         "text": "halo, harga madu?", "name": "Toko Sehat"}


@pytest.mark.parametrize("override", [{"owner": True}, {"eventType": "newContactMessageReceived"}, {"waId": None},
                                      {"text": "", "type": "text"}])
def test_parse_message_ignores_irrelevant(override):
    assert wati.parse_message({**PESAN, **override}) is None


def test_parse_message_media_is_marked_unsupported():
    assert wati.parse_message({**PESAN, "type": "image", "text": None})["text"] == "[image tidak didukung]"


def test_send_text_uses_v3_endpoint_and_bearer(wati_on, monkeypatch):
    fake = FakeHttp([_resp(200, {"message": {"id": "abc"}})])
    monkeypatch.setattr(wati.httpx, "post", fake)
    assert wati.send_text("+62 812-3456-7890", "Halo") == (True, "wati:abc", None)
    call = fake.calls[0]
    assert call["url"] == "https://live-mt-server.wati.io/api/ext/v3/conversations/messages/text"
    assert call["json"] == {"target": "6281234567890", "text": "Halo"}
    assert call["headers"]["Authorization"] == "Bearer kunci-rahasia-uji"


def test_send_text_channel_target(wati_on, monkeypatch):
    monkeypatch.setattr(settings, "wati_channel_number", "628111")
    fake = FakeHttp([_resp(200, {"message": {"id": "abc"}})])
    monkeypatch.setattr(wati.httpx, "post", fake)
    wati.send_text("6281234567890", "Halo")
    assert fake.calls[0]["json"]["target"] == "628111:6281234567890"


def test_send_text_retries_on_429(wati_on, monkeypatch):
    fake = FakeHttp([_resp(429, headers={"Retry-After": "1"}), _resp(429), _resp(200, {"message": {"id": "ok"}})])
    monkeypatch.setattr(wati.httpx, "post", fake)
    assert wati.send_text("6281", "Halo")[0] is True
    assert len(fake.calls) == 3


def test_send_text_gives_up_after_repeated_429(wati_on, monkeypatch):
    fake = FakeHttp([_resp(429)] * wati.MAX_ATTEMPTS)
    monkeypatch.setattr(wati.httpx, "post", fake)
    ok, _, err = wati.send_text("6281", "Halo")
    assert not ok and "429" in err and len(fake.calls) == wati.MAX_ATTEMPTS


def test_send_text_error_never_contains_key(wati_on, monkeypatch, caplog):
    fake = FakeHttp([_resp(401, {"message": "Unauthorized"})])
    monkeypatch.setattr(wati.httpx, "post", fake)
    ok, _, err = wati.send_text("6281", "Halo")
    assert not ok and "401" in err
    assert "kunci-rahasia-uji" not in err and "kunci-rahasia-uji" not in caplog.text


def test_allowlist_blocks_real_customers(wati_on, monkeypatch):
    monkeypatch.setattr(settings, "wati_allowlist", "6281111, 6282222")
    fake = FakeHttp([_resp(200, {"message": {"id": "abc"}})])
    monkeypatch.setattr(wati.httpx, "post", fake)
    ok, _, err = wati.send_text("6289999", "Halo")
    assert not ok and err.startswith(wati.SIMULASI_PREFIX) and fake.calls == []
    assert wati.send_text("+62 811 11", "Halo")[0] is True


def test_not_configured():
    assert wati.send_text("6281", "Halo") == (False, None, "WhatsApp belum dikonfigurasi")


def test_webhook_requires_token(client):
    assert client.post("/api/webhook/wati", json=PESAN).status_code == 401
    assert client.post("/api/webhook/wati?token=salah", json=PESAN).status_code == 401


def test_webhook_processes_customer_message_once(client, db, monkeypatch):
    from sqlalchemy import select

    from aage.models import Message

    payload = {**PESAN, "id": "uji-webhook-1", "waId": "6287700000001"}
    r = client.post("/api/webhook/wati?token=token-uji", json=payload)
    assert r.status_code == 200 and r.json()["diterima"] == 1
    client.post("/api/webhook/wati?token=token-uji", json=payload)  # WATI mengirim ulang
    rows = db.scalars(select(Message).where(Message.external_message_id == "wati:uji-webhook-1")).all()
    assert len(rows) == 1 and rows[0].arah == "masuk"


def test_webhook_acknowledges_irrelevant_events(client):
    r = client.post("/api/webhook/wati?token=token-uji", json={**PESAN, "owner": True})
    assert r.status_code == 200 and r.json()["diterima"] == 0


def test_sender_routes_whatsapp_through_wati(db, wati_on, monkeypatch):
    from aage.agents.graph import handle_inbound

    sent = []
    monkeypatch.setattr(wati, "send_text", lambda to, text: sent.append((to, text)) or (True, "wati:x", None))
    r = handle_inbound(db, external_user_id="6287700000002", text="ada produk untuk stamina?", channel="whatsapp")
    assert r.decision == "kirim"
    assert sent and sent[0][0] == "6287700000002"
    assert r.replies[0].status_kirim == "terkirim" and r.replies[0].external_message_id == "wati:x"
    db.rollback()
