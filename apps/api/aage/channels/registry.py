"""Daftar adapter kanal. Menambah kanal baru = menulis adapter + mendaftarkannya di ADAPTERS."""

from ..config import get_settings
from . import telegram, wati, whatsapp
from .base import GAGAL, SIMULASI, TERKIRIM, ChannelAdapter, SendResult

settings = get_settings()
BELUM_DIKONFIGURASI = "WhatsApp belum dikonfigurasi"


class WhatsAppAdapter:
    """Membungkus penyedia WhatsApp yang ada (WATI v3 / Meta Cloud API). Uji live WATI ditunda; adapter ini menjaga
    perilaku lama tetap jalan. Modul penyedia dipanggil saat kirim (bukan diimpor fungsinya) agar bisa di-stub eval."""

    name, label, reply_window_h = "whatsapp", "WhatsApp", 24.0

    def _provider(self):
        return wati if settings.wa_channel == "wati" else whatsapp

    def enabled(self) -> bool:
        return settings.wa_enabled

    def _result(self, ok: bool, msg_id: str | None, err: str | None) -> SendResult:
        if ok:
            return SendResult(TERKIRIM, msg_id)
        simulated = err == BELUM_DIKONFIGURASI or (err or "").startswith(wati.SIMULASI_PREFIX)
        return SendResult(SIMULASI if simulated else GAGAL, msg_id, err)

    def send_text(self, external_user_id: str, text: str) -> SendResult:
        return self._result(*self._provider().send_text(external_user_id, text))

    def send_template(self, external_user_id: str, template: str, params: list[str], fallback_text: str) -> SendResult:
        return self._result(*self._provider().send_template(external_user_id, template, params))

    def typing(self, external_user_id: str) -> None:
        return None


class WebchatAdapter:
    """Simulator di dashboard: pesan keluar cukup tersimpan di DB, dibaca lewat polling."""

    name, label, reply_window_h = "webchat", "Web chat", None

    def enabled(self) -> bool:
        return True

    def send_text(self, external_user_id: str, text: str) -> SendResult:
        return SendResult(TERKIRIM)

    def send_template(self, external_user_id: str, template: str, params: list[str], fallback_text: str) -> SendResult:
        return SendResult(TERKIRIM)

    def typing(self, external_user_id: str) -> None:
        return None


ADAPTERS: dict[str, ChannelAdapter] = {a.name: a for a in (WhatsAppAdapter(), telegram.TelegramAdapter(), WebchatAdapter())}


def get(channel: str) -> ChannelAdapter:
    try:
        return ADAPTERS[channel]
    except KeyError:
        raise ValueError(f"Kanal tidak dikenal: {channel}") from None


def status() -> dict:
    return {a.name: {"label": a.label, "aktif": a.enabled(), "jendela_balas_jam": a.reply_window_h}
            for a in ADAPTERS.values()}
