"""Barang di luar katalog dijawab tuntas, staf hanya pilihan, dan permintaannya tercatat untuk dashboard."""

from datetime import timedelta

from sqlalchemy import select

from aage import clock, kpi
from aage.agents.graph import handle_inbound
from aage.models import OrderDraft, PermintaanTakTerpenuhi


def _tanya(db, teks, user):
    r = handle_inbound(db, channel="webchat", external_user_id=user, text=teks)
    return r, " ".join(m.teks for m in r.replies)


def test_dijawab_tuntas_dengan_produk_sejenis(db):
    r, jawab = _tanya(db, "ada cincau?", "t-lk-a")
    assert r.decision == "kirim" and not r.approval_id
    assert "belum ada di katalog" in jawab and "staf" in jawab and "Rp" not in jawab
    assert "Teh Herbal" in jawab or "Wedang" in jawab
    assert jawab.count("?") == 1


def test_permintaan_tercatat_dan_masuk_ringkasan(db):
    r, _ = _tanya(db, "ada cincau dong?", "t-lk-b")
    baris = db.scalars(select(PermintaanTakTerpenuhi).where(PermintaanTakTerpenuhi.trace_id == r.trace_id)).all()
    assert [b.istilah for b in baris] == ["cincau"] and baris[0].conversation_id == r.conversation_id
    now = clock.now() + timedelta(minutes=1)
    hasil = kpi.compute(db, now - timedelta(days=1), now)["permintaan_tak_terpenuhi"]
    assert hasil["total"] >= 1 and any(x["istilah"] == "cincau" for x in hasil["teratas"])


def test_tidak_ada_formulir_pesanan(db):
    sebelum = db.scalar(select(OrderDraft.id).order_by(OrderDraft.id.desc()))
    r, jawab = _tanya(db, "mau pesen cincau 10 box", "t-lk-c")
    assert "belum ada di katalog" in jawab and "lengkapi" not in jawab and "Draf pesanan" not in jawab
    assert db.scalar(select(OrderDraft.id).order_by(OrderDraft.id.desc())) == sebelum
    assert r.decision == "kirim"


def test_kebutuhan_tak_dikenal_tanpa_tawaran_produk(db):
    _, jawab = _tanya(db, "ada kolagen buat kulit kak?", "t-lk-d")
    assert "Yang paling dekat" not in jawab and "*" in jawab  # hanya petunjuk *daftar produk*


def test_barang_tak_sejenis_tanpa_tawaran_produk(db):
    _, jawab = _tanya(db, "jual rokok ga?", "t-lk-e")
    assert "Yang paling dekat" not in jawab and "kebutuhan" in jawab


def test_klaim_tetap_menang(db):
    r, jawab = _tanya(db, "ada ginseng buat nyembuhin diabetes?", "t-lk-f")
    assert r.intent == "klaim_kesehatan" and "Yang paling dekat" not in jawab


def test_penolakan_klaim_tidak_mengaitkan_produk_giliran_lalu(db):
    _tanya(db, "ada madu stamina?", "t-lk-g")
    _, jawab = _tanya(db, "ada obat diabetes?", "t-lk-g")
    assert "Madu Stamina" not in jawab
    _tanya(db, "ada madu stamina?", "t-lk-h")
    _, jawab = _tanya(db, "ini bisa nyembuhin diabetes?", "t-lk-h")
    assert "Madu Stamina" in jawab and "tidak ditujukan" in jawab


def test_ketentuan_gratis_ongkir_kota_lain_tidak_disebut(db):
    _, jawab = _tanya(db, "saya punya kios di aceh, ongkirnya berapa?", "t-lk-i")
    assert "gratis" not in jawab.lower()
    _, jawab = _tanya(db, "ongkir ke semarang gimana?", "t-lk-j")
    assert "gratis" in jawab.lower()
