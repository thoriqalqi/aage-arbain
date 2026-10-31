"""Aplikasi FastAPI AAGE. Jalankan: uvicorn aage.main:app --reload"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import init_db
from .agents_api import router as agents_router
from .compliance_api import router as compliance_router
from .routes import router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
settings = get_settings()



@asynccontextmanager
async def lifespan(_: FastAPI):
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
