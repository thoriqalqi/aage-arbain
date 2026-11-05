"""Endpoint multi-agen CrewAI (prefix /api/agents) untuk Command Center dashboard.

- GET  /api/agents                    daftar 4 agen + model + mode
- GET  /api/agents/workday/stream     Server-Sent Events: log aktivitas agen (dipakai terminal & animasi 3D)
- POST /api/agents/negotiate          Sales agent + ClaimGuard (status AUTO_APPROVED / NEED_HUMAN_CONFIRMATION)
- POST /api/agents/audit              ClaimGuard agent: status, pasal Perban BPOM 30/2023, teks terpotong
- POST /api/agents/leads              Lead miner: prospek + skor urgensi
- POST /api/agents/content            GEO agent: draf konten (+ audit)
- POST /api/agents/invoice/approve    staf menyetujui deal → invoice disusun sebagai pratinjau, tidak dikirim ke mana pun

Item human-in-the-loop masuk tabel approvals; audit BLOCKED dan keputusan staf tercatat di Ledger."""

import json
import os
import threading

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import ledger, settings_store
from .config import get_settings
from .db import SessionLocal, get_db
from .models import Approval, User
from .security import current_user, require_izin

settings = get_settings()
# Ekspor konfigurasi .env ke environment sebelum modul crew dibaca (CrewAI & SDK Anthropic membaca env).
os.environ.setdefault("AGENT_MODEL", settings.agent_model)
os.environ.setdefault("AGENT_MODE", settings.agent_mode)
if settings.anthropic_api_key:
    os.environ.setdefault("ANTHROPIC_API_KEY", settings.anthropic_api_key)

from src import agents_crew as crew_mod  # noqa: E402

router = APIRouter(prefix="/api/agents")
_LOCK = threading.Lock()  # satu workday pada satu waktu (demo)


def _persist_hitl(item: dict, aktor: str) -> None:
    """Simpan item HITL ke antrean approval agar bisa diputus dari dashboard."""
    with SessionLocal() as db:
        jenis = item.get("jenis", "agen")
        nego = item.get("negosiasi") or {}
        draf = item.get("draf_balasan") or (item.get("konten") or {}).get("markdown", "")
        ap = Approval(objek_tipe=f"agen_{jenis}"[:24], alasan=nego.get("alasan") or item.get("judul", ""),
                      ringkasan=item.get("laporan") or item.get("judul", ""), intent=jenis, draf=draf[:4000],
                      verdict=None, status="menunggu")
        db.add(ap)
        db.flush()
        ledger.record(db, "agen_hitl", objek_ref=f"approval:{ap.id}", aktor=aktor, ringkasan=item.get("judul", "")[:280],
                      alasan=nego.get("alasan", ""), outcome=crew_mod.NEED_HUMAN_CONFIRMATION, data={"jenis": jenis})
        db.commit()


def _persist_event(ev: "crew_mod.AgentEvent", aktor: str) -> None:
    if ev.agent == "claim_guard_agent" and ev.status in (crew_mod.BLOCKED, crew_mod.REVIEW):
        audit = ev.data.get("audit") or {}
        with SessionLocal() as db:
            ledger.record(db, "agen_claimguard", aktor="AI:claim_guard_agent", ringkasan=ev.message[:280],
                          verdict="blocked" if ev.status == crew_mod.BLOCKED else "review",
                          aturan_terpicu=sorted({h["aturan"] for v in audit.get("pelanggaran", []) for h in v["temuan"]}),
                          alasan="; ".join(p["rujukan"] for p in audit.get("pasal_dilanggar", []))[:500],
                          data={"sumber": audit.get("sumber"), "pemicu": aktor})
            db.commit()


def _pagar_data_demo(db: Session) -> None:
    """Agen ini memakai berkas data contoh (`mock_products.json`), bukan katalog terverifikasi."""
    if settings_store.mode_data(db) != "demo":
        raise HTTPException(409, "Agen ini memakai data contoh, jadi hanya berjalan di mode demo. Mode data aktif: produksi.")


