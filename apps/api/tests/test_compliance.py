"""ClaimGuard & Compliance Check: engine, adapter LLM (di-mock, tanpa jaringan), repository, dan endpoint."""

import httpx
import pytest
from sqlalchemy import select

from src.compliance import ClaimGuardEngine, ClaimGuardInputError, JalurUtamaReviewer, LLMReview, UnknownProductError
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


@pytest.fixture
def jalur_utama(monkeypatch):
    """Nyalakan jalur LLM utama dengan kunci uji. Jaringan dipalsukan; tidak ada panggilan sungguhan."""
    from aage import llm

    monkeypatch.setattr(llm.settings, "llm_provider_name", "openai_compat")
    monkeypatch.setattr(llm.settings, "llm_api_key", "kunci-uji")
    monkeypatch.setattr(llm.settings, "llm_base_url", "https://llm.uji/v1")
    monkeypatch.setattr(llm.settings, "llm_judge_model", "hakim-uji")
    monkeypatch.setattr(llm.settings, "llm_fallback_models", "")
    monkeypatch.setattr(llm.settings, "llm_price_in_usd_per_m", 1.0)
    monkeypatch.setattr(llm.settings, "llm_price_out_usd_per_m", 1.0)
    monkeypatch.setattr(llm, "budget_ok", lambda: True)

    def pasang(*jawaban):
        panggilan = []
        antrean = list(jawaban)

        def palsu(url, body, timeout, headers=None):
            panggilan.append({"url": url, "body": body, "timeout": timeout})
            j = antrean.pop(0)
            if isinstance(j, Exception):
                raise j
            status, isi = j
            if status >= 300:
                return httpx.Response(status, json={"error": {"message": "kunci-uji ditolak"}})
            return httpx.Response(200, json={"choices": [{"message": {"content": isi}, "finish_reason": "stop"}],
                                             "usage": {"prompt_tokens": 321, "completion_tokens": 45}})

        monkeypatch.setattr(llm, "_post", palsu)
        return panggilan

    return pasang


def test_llm_output_tidak_valid_jadi_error(db, jalur_utama):
    jalur_utama((200, '{"status": "AMAN"}'))
    r = ClaimGuardEngine(db, JalurUtamaReviewer()).verify_content(OBA, CLEAN)
    assert r.status == "ERROR" and r.error_code == "llm_output_tidak_valid"


def test_llm_bukan_json_jadi_error(db, jalur_utama):
    jalur_utama((200, "maaf, tidak bisa"))
    r = ClaimGuardEngine(db, JalurUtamaReviewer()).verify_content(OBA, CLEAN)
    assert r.status == "ERROR" and r.error_code == "llm_output_tidak_valid"


def test_adapter_jalur_utama_output_valid(db, jalur_utama):
    panggilan = jalur_utama((200, '{"status": "ALLOWED", "summary": "Tidak ada klaim kesehatan.", "findings": []}'))
    r = ClaimGuardEngine(db, JalurUtamaReviewer()).verify_content(OBA, CLEAN)
    assert r.status == "ALLOWED" and r.stage == "llm"
    assert r.model_info.provider == "openai_compat" and r.model_info.model == "hakim-uji"
    assert r.model_info.input_tokens == 321 and r.model_info.biaya_rp > 0
    assert panggilan[0]["body"]["model"] == "hakim-uji"
    assert panggilan[0]["body"]["temperature"] == 0
    assert panggilan[0]["timeout"] == 60.0  # batas audit, bukan batas balasan chat
    assert panggilan[0]["body"]["max_tokens"] == 4096
    assert panggilan[0]["url"].startswith("https://llm.uji/v1")
    pesan = panggilan[0]["body"]["messages"]
    assert pesan[0]["role"] == "system" and "<materi>" in pesan[1]["content"]


def test_llm_timeout_ditolak_dan_tanpa_konfigurasi(db, jalur_utama, monkeypatch):
    from aage import llm

    jalur_utama(httpx.ReadTimeout("lambat"))
    r = ClaimGuardEngine(db, JalurUtamaReviewer()).verify_content(OBA, CLEAN)
    assert r.status == "ERROR" and r.error_code == "llm_timeout"

    jalur_utama((403, ""))
    r = ClaimGuardEngine(db, JalurUtamaReviewer()).verify_content(OBA, CLEAN)
    assert r.status == "ERROR" and r.error_code == "llm_gagal" and "HTTP 403" in r.reason
    assert "kunci-uji" not in r.reason  # pesan provider tidak diteruskan

    monkeypatch.setattr(llm, "budget_ok", lambda: False)
    r = ClaimGuardEngine(db, JalurUtamaReviewer()).verify_content(OBA, CLEAN)
    assert r.status == "ERROR" and r.error_code == "llm_budget_habis"

    monkeypatch.setattr(llm.settings, "llm_api_key", "")
    r = ClaimGuardEngine(db, JalurUtamaReviewer()).verify_content(OBA, CLEAN)
    assert r.status == "ERROR" and r.error_code == "llm_tidak_dikonfigurasi"
    r = ClaimGuardEngine(db, JalurUtamaReviewer(), llm_failure_status="NEED_REVIEW").verify_content(OBA, CLEAN)
    assert r.status == "NEED_REVIEW" and r.error_code == "llm_tidak_dikonfigurasi"


