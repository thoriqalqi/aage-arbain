"""Evidence-to-Action Ledger (M4). Satu-satunya cara menulis event adalah `record` (insert saja)."""

import uuid

from sqlalchemy.orm import Session

from . import ledger_chain
from .models import LedgerEvent

EVENT_TYPES = {
    "pesan_masuk": "Pesan masuk",
    "intent": "Intent dikenali",
    "retrieval": "Pengambilan sumber",
    "draf_jawaban": "Draf jawaban",
    "gaya_bahasa": "Gaya bahasa LLM (kunci fakta)",
    "memori_dihapus": "Memori percakapan kedaluwarsa",
    "claimguard": "Keputusan ClaimGuard",
    "claimguard_inbound": "ClaimGuard: klaim yang diminta",
    "kebijakan": "Keputusan kebijakan",
    "approval_dibuat": "Masuk antrean approval",
    "approval_diputus": "Approval diputus",
    "pesan_keluar": "Pesan keluar",
    "draf_pesanan": "Draf pesanan",
    "konten_dibuat": "Konten dibuat",
    "konten_disetujui": "Konten disetujui",
    "konten_diekspor": "Konten diekspor",
    "konten_diedit": "Konten diedit",
    "konten_diarsipkan": "Konten diarsipkan",
    "audit_halaman": "Audit halaman",
    "prospek_dibuat": "Prospek dibuat",
    "prospek_status": "Status prospek berubah",
    "prospek_riset": "Riset pasar & Next Best Action prospek",
    "pengingat_repeat_order": "Pengingat repeat order",
    "katalog_diimpor": "Katalog diimpor",
    "katalog_pratinjau": "Pratinjau impor katalog",
    "dokumen_diingest": "Dokumen di-ingest",
    "claimguard_playground": "Pemeriksaan Playground",
    "agen_hitl": "Agen: menunggu persetujuan manusia",
    "agen_claimguard": "Agen ClaimGuard: audit",
    "invoice_dikirim": "Invoice dikirim",
    "compliance_audit": "ClaimGuard Compliance Check",
    "compliance_tindakan": "Tindakan manusia atas draf (Compliance)",
    "pengaturan_diubah": "Pengaturan diubah",
    "evaluasi_dimulai": "Evaluasi dimulai",
    "evaluasi_selesai": "Evaluasi selesai",
    "ambil_alih": "Percakapan diambil alih staf",
    "ambil_alih_selesai": "Percakapan dikembalikan ke AI",
    "saran_ai": "Saran AI untuk staf",
    "kontak_diubah": "Profil toko diubah",
    "prospek_diperbarui": "Prospek diperbarui",
    "prospek_ditautkan": "Prospek ditautkan ke percakapan",
}


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


def record(db: Session, tipe_event: str, **fields) -> LedgerEvent:
    if tipe_event not in EVENT_TYPES:
        raise ValueError(f"Tipe event tidak dikenal: {tipe_event}")
    ev = LedgerEvent(tipe_event=tipe_event, **fields)
    db.add(ev)
    db.flush()
    ledger_chain.seal(db, ev)  # segel hash di transaksi yang sama
    return ev


def record_llm(db: Session, tipe_event: str, llm_result, **fields) -> LedgerEvent:
    """Catat event yang memakai LLM (atau jalur deterministik bila llm_result None)."""
    from .llm import OFFLINE_MODEL

    if llm_result is not None:
        fields.setdefault("model", llm_result.model)
        fields.setdefault("token_in", llm_result.token_in)
        fields.setdefault("token_out", llm_result.token_out)
        fields.setdefault("biaya_rp", llm_result.biaya_rp)
    else:
        fields.setdefault("model", OFFLINE_MODEL)
    return record(db, tipe_event, **fields)
