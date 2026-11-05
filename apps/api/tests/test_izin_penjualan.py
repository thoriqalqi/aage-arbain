"""Pagar AI Assistant: simulator wajib login, izin peran ditegakkan di server, dan invoice tidak mengirim apa pun."""

import pytest
from sqlalchemy import select

from aage.channels import fonnte
from aage.db import SessionLocal
from aage.models import Approval, ApprovedClaim, LedgerEvent


def _token(client, email, sandi):
    return {"Authorization": f"Bearer {client.post('/api/auth/login', json={'email': email, 'password': sandi}).json()['token']}"}


@pytest.fixture
def admin(client):
    return _token(client, "admin@aage.local", "admin123")


@pytest.fixture
def marketing(client):
    return _token(client, "marketing@aage.local", "marketing123")


def _obrolan(client, auth, sesi, teks="madu stamina plus 50 karton harganya?"):
    r = client.post("/api/chat/simulate", headers=auth, json={"session": sesi, "text": teks})
    assert r.status_code == 200, r.text
    return r.json()


def test_simulator_wajib_login_dan_izin_penjualan(client, auth, admin, marketing):
    tubuh = {"session": "izin-sim", "text": "halo"}
    assert client.post("/api/chat/simulate", json=tubuh).status_code == 401
    assert client.get("/api/chat/simulate/izin-sim/messages").status_code == 401
    assert client.post("/api/chat/simulate", headers=marketing, json=tubuh).status_code == 403
    assert client.get("/api/chat/simulate/izin-sim/messages", headers=marketing).status_code == 403
    for headers in (auth, admin):
        assert client.post("/api/chat/simulate", headers=headers, json=tubuh).status_code == 200
    assert client.get("/api/chat/simulate/izin-sim/messages", headers=auth).json()["pesan"]


def test_marketing_tidak_bisa_membuka_atau_mengubah_inbox(client, auth, marketing):
    cid = _obrolan(client, auth, "izin-inbox")["conversation_id"]
    kontak = client.get(f"/api/conversations/{cid}", headers=auth).json()["contact"]["id"]
    for r in (client.get("/api/conversations", headers=marketing),
              client.get(f"/api/conversations/{cid}", headers=marketing),
              client.post(f"/api/conversations/{cid}/ambil-alih", headers=marketing),
              client.post(f"/api/conversations/{cid}/kembalikan", headers=marketing),
              client.post(f"/api/conversations/{cid}/reply", headers=marketing, json={"text": "Halo"}),
              client.patch(f"/api/contacts/{kontak}", headers=marketing, json={"nama_toko": "Diubah"})):
        assert r.status_code == 403
    d = client.get(f"/api/conversations/{cid}", headers=auth).json()
    assert d["status"] != "ditangani_staf" and d["contact"]["nama_toko"] != "Diubah"


def test_marketing_hanya_memutus_approval_konten(client, auth, marketing):
    sesi = "izin-approval"
    _obrolan(client, auth, sesi)
    ap_id = _obrolan(client, auth, sesi, "bisa diskon 30%?")["approval_id"]
    assert ap_id
    assert ap_id not in [a["id"] for a in client.get("/api/approvals?status=semua", headers=marketing).json()["items"]]
    assert ap_id in [a["id"] for a in client.get("/api/approvals?status=semua", headers=auth).json()["items"]]
    assert client.post(f"/api/approvals/{ap_id}/decide", headers=marketing, json={"aksi": "setujui"}).status_code == 403
    with SessionLocal() as db:
        assert db.get(Approval, ap_id).status == "menunggu"
        konten = Approval(objek_tipe="konten", alasan="uji izin", ringkasan="uji izin", status="menunggu")
        db.add(konten)
        db.commit()
        kid = konten.id
    try:
        assert kid in [a["id"] for a in client.get("/api/approvals", headers=marketing).json()["items"]]
        # Lolos pagar peran, lalu berhenti di aturan konten karena drafnya memang tidak ada.
        r = client.post(f"/api/approvals/{kid}/decide", headers=marketing, json={"aksi": "tolak"})
        assert r.status_code == 422 and "Draf konten" in r.json()["detail"]["pesan"]
    finally:
        with SessionLocal() as db:
            db.delete(db.get(Approval, kid))
            db.commit()


