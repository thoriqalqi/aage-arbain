"""LLM lewat Gemini REST langsung (tanpa LiteLLM): request, error, jawaban kosong, JSON, budget.
Jaringan dipalsukan lewat llm._post — tidak ada panggilan sungguhan."""

import httpx
import pytest

from aage import llm
from aage.config import get_settings

settings = get_settings()


def _ok(text, finish="STOP", thought=None, usage=None):
    parts = ([{"text": thought, "thought": True}] if thought else []) + ([{"text": text}] if text is not None else [])
    return {"candidates": [{"content": {"parts": parts}, "finishReason": finish}],
            "usageMetadata": usage or {"promptTokenCount": 10, "candidatesTokenCount": 5}}


class FakePost:
    def __init__(self, items):
        self.items, self.calls = list(items), []

    def __call__(self, url, body, timeout, headers=None):
        self.calls.append({"url": url, "body": body, "timeout": timeout, "headers": headers})
        it = self.items.pop(0)
        if isinstance(it, Exception):
            raise it
        status, payload = it
        return httpx.Response(status, json=payload, request=httpx.Request("POST", url))


@pytest.fixture
def gemini(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "kunci-uji")
    monkeypatch.setattr(settings, "llm_model", "gemini/gemini-uji-flash")
    monkeypatch.setattr(settings, "llm_judge_model", "gemini/gemini-uji-flash")
    monkeypatch.setattr(settings, "llm_fallback_models", "")
    monkeypatch.setattr(settings, "llm_reasoning", False)
    monkeypatch.setattr(llm, "budget_ok", lambda: True)


def test_direct_rest_request_shape(gemini, monkeypatch):
    fake = FakePost([(200, _ok("halo"))])
    monkeypatch.setattr(llm, "_post", fake)
    res = llm.complete([{"role": "system", "content": "sys"}, {"role": "user", "content": "x"}],
                       json_mode=False, max_tokens=80, temperature=0)
    assert res.text == "halo" and res.model == "gemini/gemini-uji-flash" and res.finish_reason == "STOP"
    call = fake.calls[0]
    assert call["url"].endswith("/models/gemini-uji-flash:generateContent")
    cfg = call["body"]["generationConfig"]
    assert cfg["maxOutputTokens"] == 80 and cfg["temperature"] == 0 and cfg["thinkingConfig"] == {"thinkingBudget": 0}
    assert call["body"]["systemInstruction"]["parts"][0]["text"] == "sys"
    assert "kunci-uji" not in call["url"]  # key lewat header, bukan URL


def test_thought_parts_are_ignored(gemini, monkeypatch):
    monkeypatch.setattr(llm, "_post", FakePost([(200, _ok("jawaban", thought="pikiran internal"))]))
    assert llm.complete([{"role": "user", "content": "x"}]).text == "jawaban"


def test_http_error_recorded_no_silent_fallback(gemini, monkeypatch):
    fake = FakePost([(429, {"error": {"message": "Resource exhausted"}})])
    monkeypatch.setattr(llm, "_post", fake)
    assert llm.complete([{"role": "user", "content": "x"}]) is None
    err = llm.last_error()
    assert err["status"] == 429 and err["rate_limit"] and "Resource exhausted" in err["pesan"] and len(fake.calls) == 1


def test_key_is_redacted_from_error(gemini, monkeypatch):
    msg = "Permission denied: Consumer 'api_key:kunci-uji' has been suspended."
    monkeypatch.setattr(llm, "_post", FakePost([(403, {"error": {"message": msg}})]))
    assert llm.complete([{"role": "user", "content": "x"}]) is None
    assert "kunci-uji" not in llm.last_error()["pesan"] and "***" in llm.last_error()["pesan"]


def test_timeout_recorded(gemini, monkeypatch):
    monkeypatch.setattr(llm, "_post", FakePost([httpx.ReadTimeout("lambat")]))
    assert llm.complete([{"role": "user", "content": "x"}]) is None
    assert llm.last_error()["status"] == 408


def test_empty_answer_is_error(gemini, monkeypatch):
    monkeypatch.setattr(llm, "_post", FakePost([(200, _ok(None, finish="MAX_TOKENS", thought="mikir"))]))
    assert llm.complete([{"role": "user", "content": "x"}]) is None
    assert llm.last_error()["pesan"].startswith("jawaban kosong (finish_reason=MAX_TOKENS")


def test_json_mode(gemini, monkeypatch):
    fake = FakePost([(200, _ok('Berikut:\n{"intent": "harga_moq"} ok'))])
    monkeypatch.setattr(llm, "_post", fake)
    res = llm.complete([{"role": "user", "content": "x"}], json_mode=True)
    assert res.data == {"intent": "harga_moq"}
    assert fake.calls[0]["body"]["generationConfig"]["responseMimeType"] == "application/json"


