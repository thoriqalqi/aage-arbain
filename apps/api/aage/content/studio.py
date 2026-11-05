"""Content & GEO Studio (M6): draf konten bersumber untuk web, media sosial, WhatsApp, marketplace, dan brosur.

Semua draf melewati ClaimGuard. Konten diterbitkan lewat antrean Approval dengan aturan dua orang: pembuat atau
pengaju draf tidak boleh menyetujui drafnya sendiri (mode "Setujui dulu" untuk agen Content). Draf yang Diblokir
tidak pernah bisa disetujui atau diekspor."""

import html
import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import claimguard, ledger, llm
from ..kb import verifikasi
from ..models import Approval, ApprovedClaim, Chunk, ContentDraft, LedgerEvent, Product
from ..textutil import rupiah

ORG = {
    "@type": "Organization",
    "name": "CV Arba'in",
    "description": "Produsen dan pemasok produk kesehatan/herbal untuk apotek, toko obat, dan minimarket.",
    "url": "https://example.com/arbain",  # ganti dengan domain resmi mitra
}
TARGET_LABEL = {"apotek": "apotek & toko obat", "konsumen": "konsumen"}

# web=True → HTML + FAQ + meta + JSON-LD (SEO/AI-search). Lainnya diekspor sebagai teks siap tempel.
FORMATS: dict[str, dict] = {
    "artikel": {"label": "Artikel SEO", "web": True, "panjang": "±350 kata, pakai heading ##"},
    "deskripsi": {"label": "Deskripsi produk (web)", "web": True, "panjang": "±120 kata"},
    "caption_ig": {"label": "Caption Instagram", "web": False, "panjang": "≤120 kata, 3–6 hashtag netral di akhir"},
    "broadcast_wa": {"label": "Broadcast WhatsApp (opt-in)", "web": False,
                     "panjang": "≤90 kata, sapaan untuk mitra apotek, ajakan balas, dan baris berhenti berlangganan"},
    "marketplace": {"label": "Deskripsi marketplace", "web": False, "panjang": "judul ≤80 karakter + poin-poin"},
    "brosur": {"label": "Brosur grosir apotek", "web": False, "panjang": "judul, 3 poin, tabel harga grosir & tier"},
}
STATUSES = {"draf", "menunggu_approval", "disetujui", "ditolak", "diarsipkan"}
OPT_OUT = "Balas STOP bila tidak ingin menerima info produk lagi."


class ContentError(Exception):
    pass


def _pagar_fakta(db: Session, p: Product) -> None:
    """Konten memuat identitas, izin, harga, dan klaim sekaligus, jadi semuanya harus lolos verifikasi."""
    sar = verifikasi.Saringan(db)
    tertahan = [verifikasi.JENIS_PRODUK[j] for j in ("produk", "izin_edar", "harga") if not sar.boleh_produk(p, j)]
    if not all([sar.boleh_klaim(c) for c in db.scalars(select(ApprovedClaim).where(ApprovedClaim.product_id == p.id))]):
        tertahan.append(verifikasi.LABEL_KLAIM)
    if tertahan:
        raise ContentError(f"Data {p.nama} belum terverifikasi ({', '.join(tertahan)}), mode data: {sar.mode}. "
                           "Verifikasi dulu di halaman Katalog.")


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


def _hashtag(s: str) -> str:
    return "#" + re.sub(r"[^0-9A-Za-z]", "", s.title())


def validate_topik(topik: str) -> str:
    t = " ".join((topik or "").split())
    if len(re.findall(r"[A-Za-z]", t)) < 3 or len(t) > 120:
        raise ContentError("Topik wajib diisi: minimal 3 huruf, maksimal 120 karakter (mis. 'stamina saat musim hujan').")
    return t


def _web_extras(db: Session, p: Product, klaim_utama: str, tl: str) -> tuple[list[dict], dict]:
    simpan = _storage_note(db)
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
    return faq, meta