def _new_crew(user: User, speed: float, persist: bool = True) -> "crew_mod.AAGECrew":
    aktor = f"staf:{user.nama}"
    stream = crew_mod.ActivityStream(on_event=(lambda ev: _persist_event(ev, aktor)) if persist else None)
    return crew_mod.AAGECrew(human_in_the_loop=True, stream=stream, speed=speed,
                             on_hitl=(lambda item: _persist_hitl(item, aktor)) if persist else None)


@router.get("")
def agents_info(user: User = Depends(current_user)):
    return {
        "model": crew_mod.MODEL,
        "mode": crew_mod.resolve_mode(),
        "produk": len(crew_mod.db().products),
        "regulasi": crew_mod.regulasi()["peraturan"],
        "agen": [{"id": aid, "nama": crew_mod.AGENT_LABEL[aid], **{k: v for k, v in spec.items() if k != "backstory"}}
                 for aid, spec in crew_mod.AGENT_SPECS.items()],
    }


@router.get("/workday/stream")
def workday_stream(wilayah: str = "Kota Semarang", speed: float = 1.0, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    _pagar_data_demo(db)
    if not _LOCK.acquire(blocking=False):
        raise HTTPException(409, "Workday lain sedang berjalan — tunggu hingga selesai.")
    crew = _new_crew(user, max(0.25, min(speed, 8.0)))

    def gen():
        try:
            crew_mod.run_in_thread(lambda c: c.workday(wilayah), crew)
            for ev in crew.stream:
                yield f"data: {ev.to_json()}\n\n"
            yield "event: end\ndata: {}\n\n"
        finally:
            _LOCK.release()

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class NegotiateIn(BaseModel):
    pesan: str = Field("", max_length=1000)
    produk: str = Field(..., min_length=2)
    qty_box: int = Field(..., ge=1, le=10000)
    diskon_diminta: float | None = Field(None, ge=0, le=100)
    pembeli: str = "Apotek"


def _collect(crew: "crew_mod.AAGECrew", fn) -> tuple[object, list[dict]]:
    result = fn(crew)
    crew.stream.close()
    return result, [json.loads(ev.to_json()) for ev in crew.stream]


@router.post("/negotiate")
def negotiate(body: NegotiateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _pagar_data_demo(db)
    crew = _new_crew(user, speed=0)
    p = crew_mod.db().find(body.produk)
    if p is None:
        raise HTTPException(404, f"Produk '{body.produk}' tidak ditemukan")
    result, events = _collect(crew, lambda c: c.negotiate(body.pesan or f"{body.qty_box} box", p["id"], body.qty_box,
                                                          body.diskon_diminta, body.pembeli))
    return {**result, "log": events, "hitl": crew.hitl_items}


class AuditIn(BaseModel):
    teks: str = Field(..., min_length=3, max_length=20000)
    product_id: str | None = None
    sumber: str = "dashboard"


@router.post("/audit")
def audit(body: AuditIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    res = crew_mod.audit_compliance(body.teks, body.product_id, body.sumber)
    if res["status"] != crew_mod.PASSED:
        ledger.record(db, "agen_claimguard", aktor=f"staf:{user.nama}", ringkasan=res["notifikasi_dashboard"] or f"Audit {res['status']}",
                      verdict="blocked" if res["status"] == crew_mod.BLOCKED else "review",
                      aturan_terpicu=sorted({h["aturan"] for v in res["pelanggaran"] for h in v["temuan"]}),
                      alasan="; ".join(p["rujukan"] for p in res["pasal_dilanggar"])[:500], data={"sumber": body.sumber})
        db.commit()
    return res


class LeadsIn(BaseModel):
    wilayah: str = "Kota Semarang"
    jenis: str = "apotek"


@router.post("/leads")
def leads(body: LeadsIn, user: User = Depends(current_user)):
    crew = _new_crew(user, speed=0, persist=False)
    result, events = _collect(crew, lambda c: c.mine_leads(body.wilayah, body.jenis))
    return {"leads": result, "log": events}


class ContentIn(BaseModel):
    produk: str
    topik: str = ""


@router.post("/content")
def content(body: ContentIn, user: User = Depends(require_izin("konten")), db: Session = Depends(get_db)):
    _pagar_data_demo(db)
    p = crew_mod.db().find(body.produk)
    if p is None:
        raise HTTPException(404, f"Produk '{body.produk}' tidak ditemukan")
    crew = _new_crew(user, speed=0)
    result, events = _collect(crew, lambda c: c.write_content(p["id"], body.topik))
    return {**result, "log": events}


class InvoiceIn(BaseModel):
    produk: str
    qty_box: int = Field(..., ge=1)
    diskon_disetujui: float = Field(..., ge=0, le=100, description="Diskon final yang diputuskan staf")
    pembeli: str = "Apotek"
    target_wa: str = Field("", max_length=20, description="Nomor WhatsApp tujuan (format 62…)")


@router.post("/invoice/approve")
def invoice_approve(body: InvoiceIn, user: User = Depends(require_izin("penjualan")), db: Session = Depends(get_db)):
    """Staf menyetujui deal final (HITL). Harga dihitung ulang di server dari matriks_harga_b2b — klien tidak bisa
    mengirim harga sendiri. Pengiriman WhatsApp dinonaktifkan karena jalur ini melewati channels/sender.py dan belum ada
    kanal WhatsApp resmi: invoice hanya disusun, diaudit ClaimGuard, dan dicatat."""
    _pagar_data_demo(db)
    p = crew_mod.db().find(body.produk)
    if p is None:
        raise HTTPException(404, "Produk tidak ditemukan")
    m = p["matriks_harga_b2b"]
    harga_botol = round(m["harga_dasar_b2b_per_botol"] * (1 - body.diskon_disetujui / 100))
    total = harga_botol * m["isi_per_box_botol"] * body.qty_box
    di_atas_batas = body.diskon_disetujui > m["batas_diskon_maksimal_ai_persen"]
    teks = (f"INVOICE PROFORMA — CV Arba'in\nKepada: {body.pembeli}\n"
            f"{p['nama_produk']} ({p['nomor_izin_edar_bpom']})\n"
            f"{body.qty_box} box × {m['isi_per_box_botol']} botol @ {crew_mod.rupiah(harga_botol)} (diskon {body.diskon_disetujui:g}%)\n"
            f"Total: {crew_mod.rupiah(total)}\nPembayaran: transfer bank; tempo 14 hari untuk pelanggan tetap.\n"
            f"Disetujui oleh: {user.nama}")
    audit_res = crew_mod.audit_compliance(teks, p["id"], "invoice")
    if audit_res["status"] == crew_mod.BLOCKED:
        raise HTTPException(422, {"pesan": "ClaimGuard memblokir teks invoice", "audit": audit_res})
    status, detail = "simulasi", "Pengiriman WhatsApp dinonaktifkan. Invoice hanya disusun sebagai pratinjau."
    ledger.record(db, "invoice_disusun", aktor=f"staf:{user.nama}", ringkasan=f"Invoice {body.pembeli}: {crew_mod.rupiah(total)}",
                  alasan=("Diskon di atas batas AI disetujui manusia" if di_atas_batas else "Deal final dikonfirmasi manusia"),
                  outcome=status, verdict="allowed" if audit_res["status"] == crew_mod.PASSED else "review",
                  data={"produk": p["id"], "qty_box": body.qty_box, "diskon": body.diskon_disetujui, "detail": detail})
    db.commit()
    return {"status": status, "detail": detail, "teks": teks, "total": total, "audit": audit_res["status"]}
