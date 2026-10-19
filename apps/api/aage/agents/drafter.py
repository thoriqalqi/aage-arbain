"""Drafter (Sales Agent, langkah 3): menyusun jawaban HANYA dari sumber Knowledge Base,
`pricing_rules`, dan riwayat pesanan. LLM dipakai untuk merangkai kalimat bila tersedia;
template deterministik dipakai sebagai default/fallback."""

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import llm
from ..kb.retriever import Hit, find_products, retrieve
from ..models import ApprovedClaim, Contact, Conversation, OrderDraft, Product
from ..textutil import content_tokens, rupiah, split_sentences, stem
from . import sales

HOLD_STAF = "Pertanyaan Kakak sudah kami teruskan ke staf penjualan, mohon tunggu sebentar ya 🙏"


@dataclass
class Draft:
    text: str | None  # teks yang (jika lolos) dikirim otomatis ke pembeli
    sources: list[dict] = field(default_factory=list)
    escalate: bool = False
    escalate_reason: str = ""
    staff_draft: str | None = None  # draf balasan untuk disetujui staf
    product_ids: list[int] = field(default_factory=list)
    konteks: dict = field(default_factory=dict)
    order_draft_id: int | None = None
    llm_result: llm.LLMResult | None = None
    template: str = ""


def _claims(db: Session, product_id: int) -> list[str]:
    return [c.teks_klaim for c in db.scalars(select(ApprovedClaim).where(ApprovedClaim.product_id == product_id))]


def _product_source(db: Session, p: Product, hits: list[Hit]) -> dict:
    for h in hits:
        if h.chunk.product_id == p.id:
            return h.source()
    from ..models import Chunk

    ch = db.scalar(select(Chunk).where(Chunk.product_id == p.id, Chunk.aktif.is_(True)).order_by(Chunk.id.desc()))
    if ch is None:
        return {"jenis": "produk", "product_id": p.id}
    return Hit(ch, 1.0).source()


def _pricing_source(p: Product) -> dict:
    return {"jenis": "pricing_rules", "product_id": p.id, "judul": f"Tier harga {p.sku}"}


def _template_source(name: str) -> dict:
    return {"jenis": "template", "judul": f"Template disetujui: {name}"}


def _context_products(db: Session, text: str, conv: Conversation) -> list[Product]:
    found = find_products(db, text)
    if found:
        return found
    ids = conv.konteks.get("last_product_ids") or []
    return [p for pid in ids if (p := db.get(Product, pid)) is not None]


def _llm_answer(question: str, sources: list[dict], instruction: str) -> llm.LLMResult | None:
    if not sources:
        return None
    src = "\n".join(f"[S{i + 1}] {s.get('kutipan') or s.get('judul')}" for i, s in enumerate(sources))
    prompt = (
        "Anda asisten penjualan B2B CV Arba'in (produk herbal) yang membalas pembeli lewat WhatsApp.\n"
        "Aturan: jawab HANYA dari SUMBER; jangan menambah klaim kesehatan selain 'Klaim disetujui'; "
        "jangan menyebut penyakit; bahasa Indonesia sopan dan ringkas (maks 90 kata); sapa 'Kak'. "
        "Jika jawaban tidak ada di sumber, tulis persis: TIDAK_ADA_SUMBER.\n"
        f"{instruction}\n\nSUMBER:\n{src}\n\nPertanyaan pembeli: {question}"
    )
    res = llm.complete([{"role": "user", "content": prompt}], max_tokens=350)
    if res is None or "TIDAK_ADA_SUMBER" in res.text:
        return None
    res.text = re.sub(r"\s*\[S\d+\]", "", res.text).strip()
    return res


def _best_sentences(text: str, question: str, n: int = 2) -> str:
    q = {stem(t) for t in content_tokens(question)}

    def overlap(s: str) -> int:
        return len(q & {stem(t) for t in content_tokens(s)})

    # Potongan berisi beberapa bagian ("Judul: isi" per baris) → pilih bagian paling relevan dulu.
    sections = [ln for ln in text.split("\n") if ln.strip()]
    section = max(sections, key=overlap) if sections else text
    scored = []
    for i, s in enumerate(split_sentences(section.split(": ", 1)[-1])):
        terms = {stem(t) for t in content_tokens(s)}
        scored.append((len(q & terms), -i, s))
    scored.sort(reverse=True)
    picked = [x for x in scored[:n] if x[0] > 0] or scored[:1]
    picked.sort(key=lambda x: -x[1])
    return " ".join(s for _, _, s in picked)


