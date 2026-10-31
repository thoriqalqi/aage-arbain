"""Kontrak netral kanal. Logika AI, ambil alih staf, dan database hanya mengenal tipe di sini — tidak pernah
Telegram, WATI, atau Meta secara langsung.

Identitas pelanggan = (channel, external_user_id):
- whatsapp: nomor WA (digit saja)
- telegram: chat id privat
- webchat : ID sesi simulator
"""

from dataclasses import dataclass
from typing import Protocol

TERKIRIM, SIMULASI, GAGAL = "terkirim", "simulasi", "gagal"
# Teks netral untuk pesan "bagikan kontak" (Telegram): nomornya dibawa di InboundMessage.telepon.
TEKS_NOMOR_DIBAGIKAN = "[nomor dibagikan]"


@dataclass
class InboundMessage:
    """Pesan pembeli yang sudah dinormalisasi adapter."""

    channel: str
    external_user_id: str
    external_message_id: str  # unik lintas kanal (berawalan nama kanal) → dedup webhook yang dikirim ulang
    text: str
    nama: str | None = None  # nama profil di kanal
    telepon: str | None = None  # nomor telepon bila kanal memberikannya (WhatsApp selalu; Telegram tidak)


@dataclass
class SendResult:
    status: str  # terkirim | simulasi | gagal
    external_message_id: str | None = None
    error: str | None = None


class ChannelAdapter(Protocol):
    name: str  # kunci kanal yang disimpan di DB
    label: str  # nama untuk dashboard
    reply_window_h: float | None  # batas balas teks bebas sejak pesan terakhir pembeli (WhatsApp 24 jam); None = tanpa batas

    def enabled(self) -> bool: ...

    def send_text(self, external_user_id: str, text: str, *, minta_nomor: bool = False) -> SendResult:
        """minta_nomor: tampilkan tombol "Bagikan nomor HP" bila kanal mendukung (Telegram); kanal lain abaikan."""
        ...

    def send_template(self, external_user_id: str, template: str, params: list[str], fallback_text: str) -> SendResult:
        """Kanal tanpa template cukup mengirim fallback_text."""
        ...

    def typing(self, external_user_id: str) -> None:
        """Penanda 'sedang mengetik' selama AI menyusun jawaban. Boleh no-op."""
        ...
