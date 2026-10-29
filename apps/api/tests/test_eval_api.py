"""Endpoint agen Evaluation — proses eval dipalsukan (tidak menjalankan dataset sungguhan di tes)."""

import json
import subprocess

import pytest

from aage import eval_api
from aage.models import LedgerEvent

HASIL = {"mode": "offline (deterministik)", "qa": {"n": 10, "akurasi": 100.0, "groundedness": 100.0},
         "klaim": {"n": 5, "recall": 95.0, "precision": 90.0, "diblokir_lolos": 0},
         "eskalasi": {"n": 3, "ketepatan": 100.0}, "operasional": {"latensi_p95_ms": 40.0}}


@pytest.fixture
def admin(client):
    r = client.post("/api/auth/login", json={"email": "admin@aage.local", "password": "admin123"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def fake_eval(tmp_path, monkeypatch):
    result = tmp_path / "hasil.json"
    monkeypatch.setattr(eval_api, "RESULT", result)
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        result.write_text(json.dumps(HASIL), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "ok", "")

    class SyncThread:
        def __init__(self, target, args=(), daemon=None):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(eval_api.subprocess, "run", fake_run)
    monkeypatch.setattr(eval_api.threading, "Thread", SyncThread)
    return calls


def test_summary_without_results(client, auth, fake_eval):
    r = client.get("/api/eval/summary", headers=auth).json()
    assert r["ada"] is False and r["berjalan"] is False


def test_run_requires_admin(client, auth, fake_eval):
    assert client.post("/api/eval/run", headers=auth).status_code == 403


def test_run_records_ledger_and_updates_summary(client, admin, db, fake_eval):
    assert client.post("/api/eval/run", headers=admin).status_code == 200
    assert fake_eval and "--offline" in fake_eval[0]
    s = client.get("/api/eval/summary", headers=admin).json()
    assert s["ada"] and s["hasil"]["klaim"]["recall"] == 95.0 and not s["berjalan"]
    done = db.query(LedgerEvent).filter(LedgerEvent.tipe_event == "evaluasi_selesai").order_by(LedgerEvent.id.desc()).first()
    assert done.outcome == "selesai" and "recall 95.0%" in done.ringkasan
    status = {a["id"]: a for a in client.get("/api/agents/status", headers=admin).json()["agen"]}
    assert status["evaluation"]["tugas"] >= 2 and status["evaluation"]["status"] == "bekerja"


def test_failed_run_is_reported(client, admin, monkeypatch, fake_eval):
    monkeypatch.setattr(eval_api.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "Traceback\nValueError: rusak"))
    client.post("/api/eval/run", headers=admin)
    s = client.get("/api/eval/summary", headers=admin).json()
    assert "rusak" in s["error"] and not s["berjalan"]