# ---------------------------------------------------------------- intent handlers


def draft_salam(**_) -> Draft:
    return Draft(
        "Halo, terima kasih sudah menghubungi CV Arba'in 🙏 Saya asisten AI yang siap membantu info produk, "
        "izin edar, harga grosir, dan pemesanan 24 jam. Ada yang bisa kami bantu, Kak?",
        sources=[_template_source("salam")], template="salam",
    )


def draft_tanya_produk(db: Session, text: str, conv: Conversation, hits: list[Hit], **_) -> Draft:
    products = find_products(db, text)
    if not products:
        seen: list[int] = []
        top = hits[0].score if hits else 0
        for h in hits:
            if h.chunk.product_id and h.chunk.product_id not in seen and h.score >= top * 0.6:
                seen.append(h.chunk.product_id)
        products = [db.get(Product, pid) for pid in seen[:3]]
    if not products:
        return Draft(None, escalate=True, escalate_reason="Tidak ada produk di katalog yang cocok (tanpa sumber).",
                     staff_draft=None)
    sources = [_product_source(db, p, hits) for p in products]
    res = _llm_answer(text, sources, "Sebutkan nama produk, nomor izin edar, klaim disetujui, harga grosir & MOQ.")
    if res is not None:
        return Draft(res.text, sources=sources, product_ids=[p.id for p in products],
                     konteks={"last_product_ids": [p.id for p in products]}, llm_result=res, template="llm")
    lines = ["Ada, Kak. Berikut produk dari katalog kami yang sesuai:"]
    for p in products:
        klaim = " ".join(_claims(db, p.id)) or "Belum ada klaim yang disetujui."
        lines.append(
            f"\n• *{p.nama}*\n  {klaim}\n  Komposisi: {p.komposisi}.\n  Izin edar: {p.no_izin_edar} · Kemasan: {p.kemasan}\n"
            f"  Harga grosir {rupiah(p.harga_dasar)}/{p.satuan_grosir}, MOQ {p.moq} {p.satuan_grosir}."
        )
    lines.append("\nMau saya buatkan penawaran untuk jumlah tertentu?")
    return Draft("\n".join(lines), sources=sources, product_ids=[p.id for p in products],
                 konteks={"last_product_ids": [p.id for p in products]}, template="tanya_produk")


def draft_izin_edar(db: Session, text: str, conv: Conversation, hits: list[Hit], **_) -> Draft:
    products = _context_products(db, text, conv)
    if products:
        sources = [_product_source(db, p, hits) for p in products]
        lines = [f"• {p.nama}: *{p.no_izin_edar}*" for p in products]
        body = "Nomor izin edar produk:\n" + "\n".join(lines) + "\n\nNomor ini dapat dicek di situs Cek Produk BPOM."
        return Draft(body, sources=sources, product_ids=[p.id for p in products],
                     konteks={"last_product_ids": [p.id for p in products]}, template="izin_edar")
    doc_hits = [h for h in hits if h.chunk.product_id is None]
    if doc_hits:
        return Draft(
            _best_sentences(doc_hits[0].chunk.teks, text) + "\n\nProduk mana yang ingin Kakak cek izin edarnya?",
            sources=[doc_hits[0].source()], template="izin_edar_umum",
        )
    return Draft("Produk mana yang ingin Kakak cek nomor izin edarnya?", sources=[_template_source("tanya_produk")],
                 template="izin_edar_tanya")


