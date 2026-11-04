"""AI Sales menolak dengan aman: tidak menawarkan produk pengganti, menjawab kebijakan dari bagian dokumen yang tepat,
dan meneruskan ke staf hal yang tidak diatur Knowledge Base."""

import pytest

from aage.agents.graph import handle_inbound
from aage.agents.router import route


def _route(text: str) -> str:
    return route(text, inbound_verdict="allowed", inbound_rules=[], konteks={}).intent


@pytest.mark.parametrize("text,intent", [
    ("1 box jahe merah instan isinya brp?", "spesifikasi"),
    ("kalsium magnesium nya brp mg", "spesifikasi"),
    ("barang rusak bisa retur?", "kebijakan"),
    ("kak, pesanan sy kemarin blm sampe", "keluhan"),
    ("paket sy udh seminggu blm dtg", "keluhan"),
    ("bisa COD?", "kebijakan"),
    ("minta katalog pdf + price list lengkap dong", "minta_dokumen"),
    ("harga eceran yg disarankan (HET) brp?", "perlu_staf"),
    ("sy mau jadi distributor eksklusif wilayah solo", "perlu_staf"),
    ("diskon paling banyak berapa?", "negosiasi"),
    ("how much is vitamin c zinc per box?", "harga_moq"),
])
def test_router_intents(text, intent):
    assert _route(text) == intent


@pytest.mark.parametrize("text", ["vitamin E ada kak?", "ada kolagen buat kulit kak?", "jual masker atau hand sanitizer gk?"])
def test_out_of_catalog_is_answered_not_escalated(db, text):
    r = handle_inbound(db, external_user_id=f"t-luar-{abs(hash(text))}", text=text, channel="webchat")
    assert r.decision == "kirim" and not r.approval_id
    teks = r.replies[0].teks
    assert "belum ada di katalog" in teks and "Ada, Kak" not in teks


def test_packaging_question_answers_contents(db):
    r = handle_inbound(db, external_user_id="t-spek", text="zinc 20mg 1 box isi brp botol", channel="webchat")
    assert r.intent == "spesifikasi" and r.decision == "kirim"
    assert "72 botol" in r.replies[0].teks and "Penawaran" not in r.replies[0].teks


@pytest.mark.parametrize("text,fakta", [
    ("kirim ke magelang brp lama", "1–3 hari kerja"),
    ("barang rusak bisa retur?", "3 hari"),
    ("ongkir gratis kah utk smg?", "25 box"),
    ("bisa bayar tempo gk?", "14 hari"),
])
def test_policy_answer_from_right_section(db, text, fakta):
    r = handle_inbound(db, external_user_id=f"t-kebijakan-{abs(hash(text))}", text=text, channel="webchat")
    assert r.intent == "kebijakan" and r.decision == "kirim"
    assert fakta in r.replies[0].teks
    assert any(s.get("chunk_id") for s in r.replies[0].sumber)


def test_shipping_fee_amount_goes_to_staff_with_partial_answer(db):
    r = handle_inbound(db, external_user_id="t-ongkir", text="ongkir ke sby brp? sm brp hari nyampe", channel="webchat")
    assert r.decision == "eskalasi" and r.approval_id
    teks = r.replies[0].teks
    assert "3–7 hari kerja" in teks and "dihitung staf" in teks


@pytest.mark.parametrize("text", ["bisa COD?", "bisa kirim ke singapura?"])
def test_outside_policy_is_escalated(db, text):
    r = handle_inbound(db, external_user_id=f"t-diluar-{abs(hash(text))}", text=text, channel="webchat")
    assert r.decision == "eskalasi" and "belum ada ketentuannya" in r.replies[0].teks


def test_very_large_order_goes_to_management(db):
    r = handle_inbound(db, external_user_id="t-besar", text="kalau ambil 1000 box harga spesial brp?", channel="webchat")
    assert r.decision == "eskalasi" and "1000 box" in r.replies[0].teks


def test_parse_order_lines_ignores_numbers_in_product_names(db):
    from aage.agents.sales import parse_order_lines

    lines = parse_order_lines(db, "10 box kapsul habbatussauda 120 + 5 box omega 3")
    assert [(p.sku, q) for p, q in lines] == [("ARB-001", 10), ("ARB-042", 5)]


def test_multi_product_quote_then_order(db):
    wa = "t-multi"
    r = handle_inbound(db, external_user_id=wa, text="10 box jahe merah instan + 5 box propolis tetes brp totalnya?", channel="webchat")
    assert r.intent == "harga_moq" and r.decision == "kirim"
    teks = r.replies[0].teks
    assert "Jahe Merah Instan" in teks and "Propolis Tetes" in teks and "Total" in teks
    handle_inbound(db, external_user_id=wa, text="pesan. nama toko: Apotek Uji Multi, alamat: Jl. Pandanaran 5 Semarang", channel="webchat")
    from aage.models import OrderDraft

    od = db.query(OrderDraft).filter(OrderDraft.nama_toko == "Apotek Uji Multi").order_by(OrderDraft.id.desc()).first()
    assert od is not None and {it["sku"] for it in od.item} == {"ARB-005", "ARB-006"}
    assert {it["qty"] for it in od.item} == {10, 5}


def test_order_in_one_message_with_two_products(db):
    r = handle_inbound(db, external_user_id="t-multi-2",
                       text="pesan 6 box madu stamina plus dan 8 box sari kurma ajwa, nama toko: Apotek Dua Item, alamat: Jl. Merdeka 2",
                       channel="webchat")
    assert r.intent == "pesan" and r.approval_id
    assert "Madu Stamina Plus" in r.replies[0].teks and "Sari Kurma Ajwa" in r.replies[0].teks


def test_llm_prompt_includes_recent_history(db, monkeypatch):
    from aage import llm

    seen = {}

    def fake_complete(messages, **_):
        if "PESAN ASLI:" not in messages[0]["content"]:  # abaikan permintaan tulis ulang gaya bahasa
            seen["prompt"] = messages[0]["content"]
        return None

    monkeypatch.setattr(llm, "complete", fake_complete)
    handle_inbound(db, external_user_id="t-riwayat", text="ada propolis tetes?", channel="webchat")
    handle_inbound(db, external_user_id="t-riwayat", text="ada produk untuk stamina?", channel="webchat")
    assert "RIWAYAT PERCAKAPAN" in seen["prompt"] and "ada propolis tetes?" in seen["prompt"]


@pytest.mark.parametrize("text,decision", [
    ("ada produk untuk tidur nyenyak?", "kirim"),   # kebutuhan yang dilayani klaim resmi (rileks)
    ("ada produk untuk daya tahan tubuh?", "kirim"),
    ("ada produk untuk jerawat?", "kirim"),        # kebutuhan yang tidak ada di klaim mana pun: jujur, staf hanya pilihan
])
def test_need_questions_checked_against_official_claims(db, text, decision):
    r = handle_inbound(db, external_user_id=f"t-kebutuhan-{abs(hash(text))}", text=text, channel="webchat")
    assert r.decision == decision
