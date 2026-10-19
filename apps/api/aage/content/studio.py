"""Content & GEO Studio (M6): draf artikel/deskripsi bersumber + FAQ + meta + JSON-LD.
Semua draf melewati ClaimGuard dan hanya bisa diekspor setelah disetujui staf (dan tidak Diblokir)."""

import html
import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import claimguard, ledger, llm
from ..models import ApprovedClaim, Chunk, ContentDraft, Product
from ..textutil import rupiah

ORG = {
    "@type": "Organization",
    "name": "CV Arba'in",
    "description": "Produsen dan pemasok produk kesehatan/herbal untuk apotek, toko obat, dan minimarket.",
    "url": "https://example.com/arbain",  # ganti dengan domain resmi mitra
}
TARGET_LABEL = {"apotek": "apotek & toko obat", "konsumen": "konsumen"}


class ContentError(Exception):
    pass


def _claims(db: Session, p: Product) -> list[str]:
    return [c.teks_klaim for c in db.scalars(select(ApprovedClaim).where(ApprovedClaim.product_id == p.id))]


def _storage_note(db: Session) -> str:
    ch = db.scalar(select(Chunk).where(Chunk.aktif.is_(True), Chunk.teks.like("%Simpan produk%")))
    if ch is None:
        return "Simpan di tempat sejuk dan kering, terhindar dari sinar matahari langsung."
    m = re.search(r"Simpan produk[^.]*\.", ch.teks)
    return m.group(0) if m else ch.teks[:160]


def _lower_first(s: str) -> str:
    return s[0].lower() + s[1:] if s else s


def _template(db: Session, p: Product, topik: str, target: str, tipe: str) -> dict:
    claims = _claims(db, p)
    klaim_utama = claims[0].rstrip(".") if claims else "Produk herbal pilihan untuk kebutuhan harian"
    tl = TARGET_LABEL.get(target, target)
    judul = f"{p.nama}: {topik.strip().capitalize()}" if topik else f"Mengenal {p.nama}"
    simpan = _storage_note(db)
    if tipe == "deskripsi":
        isi = (
            f"**{p.nama}** adalah {p.kategori.lower()} dari CV Arba'in. {klaim_utama}.\n\n"
            f"**Komposisi:** {p.komposisi}.\n\n**Kemasan:** {p.kemasan}.\n\n"
            f"**Nomor izin edar:** {p.no_izin_edar}.\n\n**Penyimpanan:** {simpan}"
        )
    else:
        bagian = [
            f"## Ringkasan\n\n{p.nama} adalah {p.kategori.lower()} dengan nomor izin edar {p.no_izin_edar}. "
            f"{klaim_utama}.",
            f"## Komposisi dan kemasan\n\n{p.nama} mengandung {_lower_first(p.komposisi)}. Produk tersedia dalam "
            f"kemasan {_lower_first(p.kemasan)}.",
            "## Informasi yang disetujui\n\n" + "\n".join(f"- {c}" for c in claims) if claims else "",
            f"## Penyimpanan\n\n{simpan}",
        ]
        if target == "apotek":
            bagian.append(
                f"## Informasi untuk {tl}\n\nHarga grosir mulai {rupiah(p.harga_dasar)} per {p.satuan_grosir} "
                f"dengan minimum order {p.moq} {p.satuan_grosir}. Diskon volume tersedia mulai 10 {p.satuan_grosir}. "
                "Pemesanan dapat dilakukan melalui WhatsApp resmi CV Arba'in."
            )
        bagian.append(
            "## Catatan penting\n\nProduk ini bukan obat dan tidak ditujukan untuk mengobati penyakit. "
            "Untuk keluhan kesehatan, konsultasikan dengan dokter atau apoteker."
        )
        isi = "\n\n".join(b for b in bagian if b)
    faq = [
        {"q": f"Apa itu {p.nama}?", "a": f"{p.nama} adalah {p.kategori.lower()} dari CV Arba'in. {klaim_utama}."},
        {"q": f"Apa komposisi {p.nama}?", "a": f"{p.komposisi}."},
        {"q": f"Apakah {p.nama} memiliki izin edar BPOM?", "a": f"Ya, nomor izin edarnya {p.no_izin_edar}."},
        {"q": f"Berapa minimum order {p.nama} untuk apotek?",
         "a": f"Minimum order {p.moq} {p.satuan_grosir}; harga grosir mulai {rupiah(p.harga_dasar)} per {p.satuan_grosir}."},
        {"q": f"Bagaimana cara menyimpan {p.nama}?", "a": simpan},
        {"q": f"Apa yang perlu diperhatikan sebelum mengonsumsi {p.nama}?",
         "a": f"{p.nama} bukan pengganti obat. Untuk keluhan kesehatan, konsultasikan dengan dokter atau apoteker."},
    ]
    meta = {
        "title": f"{p.nama} | Grosir {p.kategori} CV Arba'in"[:60],
        "description": f"{p.nama} ({p.no_izin_edar}). {klaim_utama}. Grosir untuk {tl}: MOQ {p.moq} {p.satuan_grosir}."[:155],
    }
    return {"judul": judul, "isi": isi, "faq": faq, "meta": meta}


