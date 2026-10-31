"""Pelacak tahap & deteksi sinyal (aturan, deterministik), serta celah keamanan yang ditemukan eval percakapan."""

import pytest

from aage.agents.graph import handle_inbound
from aage.agents.router import route
from aage.agents.tahap import sinyal_baru, tahap_baru


@pytest.mark.parametrize("sebelumnya,intent,text,konteks,hasil", [
    (None, "salam", "halo", {}, "sapa"),
    ("closing", "salam", "halo lagi", {}, "closing"),                                  # sapaan tidak mengubah tahap
    (None, "negosiasi", "hmm mahal juga ya", {}, "keberatan"),
    ("rekomendasi", "lainnya", "nanti aku mikir dulu deh", {}, "tindak_lanjut"),
    ("rekomendasi", "lainnya", "oke nanti aku kabari", {}, "tindak_lanjut"),
    (None, "pesan", "aku mau pesan 5 box madu stamina", {}, "closing"),
    (None, "harga_moq", "minimal order brp box?", {"last_product_ids": [1]}, "rekomendasi"),  # min order bukan niat
    (None, "harga_moq", "madu stamina brp", {}, "gali_kebutuhan"),
    (None, "medis_personal", "anakku demam, aman ga?", {}, "layanan"),
    ("closing", "basa_basi", "oke lanjut", {}, "closing"),
])
def test_tahap_rules(sebelumnya, intent, text, konteks, hasil):
    assert tahap_baru(sebelumnya, intent, text, konteks) == hasil


@pytest.mark.parametrize("text,intent,sinyal", [
    ("kak mau pesan ulang yang biasanya", "pesan_ulang", ["repeat", "niat_tinggi"]),  # pembeli lama juga berniat beli
    ("madu stamina sama propolis, mana yang lebih cocok?", "tanya_produk", ["membandingkan"]),
    ("cuma nanya-nanya aja kak", "lainnya", ["penasaran"]),
    ("mau pesan 5 box", "pesan", ["niat_tinggi"]),
    ("min order brp box?", "harga_moq", []),
])
def test_sinyal_rules(text, intent, sinyal):
    assert sinyal_baru(text, intent) == sinyal


def test_tahap_and_sinyal_stored_in_conversation(db):
    user = "t-tahap-simpan"
    handle_inbound(db, channel="webchat", external_user_id=user, text="ada propolis tetes?")
    r = handle_inbound(db, channel="webchat", external_user_id=user, text="aku mikir dulu ya kak")
    from aage.models import Conversation

    conv = db.get(Conversation, r.conversation_id)
    assert conv.konteks["tahap"] == "tindak_lanjut" and conv.konteks["sinyal"] == []


@pytest.mark.parametrize("text,intent", [
    ("anakku demam, ini aman diminum ga?", "medis_personal"),
    ("gue lagi hamil, boleh minum madu?", "medis_personal"),
    ("bapakku batuk terus, kasih apa?", "medis_personal"),
    ("ibuku sesak napas dari tadi", "darurat"),  # sesak napas = darurat (119), bukan sekadar medis
])
def test_family_medical_questions_go_to_staff(text, intent):
    # Celah keamanan dari eval percakapan S09: "anak saya" dikenali, "anakku" tidak.
    assert route(text, inbound_verdict="allowed", inbound_rules=[], konteks={}).intent == intent
