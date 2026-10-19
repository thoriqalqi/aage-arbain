import os
import sys
import tempfile
from pathlib import Path

import pytest

_DB = Path(tempfile.gettempdir()) / f"aage-test-{os.getpid()}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB.as_posix()}"
os.environ["GEMINI_API_KEY"] = ""
os.environ["WA_ACCESS_TOKEN"] = ""
os.environ["WA_APP_SECRET"] = "rahasia-uji"
os.environ["AGENT_MODE"] = "simulasi"
os.environ["FONNTE_TOKEN"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(scope="session")
def seeded():
    from aage.db import SessionLocal, init_db
    from aage.seed import seed_base

    init_db(drop=True)
    with SessionLocal() as db:
        seed_base(db)
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
