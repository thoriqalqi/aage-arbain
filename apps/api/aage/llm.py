"""AI gateway di atas LiteLLM: model default murah, fallback, budget cap harian/bulanan, log biaya.

Model diganti cukup lewat konfigurasi (LLM_MODEL, LLM_JUDGE_MODEL, LLM_FALLBACK_MODELS).
Bila API key kosong, budget habis, atau provider gagal, fungsi `complete` mengembalikan None
dan pemanggil memakai jalur deterministik — demo tetap jalan."""

import json
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import func, select

from . import clock
from .config import get_settings
from .textutil import local_embed

log = logging.getLogger("aage.llm")
settings = get_settings()

OFFLINE_MODEL = "lokal/aturan-deterministik"


@dataclass
class LLMResult:
    text: str
    model: str
    token_in: int = 0
    token_out: int = 0
    biaya_rp: float = 0.0
    latensi_ms: int = 0
    data: dict | list | None = field(default=None)


_litellm = None
_disabled: ContextVar[bool] = ContextVar("aage_llm_disabled", default=False)


@contextmanager
def disabled():
    """Paksa jalur deterministik (dipakai saat draf LLM gagal ClaimGuard, dan oleh eval offline)."""
    token = _disabled.set(True)
    try:
        yield
    finally:
        _disabled.reset(token)


def _lib():
    global _litellm
    if _litellm is None:
        import litellm

        litellm.drop_params = True
        litellm.suppress_debug_info = True
        if settings.langfuse_public_key and settings.langfuse_secret_key:
            litellm.success_callback = ["langfuse"]
            litellm.failure_callback = ["langfuse"]
        _litellm = litellm
    return _litellm


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
        return spent_rp(days=1) < settings.budget_daily_rp and spent_rp(month=True) < settings.budget_monthly_rp
    except Exception:  # pragma: no cover - DB belum siap
        return True


def complete(
    messages: list[dict],
    *,
    judge: bool = False,
    json_mode: bool = False,
    max_tokens: int = 700,
    temperature: float = 0.2,
) -> LLMResult | None:
    if _disabled.get() or not settings.llm_enabled or not budget_ok():
        return None
    lib = _lib()
    primary = settings.llm_judge_model if judge else settings.llm_model
    candidates = [primary] + [m.strip() for m in settings.llm_fallback_models.split(",") if m.strip()]
    kwargs: dict = {"temperature": temperature, "max_tokens": max_tokens, "timeout": settings.llm_timeout_s}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    for model in candidates:
        started = time.perf_counter()
        try:
            resp = lib.completion(model=model, messages=messages, api_key=settings.gemini_api_key, **kwargs)
        except Exception as exc:  # provider gagal → coba model berikutnya
            log.warning("LLM %s gagal: %s", model, exc)
            continue
        text = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        try:
            usd = lib.completion_cost(completion_response=resp) or 0.0
        except Exception:
            usd = 0.0
        result = LLMResult(
            text=text,
            model=model,
            token_in=getattr(usage, "prompt_tokens", 0) or 0,
            token_out=getattr(usage, "completion_tokens", 0) or 0,
            biaya_rp=round(usd * settings.usd_to_idr, 2),
            latensi_ms=int((time.perf_counter() - started) * 1000),
        )
        if json_mode:
            try:
                cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
                result.data = json.loads(cleaned)
            except json.JSONDecodeError:
                log.warning("LLM %s tidak mengembalikan JSON valid", model)
                continue
        return result
    return None


def embed(text: str) -> list[float]:
    """Embedding multilingual. Default lokal (deterministik); set EMBEDDING_MODEL + API key dan
    re-ingest untuk memakai Gemini embedding."""
    if settings.llm_enabled and settings.embedding_model.startswith("gemini/") and settings.embedding_dim != 384:
        try:
            resp = _lib().embedding(
                model=settings.embedding_model,
                input=[text],
                api_key=settings.gemini_api_key,
                dimensions=settings.embedding_dim,
            )
            return list(resp.data[0]["embedding"])
        except Exception as exc:  # pragma: no cover - jaringan
            log.warning("Embedding gagal, pakai lokal: %s", exc)
    return local_embed(text, settings.embedding_dim)
