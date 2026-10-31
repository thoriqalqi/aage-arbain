"""AI gateway tanpa LiteLLM: Gemini REST API (GEMINI_API_KEY) atau endpoint OpenAI-compatible /chat/completions
(LLM_BASE_URL + LLM_API_KEY, mis. TokenHarbor). Satu provider aktif pada satu waktu (LLM_PROVIDER_NAME/otomatis). Model diatur lewat LLM_MODEL (jawaban & router) dan LLM_JUDGE_MODEL
(juri ClaimGuard). Fallback ke model lain hanya bila LLM_FALLBACK_MODELS diisi eksplisit.
Bila API key kosong, budget habis, atau Gemini gagal, `complete` mengembalikan None dan alasannya dicatat di
`last_error()`; pemanggil memakai jalur deterministik — demo tetap jalan."""

import json
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import timedelta

import httpx
from sqlalchemy import func, select

from . import clock
from .config import get_settings
from .textutil import local_embed

log = logging.getLogger("aage.llm")
settings = get_settings()

OFFLINE_MODEL = "lokal/aturan-deterministik"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


@dataclass
class LLMResult:
    text: str
    model: str
    token_in: int = 0
    token_out: int = 0
    biaya_rp: float = 0.0
    latensi_ms: int = 0
    data: dict | list | None = field(default=None)
    finish_reason: str | None = None


_disabled: ContextVar[bool] = ContextVar("aage_llm_disabled", default=False)
# Error panggilan terakhir (None bila sukses) — dibaca eval untuk membedakan ERROR dari jawaban sah.
_last_error: ContextVar[dict | None] = ContextVar("aage_llm_last_error", default=None)


def last_error() -> dict | None:
    """{"status": int|None, "rate_limit": bool, "pesan": str, "teks"?: str} dari panggilan terakhir, atau None."""
    return _last_error.get()


@contextmanager
def disabled():
    """Paksa jalur deterministik (dipakai saat draf LLM gagal ClaimGuard, dan oleh eval offline)."""
    token = _disabled.set(True)
    try:
        yield
    finally:
        _disabled.reset(token)


def spent_rp(days: int | None = None, month: bool = False) -> float:
    from .db import SessionLocal
    from .models import LedgerEvent

    now = clock.now()
    if month:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        start = now - timedelta(days=days or 1)
    with SessionLocal() as db:
        total = db.scalar(select(func.coalesce(func.sum(LedgerEvent.biaya_rp), 0)).where(LedgerEvent.waktu >= start))
    return float(total or 0)


def budget_ok() -> bool:
    try:
        from . import settings_store
        from .db import SessionLocal

        with SessionLocal() as db:
            return not settings_store.budget_exceeded(db)  # batas bisa diubah dari dashboard Pengaturan
    except Exception:  # pragma: no cover - DB belum siap
        return True


def _model_name(model: str) -> str:
    return model.removeprefix("gemini/").removeprefix("models/")


def _post(url: str, body: dict, timeout: float, headers: dict | None = None) -> httpx.Response:
    """Satu-satunya titik jaringan LLM (mudah dipalsukan di tes). Key dikirim lewat header, bukan URL."""
    if headers is None:
        headers = {"x-goog-api-key": settings.gemini_api_key}
    return httpx.post(url, json=body, timeout=timeout, headers={**headers, "Content-Type": "application/json"})


def _secrets() -> list[str]:
    return [k for k in (settings.gemini_api_key, settings.llm_api_key) if k]


def _redact(text: str) -> str:
    for k in _secrets():  # provider kadang menyebut key di pesan error — jangan pernah disimpan
        text = text.replace(k, "***")
    return text


def _request(name: str, messages: list[dict], *, json_mode: bool, max_tokens: int, temperature: float):
    """(url, body, headers) sesuai provider."""
    if settings.llm_provider == "openai_compat":
        body: dict = {"model": name, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        return (f"{settings.llm_base_url.rstrip('/')}/chat/completions", body,
                {"Authorization": f"Bearer {settings.llm_api_key}"})
    return (f"{GEMINI_BASE_URL}/models/{name}:generateContent",
            _body(messages, model=name, json_mode=json_mode, max_tokens=max_tokens, temperature=temperature), None)


def _parse_response(data: dict) -> tuple[str, str | None, int, int, str | None]:
    """(teks, finish_reason, token_in, token_out, alasan_blokir) dari respons provider."""
    if settings.llm_provider == "openai_compat":
        ch = (data.get("choices") or [{}])[0]
        usage = data.get("usage") or {}
        return ((ch.get("message") or {}).get("content") or "", ch.get("finish_reason"),
                usage.get("prompt_tokens", 0) or 0, usage.get("completion_tokens", 0) or 0, None)
    cand = (data.get("candidates") or [{}])[0]
    parts = (cand.get("content") or {}).get("parts") or []
    usage = data.get("usageMetadata") or {}
    return ("".join(p.get("text", "") for p in parts if not p.get("thought")), cand.get("finishReason"),
            usage.get("promptTokenCount", 0) or 0,
            (usage.get("candidatesTokenCount", 0) or 0) + (usage.get("thoughtsTokenCount", 0) or 0),
            (data.get("promptFeedback") or {}).get("blockReason"))


def _body(messages: list[dict], *, model: str, json_mode: bool, max_tokens: int, temperature: float) -> dict:
    system = "\n".join(m["content"] for m in messages if m["role"] == "system")
    contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                for m in messages if m["role"] != "system"]
    config: dict = {"maxOutputTokens": max_tokens, "temperature": temperature}
    if json_mode:
        config["responseMimeType"] = "application/json"
    if not settings.llm_reasoning and "flash" in model:
        config["thinkingConfig"] = {"thinkingBudget": 0}  # jangan habiskan token untuk "berpikir"
    body = {"contents": contents, "generationConfig": config}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    return body


