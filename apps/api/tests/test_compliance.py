"""ClaimGuard & Compliance Check: engine, adapter LLM (di-mock, tanpa jaringan), repository, dan endpoint."""

import types

import httpx
import pytest

from src.compliance import AnthropicReviewer, ClaimGuardEngine, ClaimGuardInputError, LLMReview, UnknownProductError
from src.compliance.llm_adapter import ReviewerError, ReviewerTimeout, ReviewOutcome

OBA = "ARB-001"  # Kapsul Habbatussauda 120 — Obat Bahan Alam
SK = "ARB-003"  # Sari Kurma Ajwa 330 g — Suplemen Kesehatan
CLEAN = "Kapsul Habbatussauda 120 tersedia dalam kemasan botol isi 120 kapsul untuk apotek mitra di Semarang."
RISKY = "Kapsul Habbatussauda 120 pasti sembuh dari diabetes dan 100% langsung sembuh tanpa efek samping."


class FakeReviewer:
    provider, model = "fake", "fake-claimguard"

    def __init__(self, result: LLMReview | Exception):
        self.result, self.calls = result, 0

    def review(self, req):
        self.calls += 1
        assert "<materi>" in req.to_prompt()
        if isinstance(self.result, Exception):
            raise self.result
        return ReviewOutcome(review=self.result, provider=self.provider, model=self.model, latency_ms=5,
                             input_tokens=100, output_tokens=40)


def review(status, findings=(), summary="Ringkasan uji.", rewrite=None) -> LLMReview:
    return LLMReview(status=status, summary=summary, rewrite=rewrite,
                     findings=[{"quote": q, "category": c, "explanation": "uji", "rule_id": r} for q, c, r in findings])


# ------------------------------------------------------------------ validasi input (1, 2)


def test_produk_tidak_dikenal_dan_tidak_memanggil_llm(db):
    fake = FakeReviewer(review("ALLOWED"))
    with pytest.raises(UnknownProductError):
        ClaimGuardEngine(db, fake).verify_content("ARB-999", CLEAN)
    assert fake.calls == 0


@pytest.mark.parametrize("pid,text,code", [("", CLEAN, "product_id_kosong"), (OBA, "   ", "teks_kosong"),
                                            (OBA, "a" * 61, "teks_terlalu_panjang"), (OBA, 123, "tipe_data_tidak_valid")])
def test_validasi_input(db, pid, text, code):
    fake = FakeReviewer(review("ALLOWED"))
    with pytest.raises(ClaimGuardInputError) as exc:
        ClaimGuardEngine(db, fake, max_text_length=60).verify_content(pid, text)
    assert exc.value.code == code and fake.calls == 0


# ------------------------------------------------------------------ Tahap A (3, 4)


def test_frasa_berisiko_terverifikasi_blocked_tanpa_llm(db):
    fake = FakeReviewer(review("ALLOWED"))
    r = ClaimGuardEngine(db, fake).verify_content(OBA, RISKY)
    assert r.status == "BLOCKED" and r.stage == "aturan" and fake.calls == 0
    assert {"R01", "R06", "R08"} <= {m.rule_id for m in r.matched_rules}
    assert "Perban BPOM 34/2022" in r.violation_law and "Lampiran I bagian I angka 2" in r.violation_law
    assert all(ref["verification_status"] == "VERIFIED" for ref in r.references)
    assert r.recommendation and "sembuh" not in r.recommendation.lower()
    assert "Wajib ditinjau manusia" in r.recommendation_note


def test_suplemen_tidak_dirujuk_ke_perban_30(db):
    r = ClaimGuardEngine(db, None).verify_content(SK, "Sari Kurma Ajwa menyembuhkan demam berdarah.")
    assert r.status == "BLOCKED"
    assert "Perban BPOM 34/2022" in r.violation_law and "30/2023" not in r.violation_law


def test_frasa_rujukan_belum_terverifikasi_need_review(db):
    # "pengganti kemoterapi" hanya ada di daftar larangan produk (data simulasi, R20) — bukan dasar hukum terverifikasi.
    fake = FakeReviewer(review("ALLOWED"))
    r = ClaimGuardEngine(db, fake).verify_content(OBA, "Produk ini pengganti kemoterapi.")
    assert r.status == "NEED_REVIEW" and fake.calls == 0
    assert [m.rule_id for m in r.matched_rules] == ["R20"]
    assert r.violation_law is None and "Rujukan regulasi perlu diverifikasi" in r.regulatory_note


# ------------------------------------------------------------------ Tahap B (5–9)