def test_llm_dimatikan_tidak_menjadi_allowed(db, jalur_utama):
    from aage import llm

    panggilan = jalur_utama()
    with llm.disabled():
        r = ClaimGuardEngine(db, JalurUtamaReviewer()).verify_content(OBA, CLEAN)
    assert r.status == "ERROR" and r.error_code == "llm_tidak_dikonfigurasi" and panggilan == []


def test_tahap_aturan_tidak_memanggil_llm(db, jalur_utama):
    panggilan = jalur_utama()
    r = ClaimGuardEngine(db, JalurUtamaReviewer()).verify_content(OBA, RISKY)
    assert r.status == "BLOCKED" and panggilan == []


def test_kategori_dan_risiko_di_hasil_aturan(db):
    r = ClaimGuardEngine(db, None).verify_content(OBA, RISKY)
    m = {x.rule_id: x for x in r.matched_rules}
    assert (m["R01"].kategori, m["R01"].risiko) == ("THERAPEUTIC_CLAIM", "HIGH")
    assert (m["R08"].kategori, m["R08"].risiko) == ("GUARANTEE", "HIGH")
    assert all(e.kategori and e.risiko for e in r.evidence)


def test_kategori_dan_risiko_di_hasil_llm(db):
    r = ClaimGuardEngine(db, FakeReviewer(review("NEED_REVIEW", [
        ("apotek mitra", "absolut", None),
        ("botol isi 120", "lainnya", None),
        ("Semarang", "keamanan", "R17"),
        ("kemasan", "keamanan", "R-KARANGAN"),
    ]))).verify_content(OBA, CLEAN)
    kat = {e.kutipan: (e.kategori, e.risiko) for e in r.evidence}
    assert kat["apotek mitra"] == ("GUARANTEE", "HIGH")
    assert kat["botol isi 120"] == ("UNCERTAIN_CLAIM", "MEDIUM")
    assert kat["Semarang"] == ("STATISTICAL_CLAIM", "MEDIUM")  # rule_id terdaftar menang
    assert kat["kemasan"] == ("GUARANTEE", "HIGH")  # rule_id karangan tidak dipakai
    assert r.status == "NEED_REVIEW"


def test_llm_blocked_punya_kategori(db):
    r = ClaimGuardEngine(db, FakeReviewer(review("BLOCKED", [("apotek mitra", "absolut", "R07")]))).verify_content(OBA, CLEAN)
    assert (r.matched_rules[0].kategori, r.matched_rules[0].risiko) == ("GUARANTEE", "HIGH")


def test_biaya_audit_masuk_ledger_dan_rute_memakai_jalur_utama(client, admin, db, jalur_utama):
    """Budget dihitung dari Ledger, jadi biaya audit harus tercatat di sana."""
    from aage.models import LedgerEvent

    jalur_utama((200, '{"status": "ALLOWED", "summary": "Tidak ada klaim kesehatan.", "findings": []}'))
    r = client.post("/api/compliance/audit", json={"product_id": OBA, "text": CLEAN + " Uji biaya."}, headers=admin)
    assert r.status_code == 200, r.text
    a = r.json()["audit"]
    assert a["status"] == "ALLOWED" and a["model_provider"] == "openai_compat" and a["model_name"] == "hakim-uji"
    assert a["engine_version"] == "claimguard-engine/2.1.0"
    db.expire_all()
    ev = db.scalar(select(LedgerEvent).where(LedgerEvent.objek_ref == f"audit:{a['audit_id']}"))
    assert ev.biaya_rp > 0 and ev.token_in == 321