def _template(db: Session, p: Product, topik: str, target: str, tipe: str) -> dict:
    claims = _claims(db, p)
    klaim_utama = claims[0].rstrip(".") if claims else "Produk herbal pilihan untuk kebutuhan harian"
    tl = TARGET_LABEL.get(target, target)
    simpan = _storage_note(db)
    harga = f"{rupiah(p.harga_dasar)} per {p.satuan_grosir}"
    faq, meta = ([], {})

    if tipe == "caption_ig":
        judul = f"Caption IG: {p.nama} · {topik}"
        isi = (f"{topik.capitalize()}? Kenalan dengan {p.nama} 🌿\n\n{klaim_utama}.\n\n"
               f"Komposisi: {_lower_first(p.komposisi)}.\nIzin edar {p.no_izin_edar}.\n\n"
               + ("Untuk apotek & toko obat: pemesanan grosir lewat WhatsApp resmi CV Arba'in.\n\n" if target == "apotek"
                  else "Tersedia di apotek dan toko obat terdekat.\n\n")
               + " ".join([_hashtag("herbal"), _hashtag("CV Arbain"), _hashtag(p.kategori), _hashtag(p.nama.split()[0])]))
    elif tipe == "broadcast_wa":
        judul = f"Broadcast WA: {p.nama} · {topik}"
        isi = (f"Halo Bapak/Ibu mitra apotek, salam dari CV Arba'in.\n\n"
               f"Info produk untuk {topik}: *{p.nama}* ({p.no_izin_edar}). {klaim_utama}.\n"
               f"Harga grosir mulai {harga}, minimum order {p.moq} {p.satuan_grosir}.\n\n"
               f"Balas *YA* untuk penawaran sesuai kebutuhan toko Bapak/Ibu.\n\n_{OPT_OUT}_")
    elif tipe == "marketplace":
        judul = f"{p.nama} – {p.kategori} Izin Edar {p.no_izin_edar}"[:80]
        isi = "\n".join([
            f"{p.nama} dari CV Arba'in. {klaim_utama}.", "",
            f"- Komposisi: {p.komposisi}", f"- Kemasan: {p.kemasan}", f"- Nomor izin edar: {p.no_izin_edar}",
            f"- Penyimpanan: {simpan}", "",
            "Catatan: produk ini bukan obat dan tidak ditujukan untuk mengobati penyakit. "
            "Untuk keluhan kesehatan, konsultasikan dengan dokter atau apoteker.",
        ])
    elif tipe == "brosur":
        judul = f"Brosur grosir: {p.nama}"
        tiers = "\n".join(f"| ≥ {r.min_qty} {p.satuan_grosir} | diskon hingga {r.diskon_maks_persen:g}% |" for r in p.pricing)
        isi = "\n\n".join(b for b in [
            f"## {p.nama}\n\n{klaim_utama}. Untuk {tl} — {topik}.",
            f"- Izin edar {p.no_izin_edar}\n- Komposisi: {_lower_first(p.komposisi)}\n- Kemasan: {_lower_first(p.kemasan)}",
            f"## Harga grosir\n\nMulai {harga} · MOQ {p.moq} {p.satuan_grosir}",
            f"| Pembelian | Diskon volume |\n|---|---|\n{tiers}" if tiers else "",
            "Pemesanan melalui WhatsApp resmi CV Arba'in. Produk ini bukan obat dan tidak ditujukan untuk mengobati penyakit.",
        ] if b)
    else:
        judul = f"{p.nama}: {topik.capitalize()}"
        if tipe == "deskripsi":
            isi = (f"**{p.nama}** adalah {p.kategori.lower()} dari CV Arba'in. {klaim_utama}.\n\n"
                   f"**Komposisi:** {p.komposisi}.\n\n**Kemasan:** {p.kemasan}.\n\n"
                   f"**Nomor izin edar:** {p.no_izin_edar}.\n\n**Penyimpanan:** {simpan}")
        else:
            bagian = [
                f"## Ringkasan\n\n{p.nama} adalah {p.kategori.lower()} dengan nomor izin edar {p.no_izin_edar}. {klaim_utama}.",
                f"## Komposisi dan kemasan\n\n{p.nama} mengandung {_lower_first(p.komposisi)}. Produk tersedia dalam "
                f"kemasan {_lower_first(p.kemasan)}.",
                "## Informasi yang disetujui\n\n" + "\n".join(f"- {c}" for c in claims) if claims else "",
                f"## Penyimpanan\n\n{simpan}",
            ]
            if target == "apotek":
                bagian.append(f"## Informasi untuk {tl}\n\nHarga grosir mulai {harga} dengan minimum order {p.moq} "
                              f"{p.satuan_grosir}. Diskon volume tersedia sesuai jumlah pembelian. "
                              "Pemesanan dapat dilakukan melalui WhatsApp resmi CV Arba'in.")
            bagian.append("## Catatan penting\n\nProduk ini bukan obat dan tidak ditujukan untuk mengobati penyakit. "
                          "Untuk keluhan kesehatan, konsultasikan dengan dokter atau apoteker.")
            isi = "\n\n".join(b for b in bagian if b)
        faq, meta = _web_extras(db, p, klaim_utama, tl)
    return {"judul": judul, "isi": isi, "faq": faq, "meta": meta}