def test_invalid_json_error_includes_raw_snippet(gemini, monkeypatch):
    monkeypatch.setattr(llm, "_post", FakePost([(200, _ok("bukan json sama sekali " * 20))]))
    assert llm.complete([{"role": "user", "content": "x"}], json_mode=True) is None
    err = llm.last_error()
    assert err["pesan"] == "JSON tidak valid dari model" and len(err["teks"]) == 200


def test_budget_block_is_reported(gemini, monkeypatch):
    monkeypatch.setattr(llm, "budget_ok", lambda: False)
    assert llm.complete([{"role": "user", "content": "x"}]) is None
    assert "Budget" in llm.last_error()["pesan"]


def test_cost_is_counted(gemini, monkeypatch):
    usage = {"promptTokenCount": 1_000_000, "candidatesTokenCount": 0}
    monkeypatch.setattr(llm, "_post", FakePost([(200, _ok("x", usage=usage))]))
    res = llm.complete([{"role": "user", "content": "x"}])
    assert res.biaya_rp == round(settings.llm_price_in_usd_per_m * settings.usd_to_idr, 2)


@pytest.fixture
def compat(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider_name", "")
    monkeypatch.setattr(settings, "llm_base_url", "https://contoh.ai/v1/")
    monkeypatch.setattr(settings, "llm_api_key", "thk_live_uji")
    monkeypatch.setattr(settings, "llm_model", "deepseek-uji:free")
    monkeypatch.setattr(settings, "llm_judge_model", "deepseek-uji:free")
    monkeypatch.setattr(settings, "llm_fallback_models", "")
    monkeypatch.setattr(llm, "budget_ok", lambda: True)


def _chat(text, finish="stop"):
    return {"choices": [{"message": {"content": text}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 7}}


def test_openai_compat_request_and_parse(compat, monkeypatch):
    fake = FakePost([(200, _chat('{"intent": "kebijakan"}'))])
    monkeypatch.setattr(llm, "_post", fake)
    assert settings.llm_provider == "openai_compat"
    res = llm.complete([{"role": "user", "content": "x"}], json_mode=True, max_tokens=80, temperature=0)
    assert res.data == {"intent": "kebijakan"} and res.model == "deepseek-uji:free" and res.finish_reason == "stop"
    call = fake.calls[0]
    assert call["url"] == "https://contoh.ai/v1/chat/completions"
    assert call["headers"] == {"Authorization": "Bearer thk_live_uji"} and "thk_live_uji" not in call["url"]
    assert call["body"]["model"] == "deepseek-uji:free" and call["body"]["response_format"] == {"type": "json_object"}


def test_openai_compat_rate_limit_and_redaction(compat, monkeypatch):
    resp = (429, {"error": {"message": "limit untuk key thk_live_uji tercapai"}})
    monkeypatch.setattr(llm, "_post", FakePost([resp]))
    assert llm.complete([{"role": "user", "content": "x"}]) is None
    err = llm.last_error()
    assert err["rate_limit"] and "thk_live_uji" not in err["pesan"] and "***" in err["pesan"]


def test_openai_compat_empty_is_error(compat, monkeypatch):
    monkeypatch.setattr(llm, "_post", FakePost([(200, _chat("", finish="length"))]))
    assert llm.complete([{"role": "user", "content": "x"}]) is None
    assert llm.last_error()["pesan"].startswith("jawaban kosong (finish_reason=length")


def test_disabled_without_key(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "")
    assert not settings.llm_enabled
    assert llm.complete([{"role": "user", "content": "x"}]) is None and llm.last_error() is None


def test_product_answer_gets_full_catalog_facts(db, monkeypatch):
    """LLM untuk tanya_produk menerima data lengkap (izin edar, harga, MOQ, tier, klaim) + kebijakan kirim."""
    from aage.agents import drafter
    from aage.kb.retriever import retrieve

    seen = {}

    def fake_llm_answer(question, sources, instruction):
        seen["sources"] = sources
        return None  # paksa jalur template agar tes tidak butuh LLM

    monkeypatch.setattr(drafter, "_llm_answer", fake_llm_answer)
    text = "ada produk buat jaga stamina kak?"
    d = drafter.draft_tanya_produk(db=db, text=text, conv=None, hits=retrieve(db, text))
    facts = seen["sources"][0]["kutipan"]
    for fakta in ("Madu Stamina Plus", "POM TR SIM260002", "2.340.000", "MOQ: 5 box", "diskon hingga", "Klaim disetujui"):
        assert fakta in facts
    assert seen["sources"][0].get("chunk_id")  # tetap tertaut ke sumber Knowledge Base
    assert any("Pengiriman:" in (s.get("kutipan") or "") for s in seen["sources"])
    assert d.template == "tanya_produk"