def draft_harga(db: Session, text: str, conv: Conversation, slots: dict, hits: list[Hit], **_) -> Draft:
    products = _context_products(db, text, conv)
    if not products and not slots.get("qty"):
        doc_hits = [h for h in hits if h.chunk.product_id is None]
        if doc_hits and doc_hits[0].score >= 0.3:
            best = doc_hits[0]
            return Draft(f"{_best_sentences(best.chunk.teks, text)}\n\nProduk mana yang ingin Kakak ketahui harganya?",
                         sources=[best.source()], template="harga_kebijakan")
    if not products:
        products = [db.get(Product, h.chunk.product_id) for h in hits[:1] if h.chunk.product_id]
    if not products:
        return Draft("Produk mana yang ingin Kakak ketahui harganya? Sebutkan nama produk dan jumlah kartonnya ya.",
                     sources=[_template_source("tanya_produk")], template="harga_tanya")
    p = products[0]
    qty = slots.get("qty") or conv.konteks.get("last_qty")
    sources = [_product_source(db, p, hits), _pricing_source(p)]
    if qty:
        q = sales.quote(db, p, int(qty))
        body = sales.format_quote(q)
        if len(products) > 1:
            body += f"\n\nIngin penawaran untuk produk lain ({', '.join(x.nama for x in products[1:])})?"
        else:
            body += "\n\nBalas *pesan* bila ingin kami buatkan draf pesanan."
        return Draft(body, sources=sources, product_ids=[p.id], template="harga_qty",
                     konteks={"last_product_ids": [p.id] + [x.id for x in products[1:]], "last_qty": int(qty),
                              "last_quote": {"product_id": p.id, "qty": int(qty), "diskon": q.diskon}})
    body = (f"Harga grosir *{p.nama}*: {rupiah(p.harga_dasar)}/{p.satuan_grosir}, MOQ {p.moq} {p.satuan_grosir}.\n"
            f"Diskon volume: {sales.tier_table(db, p)}.\nBerapa karton yang Kakak butuhkan?")
    return Draft(body, sources=sources, product_ids=[p.id], template="harga_dasar",
                 konteks={"last_product_ids": [p.id]})


def draft_negosiasi(db: Session, text: str, conv: Conversation, slots: dict, hits: list[Hit], **_) -> Draft:
    products = _context_products(db, text, conv)
    if not products:
        return Draft("Boleh tahu produk dan jumlah karton yang ingin dinegosiasikan, Kak?",
                     sources=[_template_source("tanya_produk")], template="nego_tanya")
    p = products[0]
    qty = slots.get("qty") or conv.konteks.get("last_qty")
    if not qty:
        return Draft(f"Diskon untuk *{p.nama}* mengikuti volume: {sales.tier_table(db, p)}. "
                     f"Berapa karton yang Kakak rencanakan?", sources=[_pricing_source(p)],
                     product_ids=[p.id], template="nego_tanpa_qty", konteks={"last_product_ids": [p.id]})
    qty = int(qty)
    diminta = slots.get("diskon_diminta")
    maks, _ = sales.max_discount(db, p, qty)
    sources = [_product_source(db, p, hits), _pricing_source(p)]
    konteks = {"last_product_ids": [p.id], "last_qty": qty}
    if diminta is not None and diminta > maks:
        q = sales.quote(db, p, qty)
        staff = (f"Terima kasih sudah menunggu, Kak. Untuk {qty} {p.satuan_grosir} *{p.nama}*, "
                 f"diskon maksimal yang dapat kami berikan saat ini adalah {maks:g}% sehingga harga menjadi "
                 f"{rupiah(q.harga_satuan)}/{p.satuan_grosir} (total {rupiah(q.total)}). "
                 f"Bila berkenan, balas *pesan* dan kami buatkan draf pesanannya.")
        hold = (f"Permintaan diskon {diminta:g}% untuk {qty} {p.satuan_grosir} {p.nama} melebihi batas yang bisa "
                f"saya berikan ({maks:g}%). Permintaan ini sudah saya teruskan ke staf penjualan, mohon tunggu sebentar ya 🙏")
        return Draft(hold, sources=sources, escalate=True, product_ids=[p.id], konteks=konteks,
                     escalate_reason=f"Diskon diminta {diminta:g}% > batas tier {maks:g}% (qty {qty}).",
                     staff_draft=staff, template="nego_eskalasi")
    q = sales.quote(db, p, qty, diminta)
    if diminta is not None:
        head = f"Bisa, Kak. Diskon {q.diskon:g}% masih sesuai tier volume untuk {qty} {p.satuan_grosir}."
    else:
        head = f"Harga sesuai tier volume untuk {qty} {p.satuan_grosir}:"
    konteks["last_quote"] = {"product_id": p.id, "qty": qty, "diskon": q.diskon}
    return Draft(f"{head}\n{sales.format_quote(q)}\n\nBalas *pesan* bila ingin kami buatkan draf pesanan.",
                 sources=sources, product_ids=[p.id], konteks=konteks, template="nego_dalam_tier")


