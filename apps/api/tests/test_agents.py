"""Tes multi-agen CrewAI (mode simulasi — tanpa panggilan LLM)."""

import json

import pytest

from src import agents_crew as ac


@pytest.fixture(autouse=True)
def _simulasi(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "simulasi")


def test_mock_products_schema():
    produk = ac.db().products
    assert len(produk) == 50
    for p in produk:
        assert p["kategori"] in {"Obat Bahan Alam", "Suplemen Kesehatan"}
        assert p["nomor_izin_edar_bpom"].startswith(("POM TR", "POM SD"))
        m = p["matriks_harga_b2b"]
        for k in ("harga_eceran_tertinggi_het", "harga_dasar_b2b_per_botol", "moq_minimal_box", "isi_per_box_botol",
                  "skema_diskon", "batas_diskon_maksimal_ai_persen"):
            assert k in m
        assert set(p["data_teknis_kefarmasian"]) >= {"status_bebas_bko", "uji_stabilitas", "efek_samping"}
        assert 1 <= len(p["klaim_khasiat_resmi_bpom"]) <= 2 and p["kata_kunci_larangan_overclaim"]


def test_negotiation_stops_above_ai_limit():
    r = ac.negotiate_price("ARB-002", 30, 15, "Toko Uji")
    assert r["status"] == ac.NEED_HUMAN_CONFIRMATION and "laporan_staf" in r
    ok = ac.negotiate_price("ARB-006", 50, 8)
    assert ok["status"] == ac.AUTO_APPROVED and ok["penawaran"]["diskon_persen"] == 8


def test_claimguard_blocks_product_forbidden_phrase_with_pasal():
    r = ac.audit_compliance("Madu ini obat kuat pria dan menyembuhkan diabetes.", "ARB-002", "uji")
    assert r["status"] == ac.BLOCKED
    assert any(h["aturan"] == "R20" for v in r["pelanggaran"] for h in v["temuan"])
    assert any(p["rujukan"].startswith("Perban BPOM 34/2022") for p in r["pasal_dilanggar"])
    assert all(p["status_verifikasi"] == "VERIFIED" for p in r["pasal_dilanggar"])
    assert r["notifikasi_dashboard"].startswith("[BPOM COMPLIANCE ALERT")


def test_disclaimer_is_not_blocked():
    r = ac.audit_compliance("Produk ini tidak ditujukan untuk menyembuhkan penyakit.", "ARB-006", "uji")
    assert r["status"] == ac.PASSED


def test_all_official_claims_and_geo_content_pass():
    for p in ac.db().products:
        for k in p["klaim_khasiat_resmi_bpom"]:
            assert ac.audit_compliance(k, p["id"])["status"] == ac.PASSED, (p["id"], k)
        g = ac.build_geo_content(p["id"], "info")
        assert ac.audit_compliance(g["markdown"], p["id"])["status"] == ac.PASSED, p["id"]


def test_workday_stream_endpoint(client, auth):
    with client.stream("GET", "/api/agents/workday/stream", headers=auth, params={"speed": 8}) as r:
        events = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: {\"")]
    agents = {e["agent"] for e in events}
    assert {"lead_miner_agent", "b2b_sales_agent", "geo_content_agent", "claim_guard_agent"} <= agents
    assert any(e["status"] == ac.BLOCKED for e in events)
    assert any(e["level"] == "hitl" for e in events) and events[-1]["level"] == "done"
    pending = client.get("/api/approvals", headers=auth).json()["items"]
    assert any(a["objek_tipe"].startswith("agen_") for a in pending)


def test_negotiate_and_invoice_endpoints(client, auth):
    r = client.post("/api/agents/negotiate", headers=auth,
                    json={"produk": "madu stamina plus", "qty_box": 30, "diskon_diminta": 15, "pembeli": "Toko Uji"}).json()
    assert r["negosiasi"]["status"] == ac.NEED_HUMAN_CONFIRMATION
    inv = client.post("/api/agents/invoice/approve", headers=auth,
                      json={"produk": "ARB-002", "qty_box": 30, "diskon_disetujui": 12, "pembeli": "Toko Uji", "target_wa": "628123"}).json()
    assert inv["status"] == "simulasi" and inv["total"] > 0
