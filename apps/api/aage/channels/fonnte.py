"""Fonnte (gateway WhatsApp) — dipakai untuk mengirim invoice yang sudah disetujui staf."""

import logging

import httpx

from ..config import get_settings

log = logging.getLogger("aage.fonnte")
settings = get_settings()


def send(target: str, message: str) -> tuple[str, str | None]:
    """Kembalikan (status, detail). Tanpa FONNTE_TOKEN → 'simulasi' (tidak ada pesan nyata yang terkirim)."""
    if not settings.fonnte_token:
        return "simulasi", "FONNTE_TOKEN belum diisi — pesan tidak dikirim (mode simulasi)"
    try:
        resp = httpx.post("https://api.fonnte.com/send", headers={"Authorization": settings.fonnte_token},
                          data={"target": target, "message": message, "countryCode": "62"}, timeout=15)
    except httpx.HTTPError as exc:
        log.error("Fonnte gagal: %s", exc)
        return "gagal", str(exc)
    try:
        body = resp.json()
    except ValueError:
        body = {"status": False, "reason": resp.text[:200]}
    if resp.status_code < 300 and body.get("status") is True:
        return "terkirim", str(body.get("id") or body.get("detail") or "")
    return "gagal", str(body.get("reason") or body)[:300]