def _finalize_order(db: Session, conv: Conversation, contact: Contact, lines: list[tuple[Product, int]],
                    sources: list[dict], konteks: dict, template: str) -> Draft:
    items, total = sales.build_items(db, lines)
    od = OrderDraft(contact_id=contact.id, conversation_id=conv.id, item=items, nama_toko=contact.nama_toko,
                    alamat=contact.alamat, total=total)
    db.add(od)
    db.flush()
    summary = sales.format_order(items, contact.nama_toko, contact.alamat, total)
    konteks = {**konteks, "order_pending": None}
    return Draft(
        f"Draf pesanan #{od.id} sudah saya buat dan *menunggu konfirmasi staf*:\n{summary}\n\n"
        "Staf kami akan mengonfirmasi stok dan total tagihan segera.",
        sources=sources, product_ids=[p.id for p, _ in lines], konteks=konteks, order_draft_id=od.id,
        staff_draft=(f"Pesanan #{od.id} sudah kami konfirmasi, Kak 🙏\n{summary}\n"
                     "Tagihan dan jadwal pengiriman akan kami kirimkan setelah ini."),
        template=template,
    )


def draft_pesan(db: Session, text: str, conv: Conversation, contact: Contact, slots: dict, hits: list[Hit], **_) -> Draft:
    pending = dict(conv.konteks.get("order_pending") or {})
    products = find_products(db, text)
    if products:
        pending["product_ids"] = [p.id for p in products]
    elif not pending.get("product_ids"):
        lq = conv.konteks.get("last_quote")
        ids = [lq["product_id"]] if lq else (conv.konteks.get("last_product_ids") or [])[:1]
        if ids:
            pending["product_ids"] = ids
    if slots.get("qty") and not (slots.get("qty_bare") and pending.get("qty")):
        pending["qty"] = slots["qty"]
    elif not pending.get("qty"):
        lq = conv.konteks.get("last_quote")
        if lq:
            pending["qty"] = lq["qty"]
    sales.ensure_contact_details(contact, slots)

    missing = []
    if not pending.get("product_ids"):
        missing.append("nama produk")
    if not pending.get("qty"):
        missing.append("jumlah karton")
    if not contact.nama_toko:
        missing.append("nama toko")
    if not contact.alamat:
        missing.append("alamat pengiriman")
    if missing:
        return Draft(f"Siap, Kak. Untuk menyusun draf pesanan, mohon lengkapi: {', '.join(missing)}.",
                     sources=[_template_source("pesanan")], konteks={"order_pending": pending},
                     template="pesan_lengkapi")
    lines = [(db.get(Product, pid), int(pending["qty"])) for pid in pending["product_ids"][:1]]
    sources = [_product_source(db, p, hits) for p, _ in lines] + [_pricing_source(p) for p, _ in lines]
    return _finalize_order(db, conv, contact, lines, sources, {"last_product_ids": pending["product_ids"]}, "pesan")


def draft_pesan_ulang(db: Session, text: str, conv: Conversation, contact: Contact, hits: list[Hit], **_) -> Draft:
    last = sales.last_order(db, contact.id)
    if last is None:
        return Draft("Kami belum menemukan riwayat pesanan sebelumnya untuk nomor ini. Produk dan jumlah apa yang "
                     "ingin dipesan, Kak?", sources=[_template_source("pesanan")], konteks={"order_pending": {}},
                     template="pesan_ulang_kosong")
    lines = [(p, int(it["qty"])) for it in last.item if (p := db.get(Product, it["product_id"])) is not None]
    sources = [{"jenis": "order_draft", "order_draft_id": last.id, "judul": f"Pesanan terakhir #{last.id}"}]
    sources += [_pricing_source(p) for p, _ in lines]
    if not contact.nama_toko and last.nama_toko:
        contact.nama_toko = last.nama_toko
    if not contact.alamat and last.alamat:
        contact.alamat = last.alamat
    return _finalize_order(db, conv, contact, lines, sources, {"last_product_ids": [p.id for p, _ in lines]},
                           "pesan_ulang")