def test_registry_melaporkan_jalur_utama(client, admin):
    from aage import llm

    info = client.get("/api/compliance/registry", headers=admin).json()["llm"]
    assert info["model"] == llm.settings.llm_judge_model
    assert info["provider"] == llm.settings.llm_provider
    assert info["dikonfigurasi"] is False  # kunci kosong di tes


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
    assert r.status_code == 200 and audit["status"] == "BLOCKED" and r.json()["draft"] is None
    latest = client.get(f"/api/compliance/latest-audit?product_id={SK}", headers=auth).json()
    assert latest["state"] == "ada" and latest["audit"]["audit_id"] == audit["audit_id"]
    ev = db.scalar(select(LedgerEvent).where(LedgerEvent.objek_ref == f"audit:{audit['audit_id']}"))
    assert ev is not None and ev.tipe_event == "compliance_audit" and ev.outcome == "BLOCKED"
    assert ev.data["input_text_hash"] == audit["input_text_hash"] and ev.data["rules_version"] == "2.2.0"


def test_ledger_juga_untuk_allowed_dan_error(client, auth, db, engine_with):
    from sqlalchemy import func, select

    from aage.models import LedgerEvent

    before = db.scalar(select(func.count()).select_from(LedgerEvent).where(LedgerEvent.tipe_event == "compliance_audit"))
    engine_with(FakeReviewer(review("ALLOWED")))
    assert client.post("/api/compliance/audit", json={"product_id": OBA, "text": CLEAN}, headers=auth).json()["audit"]["status"] == "ALLOWED"
    engine_with(FakeReviewer(ReviewerTimeout("lambat")))
    r = client.post("/api/compliance/audit", json={"product_id": OBA, "text": CLEAN}, headers=auth).json()
    assert r["audit"]["status"] == "ERROR" and r["draft"] is None
    after = db.scalar(select(func.count()).select_from(LedgerEvent).where(LedgerEvent.tipe_event == "compliance_audit"))
    assert after == before + 2


def test_retry_idempotency_tidak_duplikasi(client, auth):
    h = {**auth, "Idempotency-Key": "uji-retry-0001"}
    first = client.post("/api/compliance/audit", json={"product_id": OBA, "text": RISKY}, headers=h).json()
    again = client.post("/api/compliance/audit", json={"product_id": OBA, "text": RISKY}, headers=h).json()
    assert again["replayed"] is True and again["audit"]["audit_id"] == first["audit"]["audit_id"]
    r = client.post("/api/compliance/audit", json={"product_id": OBA, "text": RISKY + " Lain."}, headers=h)
    assert r.status_code == 409


# ------------------------------------------------------------------ satu sistem draf: content_drafts


def _draf(db, sku=OBA, isi=CLEAN, judul="Materi uji"):
    from aage.models import ContentDraft, Product

    p = db.scalar(select(Product).where(Product.sku == sku))
    d = ContentDraft(product_id=p.id, tipe="deskripsi", topik="uji", judul=judul, isi=isi, faq=[], meta={}, json_ld=[],
                     claim_verdict="allowed", claim_report={})
    db.add(d)
    db.commit()
    return d.id


def _audit_draf(client, headers, draft_id, sku=OBA):
    return client.post("/api/compliance/audit", json={"product_id": sku, "draft_id": draft_id}, headers=headers)


def test_audit_tanpa_draf_tidak_membuat_draf(client, auth, db):
    from sqlalchemy import func

    from aage.models import ContentDraft

    sebelum = db.scalar(select(func.count()).select_from(ContentDraft))
    r = client.post("/api/compliance/audit", json={"product_id": OBA, "text": RISKY}, headers=auth).json()
    assert r["draft"] is None and r["audit"]["draft_id"] is None and r["audit"]["draft_versi"] is None
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(ContentDraft)) == sebelum


def test_audit_draf_memeriksa_isi_draf(client, admin, db, engine_with):
    from aage.content import studio
    from aage.models import ContentDraft

    pid = _draf(db)
    engine_with(FakeReviewer(review("ALLOWED")))
    r = _audit_draf(client, admin, pid).json()
    d = db.get(ContentDraft, pid)
    assert r["audit"]["draft_id"] == pid and r["draft"]["id"] == pid and r["draft"]["judul"] == "Materi uji"
    assert r["audit"]["input_text_hash"] == __import__("hashlib").sha256(studio.full_text(d).encode()).hexdigest()
    hist = client.get(f"/api/compliance/audits?draft_id={pid}", headers=admin).json()["items"]
    assert [h["audit_id"] for h in hist] == [r["audit"]["audit_id"]]
    assert client.get(f"/api/compliance/latest-audit?draft_id={pid}", headers=admin).json()["draft"]["id"] == pid