def _llm_generate(db: Session, p: Product, topik: str, target: str, tipe: str) -> tuple[dict | None, llm.LLMResult | None]:
    claims = _claims(db, p)
    fmt = FORMATS[tipe]
    shape = ('{"judul": str, "isi": markdown, "faq": [{"q": str, "a": str}] (5 butir), '
             '"meta": {"title": ≤60 karakter, "description": ≤155 karakter}}' if fmt["web"]
             else '{"judul": str, "isi": teks}')
    extra = {
        "broadcast_wa": f" Hanya untuk kontak yang sudah opt-in; akhiri dengan kalimat persis: '{OPT_OUT}'",
        "caption_ig": " Hashtag netral (merek/kategori), jangan hashtag nama penyakit.",
        "brosur": " Sertakan tabel harga grosir dan tier diskon dari DATA saja.",
    }.get(tipe, "")
    tiers = [f"≥{r.min_qty} {p.satuan_grosir}: diskon ≤{r.diskon_maks_persen:g}%" for r in p.pricing]
    prompt = (
        f"Tulis {fmt['label']} berbahasa Indonesia untuk produk herbal berikut. ATURAN KERAS: hanya gunakan fakta di "
        "DATA; klaim manfaat HANYA dari 'Klaim disetujui' (boleh parafrase ringan); jangan sebut penyakit; jangan "
        "statistik; jangan superlatif; jangan janji hasil. Kalimat pertama langsung menjawab (answer-first)."
        f"{extra}\nDATA: nama={p.nama}; kategori={p.kategori}; komposisi={p.komposisi}; kemasan={p.kemasan}; "
        f"izin_edar={p.no_izin_edar}; harga_grosir={rupiah(p.harga_dasar)}/{p.satuan_grosir}; MOQ={p.moq}; "
        f"tier_diskon={tiers}; Klaim disetujui={claims}\nTopik/kata kunci: {topik}. "
        f"Target pembaca: {TARGET_LABEL.get(target, target)}. Panjang: {fmt['panjang']}.\nJawab JSON: {shape}"
    )
    res = llm.complete([{"role": "user", "content": prompt}], json_mode=True, max_tokens=1800, temperature=0.4)
    need = {"judul", "isi", "faq", "meta"} if fmt["web"] else {"judul", "isi"}
    if res is None or not isinstance(res.data, dict) or not need <= set(res.data):
        return None, None
    data = {"faq": [], "meta": {}, **res.data}
    if tipe == "broadcast_wa" and OPT_OUT not in data["isi"]:
        data["isi"] = data["isi"].rstrip() + f"\n\n_{OPT_OUT}_"
    return data, res


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


def json_ld_for(db: Session, d: ContentDraft) -> list[dict]:
    if not FORMATS.get(d.tipe, {}).get("web") or not d.product_id:
        return []
    return build_json_ld(db.get(Product, d.product_id), d.faq or [], d.meta or {})


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
    parts = [d.judul, re.sub(r"[#*_>|-]+", " ", d.isi)]
    parts += [f"{f['q']} {f['a']}" for f in (d.faq or [])]
    parts += [(d.meta or {}).get("title", ""), (d.meta or {}).get("description", "")]
    return "\n".join(p for p in parts if p)


