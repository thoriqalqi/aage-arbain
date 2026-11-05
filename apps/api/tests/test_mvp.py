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
    r = handle_inbound(db, external_user_id="t-katalog", text="ada produk untuk stamina?", channel="webchat")
    assert r.decision == "kirim"
    reply = r.replies[0]
    assert "POM" in reply.teks and any(s.get("chunk_id") for s in reply.sumber)
    events = db.query(LedgerEvent).filter(LedgerEvent.trace_id == r.trace_id).all()
    types = [e.tipe_event for e in events]
    for t in ("pesan_masuk", "intent", "retrieval", "draf_jawaban", "claimguard", "kebijakan", "pesan_keluar"):
        assert t in types


def test_discount_above_tier_escalates(db):
    handle_inbound(db, external_user_id="t-nego", text="harga 50 karton propolis tetes berapa?", channel="webchat")
    r = handle_inbound(db, external_user_id="t-nego", text="Bisa diskon 30%?", channel="webchat")
    assert r.intent == "negosiasi" and r.decision == "eskalasi" and r.approval_id
    conv = db.get(Conversation, r.conversation_id)
    assert conv.status == "eskalasi"


def test_health_claim_question_is_refused(db):
    r = handle_inbound(db, external_user_id="t-klaim", text="bisa sembuhkan hipertensi?", channel="webchat")
    assert r.inbound_verdict == "blocked"
    assert r.verdict == "allowed"
    assert "tidak dapat memberikan klaim" in r.replies[0].teks


def test_repeat_order_creates_draft(db):
    r = handle_inbound(db, channel="whatsapp", external_user_id="6281200000001", text="pesan ulang seperti bulan lalu")
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
    client.post("/api/chat/simulate", headers=auth, json={"session": sid, "text": "madu stamina plus 50 karton harganya?"})
    r = client.post("/api/chat/simulate", headers=auth, json={"session": sid, "text": "bisa diskon 30%?"}).json()
    ap_id = r["approval_id"]
    assert r["keputusan"] == "eskalasi"

    bad = client.post(f"/api/approvals/{ap_id}/decide", headers=auth,
                      json={"aksi": "edit", "teks": "Madu ini dijamin menyembuhkan diabetes."})
    assert bad.status_code == 422

    ok = client.post(f"/api/approvals/{ap_id}/decide", headers=auth, json={"aksi": "setujui"})
    assert ok.status_code == 200 and ok.json()["status"] == "disetujui"
    msgs = client.get(f"/api/chat/simulate/{sid}/messages", headers=auth).json()["pesan"]
    assert msgs[-1]["pengirim"] == "staf"


def test_ledger_trace_reaches_source_document(client, auth):
    r = client.post("/api/chat/simulate", headers=auth, json={"session": "trace", "text": "izin edar propolis tetes apa?"}).json()
    events = client.get("/api/ledger", headers=auth, params={"trace_id": r["trace_id"], "tipe": "pesan_keluar"}).json()
    trace = client.get(f"/api/ledger/{events['items'][0]['id']}/trace", headers=auth).json()
    assert trace["sumber"] and trace["sumber"][0]["dokumen"]["versi"] >= 1


def test_kpi_from_ledger(client, auth):
    k = client.get("/api/kpi", headers=auth).json()
    assert k["sumber"] == "ledger_events" and k["ringkasan"]["pesan_masuk"] > 0


def test_staff_role_sees_masked_numbers(client, auth):
    items = client.get("/api/conversations", headers=auth).json()["items"]
    wa = [i["contact"]["wa_number"] for i in items if (i["contact"]["wa_number"] or "").startswith("6281")]
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


def test_content_generate_approve_export(client):
    tok = client.post("/api/auth/login", json={"email": "marketing@aage.local", "password": "marketing123"}).json()["token"]
    auth = {"Authorization": f"Bearer {tok}"}
    d = client.post("/api/content/generate", headers=auth, json={"product_id": 1, "topik": "daya tahan tubuh"}).json()
    assert d["claim_verdict"] != "blocked" and not d["claim_report"]["json_ld_errors"]
    assert client.get(f"/api/content/{d['id']}/export", headers=auth).status_code == 422  # belum disetujui
    assert client.post(f"/api/content/{d['id']}/approve", headers=auth).status_code == 422  # aturan dua orang
    tok = client.post("/api/auth/login", json={"email": "admin@aage.local", "password": "admin123"}).json()["token"]
    assert client.post(f"/api/content/{d['id']}/approve", headers={"Authorization": f"Bearer {tok}"}).status_code == 200
    exp = client.get(f"/api/content/{d['id']}/export", headers=auth).json()
    assert "application/ld+json" in exp["html"]


