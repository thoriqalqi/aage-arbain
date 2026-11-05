import os
import sys
import tempfile
from pathlib import Path

import pytest

_DB = Path(tempfile.gettempdir()) / f"aage-test-{os.getpid()}.db"
# AAGE_TES_DATABASE_URL opsional: menjalankan tes di Postgres lokal. Isi database itu dihapus, jadi yang online ditolak.
_URL_TES = os.environ.get("AAGE_TES_DATABASE_URL") or f"sqlite:///{_DB.as_posix()}"
os.environ["DATABASE_URL"] = _URL_TES
os.environ["GEMINI_API_KEY"] = ""
os.environ["LLM_MODEL"] = "gemini/model-tes"
os.environ["LLM_API_KEY"] = ""  # tes tidak memakai kuota LLM sungguhan (provider mana pun)
os.environ["LLM_PROVIDER_NAME"] = ""
os.environ["WA_ACCESS_TOKEN"] = ""
os.environ["WA_APP_SECRET"] = "rahasia-uji"
os.environ["AGENT_MODE"] = "simulasi"
os.environ["FONNTE_TOKEN"] = ""
os.environ["WATI_API_KEY"] = ""
os.environ["WATI_WEBHOOK_TOKEN"] = "token-uji"
os.environ["WATI_ALLOWLIST"] = ""
os.environ["WA_PROVIDER"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aage.config import adalah_online  # noqa: E402

if adalah_online(_URL_TES):
    pytest.exit("AAGE_TES_DATABASE_URL mengarah ke database online; tes menghapus isi database.", returncode=2)


@pytest.fixture(scope="session")
def seeded():
    from aage import settings_store
    from aage.db import SessionLocal, init_db
    from aage.seed import seed_base

    init_db(drop=True)
    with SessionLocal() as db:
        seed_base(db)
        # Katalog seed berisi data simulasi, jadi tes lama berjalan di mode demo. test_verifikasi_fakta menguji produksi.
        settings_store.pasang_mode_data(db, "demo")
    return True


@pytest.fixture
def db(seeded):
    from aage.db import SessionLocal

    with SessionLocal() as s:
        yield s


@pytest.fixture
def client(seeded):
    from fastapi.testclient import TestClient

    from aage.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth(client):
    r = client.post("/api/auth/login", json={"email": "staf@aage.local", "password": "staf123"})
    return {"Authorization": f"Bearer {r.json()['token']}"}