def test_lolos_aturan_tapi_perlu_review_kontekstual(db):
    fake = FakeReviewer(review("NEED_REVIEW", [("apotek mitra di Semarang", "tanpa_bukti", None)]))
    r = ClaimGuardEngine(db, fake).verify_content(OBA, CLEAN)
    assert fake.calls == 1 and r.status == "NEED_REVIEW" and r.stage == "llm"
    assert r.evidence[0].sumber == "llm" and r.evidence[0].start is not None
    assert r.model_info.model == "fake-claimguard"


def test_llm_output_valid_allowed(db):
    r = ClaimGuardEngine(db, FakeReviewer(review("ALLOWED"))).verify_content(OBA, CLEAN)
    assert r.status == "ALLOWED" and "bukan jaminan" in r.reason and r.recommendation is None


def _fake_anthropic(monkeypatch, create):
    import anthropic

    class Client:
        def __init__(self, **_):
            self.messages = types.SimpleNamespace(create=create)

    monkeypatch.setattr(anthropic, "Anthropic", Client)


def test_llm_output_tidak_valid_jadi_error(db, monkeypatch):
    bad = types.SimpleNamespace(content=[types.SimpleNamespace(type="tool_use", input={"status": "AMAN"})], usage=None)
    _fake_anthropic(monkeypatch, lambda **_: bad)
    r = ClaimGuardEngine(db, AnthropicReviewer("kunci-uji", "claude-uji")).verify_content(OBA, CLEAN)
    assert r.status == "ERROR" and r.error_code == "llm_output_tidak_valid"


def test_adapter_anthropic_output_valid(db, monkeypatch):
    ok = types.SimpleNamespace(
        content=[types.SimpleNamespace(type="tool_use", input={"status": "ALLOWED", "summary": "Tidak ada klaim kesehatan.", "findings": []})],
        usage=types.SimpleNamespace(input_tokens=321, output_tokens=45))
    _fake_anthropic(monkeypatch, lambda **_: ok)
    r = ClaimGuardEngine(db, AnthropicReviewer("kunci-uji", "claude-uji")).verify_content(OBA, CLEAN)
    assert r.status == "ALLOWED" and r.model_info.provider == "anthropic" and r.model_info.input_tokens == 321


def test_llm_timeout_dan_tanpa_api_key(db, monkeypatch):
    import anthropic

    def timeout(**_):
        raise anthropic.APITimeoutError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))

    _fake_anthropic(monkeypatch, timeout)
    r = ClaimGuardEngine(db, AnthropicReviewer("kunci-uji", "claude-uji", 1)).verify_content(OBA, CLEAN)
    assert r.status == "ERROR" and r.error_code == "llm_timeout"
    r = ClaimGuardEngine(db, AnthropicReviewer("", "claude-uji")).verify_content(OBA, CLEAN)
    assert r.status == "ERROR" and r.error_code == "llm_tidak_dikonfigurasi"
    r = ClaimGuardEngine(db, AnthropicReviewer("", "claude-uji"), llm_failure_status="NEED_REVIEW").verify_content(OBA, CLEAN)
    assert r.status == "NEED_REVIEW" and r.error_code == "llm_tidak_dikonfigurasi"


@pytest.mark.parametrize("reviewer", [
    None,
    FakeReviewer(ReviewerTimeout("lambat")),
    FakeReviewer(ReviewerError("provider gagal")),
    FakeReviewer(review("BLOCKED", [("apotek mitra", "terapi_penyakit", None)])),  # BLOCKED tanpa rule terverifikasi
    FakeReviewer(review("ALLOWED", [("apotek mitra", "terapi_penyakit", None)])),  # ALLOWED tapi temuan berisiko
    FakeReviewer(review("NEED_REVIEW", [("kalimat yang tidak ada di teks", "absolut", "R07")])),  # kutipan karangan
])
def test_tidak_ada_kegagalan_yang_berubah_jadi_allowed(db, reviewer):
    r = ClaimGuardEngine(db, reviewer).verify_content(OBA, CLEAN)
    assert r.status in ("ERROR", "NEED_REVIEW")
    assert all(e.kutipan != "kalimat yang tidak ada di teks" for e in r.evidence)


def test_llm_blocked_dengan_rule_terverifikasi(db):
    r = ClaimGuardEngine(db, FakeReviewer(review("BLOCKED", [("apotek mitra", "absolut", "R07")]))).verify_content(OBA, CLEAN)
    assert r.status == "BLOCKED" and r.matched_rules[0].rule_id == "R07" and "Perban BPOM 34/2022" in r.violation_law


# ------------------------------------------------------------------ repository + endpoint (10–13, 15, 16)


@pytest.fixture
def engine_with(client):
    from aage.compliance_api import get_engine
    from aage.main import app

    def use(reviewer):
        app.dependency_overrides[get_engine] = lambda: ClaimGuardEngine(_db_holder["db"], reviewer)

    from aage.db import SessionLocal

    _db_holder = {"db": SessionLocal()}
    yield use
    app.dependency_overrides.pop(get_engine, None)
    _db_holder["db"].close()


