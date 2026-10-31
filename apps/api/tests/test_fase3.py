"""AI sales fase 3: tindak lanjut tanpa tekanan, jalur kesehatan menang atas closing, upsell & urgensi hanya dari data."""

from sqlalchemy import func, select

from aage import inbox
from aage.agents.graph import handle_inbound
from aage.models import Conversation, OrderDraft, Product


def _ask(db, text: str, user: str):
    return handle_inbound(db, channel="webchat", external_user_id=user, text=text)


def _teks(r) -> str:
    return " ".join(m.teks for m in r.replies)


def test_thinking_it_over_is_respected(db):
    u = "t-f3-mikir"
    _ask(db, "ada propolis tetes?", u)
    r = _ask(db, "aku mikir dulu ya kak", u)
    t = _teks(r)
    assert r.intent == "tindak_lanjut" and r.decision == "kirim" and "Propolis Tetes" in t
    assert t.count("?") <= 1 and "buru" in t and "staf" not in t


def test_ok_plus_will_tell_you_is_not_a_staff_request(db):
    u = "t-f3-oke"
    _ask(db, "kamu bot ya?", u)  # jawaban identitas menawarkan "balas ya" untuk staf
    r = _ask(db, "oke nanti aku kabari ya", u)
    assert r.intent == "tindak_lanjut" and r.decision == "kirim"
    assert _ask(db, "ya", "t-f3-oke-2").intent != "minta_staf"  # tanpa tawaran sebelumnya, "ya" bukan minta staf


def test_health_question_blocks_closing_until_staff_handles_it(db):
    u = "t-f3-medis"
    _ask(db, "madu stamina berapa per box?", u)
    m = _ask(db, "anakku demam, ini aman diminum ga?", u)
    assert m.intent == "medis_personal" and m.decision == "eskalasi"
    sebelum = db.scalar(select(func.count()).select_from(OrderDraft))
    r = _ask(db, "yaudah pesan 2 box aja deh", u)
    assert r.intent == "tunda_closing" and r.decision == "eskalasi" and "staf" in _teks(r)
    assert db.scalar(select(func.count()).select_from(OrderDraft)) == sebelum  # tidak ada draf pesanan
    # Setelah staf menangani (ambil alih lalu kembalikan ke AI), pesanan berjalan normal lagi.
    conv = db.get(Conversation, r.conversation_id)
    inbox.take_over(db, conv, "Sari")
    inbox.release(db, conv, aktor="staf:Sari", alasan="Sudah dijelaskan, aman dikonsultasikan ke dokter")
    db.commit()
    lanjut = _ask(db, "pesan 5 box madu stamina, nama toko: Apotek Uji Tunda, alamat: Jl. Uji 3 Semarang", u)
    assert lanjut.intent == "pesan" and lanjut.approval_id


def test_upsell_mentions_only_real_next_tier(db):
    t = _teks(_ask(db, "harga 8 box madu stamina?", "t-f3-upsell"))
    assert "mulai 10 box, diskon bisa s.d. 3%" in t
    puncak = _teks(_ask(db, "harga 150 box madu stamina?", "t-f3-upsell-max"))
    assert "Info: mulai" not in puncak  # sudah di tier tertinggi → tidak ada upsell


def test_stock_note_only_from_recorded_stock(db):
    p = db.scalar(select(Product).where(Product.sku == "ARB-002"))
    p.stok = 6
    db.commit()
    try:
        t = _teks(_ask(db, "harga 8 box madu stamina?", "t-f3-stok"))
        assert "stok tercatat" in t and "6 box" in t
        assert not any(w in t.lower() for w in ("kehabisan", "buruan", "terbatas", "segera"))
        assert "stok tercatat" not in _teks(_ask(db, "harga 5 box madu stamina?", "t-f3-stok-cukup"))
    finally:
        p.stok = None
        db.commit()


def test_recommendation_is_focused(db):
    t = _teks(_ask(db, "ada produk untuk stamina?", "t-f3-rekom"))
    assert t.count("• *") <= 2


def test_unsold_return_question_is_honest(db):
    r = _ask(db, "kalau barangnya ga laku bisa dikembalikan?", "t-f3-retur")
    t = _teks(r)
    assert r.decision == "eskalasi" and "belum ada ketentuannya" in t and "Retur diterima" in t
