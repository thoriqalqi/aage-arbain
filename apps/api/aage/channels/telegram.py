"""Telegram Bot API: parsing webhook update dan pengiriman teks. Dipakai sebagai jalur uji live sebelum WhatsApp.

Dokumentasi: https://core.telegram.org/bots/api
- Webhook: setWebhook(url, secret_token) → Telegram mengirim header X-Telegram-Bot-Api-Secret-Token pada setiap update.
  Telegram mengulang update bila tidak dapat 2xx, jadi pemrosesan idempoten (dedup per id pesan).
- Kirim: POST /bot<TOKEN>/sendMessage {chat_id, text}. Teks polos (tanpa parse_mode) agar tanda * dari draf tidak
  ditafsirkan sebagai Markdown.
- Rate limit: HTTP 429 dengan parameters.retry_after.

Token bot ada di URL API, jadi URL dan pesan exception httpx tidak pernah ditulis ke log atau pesan error.
"""

import logging
import time

import httpx

from ..config import get_settings
from .base import GAGAL, SIMULASI, TEKS_NOMOR_DIBAGIKAN, TERKIRIM, InboundMessage, SendResult

log = logging.getLogger("aage.telegram")
settings = get_settings()

CHANNEL = "telegram"
API = "https://api.telegram.org"
MAX_ATTEMPTS = 3
MAX_RETRY_AFTER_S = 10.0
_MEDIA = ("photo", "document", "voice", "audio", "video", "video_note", "sticker", "location", "contact")
_SAPAAN = {"/start", "/help"}


def _allowlist() -> set[str]:
    return {c.strip() for c in settings.telegram_allowlist.split(",") if c.strip()}


def allowed(chat_id: str) -> bool:
    allow = _allowlist()
    return not allow or chat_id in allow


def parse_update(update: dict) -> InboundMessage | None:
    """Ambil pesan pembeli dari update Telegram. None bila bukan pesan teks dari chat privat yang diizinkan."""
    msg = update.get("message")  # edited_message, callback_query, dsb. diabaikan
    if not isinstance(msg, dict):
        return None
    chat, sender = msg.get("chat") or {}, msg.get("from") or {}
    if chat.get("type") != "private" or sender.get("is_bot") or "id" not in chat or "message_id" not in msg:
        return None
    chat_id = str(chat["id"])
    if not allowed(chat_id):
        log.warning("Pesan Telegram dari chat %s diabaikan: tidak ada di TELEGRAM_ALLOWLIST", chat_id)
        return None
    nama = " ".join(p for p in (sender.get("first_name"), sender.get("last_name")) if p) or sender.get("username")
    kontak = msg.get("contact")
    if isinstance(kontak, dict):
        # Hanya nomor MILIK pengirim sendiri yang dipakai (tombol "Bagikan nomor HP"). Kontak orang lain diabaikan,
        # agar tidak ada yang bisa membuka riwayat pesanan pembeli lain dengan meneruskan kartu kontaknya.
        milik_sendiri = sender.get("id") is not None and kontak.get("user_id") == sender["id"]
        if milik_sendiri and kontak.get("phone_number"):
            return InboundMessage(channel=CHANNEL, external_user_id=chat_id, text=TEKS_NOMOR_DIBAGIKAN, nama=nama,
                                  external_message_id=f"tg:{chat_id}:{msg['message_id']}",
                                  telepon="".join(ch for ch in str(kontak["phone_number"]) if ch.isdigit()))
        return InboundMessage(channel=CHANNEL, external_user_id=chat_id, text="[contact tidak didukung]", nama=nama,
                              external_message_id=f"tg:{chat_id}:{msg['message_id']}")
    text = (msg.get("text") or msg.get("caption") or "").strip()
    if not text:
        kind = next((k for k in _MEDIA if k in msg), None)
        if kind is None:
            return None
        text = f"[{kind} tidak didukung]"
    if text.split(maxsplit=1)[0].split("@")[0].lower() in _SAPAAN:
        text = "Halo"  # perintah bawaan Telegram saat pembeli pertama kali membuka bot
    return InboundMessage(channel=CHANNEL, external_user_id=chat_id, external_message_id=f"tg:{chat_id}:{msg['message_id']}",
                          text=text, nama=nama)


def _call(method: str, body: dict, timeout: float = 10) -> httpx.Response:
    return httpx.post(f"{API}/bot{settings.telegram_bot_token}/{method}", json=body, timeout=timeout)


def _retry_after(resp: httpx.Response) -> float:
    try:
        return min(float(resp.json().get("parameters", {}).get("retry_after", 1)), MAX_RETRY_AFTER_S)
    except (ValueError, AttributeError):
        return 1.0


def _description(resp: httpx.Response) -> str:
    try:
        return str(resp.json().get("description") or "")[:300]
    except ValueError:
        return resp.text[:300]


class TelegramAdapter:
    name, label, reply_window_h = CHANNEL, "Telegram", None

    def enabled(self) -> bool:
        return bool(settings.telegram_bot_token)

    def send_text(self, external_user_id: str, text: str, *, minta_nomor: bool = False) -> SendResult:
        if not self.enabled():
            return SendResult(SIMULASI, error="Telegram belum dikonfigurasi")
        if not allowed(external_user_id):
            return SendResult(SIMULASI, error="simulasi: chat di luar TELEGRAM_ALLOWLIST, tidak dikirim")
        body = {"chat_id": external_user_id, "text": text[:4096], "disable_web_page_preview": True}
        if minta_nomor:
            body["reply_markup"] = {"keyboard": [[{"text": "📱 Bagikan nomor HP", "request_contact": True}]],
                                    "one_time_keyboard": True, "resize_keyboard": True}
        for attempt in range(MAX_ATTEMPTS):
            try:
                resp = _call("sendMessage", body)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                # Permintaan belum sampai ke Telegram → aman diulang tanpa risiko pesan ganda.
                if attempt + 1 < MAX_ATTEMPTS:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                log.error("Kirim Telegram gagal (koneksi): %s", type(exc).__name__)
                return SendResult(GAGAL, error=f"Koneksi ke Telegram gagal ({type(exc).__name__})")
            except httpx.HTTPError as exc:
                log.error("Kirim Telegram gagal: %s", type(exc).__name__)
                return SendResult(GAGAL, error=f"Kirim Telegram gagal ({type(exc).__name__})")
            if resp.status_code == 429 and attempt + 1 < MAX_ATTEMPTS:
                delay = _retry_after(resp)
                log.warning("Telegram rate limit (429), coba lagi dalam %.1fs", delay)
                time.sleep(delay)
                continue
            if resp.status_code >= 300:
                detail = _description(resp)
                log.error("Kirim Telegram ditolak %s: %s", resp.status_code, detail)
                return SendResult(GAGAL, error=f"Telegram {resp.status_code}: {detail}")
            try:
                msg_id = (resp.json().get("result") or {}).get("message_id")
            except ValueError:
                msg_id = None
            return SendResult(TERKIRIM, f"tg:{external_user_id}:{msg_id}" if msg_id else None)
        return SendResult(GAGAL, error="Telegram rate limit (429) setelah beberapa percobaan")

    def send_template(self, external_user_id: str, template: str, params: list[str], fallback_text: str) -> SendResult:
        return self.send_text(external_user_id, fallback_text)  # Telegram tidak punya template/jendela 24 jam

    def typing(self, external_user_id: str) -> None:
        if not self.enabled() or not allowed(external_user_id):
            return
        try:
            _call("sendChatAction", {"chat_id": external_user_id, "action": "typing"}, timeout=5)
        except httpx.HTTPError:
            pass  # penanda mengetik hanya kosmetik
