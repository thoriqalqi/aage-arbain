"""Repeat order (fase 2): riwayat nyata lintas kanal lewat nomor HP, tidak pernah mengarang riwayat, kandidat dari ciri,
tombol "Bagikan nomor HP" Telegram yang hanya menerima nomor milik pengirim, dan staf menautkan nomor manual."""

import httpx
from sqlalchemy import select

from aage.agents import sales
from aage.agents.graph import handle_inbound
from aage.channels import telegram
from aage.channels.base import TEKS_NOMOR_DIBAGIKAN
from aage.config import get_settings
from aage.models import Contact, Product

settings = get_settings()


def _teks(r) -> str:
    return " ".join(m.teks for m in r.replies)


def test_telegram_buyer_shares_number_and_gets_old_order(db):
    u = "tg-repeat-1"
    r1 = handle_inbound(db, channel="telegram", external_user_id=u, text="kak pesan ulang yang kemarin ya")
    assert "Bagikan nomor HP" in _teks(r1) and "Rp" not in _teks(r1) and r1.approval_id is None
    # Nomor milik pembeli lama (seed: Toko Obat Barokah, pesanan Kapsul Habbatussauda 120)
    r2 = handle_inbound(db, channel="telegram", external_user_id=u, text=TEKS_NOMOR_DIBAGIKAN, telepon="081200000002")
    assert r2.intent == "nomor_dibagikan" and "Kapsul Habbatussauda 120" in _teks(r2) and r2.approval_id
    c = db.scalar(select(Contact).where(Contact.channel == "telegram", Contact.external_user_id == u))
    assert c.wa_number == "6281200000002"  # dinormalisasi


def test_no_history_is_never_invented_then_candidates_then_staff(db):
    u = "t-repeat-kosong"
    r1 = handle_inbound(db, channel="webchat", external_user_id=u, text="kak mau pesan ulang yang biasanya itu")
    t1 = _teks(r1)
    assert "belum menemukan riwayat" in t1 and "Rp" not in t1 and "Bagikan nomor" not in t1  # web chat: tanpa tombol
    r2 = handle_inbound(db, channel="webchat", external_user_id=u, text="itu yang buat batuk-batuk, kemasannya kecil gitu")
    assert r2.intent == "cari_riwayat" and "Madu Herbal Batuk Dewasa" in _teks(r2) and "Rp" not in _teks(r2)
    r3 = handle_inbound(db, channel="webchat", external_user_id=u, text="aku yakin pernah pesan di sini kok")
    assert r3.decision == "eskalasi" and "staf" in _teks(r3) and "pesanan terakhir" not in _teks(r3).lower()


def test_inactive_product_is_not_reordered(db):
    p = db.scalar(select(Product).where(Product.sku == "ARB-006"))  # Propolis Tetes, ada di pesanan lama Apotek Sehat
    p.aktif = False
    db.commit()
    try:
        r = handle_inbound(db, channel="whatsapp", external_user_id="6281200000001", text="pesan ulang seperti biasa",
                           telepon="6281200000001")
        t = _teks(r)
        assert "sudah tidak ada di katalog" in t and "Madu Stamina Plus" in t and r.approval_id
        assert "Propolis Tetes 30 ml ×" not in t
    finally:
        p.aktif = True
        db.commit()


def test_shared_contact_must_belong_to_sender(monkeypatch):
    monkeypatch.setattr(settings, "telegram_allowlist", "")
    base = {"message_id": 7, "chat": {"id": 111, "type": "private"}, "from": {"id": 111, "is_bot": False, "first_name": "A"}}
    sendiri = telegram.parse_update({"message": {**base, "contact": {"phone_number": "+62 812-0000-0002", "user_id": 111}}})
    assert sendiri.text == TEKS_NOMOR_DIBAGIKAN and sendiri.telepon == "6281200000002"
    orang_lain = telegram.parse_update({"message": {**base, "contact": {"phone_number": "+6281200000001", "user_id": 999}}})
    assert orang_lain.telepon is None and orang_lain.text == "[contact tidak didukung]"
    tanpa_id = telegram.parse_update({"message": {**base, "contact": {"phone_number": "+6281200000001"}}})
    assert tanpa_id.telepon is None


def test_telegram_shows_share_button_only_when_asked(monkeypatch):
    calls = []

    def fake(url, json, timeout):
        calls.append(json)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}}, request=httpx.Request("POST", url))

    monkeypatch.setattr(settings, "telegram_bot_token", "123:abc")
    monkeypatch.setattr(settings, "telegram_allowlist", "")
    monkeypatch.setattr(telegram.httpx, "post", fake)
    a = telegram.TelegramAdapter()
    a.send_text("111", "halo")
    a.send_text("111", "bagikan nomor", minta_nomor=True)
    assert "reply_markup" not in calls[0]
    assert calls[1]["reply_markup"]["keyboard"][0][0]["request_contact"] is True


def test_staff_links_phone_manually(client, auth, db):
    r = handle_inbound(db, channel="telegram", external_user_id="tg-repeat-manual", text="halo kak")
    c = db.scalar(select(Contact).where(Contact.external_user_id == "tg-repeat-manual"))
    bad = client.patch(f"/api/contacts/{c.id}", headers=auth, json={"telepon": "12345"})
    assert bad.status_code == 422
    ok = client.patch(f"/api/contacts/{c.id}", headers=auth, json={"telepon": "0812-0000-0004"})
    assert ok.status_code == 200 and ok.json()["wa_number"] != "6281200000004"  # staf melihat nomor termasking
    db.expire_all()
    c = db.get(Contact, c.id)
    assert c.wa_number == "6281200000004" and sales.riwayat_terakhir(db, c) is not None
    detail = client.get(f"/api/conversations/{r.conversation_id}", headers=auth).json()
    assert detail["pesanan_terakhir"] is not None  # staf langsung melihat pesanan lama pembeli di Inbox
