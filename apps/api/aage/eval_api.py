"""Agen Evaluation (Brief §9): hasil uji terakhir + jalankan ulang dari dashboard.

Evaluasi berjalan sebagai proses terpisah (`python -m eval.run`) di database sementara, jadi data produksi tidak
tersentuh. Mulai & selesai dicatat di Ledger sehingga meja Evaluation di kantor Agen ikut bergerak.

- GET  /api/eval/summary   hasil terakhir (eval/hasil/hasil.json) + status proses
- POST /api/eval/run       jalankan evaluasi (admin); satu proses pada satu waktu
"""

import json
import logging
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from . import ledger
from .db import SessionLocal
from .models import User
from .security import current_user, require_admin

log = logging.getLogger("aage.eval")
router = APIRouter()

API_DIR = Path(__file__).resolve().parents[1]
RESULT = API_DIR / "eval" / "hasil" / "hasil.json"
TIMEOUT_S = 600

_lock = threading.Lock()
_state: dict = {"berjalan": False, "mulai": None, "error": None}


def _read() -> tuple[dict | None, str | None]:
    if not RESULT.exists():
        return None, None
    data = json.loads(RESULT.read_text(encoding="utf-8"))
    mtime = datetime.fromtimestamp(RESULT.stat().st_mtime, tz=timezone.utc).isoformat()
    return data, mtime


def _headline(r: dict) -> str:
    qa, kl, es, op = r.get("qa", {}), r.get("klaim", {}), r.get("eskalasi", {}), r.get("operasional", {})
    return (f"Akurasi {qa.get('akurasi')}% · groundedness {qa.get('groundedness')}% · ClaimGuard recall "
            f"{kl.get('recall')}% / precision {kl.get('precision')}% · eskalasi {es.get('ketepatan')}% · "
            f"p95 {op.get('latensi_p95_ms')} ms")


def _record(tipe: str, **fields) -> None:
    with SessionLocal() as db:
        ledger.record(db, tipe, aktor="AI:evaluation", **fields)
        db.commit()


def _run(offline: bool, aktor: str) -> None:
    cmd = [sys.executable, "-m", "eval.run"] + (["--offline"] if offline else [])
    try:
        # PYTHONIOENCODING: laporan memuat "≥" yang gagal dicetak di konsol Windows (cp1252).
        proc = subprocess.run(cmd, cwd=API_DIR, capture_output=True, text=True, timeout=TIMEOUT_S,
                              encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "gagal tanpa pesan").strip().splitlines()[-1][:300])
        data, _ = _read()
        _record("evaluasi_selesai", ringkasan=_headline(data or {})[:280], outcome="selesai",
                alasan=f"Dijalankan oleh {aktor}", data={"mode": (data or {}).get("mode"), "hasil": data})
        _state["error"] = None
    except Exception as exc:  # noqa: BLE001 — dilaporkan ke dashboard & Ledger
        log.exception("Evaluasi gagal")
        _state["error"] = str(exc)[:300]
        _record("evaluasi_selesai", ringkasan="Evaluasi gagal", outcome="gagal", alasan=str(exc)[:500])
    finally:
        _state["berjalan"] = False
        _lock.release()


@router.get("/eval/summary")
def eval_summary(user: User = Depends(current_user)):
    data, mtime = _read()
    return {"ada": data is not None, "hasil": data, "dijalankan_pada": mtime, "berjalan": _state["berjalan"],
            "mulai": _state["mulai"], "error": _state["error"]}


@router.post("/eval/run")
def eval_run(offline: bool = True, user: User = Depends(require_admin)):
    if not _lock.acquire(blocking=False):
        raise HTTPException(409, "Evaluasi sedang berjalan — tunggu hingga selesai.")
    _state.update(berjalan=True, mulai=datetime.now(timezone.utc).isoformat(), error=None)
    aktor = f"staf:{user.nama}"
    _record("evaluasi_dimulai", ringkasan="Menjalankan dataset uji berlabel (QA katalog, klaim, eskalasi, negosiasi)",
            outcome="berjalan", alasan=f"Diminta oleh {aktor}", data={"offline": offline})
    threading.Thread(target=_run, args=(offline, aktor), daemon=True).start()
    return {"berjalan": True, "mulai": _state["mulai"]}
