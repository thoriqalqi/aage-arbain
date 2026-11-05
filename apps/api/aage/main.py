"""Aplikasi FastAPI AAGE. Jalankan: uvicorn aage.main:app --reload"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings, sumber_database
from .db import DatabaseOnlineError, init_db
from .agents_api import router as agents_router
from .compliance_api import router as compliance_router
from .routes import router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("aage")
settings = get_settings()


def pastikan_sumber_data() -> None:
    """Satu sumber data: agent menjawab dari database online, tidak pernah diam-diam dari aage.db."""
    sumber = sumber_database(settings.database_url)
    log.info("Database aktif: jenis=%s host=%s nama=%s", sumber["jenis"], sumber["host"], sumber["nama"])
    if sumber["jenis"] != "online" and not settings.izinkan_db_lokal:
        raise DatabaseOnlineError(
            f"API menolak start: DATABASE_URL mengarah ke database {sumber['jenis']} ({sumber['nama']}), bukan database online. "
            "Isi DATABASE_URL dengan alamat Supabase. Untuk pengembangan lokal saja, pasang IZINKAN_DB_LOKAL=true.")


@asynccontextmanager
async def lifespan(_: FastAPI):
    pastikan_sumber_data()
    init_db()
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan,
              description="Agen penjualan & pemasaran AI CV Arba'in dengan ClaimGuard dan Evidence-to-Action Ledger.")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(agents_router)
app.include_router(compliance_router)


@app.get("/health")
def health():
    return {"ok": True}
