"""Alat bantu bot Telegram untuk uji live. Membaca TELEGRAM_* dari .env; token tidak pernah dicetak.

    python scripts/telegram_bot.py info                         # nama bot + status webhook
    python scripts/telegram_bot.py chat-id                      # chat id pengirim terakhir (webhook harus dihapus dulu)
    python scripts/telegram_bot.py set-webhook https://xxxx.trycloudflare.com
    python scripts/telegram_bot.py hapus-webhook
"""

import argparse
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aage.config import get_settings  # noqa: E402

settings = get_settings()


def call(method: str, body: dict | None = None) -> dict:
    try:
        resp = httpx.post(f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}", json=body or {}, timeout=15)
    except httpx.HTTPError as exc:
        sys.exit(f"Gagal menghubungi Telegram ({type(exc).__name__}).")
    data = resp.json()
    if not data.get("ok"):
        sys.exit(f"Telegram menolak {method}: {data.get('description')}")
    return data["result"]


def info(_):
    me = call("getMe")
    wh = call("getWebhookInfo")
    print(f"Bot      : @{me['username']} ({me['first_name']})")
    print(f"Webhook  : {wh.get('url') or '(belum dipasang)'}")
    print(f"Antre    : {wh.get('pending_update_count', 0)} update")
    if wh.get("last_error_message"):
        print(f"Error terakhir: {wh['last_error_message']}")
    print(f"Allowlist: {settings.telegram_allowlist or '(kosong — semua chat privat diproses)'}")


def chat_id(_):
    if call("getWebhookInfo").get("url"):
        sys.exit("Webhook masih terpasang; getUpdates tidak bisa dipakai. Jalankan 'hapus-webhook' dulu.")
    seen = {}
    for u in call("getUpdates", {"allowed_updates": ["message"]}):
        chat = (u.get("message") or {}).get("chat") or {}
        if chat.get("type") == "private":
            seen[chat["id"]] = " ".join(p for p in (chat.get("first_name"), chat.get("last_name")) if p) or chat.get("username")
    if not seen:
        sys.exit("Belum ada pesan. Kirim pesan apa saja ke bot dari Telegram Anda, lalu jalankan lagi.")
    for cid, nama in seen.items():
        print(f"{cid}\t{nama}")
    print("\nTulis ke .env: TELEGRAM_ALLOWLIST=" + ",".join(str(c) for c in seen))


def set_webhook(args):
    if not settings.telegram_webhook_secret:
        sys.exit("Isi TELEGRAM_WEBHOOK_SECRET di .env dulu (string acak, huruf/angka/_/-).")
    url = args.url.rstrip("/") + "/api/webhook/telegram"
    if not url.startswith("https://"):
        sys.exit("Telegram hanya menerima webhook HTTPS.")
    # max_connections=1: pesan dari pembeli diproses berurutan (percakapan & SQLite tidak saling balapan).
    call("setWebhook", {"url": url, "secret_token": settings.telegram_webhook_secret, "allowed_updates": ["message"],
                        "max_connections": 1, "drop_pending_updates": True})
    print(f"Webhook terpasang: {url}")


def hapus_webhook(_):
    call("deleteWebhook", {"drop_pending_updates": False})
    print("Webhook dihapus.")


def main():
    if not settings.telegram_bot_token:
        sys.exit("TELEGRAM_BOT_TOKEN belum diisi di apps/api/.env")
    p = argparse.ArgumentParser(description="Alat bantu bot Telegram AAGE")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info").set_defaults(fn=info)
    sub.add_parser("chat-id").set_defaults(fn=chat_id)
    s = sub.add_parser("set-webhook")
    s.add_argument("url", help="URL publik HTTPS yang mengarah ke API (tanpa /api/webhook/telegram)")
    s.set_defaults(fn=set_webhook)
    sub.add_parser("hapus-webhook").set_defaults(fn=hapus_webhook)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
