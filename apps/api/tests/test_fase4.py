"""AI sales fase 4: gaya bahasa LLM dengan kunci fakta, dan memori ringkasan percakapan."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from aage import clock, llm
from aage.agents import gaya, memori
from aage.agents.graph import handle_inbound
from aage.models import Approval, Conversation, LedgerEvent


def _ask(db, text: str, user: str):
    return handle_inbound(db, channel="webchat", external_user_id=user, text=text)


def _teks(r) -> str:
    return " ".join(m.teks for m in r.replies)


def _llm_gaya(monkeypatch, ubah):
    """LLM palsu: hanya menjawab permintaan tulis ulang gaya; panggilan lain (penjaga, juri) dianggap mati."""
    panggilan = []

    def fake(messages, **_):
        isi = messages[-1]["content"]
        if "PESAN ASLI:" not in isi:
            return None
        asli = isi.split("PESAN ASLI:\n", 1)[1]
        panggilan.append(asli)
        return llm.LLMResult(text=ubah(asli), model="uji/gaya")

    monkeypatch.setattr(llm, "complete", fake)
    return panggilan


ASLI = ("Harga grosir *Madu Stamina Plus 250 g* Rp45.000/box, MOQ 10 box. "
        "Data stok belum ada di katalog kami; ketersediaan dikonfirmasi staf saat pesanan. Mau saya hitungkan?")


def test_fact_lock_accepts_pure_restyle(db):
    baru = ("Siap, Kak 😊 Untuk *Madu Stamina Plus 250 g* harga grosirnya Rp45.000/box dengan MOQ 10 box. "
            "Data stok belum ada di katalog kami ya, ketersediaan dikonfirmasi staf saat pesanan. Mau saya hitungkan?")
    assert gaya.periksa_fakta(db, ASLI, baru) == []


@pytest.mark.parametrize("baru, pelanggaran", [
    (ASLI.replace("45.000", "40.000"), "angka berubah"),
    (ASLI.replace("MOQ 10 box. ", ""), "angka berubah"),
    (ASLI.replace("*Madu Stamina Plus 250 g*", "madu kami"), "teks tebal hilang"),
    (ASLI.replace("Data stok belum ada di katalog kami; ", ""), "frasa kunci hilang"),
    (ASLI + " Buruan, stoknya terbatas!", "kata terlarang"),
    (ASLI + " Dijamin cocok!", "kata terlarang"),
    (ASLI.replace("Mau saya hitungkan?", "Mau saya hitungkan? Atau mau langsung pesan?"), "pertanyaan bertambah"),
    (ASLI + " Lihat https://contoh.id", "tautan baru"),
    (ASLI + " Pasti menyembuhkan.", "kata terlarang"),
])
def test_fact_lock_rejects_changed_facts(db, baru, pelanggaran):
    assert any(pelanggaran in s for s in gaya.periksa_fakta(db, ASLI, baru))


SWAP = "*Madu Stamina Plus 250 g* harga grosir Rp45.000/box. MOQ 5 box, mulai 10 box diskon s.d. 3%."


@pytest.mark.parametrize("baru", [
    SWAP.replace("MOQ 5 box, mulai 10 box", "MOQ 10 box, mulai 5 box"),  # dua nilai bersatuan sama ditukar
    SWAP.replace("mulai 10 box diskon s.d. 3%", "mulai 3 box diskon s.d. 10%"),  # jumlah & persen ditukar
    SWAP.replace("Rp45.000/box", "Rp45.000/botol"),  # satuan berubah
])
def test_fact_lock_rejects_swapped_numbers(db, baru):
    assert any("angka berubah" in s for s in gaya.periksa_fakta(db, SWAP, baru))


def test_fact_lock_allows_natural_unit_wording_and_harmless_words(db):
    baru = ("Siap Kak, untuk *Madu Stamina Plus 250 g* harga grosirnya Rp45.000 per box. MOQ 5 box ya, "
            "dan mulai 10 box diskon s.d. 3%. Saya memastikan datanya sesuai katalog.")
    assert gaya.periksa_fakta(db, SWAP, baru) == []


def test_fact_lock_rejects_question_added_to_statement(db):
    asli = "Siap, Kak 🙏 Silakan dipertimbangkan dulu, tidak perlu buru-buru."
    assert any("pertanyaan" in s for s in gaya.periksa_fakta(db, asli, asli + " Mau pesan berapa?"))


@pytest.mark.parametrize("baru, pelanggaran", [
    (ASLI.replace(" Mau saya hitungkan?", ""), "pertanyaan hilang"),
    (ASLI.replace("Mau saya hitungkan?", "Kalau boleh tahu, mau saya hitung"), "pertanyaan hilang"),
    ("Harga grosir *Madu Stamina Plus 250 g* Rp45.000/box, MOQ 10 box. Data stok belum ada di katalog kami; ketersediaan "
     "dikonfirmasi staf saat pesanan? Mau saya hitungkan", "teks terpotong"),
])
def test_fact_lock_rejects_truncated_or_question_dropped(db, baru, pelanggaran):
    assert any(pelanggaran in s for s in gaya.periksa_fakta(db, ASLI, baru))


def test_restyle_rejected_when_model_hit_token_limit(db, monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: llm.LLMResult(text=ASLI, model="uji/gaya", finish_reason="length"))
    h = gaya.tulis_ulang(db, ASLI)
    assert h.teks is None and any("terpotong" in s for s in h.pelanggaran)


@pytest.mark.parametrize("asli, baru", [
    ("Data stok belum ada di katalog kami.", "Untuk stok, datanya belum ada di katalog kami."),
    ("Total Rp 5 (belum termasuk ongkos kirim).", "Total Rp 5."),
    ("Saya asisten AI yang siap membantu.", "Saya siap membantu Kakak."),
])
def test_fact_lock_keeps_honesty_phrases(db, asli, baru):
    assert any("frasa kunci" in s for s in gaya.periksa_fakta(db, asli, baru))


@pytest.mark.parametrize("text", ["stok madu stamina masih ada?", "madu stamina ready gk?"])
def test_stock_question_answered_from_data_not_llm(db, monkeypatch, text):
    prompts = []

    def fake(messages, **_):
        prompts.append(messages[-1]["content"])
        return llm.LLMResult(text="Stok ada banyak, Kak!", model="uji/llm") if "SUMBER:" in messages[-1]["content"] else None

    monkeypatch.setattr(llm, "complete", fake)
    t = _teks(_ask(db, text, f"t-f4-stok-{abs(hash(text))}"))
    assert not any("SUMBER:" in x for x in prompts) and "ada banyak" not in t
    assert "Data stok belum ada" in t and not t.startswith("Ada, Kak")


def test_restyle_reverted_when_claimguard_objects(db, monkeypatch):
    from aage import claimguard

    _llm_gaya(monkeypatch, lambda asli: "Halo Kak 😊 " + asli)
    asli_check = claimguard.check

    def check(db_, teks, **k):
        hasil = asli_check(db_, teks, **k)
        if teks.startswith("Halo Kak 😊"):
            hasil.verdict = claimguard.REVIEW
        return hasil

    monkeypatch.setattr(claimguard, "check", check)
    r = _ask(db, "madu stamina berapa per box?", "t-f4-gaya-cg")
    assert r.decision == "kirim" and not _teks(r).startswith("Halo Kak 😊")
    evs = list(db.scalars(select(LedgerEvent).where(LedgerEvent.tipe_event == "gaya_bahasa",
                                                    LedgerEvent.conversation_id == r.conversation_id).order_by(LedgerEvent.id)))
    assert evs[-1].data["dibatalkan_claimguard"] is True and evs[-1].data["dipakai"] is False


def test_fact_lock_rejects_new_product_name(db):
    baru = ASLI.replace("Mau saya hitungkan?", "Cocok juga dengan Sari Kurma Ajwa 330 g.")
    assert any("nama produk" in s for s in gaya.periksa_fakta(db, ASLI, baru))


def test_restyle_used_when_it_passes(db, monkeypatch):
    panggilan = _llm_gaya(monkeypatch, lambda asli: "Halo Kak 😊 " + asli)
    r = _ask(db, "madu stamina berapa per box?", "t-f4-gaya-ok")
    assert panggilan and r.decision == "kirim" and _teks(r).startswith("Halo Kak 😊")
    ev = db.scalar(select(LedgerEvent).where(LedgerEvent.tipe_event == "gaya_bahasa", LedgerEvent.conversation_id == r.conversation_id))
    assert ev is not None and ev.data["dipakai"] is True


def test_restyle_falls_back_to_template_when_fact_changes(db, monkeypatch):
    _llm_gaya(monkeypatch, lambda asli: asli.replace("Rp", "cuma Rp1"))
    r = _ask(db, "madu stamina berapa per box?", "t-f4-gaya-tolak")
    t = _teks(r)
    assert r.decision == "kirim" and "cuma" not in t and "Madu Stamina Plus" in t
    ev = db.scalar(select(LedgerEvent).where(LedgerEvent.tipe_event == "gaya_bahasa", LedgerEvent.conversation_id == r.conversation_id))
    assert ev.data["dipakai"] is False and "Kunci fakta" in ev.alasan


@pytest.mark.parametrize("text", [
    "anakku demam, ini aman diminum ga?",
    "pelayanan kalian parah, saya kecewa",
    "kamu bot ya?",
    "pesan 5 box madu stamina, nama toko: Apotek Uji Gaya, alamat: Jl. Uji 4 Semarang",
])
def test_sensitive_identity_and_order_replies_never_restyled(db, monkeypatch, text):
    panggilan = _llm_gaya(monkeypatch, lambda asli: "Halo Kak 😊 " + asli)
    _ask(db, text, f"t-f4-luar-{abs(hash(text))}")
    assert panggilan == []


def test_memory_builds_short_summary(db):
    u = "t-f4-memori"
    _ask(db, "ada produk untuk daya tahan tubuh?", u)
    _ask(db, "harga 8 box madu stamina?", u)
    r = _ask(db, "mahal kak, bisa kurang?", u)
    m = db.get(Conversation, r.conversation_id).konteks["memori"]
    assert "Madu Stamina Plus 250 g" in m["produk"]
    assert m["jumlah"]["Madu Stamina Plus 250 g"] == 8
    assert m["kebutuhan"] == ["daya tahan tubuh"] and "harga" in m["keberatan"]
    t = memori.teks(m)
    assert "kebutuhan: daya tahan tubuh" in t and "keberatan: harga" in t


def test_memory_keeps_only_a_health_flag(db):
    r = _ask(db, "anakku demam tinggi, minum madu boleh?", "t-f4-memori-sehat")
    m = db.get(Conversation, r.conversation_id).konteks["memori"]
    assert m["kesehatan"] is True and "demam" not in str(m)
    ap = db.get(Approval, r.approval_id)
    assert ap is not None


def test_memory_shown_in_staff_summary(db):
    u = "t-f4-memori-staf"
    _ask(db, "harga 8 box madu stamina?", u)
    r = _ask(db, "saya mau bicara dengan staf", u)
    ap = db.get(Approval, r.approval_id)
    assert "Ringkasan: produk dibahas: Madu Stamina Plus 250 g" in ap.ringkasan


def test_memory_expires_after_retention(db):
    u = "t-f4-memori-lama"
    lalu = clock.now() - timedelta(days=31)
    with clock.frozen_at(lalu):
        _ask(db, "harga 8 box madu stamina?", u)
    r = _ask(db, "halo kak", u)
    m = db.get(Conversation, r.conversation_id).konteks["memori"]
    assert "produk" not in m and "jumlah" not in m
    assert db.scalar(select(LedgerEvent).where(LedgerEvent.tipe_event == "memori_dihapus",
                                               LedgerEvent.conversation_id == r.conversation_id)) is not None
