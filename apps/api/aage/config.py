"""Konfigurasi aplikasi. Semua secret dibaca dari environment variable (.env), tidak pernah dari repo."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

_HOST_LOKAL = {"localhost", "127.0.0.1", "::1", "db"}  # "db" = layanan Postgres di docker compose


def adalah_online(url: str) -> bool:
    """Postgres di luar mesin ini (mis. Supabase): data sungguhan yang tidak boleh terhapus oleh seed, tes, atau eval."""
    u = make_url(url)
    return u.get_backend_name() == "postgresql" and (u.host or "localhost") not in _HOST_LOKAL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AAGE — Arba'in Autonomous Growth Engine"
    env: str = "dev"

    # Database: Postgres 16 + pgvector di produksi; SQLite untuk dev lokal tanpa Docker.
    database_url: str = "sqlite:///./aage.db"

    # Auth
    jwt_secret: str = "dev-saja-ganti-JWT_SECRET-di-env-min-32-karakter"
    jwt_expire_minutes: int = 60 * 12

    # LLM gateway (LiteLLM). Kosongkan GEMINI_API_KEY untuk mode offline deterministik.
    gemini_api_key: str = ""
    llm_model: str = "gemini/gemini-2.5-flash"
    llm_judge_model: str = "gemini/gemini-2.5-pro"
    llm_fallback_models: str = ""  # opsional, dipisah koma; kosong = tidak ada fallback diam-diam ke model lain
    embedding_model: str = "gemini/gemini-embedding-001"
    embedding_dim: int = 384
    llm_timeout_s: float = 8.0

    # Provider: "gemini" (REST Gemini) | "openai_compat" (endpoint /chat/completions, mis. TokenHarbor) |
    # kosong = otomatis (openai_compat bila LLM_API_KEY + LLM_BASE_URL terisi, selain itu gemini).
    llm_provider_name: str = ""
    llm_base_url: str = ""  # mis. https://tokenharbor.ai/v1
    llm_api_key: str = ""
    # False = Gemini Flash diminta tidak "berpikir" (thinkingBudget 0), agar token tidak habis untuk reasoning.
    llm_reasoning: bool = False
    # True = balasan jualan biasa ditulis ulang LLM agar lebih luwes (dengan kunci fakta); False = template apa adanya.
    llm_gaya: bool = True
    memori_retensi_hari: int = 30  # memori ringkasan percakapan dihapus setelah sekian hari tanpa aktivitas
    # Harga per 1 juta token (USD) untuk menghitung biaya & budget cap. Sesuaikan dengan harga model yang dipakai.
    llm_price_in_usd_per_m: float = 0.30
    llm_price_out_usd_per_m: float = 2.50
    budget_daily_rp: float = 25_000
    budget_monthly_rp: float = 500_000
    usd_to_idr: float = 16_300

    # Observability (opsional)
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = ""

    # WhatsApp Cloud API (nomor uji Meta)
    wa_verify_token: str = "aage-verify"
    wa_app_secret: str = ""
    wa_access_token: str = ""
    wa_phone_number_id: str = ""
    wa_graph_version: str = "v21.0"
    wa_reminder_template: str = ""
    ambil_alih_jam: float = 4.0  # percakapan yang diambil alih staf kembali ke AI setelah sekian jam tanpa aktivitas staf

    # Penyedia WhatsApp: "meta" | "wati" | kosong = otomatis (wati bila WATI_API_KEY terisi, selain itu meta)
    wa_provider: str = ""

    # WATI API v3 (https://docs.wati.io). Key dikirim sebagai Bearer token, tidak pernah dicetak ke log.
    wati_api_key: str = ""
    wati_base_url: str = "https://live-mt-server.wati.io/api/ext/v3"
    wati_webhook_token: str = ""  # wajib di luar env=dev; webhook: /api/webhook/wati?token=...
    wati_channel_number: str = ""  # opsional, untuk akun multi-nomor: target "Channel:PhoneNumber"
    wati_allowlist: str = ""  # nomor uji dipisah koma; bila terisi, HANYA nomor ini yang benar-benar dikirimi

    # Telegram Bot API — jalur uji live sebelum WhatsApp. Token dari @BotFather, tidak pernah dicetak ke log.
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""  # wajib di luar env=dev; dikirim Telegram di header X-Telegram-Bot-Api-Secret-Token
    telegram_allowlist: str = ""  # chat id dipisah koma; bila terisi, HANYA chat ini yang diproses & dibalas

    # Fonnte (gateway WhatsApp lokal) untuk kirim invoice yang disetujui staf
    fonnte_token: str = ""

    # Multi-agent CrewAI (src/agents_crew.py)
    agent_model: str = "anthropic/claude-sonnet-5-5"
    anthropic_api_key: str = ""
    agent_mode: str = "auto"  # auto | llm | simulasi

    # ClaimGuard & Compliance Check (src/compliance/claim_guard.py). Versi aturan ada di config/claimguard_registry.json.
    claimguard_model: str = "claude-sonnet-5-5"  # model Anthropic untuk analisis konteks (Tahap B)
    claimguard_max_text_length: int = 12_000
    claimguard_llm_timeout_s: float = 30.0
    claimguard_llm_failure_status: str = "ERROR"  # ERROR | NEED_REVIEW bila LLM tidak tersedia/gagal; tidak pernah ALLOWED

    # Prospek: Live Lead Scouting (OpenStreetMap Overpass, tanpa API key) + Opportunity Score
    serper_api_key: str = ""  # Live AI Search Audit (google.serper.dev); kosong = tidak terhubung
    overpass_urls: str = "https://overpass-api.de/api/interpreter,https://overpass.private.coffee/api/interpreter"
    overpass_timeout_s: float = 25.0
    prospek_max_results: int = 100
    gudang_nama: str = "Pusat Logistik CV Arba'in — Semarang"
    gudang_lat: float = -6.9932
    gudang_lng: float = 110.4203
    skor_zona_emas_min_km: float = 2.0
    skor_zona_emas_max_km: float = 8.0
    skor_jarak_nol_km: float = 30.0  # di atas jarak ini Geographic Fit = 0
    skor_geo_di_gudang: float = 35.0  # nilai Geographic Fit pada jarak 0 km (naik linear ke 70 di 2 km)

    # CORS untuk dashboard
    cors_origins: str = "http://localhost:3000"

    @property
    def llm_enabled(self) -> bool:
        if self.llm_provider == "openai_compat":
            return bool(self.llm_api_key and self.llm_base_url)
        return bool(self.gemini_api_key)

    @property
    def llm_provider(self) -> str:
        name = self.llm_provider_name.strip().lower()
        if name in ("gemini", "openai_compat"):
            return name
        return "openai_compat" if self.llm_api_key and self.llm_base_url else "gemini"

    @property
    def meta_enabled(self) -> bool:
        return bool(self.wa_access_token and self.wa_phone_number_id)

    @property
    def wati_enabled(self) -> bool:
        return bool(self.wati_api_key)

    @property
    def wa_channel(self) -> str:
        provider = self.wa_provider.strip().lower()
        if provider in ("meta", "wati"):
            return provider
        return "wati" if self.wati_enabled else "meta"

    @property
    def wa_enabled(self) -> bool:
        return self.wati_enabled if self.wa_channel == "wati" else self.meta_enabled


@lru_cache
def get_settings() -> Settings:
    return Settings()