def _parse_json(text: str):
    cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")  # model kadang menambah teks di luar JSON
        if start >= 0 and end > start:
            return json.loads(cleaned[start:end + 1])
        raise


def _cost_rp(token_in: int, token_out: int) -> float:
    usd = token_in / 1e6 * settings.llm_price_in_usd_per_m + token_out / 1e6 * settings.llm_price_out_usd_per_m
    return round(usd * settings.usd_to_idr, 2)


def complete(
    messages: list[dict],
    *,
    judge: bool = False,
    json_mode: bool = False,
    max_tokens: int = 700,
    temperature: float = 0.2,
) -> LLMResult | None:
    _last_error.set(None)
    if _disabled.get() or not settings.llm_enabled:
        return None
    if not budget_ok():
        _last_error.set({"status": None, "rate_limit": False, "pesan": "Budget AI terlampaui (BUDGET_DAILY_RP)"})
        return None
    primary = settings.llm_judge_model if judge else settings.llm_model
    candidates = [primary] + [m.strip() for m in settings.llm_fallback_models.split(",") if m.strip()]
    provider = settings.llm_provider
    for model in candidates:
        name = _model_name(model)
        started = time.perf_counter()
        url, body, headers = _request(name, messages, json_mode=json_mode, max_tokens=max_tokens, temperature=temperature)
        try:
            resp = _post(url, body, settings.llm_timeout_s, headers)
        except httpx.TimeoutException as exc:
            _last_error.set({"status": 408, "rate_limit": False, "pesan": f"Timeout {settings.llm_timeout_s:g} dtk: {type(exc).__name__}"})
            log.warning("LLM %s timeout", name)
            continue
        except httpx.HTTPError as exc:
            _last_error.set({"status": None, "rate_limit": False, "pesan": _redact(f"{type(exc).__name__}: {str(exc)[:200]}")})
            log.warning("LLM %s gagal: %s", name, type(exc).__name__)
            continue
        latency = int((time.perf_counter() - started) * 1000)
        if resp.status_code >= 300:
            try:
                err = resp.json().get("error", {})
                msg = err.get("message", "") if isinstance(err, dict) else str(err)
            except ValueError:
                msg = resp.text
            info = {"status": resp.status_code, "rate_limit": resp.status_code == 429,
                    "pesan": _redact(f"HTTP {resp.status_code}: {msg[:300]}")}
            if resp.headers.get("Retry-After"):
                info["retry_after"] = resp.headers["Retry-After"]
            _last_error.set(info)
            log.warning("LLM %s ditolak %s", name, resp.status_code)
            continue
        text, finish, tok_in, tok_out, block = _parse_response(resp.json())
        if not text.strip():  # mis. token habis untuk reasoning / diblokir safety — jangan anggap jawaban sah
            _last_error.set({"status": None, "rate_limit": False,
                             "pesan": f"jawaban kosong (finish_reason={finish}{', blockReason=' + block if block else ''})",
                             "teks": text[:200]})
            log.warning("LLM %s jawaban kosong (%s)", name, finish)
            continue
        label = f"gemini/{name}" if provider == "gemini" else name
        result = LLMResult(text=text, model=label, token_in=tok_in, token_out=tok_out,
                           biaya_rp=_cost_rp(tok_in, tok_out), latensi_ms=latency, finish_reason=finish)
        if json_mode:
            try:
                result.data = _parse_json(text)
            except json.JSONDecodeError:
                _last_error.set({"status": None, "rate_limit": False, "pesan": "JSON tidak valid dari model",
                                 "teks": text[:200]})  # potongan teks mentah (tanpa key) untuk diagnosis
                log.warning("Gemini %s tidak mengembalikan JSON valid", name)
                continue
        _last_error.set(None)
        return result
    return None


def embed(text: str) -> list[float]:
    """Embedding multilingual. Default lokal (deterministik); set EMBEDDING_MODEL=gemini/... + EMBEDDING_DIM≠384
    dan re-ingest untuk memakai Gemini embedding."""
    if settings.gemini_api_key and settings.embedding_model.startswith("gemini/") and settings.embedding_dim != 384:
        name = _model_name(settings.embedding_model)
        try:
            resp = _post(f"{GEMINI_BASE_URL}/models/{name}:embedContent",
                         {"content": {"parts": [{"text": text}]}, "outputDimensionality": settings.embedding_dim},
                         settings.llm_timeout_s)
            resp.raise_for_status()
            return list(resp.json()["embedding"]["values"])
        except Exception as exc:  # pragma: no cover - jaringan
            log.warning("Embedding gagal, pakai lokal: %s", type(exc).__name__)
    return local_embed(text, settings.embedding_dim)
