# Uji Live lewat Telegram

Telegram dipakai sebagai jalur uji live selama WhatsApp Business belum tersedia. AI, ClaimGuard, ambil alih staf,
approval, dan Ledger **sama persis** dengan WhatsApp; yang berbeda hanya adapter kanalnya.

```
Telegram ─┐                                   ┌─ channels/telegram.py  (sekarang)
WhatsApp ─┼─► InboundMessage ─► handle_inbound ─► graf AI ─► sender ─► registry ─┼─ channels/registry.py WhatsAppAdapter (WATI/Meta, ditunda)
Web chat ─┘   (channel, external_user_id)                                         └─ WebchatAdapter (simulator)
```

Pelanggan diidentifikasi **(channel, external_user_id)**: nomor WA untuk WhatsApp, chat id untuk Telegram, ID sesi untuk
web chat. Orang yang sama di Telegram dan WhatsApp = dua kontak (belum digabung).

## 1. Buat bot (sekali)
1. Di Telegram, buka **@BotFather** → kirim `/newbot` → beri nama, mis. `Arbain Sales Uji` → username, mis. `arbain_uji_bot`.
2. Salin token yang diberikan. **Jangan bagikan di chat**; token = kunci penuh bot.

## 2. Isi `apps/api/.env`
```
TELEGRAM_BOT_TOKEN=<token dari BotFather>
TELEGRAM_WEBHOOK_SECRET=<string acak>
TELEGRAM_ALLOWLIST=
```
Buat string acak:
```bash
apps/api/.venv/Scripts/python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## 3. Batasi ke HP uji (allowlist)
1. Dari Telegram Anda, kirim pesan apa saja ke bot (mis. `halo`).
2. Jalankan (dari `apps/api`):
   ```bash
   .venv/Scripts/python scripts/telegram_bot.py chat-id
   ```
3. Salin angka yang muncul ke `TELEGRAM_ALLOWLIST=` (pisahkan koma bila lebih dari satu HP). Chat lain diabaikan & dicatat di log.

## 4. Jalankan API + tunnel publik
Telegram butuh URL **HTTPS publik** untuk mengirim webhook ke laptop.
1. Jalankan API seperti biasa (port 8000) — restart setelah mengubah `.env`.
2. Buka tunnel (cloudflared sudah terpasang di laptop ini; gratis, tanpa akun):
   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```
   ```bash
   ngrok http 8000
   ```
3. Pasang webhook dengan URL yang muncul (mis. `https://abcd.trycloudflare.com`):
   ```bash
   .venv/Scripts/python scripts/telegram_bot.py set-webhook https://abcd.trycloudflare.com
   ```
4. Cek: `.venv/Scripts/python scripts/telegram_bot.py info` → webhook terpasang, tanpa error.

URL `trycloudflare` berubah setiap tunnel dibuka ulang → ulangi langkah 3.

## 5. Uji
- Chat ke bot memakai daftar pertanyaan di [`UJI_AI_SALES.md`](UJI_AI_SALES.md) bagian A–E. Bot menampilkan "sedang
  mengetik…" selama AI menyusun jawaban (DeepSeek gratis bisa 5–10 detik).
- Buka **Inbox** di dashboard → percakapan muncul dengan ikon Telegram. Bagian F (Ambil alih, Saran AI, balasan staf,
  Kembalikan ke AI) berjalan sama; balasan staf terkirim ke Telegram Anda.
- Semua kiriman tercatat di Ledger dengan `kanal: telegram`.

## Perbedaan dengan WhatsApp (sengaja)
| | Telegram | WhatsApp |
|---|---|---|
| Identitas | chat id (tanpa nomor HP) | nomor WA |
| Batas balas 24 jam | tidak ada (peringatan jendela tidak muncul) | ada, di luar itu wajib template |
| Tautan otomatis ke Leads | **tidak** (nomor HP tidak diketahui) | ya, bila nomor cocok |
| Format teks | polos — tanda `*` tampil apa adanya | `*tebal*` |
| Foto/stiker/suara | dibalas "[photo tidak didukung]" lalu diteruskan sesuai alur | sama |
| Grup | diabaikan, hanya chat privat | — |

## Pindah ke WhatsApp nanti
Isi `WATI_API_KEY`, `WATI_WEBHOOK_TOKEN`, `WATI_ALLOWLIST` lalu daftarkan webhook WATI. Tidak ada perubahan pada
logika AI, ClaimGuard, inbox, atau database. Adapter WhatsApp (WATI v3) sudah ada dan teruji dengan mock, belum diuji live.

## Keamanan
- Webhook ditolak tanpa header secret yang benar (wajib di luar `ENV=dev`).
- Token bot tidak pernah ditulis ke log / pesan error (token ada di URL API Telegram).
- Selesai uji: `scripts/telegram_bot.py hapus-webhook`, tutup tunnel.
