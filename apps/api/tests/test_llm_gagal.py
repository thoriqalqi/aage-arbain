"""Setiap panggilan LLM yang gagal tercatat di Ledger, tanpa teks bebas, dan tidak mengubah jalur cadangan."""
import httpx
import pytest
from sqlalchemy import select

from aage import ledger, ledger_chain, llm
from aage.agents.graph import handle_inbound
from aage.models import LedgerEvent
from src.compliance import ClaimGuardEngine, JalurUtamaReviewer

OBA = "ARB-010"


@pytest.fixture
def jaringan(monkeypatch, db):
    """Nyalakan jalur LLM dengan kunci uji. Jaringan dipalsukan; tidak ada panggilan sungguhan."""
    monkeypatch.setattr(llm.settings, "llm_provider_name", "openai_compat")
    monkeypatch.setattr(llm.settings, "llm_api_key", "kunci-uji")
    monkeypatch.setattr(llm.settings, "llm_base_url", "https://llm.uji/v1")
    monkeypatch.setattr(llm.settings, "llm_model", "model-uji")
    monkeypatch.setattr(llm.settings, "llm_judge_model", "hakim-uji")
    monkeypatch.setattr(llm.settings, "llm_fallback_models", "")
    monkeypatch.setattr(llm.settings, "llm_price_in_usd_per_m", 1.0)
    monkeypatch.setattr(llm.settings, "llm_price_out_usd_per_m", 1.0)
    monkeypatch.setattr(llm, "budget_ok", lambda: True)
    llm.ambil_kegagalan()

    def pasang(*jawaban, ulang=None):
        antrean = list(jawaban)

        def palsu(url, body, timeout, headers=None):
            j = ulang if ulang is not None else antrean.pop(0)
            if isinstance(j, Exception):
                raise j
            return j

        monkeypatch.setattr(llm, "_post", palsu)

    yield pasang
    llm.ambil_kegagalan()


def _ok(isi, token_keluar=45):
    return httpx.Response(200, json={"choices": [{"message": {"content": isi}, "finish_reason": "stop"}],
                                     "usage": {"prompt_tokens": 321, "completion_tokens": token_keluar}})


def _catatan(db, sejak):
    return list(db.scalars(select(LedgerEvent).where(LedgerEvent.tipe_event == "llm_gagal", LedgerEvent.id > sejak).order_by(LedgerEvent.id)))


def _id_terakhir(db):
    return db.scalar(select(LedgerEvent.id).order_by(LedgerEvent.id.desc()).limit(1)) or 0


def _pancing(db, **fields):
    """Event apa pun yang ditulis sesudah panggilan LLM ikut menuliskan kegagalannya."""
    ev = ledger.record(db, "claimguard_playground", ringkasan="pemicu", **fields)
    db.commit()
    return ev


@pytest.mark.parametrize(("respons", "jenis", "status"), [
    (httpx.ReadTimeout("lambat"), "timeout", 408),
    (httpx.ConnectError("putus"), "jaringan", None),
    (httpx.Response(429, json={"error": {"message": "terlalu banyak"}}, headers={"Retry-After": "7"}), "rate_limit", 429),
    (httpx.Response(403, json={"error": {"message": "ditolak"}}), "ditolak", 403),
])
def test_tiap_jenis_kegagalan_tercatat(db, jaringan, respons, jenis, status):
    sejak = _id_terakhir(db)
    jaringan(respons)
    assert llm.complete([{"role": "user", "content": "halo"}], tujuan="uji") is None
    _pancing(db)
    [ev] = _catatan(db, sejak)
    assert ev.outcome == jenis and ev.data["jenis"] == jenis and ev.data["status"] == status and ev.data["tujuan"] == "uji"
    assert ev.model == "model-uji" and ev.biaya_rp == 0
    if jenis == "rate_limit":
        assert ev.data["retry_after"] == "7"


def test_jawaban_rusak_tetap_mencatat_biaya_token(db, jaringan):
    sejak = _id_terakhir(db)
    jaringan(_ok("bukan json"), _ok(""))
    assert llm.complete([{"role": "user", "content": "x"}], json_mode=True, tujuan="uji") is None
    assert llm.complete([{"role": "user", "content": "x"}], tujuan="uji") is None
    _pancing(db)
    rusak, kosong = _catatan(db, sejak)
    assert rusak.outcome == "json_tidak_valid" and kosong.outcome == "jawaban_kosong"
    for ev in (rusak, kosong):
        assert ev.token_in == 321 and ev.token_out == 45 and ev.biaya_rp > 0 and ev.data["finish_reason"] == "stop"


def test_budget_habis_tercatat(db, jaringan, monkeypatch):
    sejak = _id_terakhir(db)
    monkeypatch.setattr(llm, "budget_ok", lambda: False)
    assert llm.complete([{"role": "user", "content": "x"}], judge=True, tujuan="uji") is None
    _pancing(db)
    [ev] = _catatan(db, sejak)
    assert ev.outcome == "budget_habis" and ev.model == "hakim-uji" and ev.latensi_ms is None


