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
    "permintaan_tak_terpenuhi": "Permintaan di luar katalog",
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
    "konten_diterbitkan": "Bukti terbit dicatat",
    "konten_terbit_dibatalkan": "Bukti terbit dibatalkan",
    "audit_halaman": "Audit halaman",
    "prospek_dibuat": "Prospek dibuat",
    "prospek_status": "Status prospek berubah",
    "prospek_riset": "Riset pasar & Next Best Action prospek",
    "prospek_diekspor": "Prospek diekspor",
    "prospek_consent": "Consent prospek berubah",
    "prospek_kontak_dibuka": "Kontak promosi prospek dibuka",
    "prospek_kontak_ditolak": "Kontak promosi prospek ditolak",
    "prospek_diperbarui": "Prospek diperbarui",
    "prospek_diimpor": "Prospek diimpor",
    "prospek_impor_pratinjau": "Pratinjau impor prospek",
    "prospek_digabung": "Prospek digabung",
    "prospek_duplikat_diputus": "Calon duplikat diputus",
    "prospek_dedupe_dipindai": "Pindai duplikat prospek",
    "prospek_diverifikasi": "Verifikasi prospek",
    "prospek_skor_dihitung": "Skor prospek dihitung ulang",
    "leads_konfigurasi": "Konfigurasi Leads diubah",
    "pengingat_repeat_order": "Pengingat repeat order",
    "katalog_diimpor": "Katalog diimpor",
    "katalog_pratinjau": "Pratinjau impor katalog",
    "katalog_diganti": "Seluruh katalog diganti",
    "katalog_ganti_gagal": "Ganti katalog gagal",
    "dokumen_diingest": "Dokumen di-ingest",
    "claimguard_playground": "Pemeriksaan Playground",
    "llm_gagal": "Panggilan LLM gagal",
    "agen_hitl": "Agen: menunggu persetujuan manusia",
    "agen_claimguard": "Agen ClaimGuard: audit",
    "invoice_dikirim": "Invoice dikirim",
    "invoice_disusun": "Invoice disusun (tidak dikirim)",
    "klaim_diverifikasi": "Klaim produk diverifikasi",
    "fakta_status_diubah": "Status verifikasi fakta diubah",
    "fakta_tertahan": "Fakta belum terverifikasi ditahan",
    "compliance_audit": "ClaimGuard Compliance Check",
    "compliance_tindakan": "Tindakan manusia atas draf (Compliance)",
    "pengaturan_diubah": "Pengaturan diubah",
    "evaluasi_dimulai": "Evaluasi dimulai",
    "evaluasi_selesai": "Evaluasi selesai",
    "ambil_alih": "Percakapan diambil alih staf",
    "ambil_alih_selesai": "Percakapan dikembalikan ke AI",
    "saran_ai": "Saran AI untuk staf",
    "kontak_diubah": "Profil toko diubah",
    "prospek_ditautkan": "Prospek ditautkan ke percakapan",
}


# Yang boleh dibaca peran tanpa izin penjualan. Daftar putih: tipe baru tertutup sampai sengaja ditambahkan.
TIPE_UNTUK_MARKETING = frozenset({
    "konten_dibuat", "konten_disetujui", "konten_diekspor", "konten_diedit", "konten_diarsipkan", "konten_diterbitkan",
    "konten_terbit_dibatalkan", "audit_halaman", "claimguard",
    "claimguard_playground", "llm_gagal", "compliance_audit", "compliance_tindakan", "agen_claimguard", "approval_dibuat", "approval_diputus",
})


def boleh_dibaca_marketing(ev: LedgerEvent) -> bool:
    """Event yang menempel pada percakapan memuat isi chat pelanggan, jadi selalu tertutup."""
    return ev.conversation_id is None and ev.tipe_event in TIPE_UNTUK_MARKETING


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


def record(db: Session, tipe_event: str, **fields) -> LedgerEvent:
    if tipe_event not in EVENT_TYPES:
        raise ValueError(f"Tipe event tidak dikenal: {tipe_event}")
    simpan_kegagalan_llm(db, **fields)
    ev = LedgerEvent(tipe_event=tipe_event, **fields)
    db.add(ev)
    db.flush()
    ledger_chain.seal(db, ev)  # segel hash di transaksi yang sama
    return ev


def simpan_kegagalan_llm(db: Session, **konteks) -> None:
    """Tulis kegagalan LLM yang tertunda, dengan rujukan event yang memicunya. `llm` tidak bisa menulis sendiri: sesi
    terpisah akan menunggu kunci rantai hash yang dipegang transaksi pemanggil. Jalur yang tidak menulis event lain
    sesudah memanggil LLM harus memanggil fungsi ini.

    Hanya jenis dan kode yang disimpan. Pesan provider tidak ikut karena bisa mengutip prompt, dan Ledger tidak bisa dihapus."""
    from .llm import ambil_kegagalan

    for g in ambil_kegagalan():
        ev = LedgerEvent(tipe_event="llm_gagal", trace_id=konteks.get("trace_id"), conversation_id=konteks.get("conversation_id"),
                         product_id=konteks.get("product_id"), objek_ref=konteks.get("objek_ref"),
                         ringkasan=f"Panggilan LLM gagal: {g['jenis']} · {g['tujuan']}", model=g["model"], token_in=g["token_in"],
                         token_out=g["token_out"], biaya_rp=g["biaya_rp"], latensi_ms=g["latensi_ms"], outcome=g["jenis"],
                         data={k: g[k] for k in ("jenis", "tujuan", "status", "finish_reason", "retry_after")})
        db.add(ev)
        db.flush()
        ledger_chain.seal(db, ev)


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
