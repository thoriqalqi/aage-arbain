"""Status agen live (dari Ledger), Pengaturan (mode otonomi, jeda, budget), dan role marketing."""

import pytest

from aage import agent_status
from aage.agents.graph import handle_inbound
from aage.models import Approval, LedgerEvent

DEFAULTS = {"otonomi": {"sales": "otonom"}, "jeda": {"sales": False},
            "anggaran": {"harian_rp": 25_000, "bulanan_rp": 500_000}}


@pytest.fixture
def admin(client):
    r = client.post("/api/auth/login", json={"email": "admin@aage.local", "password": "admin123"})
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    yield h
    assert client.put("/api/settings", headers=h, json=DEFAULTS).status_code == 200


def test_status_lists_six_agents_from_ledger(client, auth, db):
    handle_inbound(db, external_user_id="t-status", text="ada produk untuk stamina?", channel="webchat")
    db.commit()
    data = client.get("/api/agents/status", headers=auth).json()
    by_id = {a["id"]: a for a in data["agen"]}
    assert set(by_id) == {"orchestrator", "opportunity", "sales", "content", "claimguard", "evaluation"}
    assert by_id["sales"]["status"] == "bekerja" and by_id["sales"]["tugas"] > 0
    assert by_id["claimguard"]["tugas"] > 0
    assert by_id["sales"]["mode_efektif"] == "otonom"
    assert "terpakai_hari_ini_rp" in data["anggaran"]


def test_settings_requires_admin(client, auth):
    assert client.get("/api/settings", headers=auth).status_code == 200
    assert client.put("/api/settings", headers=auth, json={"otonomi": {"sales": "saran"}}).status_code == 403


def test_settings_validation(client, admin):
    assert client.put("/api/settings", headers=admin, json={"otonomi": {"content": "otonom"}}).status_code == 422
    assert client.put("/api/settings", headers=admin, json={"otonomi": {"sales": "liar"}}).status_code == 422
    assert client.put("/api/settings", headers=admin, json={"apa": 1}).status_code == 422
    r = client.put("/api/settings", headers=admin, json={"anggaran": {"harian_rp": 900_000, "bulanan_rp": 500_000}})
    assert r.status_code == 422


def test_setujui_dulu_holds_routine_reply_for_staff(client, admin, db):
    r = client.put("/api/settings", headers=admin, json={"otonomi": {"sales": "setujui"}})
    assert r.status_code == 200 and r.json()["otonomi"]["sales"] == "setujui"
    res = handle_inbound(db, external_user_id="t-setujui", text="ada produk untuk stamina?", channel="webchat")
    assert res.decision == "tahan"
    ap = db.get(Approval, res.approval_id)
    assert "Setujui dulu" in ap.alasan and "Madu Stamina" in ap.draf and ap.verdict == "allowed"
    db.rollback()
    assert db.query(LedgerEvent).filter(LedgerEvent.tipe_event == "pengaturan_diubah").count() >= 1


def test_paused_sales_holds_reply(client, admin, db):
    client.put("/api/settings", headers=admin, json={"jeda": {"sales": True}})
    res = handle_inbound(db, external_user_id="t-jeda", text="ada produk untuk stamina?", channel="webchat")
    assert res.decision == "tahan" and "dijeda" in db.get(Approval, res.approval_id).alasan
    db.rollback()
    status = {a["id"]: a for a in client.get("/api/agents/status", headers=admin).json()["agen"]}
    assert status["sales"]["status"] == "jeda"


def test_budget_exceeded_falls_back_to_setujui(client, admin, db):
    client.put("/api/settings", headers=admin, json={"anggaran": {"harian_rp": 0}})
    res = handle_inbound(db, external_user_id="t-budget", text="ada produk untuk stamina?", channel="webchat")
    assert res.decision == "tahan" and "Budget AI terlampaui" in db.get(Approval, res.approval_id).alasan
    db.rollback()
    sales = {a["id"]: a for a in client.get("/api/agents/status", headers=admin).json()["agen"]}["sales"]
    assert sales["mode"] == "otonom" and sales["mode_efektif"] == "setujui"


def test_escalation_rules_still_apply_in_otonom(client, admin, db):
    res = handle_inbound(db, external_user_id="t-otonom", text="50 box madu stamina, bisa diskon 25%?", channel="webchat")
    assert res.decision == "eskalasi"
    db.rollback()


def test_status_stream_emits_snapshot(client, auth, monkeypatch):
    monkeypatch.setattr(agent_status, "STREAM_MAX_S", 0.01)
    monkeypatch.setattr(agent_status, "STREAM_TICK_S", 0)
    r = client.get("/api/agents/status/stream", headers=auth)
    assert r.status_code == 200 and r.text.startswith("data: {") and "event: end" in r.text


def test_marketing_role_can_login(client):
    r = client.post("/api/auth/login", json={"email": "marketing@aage.local", "password": "marketing123"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "marketing"