def generate(db: Session, *, product_id: int, topik: str, target: str, tipe: str, aktor: str) -> ContentDraft:
    if tipe not in FORMATS:
        raise ContentError(f"Format tidak dikenal: {tipe}")
    topik = validate_topik(topik)
    p = db.get(Product, product_id)
    if p is None:
        raise ContentError("Produk tidak ditemukan")
    _pagar_fakta(db, p)
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
    d.json_ld = json_ld_for(db, d)
    check = claimguard.check(db, full_text(d), product_ids=[p.id])
    d.claim_verdict = check.verdict
    errors = validate_json_ld(d.json_ld)
    d.claim_report = {**check.to_dict(), "json_ld_errors": errors, "sumber_generator": source}
    db.add(d)
    db.flush()
    ledger.record_llm(
        db, "konten_dibuat", res, objek_ref=f"content:{d.id}", product_id=p.id, aktor=aktor,
        ringkasan=f"{FORMATS[tipe]['label']} '{d.judul}' · ClaimGuard {check.label}", verdict=check.verdict,
        aturan_terpicu=check.rules_triggered, alasan=f"Generator: {source}; JSON-LD valid: {not errors}",
        sumber_ref=[{"jenis": "produk", "product_id": p.id, "judul": p.nama}], outcome="draf",
        data={"topik": topik, "target": target, "format": tipe},
    )
    db.commit()
    return d


def recheck(db: Session, d: ContentDraft) -> ContentDraft:
    check = claimguard.check(db, full_text(d), product_ids=[d.product_id] if d.product_id else None)
    d.claim_verdict = check.verdict
    d.claim_report = {**check.to_dict(), "json_ld_errors": validate_json_ld(d.json_ld or []),
                      "sumber_generator": (d.claim_report or {}).get("sumber_generator", "edit staf")}
    return d


def edit(db: Session, d: ContentDraft, changes: dict, aktor: str) -> ContentDraft:
    if d.status == "menunggu_approval":
        raise ContentError("Draf sedang menunggu approval. Minta penyetuju menolaknya dulu bila perlu diubah.")
    if d.status == "diarsipkan":
        raise ContentError("Draf sudah diarsipkan.")
    for k in ("judul", "isi", "faq", "meta"):
        if changes.get(k) is not None:
            setattr(d, k, changes[k])
    d.json_ld = json_ld_for(db, d)
    d.status = "draf"  # konten yang diubah wajib disetujui ulang
    recheck(db, d)
    ledger.record(db, "konten_diedit", objek_ref=f"content:{d.id}", product_id=d.product_id, aktor=aktor,
                  ringkasan=f"Draf '{d.judul}' diedit · ClaimGuard {claimguard.LABELS.get(d.claim_verdict, d.claim_verdict)}",
                  verdict=d.claim_verdict, aturan_terpicu=d.claim_report.get("rules_triggered", []), outcome="draf")
    db.commit()
    return d


def creators(db: Session, d: ContentDraft) -> set[str]:
    """Aktor yang membuat atau mengedit draf (dibaca dari Ledger, satu sumber kebenaran)."""
    rows = db.scalars(select(LedgerEvent.aktor).where(LedgerEvent.objek_ref == f"content:{d.id}",
                                                      LedgerEvent.tipe_event.in_(("konten_dibuat", "konten_diedit"))))
    return set(rows)


def pending_approval(db: Session, d: ContentDraft) -> Approval | None:
    return db.scalar(select(Approval).where(Approval.objek_tipe == "konten", Approval.objek_id == d.id,
                                            Approval.status == "menunggu"))


