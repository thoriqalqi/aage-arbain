"""Segmen dan bobot skor Leads yang bisa diatur admin. Nilai awal adalah draf, belum disetujui CV Arba'in."""

from sqlalchemy.orm import Session

from .. import ledger, settings_store
from .scoring_service import BOBOT_AWAL

SEGMEN_AWAL = ["Apotek", "Toko Obat", "Minimarket"]
AMBANG_AWAL = 0.4
_ANGKA = ("geo_maks", "telepon", "jam", "jalan", "penalti_jaringan")


class KonfigurasiTidakValid(ValueError):
    pass


def segmen(db: Session) -> list[str]:
    return list(settings_store._raw(db, "leads_segmen").get("daftar") or SEGMEN_AWAL)


def skor(db: Session) -> dict:
    tersimpan = settings_store._raw(db, "leads_skor")
    return {**BOBOT_AWAL, "versi": 0, "ambang_confidence": AMBANG_AWAL, **tersimpan}


def versi(cfg: dict) -> str:
    return f"draf-geo-data-v{int(cfg.get('versi', 0))}"


def snapshot(db: Session) -> dict:
    cfg = skor(db)
    return {"segmen": segmen(db), "bobot": {k: cfg[k] for k in _ANGKA}, "ambang_confidence": cfg["ambang_confidence"],
            "versi": versi(cfg), "sementara": True}


def ubah(db: Session, aktor: str, *, bobot: dict | None = None, ambang_confidence: float | None = None,
         daftar_segmen: list[str] | None = None) -> dict:
    perubahan: list[str] = []
    if daftar_segmen is not None:
        bersih = [" ".join(s.split()) for s in daftar_segmen if s and s.strip()]
        if not bersih or len({s.lower() for s in bersih}) != len(bersih) or any(len(s) > 24 for s in bersih):
            raise KonfigurasiTidakValid("Segmen harus terisi, tidak kembar, dan maksimal 24 karakter")
        if bersih != segmen(db):
            perubahan.append(f"segmen: {', '.join(bersih)}")
            settings_store._put(db, "leads_segmen", {"daftar": bersih}, aktor)
    cfg = skor(db)
    baru = dict(cfg)
    for kunci, nilai in (bobot or {}).items():
        if kunci not in _ANGKA:
            raise KonfigurasiTidakValid(f"Bobot tidak dikenal: {kunci}")
        if not isinstance(nilai, int | float) or isinstance(nilai, bool) or not 0 <= nilai <= 100:
            raise KonfigurasiTidakValid(f"Bobot {kunci} harus angka 0-100")
        baru[kunci] = nilai
    if baru["geo_maks"] + baru["telepon"] + baru["jam"] + baru["jalan"] != 100:
        raise KonfigurasiTidakValid("Bobot lokasi, telepon, jam, dan jalan harus berjumlah 100")
    if ambang_confidence is not None:
        if not 0 <= ambang_confidence <= 1:
            raise KonfigurasiTidakValid("Ambang confidence harus 0-1")
        baru["ambang_confidence"] = ambang_confidence
    if baru != cfg:
        baru["versi"] = int(cfg["versi"]) + 1
        perubahan.append(f"skor: {versi(cfg)} → {versi(baru)}")
        settings_store._put(db, "leads_skor", baru, aktor)
    if perubahan:
        ledger.record(db, "leads_konfigurasi", aktor=aktor, model=None, outcome="tersimpan", ringkasan="; ".join(perubahan)[:280],
                      data={"perubahan": perubahan, "bobot": {k: baru[k] for k in _ANGKA}, "ambang_confidence": baru["ambang_confidence"]})
    db.commit()
    return snapshot(db)