def test_hanya_admin_yang_memverifikasi_klaim_dan_tercatat(client, auth, admin, marketing):
    with SessionLocal() as db:
        klaim = db.scalars(select(ApprovedClaim).limit(1)).first()
        cid, semula = klaim.id, klaim.diverifikasi_oleh
    try:
        assert client.post(f"/api/kb/claims/{cid}/verify", headers=auth).status_code == 403
        assert client.post(f"/api/kb/claims/{cid}/verify", headers=marketing).status_code == 403
        with SessionLocal() as db:
            assert db.get(ApprovedClaim, cid).diverifikasi_oleh == semula
        r = client.post(f"/api/kb/claims/{cid}/verify", headers=admin)
        assert r.status_code == 200 and r.json()["diverifikasi_oleh"]
        with SessionLocal() as db:
            assert db.scalar(select(LedgerEvent.id).where(LedgerEvent.tipe_event == "klaim_diverifikasi", LedgerEvent.objek_ref == f"claim:{cid}"))
    finally:
        with SessionLocal() as db:
            db.get(ApprovedClaim, cid).diverifikasi_oleh = semula
            db.commit()


def test_isi_chat_tidak_bocor_ke_marketing_lewat_ledger(client, auth, marketing):
    r = _obrolan(client, auth, "izin-ledger")
    params = {"trace_id": r["trace_id"], "tipe": "pesan_masuk"}
    punya_staf = client.get("/api/ledger", headers=auth, params=params).json()
    assert punya_staf["total"] == 1
    assert client.get("/api/ledger", headers=marketing, params=params).json()["total"] == 0
    assert client.get("/api/ledger", headers=marketing, params={"conversation_id": r["conversation_id"]}).json()["total"] == 0
    assert all(e["conversation_id"] is None for e in client.get("/api/ledger", headers=marketing, params={"limit": 500}).json()["items"])
    assert client.get(f"/api/ledger/{punya_staf['items'][0]['id']}/trace", headers=marketing).status_code == 403
    assert client.get(f"/api/ledger/{punya_staf['items'][0]['id']}/trace", headers=auth).status_code == 200


def test_status_agen_tidak_memuat_isi_chat_untuk_marketing(client, auth, marketing):
    _obrolan(client, auth, "izin-status")

    def kerja(headers):
        return next(a["kerja"] for a in client.get("/api/agents/status", headers=headers).json()["agen"] if a["id"] == "sales")

    staf, mkt = kerja(auth), kerja(marketing)
    assert len(mkt) < len(staf) and staf.startswith(mkt)


def test_invoice_tidak_mengirim_dan_izin_penjualan(client, auth, marketing, monkeypatch):
    def jangan_kirim(*_a, **_k):
        raise AssertionError("Invoice tidak boleh dikirim lewat Fonnte")

    monkeypatch.setattr(fonnte, "send", jangan_kirim)
    tubuh = {"produk": "ARB-002", "qty_box": 30, "diskon_disetujui": 12, "pembeli": "Toko Uji Izin", "target_wa": "6281200000000"}
    assert client.post("/api/agents/invoice/approve", headers=marketing, json=tubuh).status_code == 403
    r = client.post("/api/agents/invoice/approve", headers=auth, json=tubuh)
    assert r.status_code == 200 and r.json()["status"] == "simulasi" and "dinonaktifkan" in r.json()["detail"]
    with SessionLocal() as db:
        ev = db.scalars(select(LedgerEvent).where(LedgerEvent.tipe_event == "invoice_disusun").order_by(LedgerEvent.id.desc())).first()
        assert ev.outcome == "simulasi" and "kanal" not in ev.data