def test_prospek_scout_osm(client, auth, monkeypatch):
    """Scouting memakai respons Overpass NYATA (fixture Kota Semarang) — tanpa jaringan saat tes."""
    import json
    from pathlib import Path

    from aage.prospects import lead_service

    fixture = json.loads((Path(__file__).parent / "fixtures" / "overpass_kota_semarang_apotek.json").read_text(encoding="utf-8"))
    calls = []

    def fake_post(url, query, timeout_s):
        calls.append(query)
        return fixture

    monkeypatch.setattr(lead_service, "_post", fake_post)
    r = client.post("/api/prospek/scout", headers=auth, json={"wilayah": "Kota Semarang", "jenis_toko": "Apotek"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert 'area["name"="Kota Semarang"]["boundary"="administrative"]' in calls[0] and 'node["amenity"="pharmacy"]' in calls[0]
    assert data["sumber"] == "osm_live" and 0 < data["jumlah"] <= 100
    for it in data["items"]:
        assert 0 <= it["skor"] <= 100 and it["osm_id"].startswith("osm:")
        assert it["alamat"]  # nyata atau "Alamat tidak spesifik"
    assert any(it["alamat"] == "Alamat tidak spesifik" for it in data["items"])
    # Pindai ulang tidak menggandakan data
    again = client.post("/api/prospek/scout", headers=auth, json={"wilayah": "Kota Semarang", "jenis_toko": "Apotek"}).json()
    assert again["baru"] == 0 and again["jumlah"] == data["jumlah"]
    pid = data["items"][0]["id"]
    assert client.patch(f"/api/prospects/{pid}", headers=auth, json={"status": "dihubungi"}).json()["status"] == "dihubungi"

    # Overpass penuh → kembali ke hasil pindaian nyata terakhir (cache), bukan data tiruan
    def busy(url, query, timeout_s):
        raise lead_service.ScoutError("Overpass penuh (504)")

    monkeypatch.setattr(lead_service, "_post", busy)
    cached = client.post("/api/prospek/scout", headers=auth, json={"wilayah": "Kota Semarang", "jenis_toko": "Apotek"}).json()
    assert cached["sumber"] == "cache" and cached["jumlah"] == data["jumlah"] and cached["peringatan"]
    fresh = client.post("/api/prospek/scout", headers=auth, json={"wilayah": "Kota Salatiga", "jenis_toko": "Minimarket"})
    assert fresh.status_code == 503


def test_opportunity_score_math():
    from aage.prospects import scoring_service as sc

    assert sc.geographic_fit(5) == 70 and sc.geographic_fit(2) == 70 and sc.geographic_fit(8) == 70
    assert sc.geographic_fit(0) == 35 and sc.geographic_fit(1) == 52.5
    assert sc.geographic_fit(19) == 35 and sc.geographic_fit(30) == 0 and sc.geographic_fit(50) == 0
    assert sc.data_completeness("024-1", "Mo-Su 08:00-21:00", True) == 30
    assert sc.data_completeness(None, None, False) == 0
    assert round(sc.haversine_km(-6.9932, 110.4203, -7.5695, 110.8290), 0) == 78  # Semarang → Solo ±78 km


def test_prospek_riset_tanpa_key_dan_dengan_serper(client, auth, monkeypatch):
    from aage.prospects import market_service

    pid = client.get("/api/prospects", headers=auth, params={"wilayah": "Kota Semarang", "tipe": "Apotek"}).json()["items"][0]["id"]

    # Tanpa SERPER_API_KEY: tidak ada data pasar karangan, NBA tetap dari data internal
    monkeypatch.setattr(market_service.settings, "serper_api_key", "")
    p = client.post(f"/api/prospects/{pid}/riset", headers=auth).json()
    assert p["market_analysis"]["status"] == "tidak_terhubung" and p["market_analysis"]["topik"] == []
    assert p["nba"]["verdict"] == "allowed" and p["nba"]["produk"]

    # Dengan Serper: hitungan = jumlah artikel yang dikembalikan, tautan asli diteruskan
    monkeypatch.setattr(market_service.settings, "serper_api_key", "kunci-uji")
    def fake_news(query):
        if "maag" in query:
            return [{"judul": f"Berita {i}", "tautan": f"https://contoh.id/{i}", "cuplikan": "", "sumber": "Contoh", "tanggal": "1 hari lalu"} for i in range(3)]
        return []
    monkeypatch.setattr(market_service, "_serper_news", fake_news)
    p = client.post(f"/api/prospects/{pid}/riset", headers=auth).json()
    m = p["market_analysis"]
    assert m["status"] == "ok" and m["topik_utama"] == "pencernaan"
    assert next(t for t in m["topik"] if t["id"] == "pencernaan")["jumlah_artikel"] == 3
    nba = p["nba"]
    assert nba["topik"] == "kesehatan pencernaan" and nba["verdict"] == "allowed"
    assert all("pencernaan" in x["klaim_resmi"].lower() or "kembung" in x["klaim_resmi"].lower() or "diare" in x["klaim_resmi"].lower() for x in nba["produk"])
    assert "%" not in m["ringkasan"]  # tidak ada persentase tren karangan