def test_audit_draf_menolak_permintaan_yang_salah(client, auth, admin, db):
    from aage.models import ContentDraft

    pid = _draf(db)
    assert _audit_draf(client, auth, pid).status_code == 403  # staf penjualan tidak memegang izin konten
    assert _audit_draf(client, admin, pid, sku=SK).status_code == 422  # draf milik produk lain
    assert _audit_draf(client, admin, 999_999).status_code == 404
    r = client.post("/api/compliance/audit", json={"product_id": OBA, "draft_id": pid, "text": CLEAN}, headers=admin)
    assert r.status_code == 422  # isi draf yang diperiksa, bukan teks kiriman
    assert client.post("/api/compliance/audit", json={"product_id": OBA}, headers=admin).status_code == 422
    db.get(ContentDraft, pid).status = "diarsipkan"
    db.commit()
    assert _audit_draf(client, admin, pid).status_code == 409


def test_blokir_llm_bertahan_sampai_teks_berubah(client, admin, db, engine_with):
    """Aturan meloloskan teks ini; hanya LLM yang memblokir. Pemeriksaan aturan berikutnya tidak boleh menghapusnya."""
    from aage.content import studio
    from aage.models import ContentDraft

    pid = _draf(db)
    engine_with(FakeReviewer(review("BLOCKED", [("apotek mitra", "absolut", "R07")])))
    r = _audit_draf(client, admin, pid).json()
    assert r["audit"]["status"] == "BLOCKED" and r["audit"]["status_draf_diperbarui"] is True
    assert r["draft"]["claim_verdict"] == "blocked"

    d = db.get(ContentDraft, pid)
    db.refresh(d)
    with pytest.raises(studio.ContentError):
        studio.submit(db, d, "staf:pembuat")
    assert d.claim_verdict == "blocked"
    with pytest.raises(studio.ContentError):
        studio.approve(db, d, "staf:penyetuju", commit=False)
    db.rollback()

    # Audit ulang yang lolos tidak melepaskan blokir: hasil LLM tidak boleh diundi sampai cocok.
    engine_with(FakeReviewer(review("ALLOWED")))
    r = _audit_draf(client, admin, pid).json()
    assert r["audit"]["status"] == "ALLOWED" and r["draft"]["claim_verdict"] == "blocked"
    assert r["audit"]["status_draf_diperbarui"] is False
    db.expire_all()
    d = db.get(ContentDraft, pid)
    studio.recheck(db, d)
    assert d.claim_verdict == "blocked"

    # Teks berubah: audit lama tidak berlaku, dan pengajuan bisa berjalan lagi.
    studio.edit(db, d, {"isi": CLEAN + " Tersedia untuk grosir."}, "staf:pembuat")
    assert d.claim_verdict != "blocked"


def test_need_review_dan_error_tidak_melonggarkan(client, admin, db, engine_with):
    from aage.content import studio
    from aage.models import ContentDraft

    pid = _draf(db)
    engine_with(FakeReviewer(ReviewerTimeout("lambat")))
    r = _audit_draf(client, admin, pid).json()
    assert r["audit"]["status"] == "ERROR" and r["draft"]["claim_verdict"] == "allowed"  # LLM mati bukan bukti pelanggaran
    engine_with(FakeReviewer(review("NEED_REVIEW", [("apotek mitra", "absolut", None)])))
    r = _audit_draf(client, admin, pid).json()
    assert r["audit"]["status"] == "NEED_REVIEW" and r["draft"]["claim_verdict"] == "review"
    db.expire_all()
    d = db.get(ContentDraft, pid)
    studio.recheck(db, d)
    assert d.claim_verdict == "review"


def test_aturan_dua_orang_tidak_punya_jalan_pintas(client, admin, db):
    """Menyetujui, membuang, dan menerapkan rekomendasi hanya lewat Studio Konten."""
    pid = _draf(db)
    for aksi in ("approve", "discard", "apply-recommendation"):
        r = client.post(f"/api/compliance/drafts/{pid}/{aksi}", json={"confirm": True, "audit_id": "x" * 10}, headers=admin)
        assert r.status_code == 404
    assert client.get(f"/api/compliance/drafts/{pid}", headers=admin).status_code == 404
    assert client.get("/api/compliance/drafts", headers=admin).status_code == 404


def test_idempotency_draf_berbeda_ditolak(client, admin, db, engine_with):
    engine_with(FakeReviewer(review("ALLOWED")))
    a, b = _draf(db), _draf(db)
    h = {**admin, "Idempotency-Key": "uji-draf-beda-1"}
    pertama = _audit_draf(client, h, a).json()
    assert _audit_draf(client, h, a).json()["replayed"] is True
    assert pertama["draft"]["id"] == a
    assert _audit_draf(client, h, b).status_code == 409


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
    assert r["rules_version"] == "2.2.0" and r["llm"]["status_bila_gagal"] == "ERROR"
    assert {x["id"] for x in r["regulations"]} == {"PERBAN_34_2022", "PERBAN_30_2023"}
