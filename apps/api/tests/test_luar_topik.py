"""Chat di luar topik: AI menolak sopan & mengarahkan kembali, tidak menebak produk dari satu kata kebetulan,
dan tidak membebani staf. Kalimat diambil dari uji manual 31 Okt 2026 yang sebelumnya salah tangkap."""

import pytest

from aage.agents.graph import handle_inbound


def _ask(db, text: str, user: str | None = None):
    return handle_inbound(db, channel="webchat", external_user_id=user or f"t-topik-{abs(hash(text))}", text=text)


@pytest.mark.parametrize("text", [
    "siapa presiden indonesia sekarang?",
    "cuaca semarang hari ini gimana",
    "ceritain lelucon dong",
    "bisa bantu kerjain pr matematika?",
    "rekomendasi tempat makan enak di semarang",
])
def test_off_topic_is_redirected_without_staff(db, text):
    r = _ask(db, text)
    assert r.intent == "luar_topik" and r.decision == "kirim" and r.approval_id is None
    reply = r.replies[0].teks
    assert "asisten AI penjualan" in reply and "Ada, Kak" not in reply and "Rp" not in reply


@pytest.mark.parametrize("text", ["kamu bot ya?", "ini siapa?", "apakah ini dibalas manusia?"])
def test_identity_answered_honestly(db, text):
    r = _ask(db, text)
    assert r.intent == "identitas" and r.decision == "kirim" and "asisten AI" in r.replies[0].teks


def test_identity_offer_staff_then_yes_escalates(db):
    _ask(db, "kamu bot ya?", user="t-identitas-ya")
    r = _ask(db, "ya", user="t-identitas-ya")
    assert r.intent == "minta_staf" and r.decision == "eskalasi"


def test_staff_offer_only_valid_for_next_message(db):
    _ask(db, "kamu bot ya?", user="t-tawar-sekali")
    _ask(db, "ada propolis tetes?", user="t-tawar-sekali")
    assert _ask(db, "ya", user="t-tawar-sekali").intent != "minta_staf"


def test_unclear_message_asks_first_then_escalates(db):
    r1 = _ask(db, "asdfgh", user="t-klarifikasi")
    assert r1.decision == "kirim" and r1.approval_id is None and "belum menangkap maksudnya" in r1.replies[0].teks
    r2 = _ask(db, "qwerty zxc", user="t-klarifikasi")
    assert r2.decision == "eskalasi" and r2.approval_id


def test_off_topic_word_does_not_override_sales_question(db):
    r = _ask(db, "harga madu stamina berapa? sambil nonton bola nih")
    assert r.intent == "harga_moq" and "Madu Stamina Plus" in r.replies[0].teks


@pytest.mark.parametrize("text,product", [
    ("ada madu nafsu makan?", "Madu Anak Nafsu Makan"),  # nama lengkap tetap cocok
    ("kapsul daun salam ready?", "Kapsul Daun Salam"),
    ("habatusauda 120 hrg nya brp ya", "Kapsul Habbatussauda 120"),  # salah ketik nama khas tetap ditoleransi
])
def test_full_product_names_still_match(db, text, product):
    r = _ask(db, text)
    assert product in " ".join(m.teks for m in r.replies)


def test_greeting_word_is_not_a_product(db):
    from aage.kb.retriever import find_products

    assert find_products(db, "salam kenal kak") == []
    assert find_products(db, "bisa bantu saya?") == []