def draft_klaim(db: Session, text: str, conv: Conversation, hits: list[Hit], **_) -> Draft:
    products = _context_products(db, text, conv)
    lines = ["Mohon maaf, Kak 🙏 Produk kami adalah produk herbal/suplemen yang tidak ditujukan untuk mengobati "
             "atau menyembuhkan penyakit, jadi kami tidak dapat memberikan klaim tersebut."]
    sources = [_template_source("penolakan klaim")]
    for p in products[:1]:
        klaim = _claims(db, p.id)
        if klaim:
            lines.append(f"Informasi yang disetujui untuk *{p.nama}*: {' '.join(klaim)}")
            sources.append(_product_source(db, p, hits))
    lines.append("Untuk kondisi kesehatan tertentu, sebaiknya konsultasikan dengan dokter atau apoteker. "
                 "Apakah Kakak ingin dihubungkan dengan staf kami?")
    return Draft("\n\n".join(lines), sources=sources, product_ids=[p.id for p in products[:1]],
                 konteks={"tawar_staf": True}, template="penolakan_klaim")


def draft_medis(db: Session, text: str, **_) -> Draft:
    return Draft(
        "Terima kasih sudah bercerita, Kak 🙏 Untuk pertanyaan yang berkaitan dengan kondisi kesehatan pribadi, "
        "kami sarankan berkonsultasi dengan dokter atau apoteker. " + HOLD_STAF,
        sources=[_template_source("medis personal")], escalate=True,
        escalate_reason="Pertanyaan medis personal selalu ditangani staf/tenaga kesehatan.",
        staff_draft=("Halo Kak, kami dari tim CV Arba'in. Terkait pertanyaan Kakak, karena menyangkut kondisi "
                     "kesehatan pribadi, kami sarankan berkonsultasi dengan dokter atau apoteker sebelum "
                     "mengonsumsi produk herbal apa pun. Ada informasi produk lain yang bisa kami bantu?"),
        template="medis_personal",
    )


def draft_keluhan(db: Session, text: str, hits: list[Hit], **_) -> Draft:
    retur = next((h for h in hits if "retur" in h.chunk.teks.lower()), None)
    staff = ("Mohon maaf atas ketidaknyamanannya, Kak. Kami sudah menerima keluhannya. "
             "Mohon kirimkan foto produk/kemasan dan nomor pesanan agar kami proses penggantian sesuai kebijakan retur.")
    return Draft(
        "Mohon maaf atas ketidaknyamanannya, Kak 🙏 Keluhan Kakak sudah kami catat dan kami teruskan ke staf "
        "penjualan yang akan segera menghubungi untuk penyelesaian.",
        sources=[_template_source("keluhan")] + ([retur.source()] if retur else []),
        escalate=True, escalate_reason="Keluhan pembeli selalu ditangani staf.", staff_draft=staff, template="keluhan",
    )


def draft_minta_staf(**_) -> Draft:
    return Draft("Baik, Kak. " + HOLD_STAF, sources=[_template_source("minta staf")], escalate=True,
                 escalate_reason="Pembeli meminta bicara dengan staf.",
                 staff_draft="Halo Kak, saya staf penjualan CV Arba'in. Ada yang bisa saya bantu?",
                 konteks={"tawar_staf": False}, template="minta_staf")


def draft_dokumen(db: Session, text: str, conv: Conversation, hits: list[Hit], **_) -> Draft:
    doc_hits = [h for h in hits if h.chunk.product_id is None] or hits
    if not doc_hits:
        return Draft("Terima kasih, Kak. " + HOLD_STAF, sources=[_template_source("eskalasi")], escalate=True,
                     escalate_reason="Tidak ada sumber di Knowledge Base untuk pertanyaan ini.", staff_draft=None,
                     template="tanpa_sumber")
    best = doc_hits[0]
    sources = [best.source()]
    res = _llm_answer(text, sources, "Jawab pertanyaan kebijakan/umum secara ringkas.")
    if res is not None:
        return Draft(res.text, sources=sources, llm_result=res, template="llm")
    return Draft(f"Berikut info dari {best.chunk.document.judul.split(' (')[0].lower()} kami:\n"
                 f"{_best_sentences(best.chunk.teks, text)}", sources=sources, template="kutipan_dokumen")


HANDLERS = {
    "salam": draft_salam,
    "tanya_produk": draft_tanya_produk,
    "izin_edar": draft_izin_edar,
    "harga_moq": draft_harga,
    "negosiasi": draft_negosiasi,
    "pesan": draft_pesan,
    "pesan_ulang": draft_pesan_ulang,
    "klaim_kesehatan": draft_klaim,
    "medis_personal": draft_medis,
    "keluhan": draft_keluhan,
    "minta_staf": draft_minta_staf,
    "kebijakan": draft_dokumen,
    "lainnya": draft_dokumen,
}
