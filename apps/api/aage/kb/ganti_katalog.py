"""Ganti Katalog: satu file menggantikan seluruh katalog yang sedang dipakai agent, tanpa restart.

Isi file diterapkan lewat alur impor biasa, lalu katalog lama disingkirkan di transaksi yang sama: gagal di mana pun berarti
katalog lama tetap utuh, dan pesan pembeli yang masuk selama proses dijawab dari katalog lama sampai transaksi selesai.

- nonaktif: produk, chunk, dan dokumen lama dinonaktifkan. Klaim, tier, dan verifikasinya tetap tersimpan tetapi tidak terbaca
  agent, karena semua pembacaan menyaring produk aktif. Bisa dikembalikan dengan mengunggah file lama.
- hapus: produk, klaim, tier, chunk beserta vektornya, dokumen, dan baris verifikasinya dihapus permanen.

Ledger, percakapan, pesan, dan kontak tidak diubah. Ledger hanya bertambah satu catatan penggantian.
Produk yang dirujuk draf pemasaran atau audit kepatuhan tidak bisa dihapus karena tabel itu append-only: produknya tetap ada
dalam keadaan nonaktif, sedangkan klaim, tier, chunk, dan verifikasinya tetap terhapus.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from .. import clock, ledger, settings_store
from ..config import get_settings, sumber_database
from ..db import SessionLocal
from ..models import (
    Approval,
    ApprovedClaim,
    Chunk,
    ComplianceAudit,
    Contact,
    ContentDraft,
    Conversation,
    Document,
    KatalogImpor,
    LedgerEvent,
    MarketingDraft,
    Message,
    PricingRule,
    Product,
    VerifikasiFakta,
)
from . import katalog_impor, verifikasi

log = logging.getLogger("aage.katalog")

NONAKTIF, HAPUS = "nonaktif", "hapus"
MODE = (NONAKTIF, HAPUS)
KONFIRMASI_HAPUS = "HAPUS PERMANEN"
DIPROSES = "diproses"
_BATAS_PROSES = timedelta(minutes=15)  # API mati di tengah proses: transaksinya sudah dibatalkan database
_TIPE_DRAF = ("balasan", "order_draft", "konten")


class GantiDitolak(ValueError):
    pass


def _dokumen_lama(db: Session, *, kecuali: set[int], ganti_kebijakan: bool) -> list[Document]:
    """Dokumen milik katalog lama: katalog, kebijakan yang diganti file, dan dokumen berlabel simulasi. Dokumen lain yang
    diunggah staf tetap dipakai."""
    simulasi = set(db.scalars(select(VerifikasiFakta.objek_id).where(VerifikasiFakta.objek_tipe == verifikasi.DOKUMEN,
                                                                     VerifikasiFakta.status_verifikasi == verifikasi.SIMULASI)))
    return [d for d in db.scalars(select(Document).where(Document.id.not_in(kecuali)).order_by(Document.id))
            if d.tipe == "katalog" or verifikasi.judul_simulasi(d.judul) or d.id in simulasi
            or (ganti_kebijakan and d.judul.startswith(katalog_impor.KEBIJAKAN_JUDUL))]


def _produk_lama(db: Session, sku_baru: set[str] | None = None, id_baru: set[int] | None = None) -> list[Product]:
    produk = db.scalars(select(Product).order_by(Product.id))
    return [p for p in produk if p.sku not in (sku_baru or ()) and p.id not in (id_baru or ())]


def _terkunci(db: Session, ids: set[int]) -> set[int]:
    return ({*db.scalars(select(MarketingDraft.product_id).where(MarketingDraft.product_id.in_(ids))),
             *db.scalars(select(ComplianceAudit.product_id).where(ComplianceAudit.product_id.in_(ids)))} if ids else set())


def _baris_verifikasi(ids_produk: set[int], ids_klaim: set[int], ids_dokumen: set[int]):
    return or_(
        (VerifikasiFakta.objek_tipe == verifikasi.PRODUK) & VerifikasiFakta.objek_id.in_(ids_produk),
        (VerifikasiFakta.objek_tipe == verifikasi.KLAIM) & VerifikasiFakta.objek_id.in_(ids_klaim),
        (VerifikasiFakta.objek_tipe == verifikasi.DOKUMEN) & VerifikasiFakta.objek_id.in_(ids_dokumen),
    )


def _hitung_lama(db: Session, ids_produk: set[int], ids_dokumen: set[int]) -> dict:
    ids_klaim = set(db.scalars(select(ApprovedClaim.id).where(ApprovedClaim.product_id.in_(ids_produk))))
    return {
        "klaim": len(ids_klaim),
        "tier": db.scalar(select(func.count()).select_from(PricingRule).where(PricingRule.product_id.in_(ids_produk))) or 0,
        "chunk": db.scalar(select(func.count()).select_from(Chunk).where(
            or_(Chunk.document_id.in_(ids_dokumen), Chunk.product_id.in_(ids_produk)))) or 0,
        "verifikasi": db.scalar(select(func.count()).select_from(VerifikasiFakta).where(
            _baris_verifikasi(ids_produk, ids_klaim, ids_dokumen))) or 0,
    }


def _tidak_disentuh(db: Session) -> dict:
    return {nama: db.scalar(select(func.count()).select_from(model)) or 0
            for nama, model in (("ledger", LedgerEvent), ("percakapan", Conversation), ("pesan", Message), ("kontak", Contact))}


def ringkasan(db: Session, token: str | None = None) -> dict:
    """Keadaan katalog sekarang dan, bila ada pratinjau, dampak penggantiannya. Hanya membaca."""
    aktif = list(db.scalars(select(Product).where(Product.aktif.is_(True))))
    ids_aktif = {p.id for p in aktif}
    out = {
        "sumber": sumber_database(get_settings().database_url),
        "mode_data": settings_store.mode_data(db),
        "sekarang": {
            "produk": len(aktif),
            "produk_arsip": (db.scalar(select(func.count()).select_from(Product)) or 0) - len(aktif),
            "tampak_demo": any(p.sumber_data in ("simulasi", "sintetis") or "SIM" in (p.no_izin_edar or "") for p in aktif),
            "klaim": db.scalar(select(func.count()).select_from(ApprovedClaim).where(ApprovedClaim.product_id.in_(ids_aktif))) or 0,
            "tier": db.scalar(select(func.count()).select_from(PricingRule).where(PricingRule.product_id.in_(ids_aktif))) or 0,
            "chunk": db.scalar(select(func.count()).select_from(Chunk).where(Chunk.aktif.is_(True))) or 0,
            "dokumen": list(db.scalars(select(Document.judul).where(Document.aktif.is_(True)).order_by(Document.id))),
        },
        "terakhir_diganti": settings_store.katalog_diganti(db) or None,
        "tidak_disentuh": _tidak_disentuh(db),
        "konfirmasi_hapus": KONFIRMASI_HAPUS,
    }
    if token and (imp := db.scalar(select(KatalogImpor).where(KatalogImpor.token == token))) is not None:
        out["dampak"] = _dampak(db, imp)
    return out


def _dampak(db: Session, imp: KatalogImpor) -> dict:
    ganti_kebijakan = bool((imp.laporan or {}).get("ganti_kebijakan"))
    produk = _produk_lama(db, sku_baru={r["sku"] for r in imp.produk})
    ids = {p.id for p in produk}
    dokumen = _dokumen_lama(db, kecuali=set(), ganti_kebijakan=ganti_kebijakan)
    id_dok = {d.id for d in dokumen}
    aktif = list(db.scalars(select(Document).where(Document.aktif.is_(True), Document.id.not_in(id_dok)).order_by(Document.id)))
    punya_kebijakan = db.scalar(select(func.count()).select_from(Document).where(
        Document.aktif.is_(True), Document.judul.startswith(katalog_impor.KEBIJAKAN_JUDUL))) or 0
    tetap_kebijakan = any(d.judul.startswith(katalog_impor.KEBIJAKAN_JUDUL) for d in aktif)
    terkunci = _terkunci(db, ids)
    return {
        "produk": len(ids),
        "produk_nama": [p.nama for p in produk][:200],
        "produk_terkunci": [p.nama for p in produk if p.id in terkunci],
        "dokumen": sorted({d.judul for d in dokumen if d.aktif}),
        "dokumen_tetap": [d.judul for d in aktif],
        "kebijakan": ("diganti" if ganti_kebijakan else "tetap" if tetap_kebijakan else "hilang" if punya_kebijakan else "tidak_ada"),
        "konten_dilepas": db.scalar(select(func.count()).select_from(ContentDraft).where(ContentDraft.product_id.in_(ids))) or 0,
        "draf_menunggu": db.scalar(select(func.count()).select_from(Approval).where(
            Approval.status == "menunggu", Approval.objek_tipe.in_(_TIPE_DRAF))) or 0,
        **_hitung_lama(db, ids, id_dok),
    }


def mulai(db: Session, token: str, aktor: str, *, mode: str, konfirmasi: str = "", lewati_error: bool = False) -> None:
    """Pemeriksaan sebelum proses berjalan di latar belakang. Menahan pratinjau supaya tidak dijalankan dua kali."""
    if mode not in MODE:
        raise GantiDitolak("Pilih cara menyingkirkan katalog lama: nonaktif atau hapus.")
    if mode == HAPUS and konfirmasi.strip() != KONFIRMASI_HAPUS:
        raise GantiDitolak(f"Hapus permanen perlu konfirmasi: ketik {KONFIRMASI_HAPUS}.")
    try:
        imp = katalog_impor.periksa_siap(db, token, lewati_error=lewati_error)
    except katalog_impor.ImporDitolak as exc:
        raise GantiDitolak(str(exc)) from None
    hasil = db.execute(update(KatalogImpor).where(KatalogImpor.id == imp.id, KatalogImpor.status == "pratinjau")
                       .values(status=DIPROSES, laporan={**imp.laporan, "gagal": None,
                                                         "proses": {"mode": mode, "mulai": clock.now().isoformat(), "aktor": aktor}}))
    if hasil.rowcount != 1:
        db.rollback()
        raise GantiDitolak("Pratinjau ini sudah diproses.")
    db.commit()


def _singkirkan(mode: str, ganti_kebijakan: bool):
    def jalan(db: Session, doc_baru: set[int], produk_baru: set[int]) -> dict:
        db.flush()  # perubahan produk yang tertunda harus tertulis sebelum baris yang sama dihapus massal
        produk = _produk_lama(db, id_baru=produk_baru)
        ids = {p.id for p in produk}
        dokumen = _dokumen_lama(db, kecuali=doc_baru, ganti_kebijakan=ganti_kebijakan)
        id_dok = {d.id for d in dokumen}
        hitung = _hitung_lama(db, ids, id_dok)
        db.execute(update(Chunk).where(or_(Chunk.document_id.in_(id_dok), Chunk.product_id.in_(ids))).values(aktif=False))
        db.execute(update(Document).where(Document.id.in_(id_dok)).values(aktif=False))
        db.execute(update(Product).where(Product.id.in_(ids)).values(aktif=False))
        terkunci = _terkunci(db, ids)
        keluar = {"mode": mode, "produk": len(ids), "dokumen": len(id_dok), "produk_terkunci": len(terkunci), **hitung}
        if mode == HAPUS:
            ids_klaim = set(db.scalars(select(ApprovedClaim.id).where(ApprovedClaim.product_id.in_(ids))))
            ids_hapus = ids - terkunci
            db.execute(delete(VerifikasiFakta).where(_baris_verifikasi(ids, ids_klaim, id_dok)))
            db.execute(delete(ApprovedClaim).where(ApprovedClaim.id.in_(ids_klaim)))
            db.execute(delete(PricingRule).where(PricingRule.product_id.in_(ids)))
            db.execute(delete(Chunk).where(or_(Chunk.document_id.in_(id_dok), Chunk.product_id.in_(ids))))
            db.execute(delete(Document).where(Document.id.in_(id_dok)))
            keluar["konten_dilepas"] = db.execute(update(ContentDraft).where(ContentDraft.product_id.in_(ids_hapus))
                                                  .values(product_id=None)).rowcount
            db.execute(delete(Product).where(Product.id.in_(ids_hapus)))
            db.expire_all()
        settings_store.catat_katalog_diganti(db, {
            "pada": clock.now().isoformat(), "mode": mode,
            "pesan_id": db.scalar(select(func.max(Message.id))) or 0,
            "approval_id": db.scalar(select(func.max(Approval.id))) or 0,
        }, "sistem")
        return keluar
    return jalan


def jalankan(token: str, aktor: str, *, mode: str, lewati_error: bool = False) -> None:
    """Berjalan di latar belakang karena katalog besar bisa lebih lama dari batas waktu proxy dashboard."""
    with SessionLocal() as db:
        try:
            imp = katalog_impor.periksa_siap(db, token, lewati_error=lewati_error, status=DIPROSES)
            ganti_kebijakan = bool(imp.laporan.get("ganti_kebijakan"))
            hasil = katalog_impor._terapkan(db, imp, aktor, singkirkan=_singkirkan(mode, ganti_kebijakan))
            imp.laporan = {**imp.laporan, "hasil": hasil, "proses": None}
            db.commit()
            log.info("Katalog diganti: %s", hasil)
        except Exception as exc:
            db.rollback()
            log.exception("Ganti katalog gagal, katalog lama tetap utuh")
            alasan = str(exc) if isinstance(exc, katalog_impor.ImporDitolak) else "Terjadi kesalahan saat menyimpan."
            _tandai_gagal(db, token, aktor, alasan)


def _tandai_gagal(db: Session, token: str, aktor: str, alasan: str) -> None:
    try:
        imp = db.scalar(select(KatalogImpor).where(KatalogImpor.token == token))
        imp.status = "pratinjau"
        imp.laporan = {**imp.laporan, "gagal": f"{alasan} Katalog lama tetap utuh.", "proses": None}
        ledger.record(db, "katalog_ganti_gagal", aktor=aktor, objek_ref=f"katalog_impor:{token}", outcome="gagal",
                      ringkasan=f"Ganti katalog gagal: {alasan}"[:280], model=None)
        db.commit()
    except Exception:  # pragma: no cover - database tidak terjangkau; dipulihkan oleh `status`
        db.rollback()
        log.exception("Status penggantian katalog tidak bisa ditandai gagal")


def status(db: Session, token: str) -> dict | None:
    imp = db.scalar(select(KatalogImpor).where(KatalogImpor.token == token))
    if imp is None:
        return None
    lap = imp.laporan or {}
    mulai_pada = (lap.get("proses") or {}).get("mulai")
    if imp.status == DIPROSES and mulai_pada and clock.now() - clock.aware(datetime.fromisoformat(mulai_pada)) > _BATAS_PROSES:
        _tandai_gagal(db, token, (lap.get("proses") or {}).get("aktor") or "sistem", "Proses terhenti sebelum selesai.")
        lap = imp.laporan or {}
    return {"status": imp.status, "hasil": lap.get("hasil"), "gagal": lap.get("gagal"), "proses": lap.get("proses")}