def submit(db: Session, d: ContentDraft, aktor: str) -> Approval:
    """Ajukan draf ke antrean Approval (mode Setujui dulu)."""
    if d.status == "diarsipkan":
        raise ContentError("Draf sudah diarsipkan.")
    if d.status == "disetujui":
        raise ContentError("Draf sudah disetujui.")
    existing = pending_approval(db, d)
    if existing:
        return existing
    recheck(db, d)
    if d.claim_verdict == claimguard.BLOCKED:
        db.commit()
        raise ContentError("Draf Diblokir ClaimGuard. Perbaiki kalimat bertanda merah sebelum diajukan.")
    label = FORMATS.get(d.tipe, {}).get("label", d.tipe)
    ap = Approval(objek_tipe="konten", objek_id=d.id, intent="konten",
                  alasan=f"{label} menunggu persetujuan (mode Setujui dulu, aturan dua orang)",
                  ringkasan=f"{label} · {d.judul}", draf=d.isi, verdict=d.claim_verdict)
    db.add(ap)
    db.flush()
    d.status = "menunggu_approval"
    ledger.record(db, "approval_dibuat", objek_ref=f"approval:{ap.id}", product_id=d.product_id, aktor=aktor,
                  ringkasan=f"Konten diajukan: {d.judul}"[:280], alasan=ap.alasan, verdict=d.claim_verdict,
                  outcome="menunggu", data={"content_id": d.id, "format": d.tipe})
    db.commit()
    return ap


def approve(db: Session, d: ContentDraft, aktor: str, *, commit: bool = True) -> ContentDraft:
    if aktor in creators(db, d):
        raise ContentError("Aturan dua orang: pembuat atau pengedit draf tidak boleh menyetujui drafnya sendiri.")
    recheck(db, d)
    if d.claim_verdict == claimguard.BLOCKED:
        raise ContentError("Draf berstatus Diblokir oleh ClaimGuard dan tidak dapat disetujui/diekspor.")
    d.status = "disetujui"
    ledger.record(db, "konten_disetujui", objek_ref=f"content:{d.id}", product_id=d.product_id, aktor=aktor,
                  ringkasan=f"Konten '{d.judul}' disetujui", verdict=d.claim_verdict, outcome="disetujui")
    if commit:
        db.commit()
    return d


def archive(db: Session, d: ContentDraft, aktor: str) -> ContentDraft:
    ap = pending_approval(db, d)
    if ap:
        ap.status, ap.catatan, ap.ditinjau_oleh = "ditolak", "Draf diarsipkan", aktor.removeprefix("staf:")
    d.status = "diarsipkan"
    ledger.record(db, "konten_diarsipkan", objek_ref=f"content:{d.id}", product_id=d.product_id, aktor=aktor,
                  ringkasan=f"Draf '{d.judul}' diarsipkan", outcome="diarsipkan")
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
        raise ContentError("Konten harus disetujui lewat antrean Approval sebelum diekspor.")
    if d.claim_verdict == claimguard.BLOCKED:
        raise ContentError("Konten Diblokir ClaimGuard tidak dapat diekspor.")
    if d.product_id is not None and (p := db.get(Product, d.product_id)) is not None:
        _pagar_fakta(db, p)
    web = FORMATS.get(d.tipe, {}).get("web", True)
    out: dict = {"format": "html" if web else "teks", "markdown": f"# {d.judul}\n\n{d.isi}", "json_ld": d.json_ld}
    if web:
        faq_html = "".join(f"<h3>{html.escape(f['q'])}</h3><p>{html.escape(f['a'])}</p>" for f in d.faq)
        scripts = "\n".join(f'<script type="application/ld+json">{json.dumps(b, ensure_ascii=False)}</script>' for b in d.json_ld)
        out["html"] = (f"<title>{html.escape(d.meta.get('title', ''))}</title>\n"
                       f"<meta name=\"description\" content=\"{html.escape(d.meta.get('description', ''))}\">\n"
                       f"<h1>{html.escape(d.judul)}</h1>\n{_md_to_html(d.isi)}\n<section><h2>Pertanyaan umum</h2>{faq_html}</section>\n{scripts}")
    else:
        out["teks"] = d.isi if d.tipe in ("caption_ig", "broadcast_wa") else f"{d.judul}\n\n{d.isi}"
    ledger.record(db, "konten_diekspor", objek_ref=f"content:{d.id}", product_id=d.product_id, aktor=aktor,
                  ringkasan=f"Konten '{d.judul}' diekspor ({out['format']})", verdict=d.claim_verdict, outcome="diekspor")
    db.commit()
    return out
