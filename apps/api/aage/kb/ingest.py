"""Knowledge Base (M1): impor katalog CSV/XLSX dan ingest dokumen PDF/DOCX/URL/teks.

Setiap potongan menyimpan sumber + versi. Impor versi baru menonaktifkan potongan versi lama,
tetapi tidak menghapusnya — event Ledger lama tetap bisa ditelusuri ke versi yang dipakai saat itu."""

import csv
import io
import re
from dataclasses import dataclass

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .. import ledger, llm
from ..models import ApprovedClaim, Chunk, Document, PricingRule, Product
from ..textutil import rupiah

CATALOG_COLUMNS = {"sku", "nama"}


@dataclass
class ImportResult:
    document_id: int
    versi: int
    produk: int
    klaim: int
    potongan: int


def _rows_from_upload(filename: str, content: bytes) -> list[dict]:
    if filename.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        header = [str(h).strip().lower() for h in rows[0]]
        return [{header[i]: ("" if v is None else str(v)) for i, v in enumerate(r)} for r in rows[1:] if any(r)]
    text = content.decode("utf-8-sig")
    return [{k.strip().lower(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(io.StringIO(text))]


def product_chunk_text(p: Product, claims: list[str]) -> str:
    klaim = " ".join(claims) if claims else "Belum ada klaim disetujui."
    return (
        f"Produk: {p.nama} (SKU {p.sku}). Kategori: {p.kategori}. "
        f"Komposisi: {p.komposisi}. Kemasan: {p.kemasan}. "
        f"Nomor izin edar: {p.no_izin_edar}. "
        f"Harga dasar grosir: {rupiah(p.harga_dasar)} per {p.satuan_grosir}. MOQ: {p.moq} {p.satuan_grosir}. "
        f"Klaim disetujui: {klaim} Kata kunci: {p.kata_kunci}."
        + _teknis_text(p)
    )


def _teknis_text(p: Product) -> str:
    t = p.data_teknis or {}
    if not t:
        return ""
    bko = t.get("status_bebas_bko", {})
    halal = t.get("sertifikasi_halal", {})
    return (f" Sertifikasi halal: {halal.get('status', '-')}. Uji BKO: {bko.get('hasil', '-')} ({bko.get('nomor_laporan_uji', '-')})."
            f" HET: {rupiah(p.het_per_botol or 0)}/botol.")


def _next_version(db: Session, judul: str) -> int:
    current = db.scalar(select(func.max(Document.versi)).where(Document.judul == judul))
    return (current or 0) + 1


def import_catalog(db: Session, rows: list[dict], *, judul: str = "Katalog Produk", aktor: str = "admin",
                   verifikator: str | None = None) -> ImportResult:
    missing = CATALOG_COLUMNS - set(rows[0].keys()) if rows else CATALOG_COLUMNS
    if missing:
        raise ValueError(f"Kolom wajib tidak ada: {', '.join(sorted(missing))}")

    versi = _next_version(db, judul)
    db.execute(update(Document).where(Document.judul == judul).values(aktif=False))
    old_doc_ids = select(Document.id).where(Document.judul == judul).scalar_subquery()
    db.execute(update(Chunk).where(Chunk.document_id.in_(old_doc_ids)).values(aktif=False))
    doc = Document(judul=judul, tipe="katalog", file=f"{judul} v{versi}", versi=versi)
    db.add(doc)
    db.flush()

    n_claims = 0
    chunk_ids = []
    for row in rows:
        sku = row["sku"].strip()
        p = db.scalar(select(Product).where(Product.sku == sku))
        if p is None:
            p = Product(sku=sku)
            db.add(p)
        p.nama = row.get("nama", p.nama)
        p.kategori = row.get("kategori", "")
        p.komposisi = row.get("komposisi", "")
        p.kemasan = row.get("kemasan", "")
        p.satuan_grosir = row.get("satuan_grosir") or "box"
        p.no_izin_edar = row.get("no_izin_edar", "")
        p.harga_dasar = float(row.get("harga_dasar") or 0)
        p.moq = int(float(row.get("moq") or 1))
        p.kata_kunci = row.get("kata_kunci", "")
        p.sumber_data = row.get("sumber_data") or "sintetis"
        p.larangan = list(row.get("larangan") or [])
        p.data_teknis = dict(row.get("data_teknis") or {})
        p.het_per_botol = row.get("het_per_botol")
        p.aktif = True
        db.flush()

        claims_text = [c.strip() for c in (row.get("klaim_disetujui") or "").split("|") if c.strip()]
        if claims_text:
            existing = {c.teks_klaim for c in db.scalars(select(ApprovedClaim).where(ApprovedClaim.product_id == p.id))}
            for teks in claims_text:
                if teks in existing:
                    continue
                db.add(ApprovedClaim(product_id=p.id, teks_klaim=teks, sumber_dokumen=f"{judul} v{versi}",
                                     diverifikasi_oleh=verifikator, embedding=llm.embed(teks)))
                n_claims += 1

        teks = product_chunk_text(p, claims_text)
        ch = Chunk(document_id=doc.id, product_id=p.id, teks=teks, halaman=None,
                   embedding=llm.embed(teks), versi=versi)
        db.add(ch)
        db.flush()
        chunk_ids.append(ch.id)

    ledger.record(db, "katalog_diimpor", aktor=aktor, objek_ref=f"document:{doc.id}",
                  ringkasan=f"{judul} v{versi}: {len(rows)} produk, {n_claims} klaim baru",
                  sumber_ref=[{"document_id": doc.id, "versi": versi, "judul": judul}],
                  outcome="sukses", model=llm.OFFLINE_MODEL)
    db.commit()
    return ImportResult(doc.id, versi, len(rows), n_claims, len(chunk_ids))


def import_pricing(db: Session, rows: list[dict]) -> int:
    products = list(db.scalars(select(Product)))
    n = 0
    default_rows = [r for r in rows if r["sku"] == "*"]
    specific = [r for r in rows if r["sku"] != "*"]
    for p in products:
        db.query(PricingRule).filter(PricingRule.product_id == p.id).delete()
        tiers = {int(r["min_qty"]): float(r["diskon_maks_persen"]) for r in default_rows}
        for r in specific:
            if r["sku"] == p.sku:
                tiers[int(r["min_qty"])] = float(r["diskon_maks_persen"])
        for q, d in sorted(tiers.items()):
            db.add(PricingRule(product_id=p.id, min_qty=q, diskon_maks_persen=d))
            n += 1
    db.commit()
    return n


def rows_from_products_json(data: dict) -> tuple[list[dict], list[dict]]:
    """Ubah config/mock_products.json → baris katalog + baris tier harga (satuan grosir = box)."""
    rows, tiers = [], []
    for p in data["produk"]:
        m = p["matriks_harga_b2b"]
        isi = m["isi_per_box_botol"]
        rows.append({
            "sku": p["id"], "nama": p["nama_produk"], "kategori": p["kategori"],
            "komposisi": "; ".join(p["bahan_aktif"]), "kemasan": f"{p['kemasan']}; box isi {isi} botol",
            "satuan_grosir": "box", "no_izin_edar": p["nomor_izin_edar_bpom"],
            "harga_dasar": m["harga_dasar_b2b_per_botol"] * isi, "moq": m["moq_minimal_box"],
            "kata_kunci": p.get("kata_kunci", ""), "klaim_disetujui": "|".join(p["klaim_khasiat_resmi_bpom"]),
            "sumber_data": "simulasi", "larangan": p["kata_kunci_larangan_overclaim"],
            "data_teknis": {**p["data_teknis_kefarmasian"], "sertifikasi_halal": p["sertifikasi_halal"]},
            "het_per_botol": m["harga_eceran_tertinggi_het"],
        })
        tiers += [{"sku": p["id"], "min_qty": t["min_box"], "diskon_maks_persen": t["diskon_persen"]} for t in m["skema_diskon"]]
    return rows, tiers


def chunk_text(text: str, size: int = 700, overlap: int = 120) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    heading = ""
    for p in paras:
        if p.startswith("#"):
            heading = p.lstrip("# ").strip()
            continue
        piece = f"{heading}: {p}" if heading else p
        if len(buf) + len(piece) + 1 <= size:
            buf = f"{buf}\n{piece}".strip()
        else:
            if buf:
                chunks.append(buf)
            tail = buf[-overlap:] if buf and overlap else ""
            buf = f"{tail} {piece}".strip() if len(piece) < size else piece
    if buf:
        chunks.append(buf)
    return chunks


def extract_text(filename: str | None, content: bytes | None, url: str | None) -> tuple[str, str]:
    if url:
        resp = httpx.get(url, timeout=15, follow_redirects=True, headers={"User-Agent": "AAGE/0.1"})
        resp.raise_for_status()
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        lines = [ln.strip() for ln in soup.get_text("\n").splitlines() if ln.strip()]
        return "\n\n".join(lines), "url"
    assert filename and content is not None
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages), "pdf"
    if name.endswith(".docx"):
        import docx

        d = docx.Document(io.BytesIO(content))
        return "\n\n".join(p.text for p in d.paragraphs if p.text.strip()), "docx"
    return content.decode("utf-8-sig"), "teks"


def ingest_document(db: Session, *, judul: str, text: str, tipe: str, url: str | None = None,
                    aktor: str = "admin") -> Document:
    versi = _next_version(db, judul)
    old_doc_ids = select(Document.id).where(Document.judul == judul).scalar_subquery()
    db.execute(update(Chunk).where(Chunk.document_id.in_(old_doc_ids)).values(aktif=False))
    db.execute(update(Document).where(Document.judul == judul).values(aktif=False))
    doc = Document(judul=judul, tipe=tipe, url=url, file=None if url else judul, versi=versi)
    db.add(doc)
    db.flush()
    products = list(db.scalars(select(Product)))
    pieces = chunk_text(text)
    for i, piece in enumerate(pieces, start=1):
        low = piece.lower()
        pid = next((p.id for p in products if p.nama.lower() in low), None)
        db.add(Chunk(document_id=doc.id, product_id=pid, teks=piece, halaman=i, embedding=llm.embed(piece), versi=versi))
    ledger.record(db, "dokumen_diingest", aktor=aktor, objek_ref=f"document:{doc.id}",
                  ringkasan=f"{judul} v{versi}: {len(pieces)} potongan",
                  sumber_ref=[{"document_id": doc.id, "versi": versi, "judul": judul, "url": url}],
                  outcome="sukses", model=llm.OFFLINE_MODEL)
    db.commit()
    return doc
