"""WATI API v3: parsing webhook pesan masuk dan pengiriman teks sesi.

Dokumentasi: https://docs.wati.io/llms.txt
- Kirim teks: POST {WATI_BASE_URL}/conversations/messages/text  body {"target", "text"}
- Auth: header Authorization: Bearer WATI_API_KEY (tanpa tenantId di URL untuk v3)
- Webhook "Message Received" (eventType "message") — WATI tidak menandatangani webhook, jadi endpoint
  dilindungi token rahasia di URL (WATI_WEBHOOK_TOKEN). WATI mengulang hingga 144x bila tidak dapat 200,
  jadi pemrosesan harus idempoten (dedup per id pesan).
- Rate limit ditandai HTTP 429 → coba ulang dengan jeda bertahap.

API key tidak pernah ditulis ke log atau pesan error.
"""

import logging
import time

import httpx

from ..config import get_settings

log = logging.getLogger("aage.wati")
settings = get_settings()

SIMULASI_PREFIX = "simulasi:"
MAX_ATTEMPTS = 4
BACKOFF_S = (1.0, 2.0, 4.0)
MAX_RETRY_AFTER_S = 10.0


def _digits(number: str) -> str:
    return "".join(ch for ch in number if ch.isdigit())


def _allowlist() -> set[str]:
    return {_digits(n) for n in settings.wati_allowlist.split(",") if _digits(n)}


def parse_message(payload: dict) -> dict | None:
    """Ambil pesan pembeli dari webhook WATI. None bila bukan pesan masuk dari kontak."""
    if payload.get("eventType") != "message" or payload.get("owner") is True:
        return None  # owner=True → pesan dari sisi bisnis (termasuk balasan kita sendiri)
    wa_id, msg_id = payload.get("waId"), payload.get("id")
    if not wa_id or not msg_id:
        log.warning("Webhook WATI tanpa waId/id diabaikan (eventType=%s)", payload.get("eventType"))
        return None
    kind = payload.get("type") or "text"
    text = (payload.get("text") or "").strip()
    if kind != "text" and not text:
        text = f"[{kind} tidak didukung]"
    if not text:
        return None
    return {"from": _digits(str(wa_id)), "id": f"wati:{msg_id}", "text": text, "name": payload.get("senderName")}


def _target(number: str) -> str:
    phone = _digits(number)
    return f"{settings.wati_channel_number}:{phone}" if settings.wati_channel_number else phone


def _retry_delay(resp: httpx.Response, attempt: int) -> float:
    try:
        return min(float(resp.headers.get("Retry-After", "")), MAX_RETRY_AFTER_S)
    except ValueError:
        return BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)]


def send_text(to: str, text: str) -> tuple[bool, str | None, str | None]:
    """Kirim teks ke percakapan aktif (jendela 24 jam). Return (ok, id_pesan, error)."""
    if not settings.wati_enabled:
        return False, None, "WhatsApp belum dikonfigurasi"
    allow = _allowlist()
    if allow and _digits(to) not in allow:
        return False, None, f"{SIMULASI_PREFIX} nomor di luar WATI_ALLOWLIST, tidak dikirim"

    url = settings.wati_base_url.rstrip("/") + "/conversations/messages/text"
    headers = {"Authorization": f"Bearer {settings.wati_api_key}", "Content-Type": "application/json"}
    body = {"target": _target(to), "text": text[:4096]}

    for attempt in range(MAX_ATTEMPTS):
        try:
            resp = httpx.post(url, json=body, headers=headers, timeout=10)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # Permintaan belum sampai ke WATI → aman diulang tanpa risiko pesan ganda.
            if attempt + 1 < MAX_ATTEMPTS:
                time.sleep(BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)])
                continue
            log.error("Kirim WATI gagal (koneksi): %s", type(exc).__name__)
            return False, None, f"Koneksi ke WATI gagal ({type(exc).__name__})"
        except httpx.HTTPError as exc:
            log.error("Kirim WATI gagal: %s", type(exc).__name__)
            return False, None, f"Kirim WATI gagal ({type(exc).__name__})"

        if resp.status_code == 429 and attempt + 1 < MAX_ATTEMPTS:
            delay = _retry_delay(resp, attempt)
            log.warning("WATI rate limit (429), coba lagi dalam %.1fs", delay)
            time.sleep(delay)
            continue
        if resp.status_code >= 300:
            detail = resp.text[:300]
            log.error("Kirim WATI ditolak %s: %s", resp.status_code, detail)
            return False, None, f"WATI {resp.status_code}: {detail}"
        try:
            msg_id = (resp.json().get("message") or {}).get("id")
        except ValueError:
            msg_id = None
        return True, f"wati:{msg_id}" if msg_id else None, None

    return False, None, "WATI rate limit (429) setelah beberapa percobaan"


def send_template(to: str, template: str, params: list[str]) -> tuple[bool, str | None, str | None]:
    if not settings.wati_enabled:
        return False, None, "WhatsApp belum dikonfigurasi"
    return False, None, "Template WATI belum didukung adapter ini"
