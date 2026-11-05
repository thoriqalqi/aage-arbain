"""Inbox: staf mengambil alih percakapan → AI berhenti mengirim dan hanya menyiapkan saran."""

from datetime import timedelta

from sqlalchemy import event

from aage import clock
from aage.agents.graph import handle_inbound
from aage.db import SessionLocal, engine
from aage.models import Conversation, LedgerEvent, Message


def _conv(text: str, wa: str) -> int:
    with SessionLocal() as db:
        return handle_inbound(db, external_user_id=wa, text=text, channel="whatsapp", nama="Bu Rina").conversation_id


def test_take_over_stops_ai_and_stores_suggestion(client, auth):
    cid = _conv("harga propolis tetes berapa?", "6281300000101")
    r = client.post(f"/api/conversations/{cid}/ambil-alih", headers=auth)
    assert r.status_code == 200 and r.json()["status"] == "ditangani_staf"

    with SessionLocal() as db:
        res = handle_inbound(db, external_user_id="6281300000101", text="kalau 30 box berapa?", channel="whatsapp")
        assert res.decision == "staf" and res.replies == []

    d = client.get(f"/api/conversations/{cid}", headers=auth).json()
    assert d["ditangani_oleh"] and d["saran_ai"]["teks"] and "30" in d["saran_ai"]["teks"]
    assert d["saran_ai"]["verdict"] == "allowed"
    assert d["contact"]["nama_wa"] == "Bu Rina"
    assert d["jendela"]["berlaku"] and d["jendela"]["terbuka"] and d["jendela"]["jam"] == 24

    r = client.post(f"/api/conversations/{cid}/kembalikan", headers=auth)
    assert r.json()["status"] == "otomatis"
    with SessionLocal() as db:
        res = handle_inbound(db, external_user_id="6281300000101", text="harga madu stamina?", channel="whatsapp")
        assert res.decision == "kirim" and res.replies


def test_staff_reply_takes_over_automatically(client, auth):
    cid = _conv("ada propolis?", "6281300000102")
    r = client.post(f"/api/conversations/{cid}/reply", headers=auth, json={"text": "Halo Kak, saya bantu ya."})
    assert r.status_code == 200
    with SessionLocal() as db:
        conv = db.get(Conversation, cid)
        assert conv.status == "ditangani_staf"
        types = {e.tipe_event for e in db.query(LedgerEvent).filter(LedgerEvent.conversation_id == cid)}
        assert "ambil_alih" in types


def test_take_over_expires_after_idle_hours(client, auth):
    cid = _conv("ada madu stamina?", "6281300000103")
    client.post(f"/api/conversations/{cid}/ambil-alih", headers=auth)
    with SessionLocal() as db:
        conv = db.get(Conversation, cid)
        conv.aktivitas_staf_terakhir = clock.now() - timedelta(hours=5)
        db.commit()
        res = handle_inbound(db, external_user_id="6281300000103", text="harga madu stamina?", channel="whatsapp")
        assert res.decision == "kirim"
        assert db.get(Conversation, cid).status == "otomatis"


def test_contact_profile_edit_is_logged(client, auth):
    cid = _conv("halo", "6281300000104")
    contact_id = client.get(f"/api/conversations/{cid}", headers=auth).json()["contact"]["id"]
    r = client.patch(f"/api/contacts/{contact_id}", headers=auth, json={"nama_toko": "Apotek Sehat Jaya", "alamat": "Jl. Pemuda 1"})
    assert r.status_code == 200 and r.json()["nama_toko"] == "Apotek Sehat Jaya"
    with SessionLocal() as db:
        assert db.query(LedgerEvent).filter(LedgerEvent.tipe_event == "kontak_diubah",
                                            LedgerEvent.objek_ref == f"contact:{contact_id}").count() == 1


def test_conversation_list_reports_waiting_since(client, auth):
    with SessionLocal() as db:
        res = handle_inbound(db, external_user_id="6281300000105", text="barang saya rusak, kecewa", channel="whatsapp")
        assert res.decision == "eskalasi"
    items = client.get("/api/conversations?status=eskalasi", headers=auth).json()["items"]
    item = next(i for i in items if i["id"] == res.conversation_id)
    assert item["approval_menunggu"] >= 1 and item["menunggu_sejak"]


def _jumlah_query(client, auth, path: str) -> tuple[int, dict]:
    hitung = {"n": 0}

    def tambah(*_):
        hitung["n"] += 1

    event.listen(engine, "before_cursor_execute", tambah)
    try:
        r = client.get(path, headers=auth)
    finally:
        event.remove(engine, "before_cursor_execute", tambah)
    assert r.status_code == 200
    return hitung["n"], r.json()


def test_daftar_inbox_dan_approval_jumlah_query_tidak_ikut_jumlah_percakapan(client, auth):
    _conv("ada madu stamina?", "6281300000201")
    _conv("bisa menyembuhkan diabetes?", "6281300000202")
    awal_inbox, _ = _jumlah_query(client, auth, "/api/conversations")
    awal_approval, _ = _jumlah_query(client, auth, "/api/approvals?status=semua")

    for i in range(203, 208):
        _conv("bisa menyembuhkan diabetes?", f"62813000002{i - 200:02d}")

    akhir_inbox, inbox = _jumlah_query(client, auth, "/api/conversations")
    akhir_approval, approvals = _jumlah_query(client, auth, "/api/approvals?status=semua")
    assert akhir_inbox == awal_inbox
    assert akhir_approval == awal_approval

    with SessionLocal() as db:
        for item in inbox["items"]:
            terakhir = db.query(Message).filter(Message.conversation_id == item["id"]).order_by(Message.id.desc()).first()
            assert item["pesan_terakhir"]["id"] == terakhir.id
            assert item["contact"]["id"] == db.get(Conversation, item["id"]).contact_id
    terkait = [a for a in approvals["items"] if a["conversation_id"]]
    assert terkait and all(a["contact"] for a in terkait)