def _llm_generate(db: Session, p: Product, topik: str, target: str, tipe: str) -> tuple[dict | None, llm.LLMResult | None]:
    claims = _claims(db, p)
    prompt = (
        "Tulis konten SEO & AI-search (GEO) berbahasa Indonesia untuk produk herbal berikut. ATURAN KERAS: hanya "
        "gunakan fakta di DATA; klaim manfaat HANYA dari 'Klaim disetujui' (boleh parafrase ringan); jangan sebut "
        "penyakit; jangan statistik; jangan superlatif. Paragraf pertama menjawab langsung (answer-first).\n"
        f"DATA: nama={p.nama}; kategori={p.kategori}; komposisi={p.komposisi}; kemasan={p.kemasan}; "
        f"izin_edar={p.no_izin_edar}; harga_grosir={rupiah(p.harga_dasar)}/{p.satuan_grosir}; MOQ={p.moq}; "
        f"Klaim disetujui={claims}\nTopik/kata kunci: {topik}. Target pembaca: {TARGET_LABEL.get(target, target)}. "
        f"Tipe: {tipe} ({'±350 kata, pakai heading ##' if tipe == 'artikel' else '±120 kata'}).\n"
        'Jawab JSON: {"judul": str, "isi": markdown, "faq": [{"q": str, "a": str}] (5 butir), '
        '"meta": {"title": ≤60 karakter, "description": ≤155 karakter}}'
    )
    res = llm.complete([{"role": "user", "content": prompt}], json_mode=True, max_tokens=1800, temperature=0.4)
    if res is None or not isinstance(res.data, dict) or not {"judul", "isi", "faq", "meta"} <= set(res.data):
        return None, None
    return res.data, res


def build_json_ld(p: Product, faq: list[dict], meta: dict) -> list[dict]:
    product = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": p.nama,
        "sku": p.sku,
        "description": meta.get("description", ""),
        "brand": {"@type": "Brand", "name": "CV Arba'in"},
        "manufacturer": ORG,
        "additionalProperty": [{"@type": "PropertyValue", "name": "Nomor izin edar", "value": p.no_izin_edar}],
        "offers": {
            "@type": "Offer", "priceCurrency": "IDR", "price": f"{p.harga_dasar:.0f}",
            "availability": "https://schema.org/InStock", "businessFunction": "http://purl.org/goodrelations/v1#Sell",
            "eligibleQuantity": {"@type": "QuantitativeValue", "minValue": p.moq, "unitText": p.satuan_grosir},
        },
    }
    faq_page = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [{"@type": "Question", "name": f["q"], "acceptedAnswer": {"@type": "Answer", "text": f["a"]}} for f in faq],
    }
    org = {"@context": "https://schema.org", **ORG}
    return [product, faq_page, org]


def validate_json_ld(blocks: list[dict]) -> list[str]:
    errors = []
    for b in blocks:
        try:
            json.loads(json.dumps(b, ensure_ascii=False))
        except (TypeError, ValueError) as exc:
            errors.append(f"JSON tidak valid: {exc}")
        if b.get("@context") != "https://schema.org" or "@type" not in b:
            errors.append(f"Blok {b.get('@type', '?')} tanpa @context/@type")
    return errors


def full_text(d: ContentDraft) -> str:
    parts = [d.judul, re.sub(r"[#*_>-]+", " ", d.isi)]
    parts += [f"{f['q']} {f['a']}" for f in d.faq]
    parts += [d.meta.get("title", ""), d.meta.get("description", "")]
    return "\n".join(parts)


