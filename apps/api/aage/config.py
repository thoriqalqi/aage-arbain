"""Konfigurasi aplikasi. Semua secret dibaca dari environment variable (.env), tidak pernah dari repo."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    llm_fallback_models: str = "gemini/gemini-2.0-flash"
    embedding_model: str = "gemini/gemini-embedding-001"
    embedding_dim: int = 384
    llm_timeout_s: float = 8.0
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

    # Fonnte (gateway WhatsApp lokal) untuk kirim invoice yang disetujui staf
    fonnte_token: str = ""

    # Multi-agent CrewAI (src/agents_crew.py)
    agent_model: str = "anthropic/claude-sonnet-5-5"
    anthropic_api_key: str = ""
    agent_mode: str = "auto"  # auto | llm | simulasi

    # Prospect Mapper
    google_places_api_key: str = ""
    prospect_allow_network: bool = True
    gudang_nama: str = "Gudang contoh — Semarang"
    gudang_lat: float = -6.9932
    gudang_lng: float = 110.4203

    # CORS untuk dashboard
    cors_origins: str = "http://localhost:3000"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def wa_enabled(self) -> bool:
        return bool(self.wa_access_token and self.wa_phone_number_id)


@lru_cache
def get_settings() -> Settings:
    return Settings()
