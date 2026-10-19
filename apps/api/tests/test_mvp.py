"""Tes acceptance criteria utama MVP (PRD §5)."""

import hashlib
import hmac
import json

import pytest

from aage import claimguard
from aage.agents.graph import handle_inbound
from aage.channels import sender
from aage.models import Conversation, LedgerEvent, LedgerImmutableError


# ---------------------------------------------------------------- M3 ClaimGuard

@pytest.mark.parametrize("text,expected", [
    ("Bisa menyembuhkan hipertensi dalam 7 hari.", "blocked"),
    ("Tidak hanya menyembuhkan maag, tapi juga asam urat.", "blocked"),
    ("100% aman tanpa efek samping.", "blocked"),
    ("Produk ini bukan obat dan tidak ditujukan untuk mengobati penyakit.", "allowed"),
    ("Membantu memelihara stamina dan kebugaran tubuh.", "allowed"),
    ("87% pelanggan merasa lebih bugar.", "review"),
    ("Diskon 7% untuk pembelian 50 karton.", "allowed"),
])
def test_claimguard_verdicts(db, text, expected):
    assert claimguard.check(db, text, use_llm=False).verdict == expected


def test_claimguard_fast_and_has_suggestion(db):
    res = claimguard.check(db, "Madu ini terbukti ampuh menyembuhkan diabetes.", use_llm=False)
    assert res.verdict == "blocked"
    assert res.duration_ms < 3000
    assert res.sentences[0].suggestion and "konsultasikan" in res.sentences[0].suggestion


# ---------------------------------------------------------------- M4 Ledger

def test_ledger_is_append_only(db):
    ev = db.query(LedgerEvent).first()
    ev.ringkasan = "diubah"
    with pytest.raises(LedgerImmutableError):
        db.flush()
    db.rollback()
    with pytest.raises(LedgerImmutableError):
        db.delete(db.query(LedgerEvent).first())
        db.flush()
    db.rollback()


# ---------------------------------------------------------------- M2 Sales Assistant

def test_catalog_answer_is_sourced(db):
    r = handle_inbound(db, wa_number="t-katalog", text="ada produk untuk stamina?", kanal="webchat")
    assert r.decision == "kirim"
    reply = r.replies[0]
    assert "POM" in reply.teks and any(s.get("chunk_id") for s in reply.sumber)
    events = db.query(LedgerEvent).filter(LedgerEvent.trace_id == r.trace_id).all()
    types = [e.tipe_event for e in events]
    for t in ("pesan_masuk", "intent", "retrieval", "draf_jawaban", "claimguard", "kebijakan", "pesan_keluar"):
        assert t in types


def test_discount_above_tier_escalates(db):
    handle_inbound(db, wa_number="t-nego", text="harga 50 karton propolis tetes berapa?", kanal="webchat")
    r = handle_inbound(db, wa_number="t-nego", text="Bisa diskon 30%?", kanal="webchat")
    assert r.intent == "negosiasi" and r.decision == "eskalasi" and r.approval_id
    conv = db.get(Conversation, r.conversation_id)
    assert conv.status == "eskalasi"


def test_health_claim_question_is_refused(db):
    r = handle_inbound(db, wa_number="t-klaim", text="bisa sembuhkan hipertensi?", kanal="webchat")
    assert r.inbound_verdict == "blocked"
    assert r.verdict == "allowed"
    assert "tidak dapat memberikan klaim" in r.replies[0].teks


def test_repeat_order_creates_draft(db):
    r = handle_inbound(db, wa_number="6281200000001", text="pesan ulang seperti bulan lalu", kanal="webchat")
    assert r.intent == "pesan_ulang" and r.approval_id
    assert "menunggu konfirmasi staf" in r.replies[0].teks


def test_sender_refuses_unchecked_text(db):
    conv = db.query(Conversation).first()
    bad = claimguard.check(db, "Dijamin sembuh total.", use_llm=False)
    with pytest.raises(sender.ClaimGuardRequired):
        sender.send(db, conv, "Dijamin sembuh total.", check=bad, pengirim="staf", trace_id=None)
    db.rollback()