def generate(db: Session, *, product_id: int, topik: str, target: str, tipe: str, aktor: str) -> ContentDraft:
    p = db.get(Product, product_id)
    if p is None:
        raise ContentError("Produk tidak ditemukan")
    data, res = _llm_generate(db, p, topik, target, tipe)
    source = "llm"
    if data is not None:
        check = claimguard.check(db, "\n".join([data["judul"], data["isi"], *[f"{f['q']} {f['a']}" for f in data["faq"]]]),
                                 product_ids=[p.id])
        if check.verdict == claimguard.BLOCKED:
            data, source = None, "template (draf LLM diblokir ClaimGuard)"
    if data is None:
        data = _template(db, p, topik, target, tipe)
        source = source if source != "llm" else "template"
    d = ContentDraft(product_id=p.id, tipe=tipe, topik=topik, target=target, judul=data["judul"], isi=data["isi"],
                     faq=data["faq"], meta=data["meta"])
    d.json_ld = build_json_ld(p, d.faq, d.meta)
    check = claimguard.check(db, full_text(d), product_ids=[p.id])
    d.claim_verdict = check.verdict
    errors = validate_json_ld(d.json_ld)
    d.claim_report = {**check.to_dict(), "json_ld_errors": errors, "sumber_generator": source}
    db.add(d)
    db.flush()
    ledger.record_llm(
        db, "konten_dibuat", res, objek_ref=f"content:{d.id}", product_id=p.id, aktor=aktor,
        ringkasan=f"{tipe.capitalize()} '{d.judul}' · ClaimGuard {check.label}", verdict=check.verdict,
        aturan_terpicu=check.rules_triggered, alasan=f"Generator: {source}; JSON-LD valid: {not errors}",
        sumber_ref=[{"jenis": "produk", "product_id": p.id, "judul": p.nama}], outcome="draf",
        data={"topik": topik, "target": target},
    )
    db.commit()
    return d


def recheck(db: Session, d: ContentDraft) -> ContentDraft:
    check = claimguard.check(db, full_text(d), product_ids=[d.product_id] if d.product_id else None)
    d.claim_verdict = check.verdict
    d.claim_report = {**check.to_dict(), "json_ld_errors": validate_json_ld(d.json_ld),
                      "sumber_generator": d.claim_report.get("sumber_generator", "edit staf")}
    return d


def approve(db: Session, d: ContentDraft, aktor: str) -> ContentDraft:
    recheck(db, d)
    if d.claim_verdict == claimguard.BLOCKED:
        raise ContentError("Draf berstatus Diblokir oleh ClaimGuard dan tidak dapat disetujui/diekspor.")
    d.status = "disetujui"
    ledger.record(db, "konten_disetujui", objek_ref=f"content:{d.id}", product_id=d.product_id, aktor=aktor,
                  ringkasan=f"Konten '{d.judul}' disetujui", verdict=d.claim_verdict, outcome="disetujui")
    db.commit()
    return d


def _md_to_html(md: str) -> str:
    out = []
    for block in md.split("\n\n"):
        b = block.strip()
        if b.startswith("## "):
            out.append(f"<h2>{html.escape(b[3:])}</h2>")
        elif b.startswith("- "):
            items = "".join(f"<li>{html.escape(x[2:])}</li>" for x in b.splitlines() if x.startswith("- "))
            out.append(f"<ul>{items}</ul>")
        elif b:
            out.append("<p>" + re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(b)) + "</p>")
    return "\n".join(out)


def export(db: Session, d: ContentDraft, aktor: str) -> dict:
    if d.status != "disetujui":
        raise ContentError("Konten harus disetujui staf sebelum diekspor.")
    if d.claim_verdict == claimguard.BLOCKED:
        raise ContentError("Konten Diblokir ClaimGuard tidak dapat diekspor.")
    faq_html = "".join(f"<h3>{html.escape(f['q'])}</h3><p>{html.escape(f['a'])}</p>" for f in d.faq)
    scripts = "\n".join(f'<script type="application/ld+json">{json.dumps(b, ensure_ascii=False)}</script>' for b in d.json_ld)
    page = (f"<title>{html.escape(d.meta.get('title', ''))}</title>\n"
            f"<meta name=\"description\" content=\"{html.escape(d.meta.get('description', ''))}\">\n"
            f"<h1>{html.escape(d.judul)}</h1>\n{_md_to_html(d.isi)}\n<section><h2>Pertanyaan umum</h2>{faq_html}</section>\n{scripts}")
    ledger.record(db, "konten_diekspor", objek_ref=f"content:{d.id}", product_id=d.product_id, aktor=aktor,
                  ringkasan=f"Konten '{d.judul}' diekspor", verdict=d.claim_verdict, outcome="diekspor")
    db.commit()
    return {"html": page, "markdown": f"# {d.judul}\n\n{d.isi}", "json_ld": d.json_ld}