def test_llm_mati_bukan_kegagalan(db, jaringan, monkeypatch):
    sejak = _id_terakhir(db)
    with llm.disabled():
        assert llm.complete([{"role": "user", "content": "x"}]) is None
    monkeypatch.setattr(llm.settings, "llm_api_key", "")
    assert llm.complete([{"role": "user", "content": "x"}]) is None
    _pancing(db)
    assert _catatan(db, sejak) == []


def test_model_cadangan_berhasil_tetap_mencatat_yang_gagal(db, jaringan, monkeypatch):
    sejak = _id_terakhir(db)
    monkeypatch.setattr(llm.settings, "llm_fallback_models", "cadangan-uji")
    jaringan(httpx.ReadTimeout("lambat"), _ok("jawaban"))
    res = llm.complete([{"role": "user", "content": "x"}], tujuan="uji")
    assert res is not None and res.model == "cadangan-uji" and llm.last_error() is None
    _pancing(db)
    [ev] = _catatan(db, sejak)
    assert ev.model == "model-uji" and ev.outcome == "timeout"


def test_tidak_menyimpan_teks_bebas(db, jaringan):
    """Pesan provider bisa mengutip prompt; Ledger tidak bisa dihapus."""
    sejak = _id_terakhir(db)
    jaringan(httpx.Response(400, json={"error": {"message": "prompt: nomor 08123456789 kunci-uji"}}), _ok("nomor 08123456789"))
    llm.complete([{"role": "user", "content": "x"}], tujuan="uji")
    llm.complete([{"role": "user", "content": "x"}], json_mode=True, tujuan="uji")
    _pancing(db)
    for ev in _catatan(db, sejak):
        isi = f"{ev.ringkasan} {ev.alasan} {ev.data}"
        assert "08123456789" not in isi and "kunci-uji" not in isi


def test_mewarisi_rujukan_event_pemicu_dan_rantai_utuh(db, jaringan):
    sejak = _id_terakhir(db)
    jaringan(httpx.ReadTimeout("lambat"))
    llm.complete([{"role": "user", "content": "x"}], tujuan="uji")
    ev_pemicu = _pancing(db, trace_id="jejak-uji", product_id=1, objek_ref="content:1")
    [ev] = _catatan(db, sejak)
    assert (ev.trace_id, ev.product_id, ev.objek_ref) == ("jejak-uji", 1, "content:1")
    assert ev.id < ev_pemicu.id
    assert ledger_chain.verify(db)["utuh"] is True


def test_kegagalan_hanya_tertulis_sekali(db, jaringan):
    sejak = _id_terakhir(db)
    jaringan(httpx.ReadTimeout("lambat"))
    llm.complete([{"role": "user", "content": "x"}], tujuan="uji")
    _pancing(db)
    _pancing(db)
    assert len(_catatan(db, sejak)) == 1


def test_bot_tetap_membalas_dan_kegagalannya_tercatat(db, jaringan, monkeypatch):
    """Setiap node LangGraph berjalan di salinan konteks, jadi kegagalan harus tertulis di node tempatnya terjadi."""
    sejak = _id_terakhir(db)
    panggilan = []

    def palsu(url, body, timeout, headers=None):
        panggilan.append(body["model"])
        raise httpx.ReadTimeout("lambat")

    jaringan()
    monkeypatch.setattr(llm, "_post", palsu)
    r = handle_inbound(db, external_user_id="t-llm-gagal", text="ada produk untuk stamina?", channel="webchat")
    db.commit()
    assert r is not None
    catatan = _catatan(db, sejak)
    assert panggilan, "skenario ini harus memanggil LLM"
    assert len(catatan) == len(panggilan), [e.data["tujuan"] for e in catatan]
    assert all(e.conversation_id is not None and e.trace_id for e in catatan)
    assert ledger.boleh_dibaca_marketing(catatan[0]) is False
    assert ledger_chain.verify(db)["utuh"] is True


def test_audit_compliance_error_mencatat_kegagalan(db, jaringan):
    from aage import compliance as svc
    from aage.models import User

    sejak = _id_terakhir(db)
    jaringan(httpx.ReadTimeout("lambat"))
    user = db.scalar(select(User).where(User.role == "admin"))
    a, _, _ = svc.run_audit(db, engine=ClaimGuardEngine(db, JalurUtamaReviewer()), product_id=OBA,
                            text="Produk ini tersedia dalam kemasan botol.", user=user)
    assert a.status == "ERROR" and a.error_code == "llm_timeout"
    [ev] = _catatan(db, sejak)
    assert ev.data["tujuan"] == "compliance_audit" and ev.objek_ref == f"audit:{a.audit_id}"
    assert ev.latensi_ms is not None