# ---------------------------------------------------------------- API & approval

def test_approval_flow_and_claimguard_on_staff_edit(client, auth):
    sid = "approval-flow"
    client.post("/api/chat/simulate", json={"session": sid, "text": "madu stamina plus 50 karton harganya?"})
    r = client.post("/api/chat/simulate", json={"session": sid, "text": "bisa diskon 30%?"}).json()
    ap_id = r["approval_id"]
    assert r["keputusan"] == "eskalasi"

    bad = client.post(f"/api/approvals/{ap_id}/decide", headers=auth,
                      json={"aksi": "edit", "teks": "Madu ini dijamin menyembuhkan diabetes."})
    assert bad.status_code == 422

    ok = client.post(f"/api/approvals/{ap_id}/decide", headers=auth, json={"aksi": "setujui"})
    assert ok.status_code == 200 and ok.json()["status"] == "disetujui"
    msgs = client.get(f"/api/chat/simulate/{sid}/messages").json()["pesan"]
    assert msgs[-1]["pengirim"] == "staf"


def test_ledger_trace_reaches_source_document(client, auth):
    r = client.post("/api/chat/simulate", json={"session": "trace", "text": "izin edar propolis tetes apa?"}).json()
    events = client.get("/api/ledger", headers=auth, params={"trace_id": r["trace_id"], "tipe": "pesan_keluar"}).json()
    trace = client.get(f"/api/ledger/{events['items'][0]['id']}/trace", headers=auth).json()
    assert trace["sumber"] and trace["sumber"][0]["dokumen"]["versi"] >= 1


def test_kpi_from_ledger(client, auth):
    k = client.get("/api/kpi", headers=auth).json()
    assert k["sumber"] == "ledger_events" and k["ringkasan"]["pesan_masuk"] > 0


def test_staff_role_sees_masked_numbers(client, auth):
    items = client.get("/api/conversations", headers=auth).json()["items"]
    wa = [i["contact"]["wa_number"] for i in items if i["contact"]["wa_number"].startswith("6281")]
    assert all("•" in w for w in wa)


def test_requires_login(client):
    assert client.get("/api/ledger").status_code == 401


def test_whatsapp_webhook_signature(client):
    payload = {"entry": [{"changes": [{"value": {"messages": [
        {"from": "628999", "id": "wamid.1", "type": "text", "text": {"body": "halo"}}]}}]}]}
    raw = json.dumps(payload).encode()
    assert client.post("/api/webhook/whatsapp", content=raw, headers={"X-Hub-Signature-256": "sha256=salah"}).status_code == 401
    sig = hmac.new(b"rahasia-uji", raw, hashlib.sha256).hexdigest()
    ok = client.post("/api/webhook/whatsapp", content=raw,
                     headers={"X-Hub-Signature-256": f"sha256={sig}", "content-type": "application/json"})
    assert ok.status_code == 200 and ok.json()["diterima"] == 1


def test_content_generate_approve_export(client, auth):
    d = client.post("/api/content/generate", headers=auth, json={"product_id": 1, "topik": "daya tahan tubuh"}).json()
    assert d["claim_verdict"] != "blocked" and not d["claim_report"]["json_ld_errors"]
    assert client.get(f"/api/content/{d['id']}/export", headers=auth).status_code == 422  # belum disetujui
    assert client.post(f"/api/content/{d['id']}/approve", headers=auth).status_code == 200
    exp = client.get(f"/api/content/{d['id']}/export", headers=auth).json()
    assert "application/ld+json" in exp["html"]


def test_prospects_offline(client, auth, monkeypatch):
    from aage.prospects import mapper

    monkeypatch.setattr(mapper.settings, "prospect_allow_network", False)
    r = client.post("/api/prospects/search", headers=auth, json={"wilayah": "Kota Semarang", "tipe": "apotek"}).json()
    assert r["jumlah"] >= 30 and r["items"][0]["alasan_skor"]
    pid = r["items"][0]["id"]
    assert client.patch(f"/api/prospects/{pid}", headers=auth, json={"status": "dihubungi"}).json()["status"] == "dihubungi"