@pytest.fixture
def admin(client):
    r = client.post("/api/auth/login", json={"email": "admin@aage.local", "password": "admin123"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_endpoint_validasi_dan_auth(client, auth):
    assert client.post("/api/compliance/audit", json={"product_id": OBA, "text": CLEAN}).status_code == 401
    r = client.post("/api/compliance/audit", json={"product_id": "ARB-999", "text": CLEAN}, headers=auth)
    assert r.status_code == 404 and r.json()["detail"]["kode"] == "produk_tidak_dikenal"
    r = client.post("/api/compliance/audit", json={"product_id": OBA, "text": "x" * 12_001}, headers=auth)
    assert r.status_code == 422 and r.json()["detail"]["kode"] == "teks_terlalu_panjang"
    assert "Traceback" not in r.text


def test_latest_audit_kosong_lalu_ada_dan_ledger(client, auth, db):
    from sqlalchemy import select

    from aage.models import LedgerEvent

    r = client.get(f"/api/compliance/latest-audit?product_id={SK}", headers=auth)
    assert r.status_code == 200 and r.json() == {"state": "kosong", "audit": None, "draft": None}
    r = client.post("/api/compliance/audit", json={"product_id": SK, "text": "Sari Kurma Ajwa menyembuhkan penyakit."}, headers=auth)
    audit = r.json()["audit"]
    assert r.status_code == 200 and audit["status"] == "BLOCKED" and r.json()["draft"]["status"] == "diblokir"
    latest = client.get(f"/api/compliance/latest-audit?product_id={SK}", headers=auth).json()
    assert latest["state"] == "ada" and latest["audit"]["audit_id"] == audit["audit_id"]
    ev = db.scalar(select(LedgerEvent).where(LedgerEvent.objek_ref == f"audit:{audit['audit_id']}"))
    assert ev is not None and ev.tipe_event == "compliance_audit" and ev.outcome == "BLOCKED"
    assert ev.data["input_text_hash"] == audit["input_text_hash"] and ev.data["rules_version"] == "2.1.0"


def test_ledger_juga_untuk_allowed_dan_error(client, auth, db, engine_with):
    from sqlalchemy import func, select

    from aage.models import LedgerEvent

    before = db.scalar(select(func.count()).select_from(LedgerEvent).where(LedgerEvent.tipe_event == "compliance_audit"))
    engine_with(FakeReviewer(review("ALLOWED")))
    assert client.post("/api/compliance/audit", json={"product_id": OBA, "text": CLEAN}, headers=auth).json()["audit"]["status"] == "ALLOWED"
    engine_with(FakeReviewer(ReviewerTimeout("lambat")))
    r = client.post("/api/compliance/audit", json={"product_id": OBA, "text": CLEAN}, headers=auth).json()
    assert r["audit"]["status"] == "ERROR" and r["draft"]["status"] == "audit_gagal"
    after = db.scalar(select(func.count()).select_from(LedgerEvent).where(LedgerEvent.tipe_event == "compliance_audit"))
    assert after == before + 2


def test_status_draf_tepat_dan_tidak_menyentuh_draf_lain(client, auth, engine_with):
    engine_with(FakeReviewer(review("ALLOWED")))
    a = client.post("/api/compliance/audit", json={"product_id": OBA, "text": CLEAN}, headers=auth).json()
    b = client.post("/api/compliance/audit", json={"product_id": OBA, "text": RISKY}, headers=auth).json()
    assert a["draft"]["id"] != b["draft"]["id"] and b["draft"]["status"] == "diblokir"
    other = client.get(f"/api/compliance/drafts/{a['draft']['id']}", headers=auth).json()
    assert other["draft"]["status"] == "lolos_pemeriksaan"
    r = client.post("/api/compliance/audit", json={"product_id": SK, "text": CLEAN, "draft_id": a["draft"]["id"]}, headers=auth)
    assert r.status_code == 422  # draf milik produk lain


def test_retry_idempotency_tidak_duplikasi(client, auth):
    h = {**auth, "Idempotency-Key": "uji-retry-0001"}
    first = client.post("/api/compliance/audit", json={"product_id": OBA, "text": RISKY}, headers=h).json()
    again = client.post("/api/compliance/audit", json={"product_id": OBA, "text": RISKY}, headers=h).json()
    assert again["replayed"] is True and again["audit"]["audit_id"] == first["audit"]["audit_id"]
    hist = client.get(f"/api/compliance/audits?draft_id={first['draft']['id']}", headers=auth).json()["items"]
    assert len(hist) == 1
    r = client.post("/api/compliance/audit", json={"product_id": OBA, "text": RISKY + " Lain."}, headers=h)
    assert r.status_code == 409


def test_tombol_intervensi_butuh_persetujuan_dan_audit_ulang_simpan_riwayat(client, auth, admin, engine_with):
    engine_with(FakeReviewer(review("ALLOWED")))
    r = client.post("/api/compliance/audit", json={"product_id": OBA, "text": RISKY}, headers=auth).json()
    draft_id, audit_id = r["draft"]["id"], r["audit"]["audit_id"]
    assert r["audit"]["status"] == "BLOCKED" and r["audit"]["recommendation"]

    # Tanpa confirm → ditolak, draf tidak berubah
    bad = client.post(f"/api/compliance/drafts/{draft_id}/apply-recommendation", json={"audit_id": audit_id}, headers=auth)
    assert bad.status_code == 422
    assert client.post(f"/api/compliance/drafts/{draft_id}/discard", json={}, headers=auth).status_code == 422
    assert client.post(f"/api/compliance/drafts/{draft_id}/approve", json={"confirm": True}, headers=auth).status_code == 409
    d = client.get(f"/api/compliance/drafts/{draft_id}", headers=auth).json()["draft"]
    assert d["teks"] == RISKY and d["versi"] == 1 and d["status"] == "diblokir"

    # Dengan confirm → teks diganti, audit ulang otomatis (audit baru), riwayat tetap
    ok = client.post(f"/api/compliance/drafts/{draft_id}/apply-recommendation",
                     json={"audit_id": audit_id, "confirm": True}, headers=auth).json()
    assert ok["audit"]["audit_id"] != audit_id and ok["audit"]["status"] == "ALLOWED"
    assert ok["draft"]["versi"] == 2 and ok["draft"]["status"] == "lolos_pemeriksaan"
    hist = client.get(f"/api/compliance/audits?draft_id={draft_id}", headers=auth).json()["items"]
    assert [h["audit_id"] for h in hist] == [ok["audit"]["audit_id"], audit_id]
    # Rekomendasi lama tidak bisa diterapkan lagi
    stale = client.post(f"/api/compliance/drafts/{draft_id}/apply-recommendation",
                        json={"audit_id": audit_id, "confirm": True}, headers=auth)
    assert stale.status_code == 409

    # Keputusan manusia tidak ditimpa audit ulang teks yang sama
    assert client.post(f"/api/compliance/drafts/{draft_id}/approve", json={"confirm": True}, headers=auth).json()["draft"]["status"] == "disetujui"
    again = client.post("/api/compliance/audit", json={"product_id": OBA, "text": ok["draft"]["teks"], "draft_id": draft_id}, headers=auth).json()
    assert again["draft"]["status"] == "disetujui" and again["audit"]["status_draf_diperbarui"] is False

    # Buang dengan confirm → soft delete, tercatat
    gone = client.post(f"/api/compliance/drafts/{draft_id}/discard", json={"confirm": True, "catatan": "uji"}, headers=auth).json()
    assert gone["draft"]["status"] == "dibuang"


def test_need_review_hanya_admin_dengan_catatan(client, auth, admin):
    r = client.post("/api/compliance/audit", json={"product_id": OBA, "text": "Produk ini pengganti kemoterapi."}, headers=auth).json()
    draft_id = r["draft"]["id"]
    assert r["audit"]["status"] == "NEED_REVIEW"
    assert client.post(f"/api/compliance/drafts/{draft_id}/approve", json={"confirm": True, "catatan": "sudah dicek tim"}, headers=auth).status_code == 403
    assert client.post(f"/api/compliance/drafts/{draft_id}/approve", json={"confirm": True}, headers=admin).status_code == 422
    ok = client.post(f"/api/compliance/drafts/{draft_id}/approve", json={"confirm": True, "catatan": "Dicek tim regulasi: aman"}, headers=admin)
    assert ok.status_code == 200 and ok.json()["draft"]["status"] == "disetujui"


def test_audit_append_only(db, client, auth):
    from sqlalchemy import select

    from aage.models import ComplianceAudit, LedgerImmutableError

    client.post("/api/compliance/audit", json={"product_id": OBA, "text": RISKY}, headers=auth)
    a = db.scalar(select(ComplianceAudit).order_by(ComplianceAudit.id.desc()))
    a.status = "ALLOWED"
    with pytest.raises(LedgerImmutableError):
        db.commit()
    db.rollback()


def test_registry_endpoint(client, auth):
    r = client.get("/api/compliance/registry", headers=auth).json()
    assert r["rules_version"] == "2.1.0" and r["llm"]["status_bila_gagal"] == "ERROR"
    assert {x["id"] for x in r["regulations"]} == {"PERBAN_34_2022", "PERBAN_30_2023"}
