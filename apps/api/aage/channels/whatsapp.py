"""WhatsApp Cloud API: verifikasi webhook, verifikasi signature, parsing pesan, dan pengiriman."""

import hashlib
import hmac
import logging

import httpx

from ..config import get_settings

log = logging.getLogger("aage.wa")
settings = get_settings()


def verify_signature(raw_body: bytes, header: str | None) -> bool:
    """Validasi X-Hub-Signature-256. Bila WA_APP_SECRET kosong (mode dev), dilewati."""
    if not settings.wa_app_secret:
        return True
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(settings.wa_app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def parse_messages(payload: dict) -> list[dict]:
    out = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            names = {c.get("wa_id"): c.get("profile", {}).get("name") for c in value.get("contacts", [])}
            for m in value.get("messages", []):
                if m.get("type") == "text":
                    text = m["text"]["body"]
                elif m.get("type") == "button":
                    text = m["button"].get("text", "")
                elif m.get("type") == "interactive":
                    inter = m["interactive"]
                    text = (inter.get("button_reply") or inter.get("list_reply") or {}).get("title", "")
                else:
                    text = f"[{m.get('type')} tidak didukung]"
                out.append({"from": m["from"], "id": m["id"], "text": text, "name": names.get(m["from"])})
    return out


def _post(payload: dict) -> tuple[bool, str | None, str | None]:
    url = f"https://graph.facebook.com/{settings.wa_graph_version}/{settings.wa_phone_number_id}/messages"
    try:
        resp = httpx.post(url, json=payload, timeout=10,
                          headers={"Authorization": f"Bearer {settings.wa_access_token}"})
    except httpx.HTTPError as exc:
        log.error("Kirim WA gagal: %s", exc)
        return False, None, str(exc)
    if resp.status_code >= 300:
        log.error("Kirim WA ditolak %s: %s", resp.status_code, resp.text[:300])
        return False, None, resp.text[:300]
    data = resp.json()
    return True, (data.get("messages") or [{}])[0].get("id"), None


def send_text(to: str, text: str) -> tuple[bool, str | None, str | None]:
    if not settings.meta_enabled:
        return False, None, "WhatsApp belum dikonfigurasi"
    return _post({"messaging_product": "whatsapp", "to": to, "type": "text",
                  "text": {"preview_url": False, "body": text[:4096]}})


def send_template(to: str, template: str, params: list[str]) -> tuple[bool, str | None, str | None]:
    if not settings.meta_enabled:
        return False, None, "WhatsApp belum dikonfigurasi"
    return _post({
        "messaging_product": "whatsapp", "to": to, "type": "template",
        "template": {"name": template, "language": {"code": "id"},
                     "components": [{"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}]},
    })
