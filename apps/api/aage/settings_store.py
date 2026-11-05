"""Pengaturan yang bisa diubah dari dashboard (Brief §6.4): mode otonomi per agen, jeda agen, dan budget AI.

Disimpan di tabel `settings` (kunci → JSON). Setiap perubahan tercatat di Ledger. UI tidak menyimpan state bisnis;
nilai efektif (mis. mode turun ke "setujui" saat budget terlampaui) selalu dihitung di sini.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import clock, ledger
from .config import get_settings
from .db import Base

settings = get_settings()

AGENT_IDS = ("orchestrator", "opportunity", "sales", "content", "claimguard", "evaluation")
MODES = ("saran", "setujui", "otonom")
# Produksi: data simulasi tidak disajikan sebagai fakta. Demo: boleh, dengan label. Tanpa pilihan tersimpan = produksi.
MODE_DATA = ("produksi", "demo")
# "Otonom" hanya untuk jawaban katalog berisiko rendah (Sales Assistant), dan tetap di dalam gerbang ClaimGuard.
OTONOM_ALLOWED = {"sales"}

DEFAULT_OTONOMI = {
    "orchestrator": "setujui",
    "opportunity": "saran",
    # Perilaku yang sudah berjalan: jawaban katalog yang lolos ClaimGuard & bersumber terkirim otomatis.
    "sales": "otonom",
    "content": "setujui",
    "claimguard": "setujui",
    "evaluation": "saran",
}


class AppSetting(Base):
    __tablename__ = "settings"
    kunci: Mapped[str] = mapped_column(String(40), primary_key=True)
    nilai: Mapped[dict] = mapped_column(JSON, default=dict)
    diubah_oleh: Mapped[str] = mapped_column(String(80), default="sistem")
    diubah_pada: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)


def _raw(db: Session, kunci: str) -> dict:
    row = db.get(AppSetting, kunci)
    return dict(row.nilai or {}) if row else {}


def otonomi(db: Session) -> dict[str, str]:
    saved = _raw(db, "otonomi")
    return {a: saved.get(a, DEFAULT_OTONOMI[a]) for a in AGENT_IDS}


def jeda(db: Session) -> dict[str, bool]:
    saved = _raw(db, "jeda")
    return {a: bool(saved.get(a, False)) for a in AGENT_IDS}


def anggaran(db: Session) -> dict[str, float]:
    saved = _raw(db, "anggaran")
    return {"harian_rp": float(saved.get("harian_rp", settings.budget_daily_rp)),
            "bulanan_rp": float(saved.get("bulanan_rp", settings.budget_monthly_rp))}


def mode_data(db: Session) -> str:
    mode = _raw(db, "mode_data").get("mode")
    return mode if mode in MODE_DATA else MODE_DATA[0]


def pasang_mode_data(db: Session, mode: str, aktor: str = "uji") -> None:
    """Untuk tes dan eval pada database sementara. Perubahan dari dashboard lewat `update` agar tercatat di Ledger."""
    if mode not in MODE_DATA:
        raise InvalidSetting(f"Mode data tidak dikenal: {mode}")
    _put(db, "mode_data", {"mode": mode}, aktor)
    db.commit()


def budget_exceeded(db: Session) -> bool:
    from . import llm

    caps = anggaran(db)
    try:
        return llm.spent_rp(days=1) >= caps["harian_rp"] or llm.spent_rp(month=True) >= caps["bulanan_rp"]
    except Exception:  # pragma: no cover - DB belum siap
        return False


def effective_mode(db: Session, agent: str) -> tuple[str, str | None]:
    """Mode yang benar-benar berlaku + alasan bila berbeda dari pilihan staf."""
    mode = otonomi(db)[agent]
    if mode == "otonom" and budget_exceeded(db):
        return "setujui", "Budget AI terlampaui — agen otomatis kembali ke Setujui dulu."
    return mode, None


def snapshot(db: Session) -> dict:
    return {
        "otonomi": otonomi(db),
        "jeda": jeda(db),
        "anggaran": anggaran(db),
        "budget_terlampaui": budget_exceeded(db),
        "boleh_otonom": sorted(OTONOM_ALLOWED),
        "mode_data": mode_data(db),
    }


class InvalidSetting(ValueError):
    pass


def update(db: Session, patch: dict, aktor: str) -> dict:
    """Validasi lalu simpan. Setiap kunci yang berubah dicatat di Ledger."""
    changes: list[str] = []

    if "otonomi" in patch:
        cur = otonomi(db)
        for agent, mode in (patch["otonomi"] or {}).items():
            if agent not in AGENT_IDS:
                raise InvalidSetting(f"Agen tidak dikenal: {agent}")
            if mode not in MODES:
                raise InvalidSetting(f"Mode tidak dikenal: {mode}")
            if mode == "otonom" and agent not in OTONOM_ALLOWED:
                raise InvalidSetting(f"Mode Otonom tidak diizinkan untuk agen {agent}")
            if cur[agent] != mode:
                changes.append(f"otonomi.{agent}: {cur[agent]} → {mode}")
                cur[agent] = mode
        _put(db, "otonomi", cur, aktor)

    if "jeda" in patch:
        cur = jeda(db)
        for agent, paused in (patch["jeda"] or {}).items():
            if agent not in AGENT_IDS:
                raise InvalidSetting(f"Agen tidak dikenal: {agent}")
            if cur[agent] != bool(paused):
                changes.append(f"jeda.{agent}: {'dijeda' if paused else 'dilanjutkan'}")
                cur[agent] = bool(paused)
        _put(db, "jeda", cur, aktor)

    if "anggaran" in patch:
        cur = anggaran(db)
        for k in ("harian_rp", "bulanan_rp"):
            if k in (patch["anggaran"] or {}):
                v = float(patch["anggaran"][k])
                if v < 0 or v > 1_000_000_000:
                    raise InvalidSetting(f"Nilai {k} tidak wajar")
                if cur[k] != v:
                    changes.append(f"anggaran.{k}: {cur[k]:g} → {v:g}")
                    cur[k] = v
        if cur["harian_rp"] > cur["bulanan_rp"]:
            raise InvalidSetting("Budget harian tidak boleh melebihi budget bulanan")
        _put(db, "anggaran", cur, aktor)

    if "mode_data" in patch:
        baru, lama = patch["mode_data"], mode_data(db)
        if baru not in MODE_DATA:
            raise InvalidSetting(f"Mode data tidak dikenal: {baru}")
        if baru != lama:
            changes.append(f"mode_data: {lama} → {baru}")
            _put(db, "mode_data", {"mode": baru}, aktor)

    if changes:
        ledger.record(db, "pengaturan_diubah", aktor=aktor, ringkasan="; ".join(changes)[:280],
                      alasan="Diubah dari dashboard Pengaturan", outcome="tersimpan", data={"perubahan": changes})
    db.commit()
    return snapshot(db)


def _put(db: Session, kunci: str, nilai: dict, aktor: str) -> None:
    row = db.get(AppSetting, kunci)
    if row is None:
        db.add(AppSetting(kunci=kunci, nilai=nilai, diubah_oleh=aktor, diubah_pada=clock.now()))
    else:
        row.nilai = dict(nilai)
        row.diubah_oleh = aktor
        row.diubah_pada = clock.now()
    db.flush()
