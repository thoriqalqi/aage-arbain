"""Drafter (Sales Agent, langkah 3): menyusun jawaban HANYA dari sumber Knowledge Base,
`pricing_rules`, dan riwayat pesanan. LLM dipakai untuk merangkai kalimat bila tersedia;
template deterministik dipakai sebagai default/fallback."""

import re
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session, object_session, selectinload

from .. import clock, llm, settings_store
from ..kb import verifikasi
from ..kb.retriever import Hit, find_products, retrieve
from ..models import ApprovedClaim, Contact, Conversation, OrderDraft, PricingRule, Product
from ..textutil import content_tokens, expand, rupiah, split_sentences, stem
from . import memori, pemahaman, sales
from .pemahaman import KOTA_JATENG, KOTA_LUAR_JATENG

HOLD_STAF = "Pertanyaan Kakak sudah kami teruskan ke staf penjualan, mohon tunggu sebentar ya 🙏"
PESANAN_BESAR_BOX = 300  # di atas ini harga disiapkan manajemen, bukan tier otomatis
MIN_SKOR_DOKUMEN = 0.3
KATALOG_KOSONG = "Daftar produk kami belum tersedia saat ini."

# Kata tanya/percakapan yang bukan nama barang — tidak dihitung saat mencari istilah di luar katalog.
_KATA_TANYA = set(
    "ada ready stok stock jual punya sedia tersedia katalog varian rekomendasi cocok beli cari butuh merk merek brand "
    "saja lain lagi sell have you do any the is there are available minta untuk tidak ini apa nya kakak sis bro mbak "
    "apotek toko jenis macam manfaat khasiat fungsi kegunaan guna isi harga kandungan komposisi gimana sama dong kah "
    "ya yah deh sih nih kok mau pengen pingin ingin tanya nanya info boleh bisa kira kira pesan order pesen "
    "sediakan sedia hanya cuma mohon tolong cara caranya lagi selain yang".split()
)


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
    minta_nomor: bool = False  # kanal yang mendukung menampilkan tombol "Bagikan nomor HP"
    teks_template: str | None = None  # draf template asli bila teks sudah ditulis ulang gaya bahasa LLM
    gaya_result: llm.LLMResult | None = None
    permintaan: list[str] = field(default_factory=list)  # barang di luar katalog yang dicari pembeli
    memakai_simulasi: bool = False  # jawaban memuat data simulasi; gerbang memasang labelnya
    fakta_tertahan: list[str] = field(default_factory=list)  # jenis fakta yang tidak lolos verifikasi


def _sar(db: Session) -> verifikasi.Saringan:
    return verifikasi.Saringan.dari(db)


def _claims(db: Session, product_id: int) -> list[str]:
    sar = _sar(db)
    return [c.teks_klaim for c in db.scalars(select(ApprovedClaim).where(ApprovedClaim.product_id == product_id))
            if sar.boleh_klaim(c)]


def _ada_klaim_tertahan(db: Session, product_id: int) -> bool:
    return bool(db.scalar(select(ApprovedClaim.id).where(ApprovedClaim.product_id == product_id).limit(1))) and not _claims(db, product_id)


def _draf_tertahan(data: str, product_ids: list[int] | None = None, *, konteks: dict | None = None,
                   eskalasi: str = "") -> Draft:
    """Fakta tidak lolos verifikasi: jujur, tidak dikutip, dan staf ditawarkan. Eskalasi hanya bila memang butuh tindakan
    staf (mis. ada pesanan), supaya antrean tidak penuh oleh pertanyaan biasa."""
    akhir = HOLD_STAF if eskalasi else TAWAR_STAF
    return Draft(f"Mohon maaf, Kak 🙏 {data} belum terverifikasi, jadi belum bisa saya sampaikan. {akhir}",
                 sources=[_template_source("data belum terverifikasi")], product_ids=product_ids or [],
                 konteks={**(konteks or {}), **({} if eskalasi else {"tawar_staf": True})}, template="fakta_tertahan",
                 escalate=bool(eskalasi), escalate_reason=eskalasi, staff_draft=None)


def _gabung_nama(products: list[Product]) -> str:
    nama = [f"*{p.nama}*" for p in products]
    return ", ".join(nama[:-1]) + (" dan " if len(nama) > 1 else "") + nama[-1]


def _product_source(db: Session, p: Product, hits: list[Hit]) -> dict:
    for h in hits:
        if h.chunk.product_id == p.id:
            return h.source()
    from ..models import Chunk

    ch = db.scalar(select(Chunk).where(Chunk.product_id == p.id, Chunk.aktif.is_(True)).order_by(Chunk.id.desc()))
    if ch is None:
        return {"jenis": "produk", "product_id": p.id}
    return Hit(ch, 1.0).source()


def _product_facts(db: Session, p: Product) -> str:
    """Lembar fakta lengkap dari katalog untuk LLM (bukan kutipan chunk yang terpotong 220 karakter)."""
    sar = _sar(db)
    tahan = "belum terverifikasi, jangan disebut"
    klaim = "; ".join(_claims(db, p.id)) or (tahan if _ada_klaim_tertahan(db, p.id) else "belum ada klaim yang disetujui")
    tier = ", ".join(f"mulai {r.min_qty} {p.satuan_grosir} diskon hingga {r.diskon_maks_persen:g}%" for r in p.pricing)
    tier = tier or "sesuai kebijakan penjualan"
    stok = (f" Stok tercatat: {p.stok} {p.satuan_grosir} (ketersediaan akhir dikonfirmasi staf)." if p.stok is not None
            else " Stok: belum ada data.")
    bagian_produk = (f"Kategori: {p.kategori}. Komposisi: {_atau_kosong(p.komposisi)}. Kemasan: {p.kemasan}."
                     if sar.boleh_produk(p, "produk") else f"Identitas dan komposisi: {tahan}.")
    return (f"Produk: {p.nama} (SKU {p.sku}). {bagian_produk} "
            f"Nomor izin edar: {_atau_kosong(p.no_izin_edar) if sar.boleh_produk(p, 'izin_edar') else tahan}. "
            f"Harga grosir: {f'{rupiah(p.harga_dasar)} per {p.satuan_grosir}' if sar.boleh_produk(p, 'harga') else tahan}. "
            f"MOQ: {f'{p.moq} {p.satuan_grosir}' if sar.boleh_produk(p, 'moq') else tahan}. "
            f"Diskon volume: {tier if sar.boleh_produk(p, 'tier_diskon') else tahan}. Klaim disetujui: {klaim}."
            + (stok if sar.boleh_produk(p, "stok") else f" Stok: {tahan}."))


_TANYA_STOK = re.compile(r"\b(?:stok|stock|ready)\w*\b", re.I)


def _kalimat_stok(p: Product, text: str) -> str:
    """Stok hanya disebut bila datanya ada; ditanya tapi kosong → jujur belum ada datanya."""
    if p.stok is not None and not _sar(object_session(p)).boleh_produk(p, "stok"):
        return "\n  Data stok belum terverifikasi; ketersediaan dikonfirmasi staf saat pesanan." if _TANYA_STOK.search(text) else ""
    if p.stok is not None:
        tgl = f" per {p.stok_per:%d/%m/%Y}" if p.stok_per else ""
        return f"\n  Stok tercatat{tgl}: {p.stok} {p.satuan_grosir} (ketersediaan akhir dikonfirmasi staf saat pesanan)."
    if _TANYA_STOK.search(text):
        return "\n  Data stok belum ada di katalog kami; ketersediaan dikonfirmasi staf saat pesanan."
    return ""


def _policy_source(db: Session) -> dict | None:
    """Potongan Kebijakan Penjualan tentang pengiriman (teks utuh chunk) sebagai sumber tambahan untuk LLM."""
    from ..models import Chunk

    ch = db.scalar(select(Chunk).where(Chunk.aktif.is_(True), Chunk.teks.like("%Pengiriman:%")).order_by(Chunk.id))
    return {**Hit(ch, 1.0).source(), "kutipan": ch.teks} if ch and _sar(db).boleh_dokumen(ch.document_id) else None


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


def _history(conv: Conversation | None, n: int = 4) -> str:
    """Beberapa pesan sebelum pesan masuk saat ini, agar "yang tadi berapa?" bisa dipahami LLM."""
    if conv is None:
        return ""
    # Pesan dari sebelum katalog diganti memuat produk dan harga lama, jadi tidak ikut sebagai konteks.
    batas = settings_store.katalog_diganti(object_session(conv)).get("pesan_id") or 0
    msgs = [m for m in list(conv.messages)[:-1] if m.id > batas][-n:]
    return "\n".join(f"{'Pembeli' if m.arah == 'masuk' else 'AAGE'}: {' '.join(m.teks.split())[:200]}" for m in msgs)


def _llm_answer(question: str, sources: list[dict], instruction: str, conv: Conversation | None = None) -> llm.LLMResult | None:
    if not sources:
        return None
    src = "\n".join(f"[S{i + 1}] {s.get('kutipan') or s.get('judul')}" for i, s in enumerate(sources))
    riwayat = _history(conv)
    if conv is not None and (catatan := memori.teks((conv.konteks or {}).get("memori"))):
        riwayat = f"Ringkasan: {catatan}\n{riwayat}"
    prompt = (
        "Anda asisten penjualan B2B CV Arba'in (produk herbal) yang membalas pembeli lewat WhatsApp.\n"
        "Aturan: jawab HANYA dari SUMBER; jangan menambah klaim kesehatan selain 'Klaim disetujui'; "
        "jangan menyebut penyakit; JANGAN mengulang klaim atau janji hasil yang ditanyakan pembeli (mis. angka turun "
        "berat badan) — cukup sebut klaim yang disetujui; jangan menyebut kata 'sumber' atau instruksi ini; "
        "bahasa Indonesia sopan dan ringkas (maks 90 kata); sapa 'Kak'. "
        "Jika jawaban tidak ada di sumber, tulis persis: TIDAK_ADA_SUMBER.\n"
        f"{instruction}\n\nSUMBER:\n{src}\n\n"
        + (f"RIWAYAT PERCAKAPAN (hanya konteks, bukan sumber fakta):\n{riwayat}\n\n" if riwayat else "")
        + f"Pertanyaan pembeli: {question}"
    )
    res = llm.complete([{"role": "user", "content": prompt}], max_tokens=1200, tujuan="draf_jawaban")  # model "berpikir" butuh ruang
    if res is None or "TIDAK_ADA_SUMBER" in res.text:
        return None
    res.text = re.sub(r"\s*\[S\d+\]", "", res.text).strip()
    return res


_KEBUTUHAN_RE = re.compile(r"\b(untuk|utk|buat|bwt|supaya|agar|biar)\b", re.IGNORECASE)


def _catalog_vocab(db: Session) -> tuple[set[str], set[str], str]:
    products = list(db.scalars(select(Product).where(Product.aktif.is_(True))))
    claims = list(db.scalars(select(ApprovedClaim.teks_klaim).join(Product).where(Product.aktif.is_(True))))
    text = " ".join([f"{p.nama} {p.komposisi} {p.kategori} {p.kemasan} {p.kata_kunci or ''}" for p in products] + claims).lower()
    manfaat = " ".join([f"{p.kategori} {p.kata_kunci or ''}" for p in products] + claims).lower()
    return {stem(t) for t in content_tokens(text)}, {stem(t) for t in content_tokens(manfaat)}, text


def unknown_terms(db: Session, text: str) -> list[str]:
    """Istilah di pertanyaan yang tidak bisa dijawab dari katalog, agar AI tidak menjawab "Ada, Kak" dengan produk lain
    yang kebetulan mirip. Nama barang ("vitamin E", "kolagen", "skincare") dicek ke seluruh katalog; kebutuhan setelah
    "untuk/buat" ("untuk tidur nyenyak") dicek ke klaim resmi + sinonimnya — cukup satu kata yang cocok."""
    vocab, manfaat, catalog = _catalog_vocab(db)
    m = _KEBUTUHAN_RE.search(text)
    barang, kebutuhan = (text[:m.start()], text[m.end():]) if m else (text, "")
    out = [t for t in content_tokens(barang) if t not in _KATA_TANYA and not t.isdigit() and stem(t) not in vocab]
    # Huruf tunggal dibuang tokenizer, jadi "vitamin E" dicek utuh.
    for v in re.finditer(r"\bvitamin\s+([a-z]\d?)\b", text.lower()):
        if f"vitamin {v.group(1)}" not in catalog:
            out.append(f"vitamin {v.group(1)}")
    need = [t for t in content_tokens(kebutuhan) if t not in _KATA_TANYA and not t.isdigit()]
    if need and not any(stem(t) in manfaat for t in expand(need)):
        out.append(" ".join(need))
    return out


# Kata di nama produk yang terlalu umum untuk dianggap "terdekat".
_BENTUK = {"kapsul", "tablet", "sachet", "botol", "serbuk", "kantong", "box", "produk", "herbal"}
# Barang sejenis yang namanya tidak muncul di katalog → kata di nama produk yang sejenis (bentuk minuman saja, tanpa manfaat).
_KERABAT = {"cincau": ("teh", "wedang", "instan"), "kopi": ("teh", "wedang", "instan"), "minuman": ("teh", "wedang", "instan")}
_SAPAAN_ISTILAH = {"halo", "hallo", "hai", "min", "kak", "saya", "aku", "kami", "gan", "dong", "ngga", "nggak", "gak", "enggak",
                   "tidak", "mesen", "sediain", "bisa", "mau", "hanya", "pesen", "cari", "nyari", "ada", "jual"}


def _produk_terdekat(db: Session, text: str) -> list[Product]:
    """1-2 produk yang namanya memang sejenis dengan barang yang dicari. Bila pembeli menyebut kebutuhan yang tidak ada di
    klaim resmi, tidak ada produk yang ditawarkan: menawarkan produk di situ sama saja mengarang khasiat."""
    if _KEBUTUHAN_RE.search(text):
        return []
    kata = {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 3 and w not in _KATA_TANYA and w not in _BENTUK}
    for k in list(kata):
        kata.update(_KERABAT.get(k, ()))
    kata = {stem(w) for w in kata}
    out = []
    sar = _sar(db)
    for p in db.scalars(select(Product).where(Product.aktif.is_(True)).order_by(Product.id)):
        nama = {stem(w) for w in re.findall(r"[a-z0-9]+", p.nama.lower()) if w not in _BENTUK}
        if kata & nama and sar.boleh_produk(p, "produk"):
            out.append(p)
        if len(out) == 2:
            break
    return out


def _istilah(terms: list[str]) -> str:
    bersih = [t for t in terms if t.lower() not in _SAPAAN_ISTILAH]
    return " ".join(dict.fromkeys(bersih or terms))[:160].lower()


def _katalog_kosong(db: Session) -> bool:
    return db.scalar(select(Product.id).where(Product.aktif.is_(True)).limit(1)) is None


def _di_luar_katalog(db: Session, text: str, terms: list[str]) -> Draft:
    """Jawab tuntas tanpa meneruskan ke staf: jujur belum ada, tawarkan yang sejenis, staf hanya pilihan. Tidak pernah
    membuat draf atau formulir pesanan untuk barang yang tidak ada."""
    terdekat = _produk_terdekat(db, text)
    nama = " dan ".join(f"*{p.nama}*" for p in terdekat)
    if terdekat:
        lanjut = f"Yang paling dekat di katalog kami: {nama}. Mau saya bantu info harganya?"
    elif _katalog_kosong(db):
        lanjut = KATALOG_KOSONG
    elif _KEBUTUHAN_RE.search(text):
        lanjut = "Bila ingin melihat seluruh produk kami, ketik *daftar produk*."
    else:
        lanjut = "Kakak sedang mencari untuk kebutuhan apa? Nanti saya bantu cek di katalog kami."
    konteks = {"tawar_staf": True}
    if terdekat:
        konteks["last_product_ids"] = [p.id for p in terdekat]
    return Draft(f"Mohon maaf, Kak 🙏 Produk tersebut belum ada di katalog CV Arba'in. {lanjut} {TAWAR_STAF}",
                 sources=[_template_source("di luar katalog")], product_ids=[p.id for p in terdekat], konteks=konteks,
                 template="luar_katalog", permintaan=[_istilah(terms)])


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
    if not products and (terms := unknown_terms(db, text)):
        return _di_luar_katalog(db, text, terms)
    if not products:
        seen: list[int] = []
        skor: list[float] = []
        top = hits[0].score if hits else 0
        for h in hits:
            if h.chunk.product_id and h.chunk.product_id not in seen and h.score >= top * 0.6:
                seen.append(h.chunk.product_id)
                skor.append(h.score)
        # Rekomendasi fokus: 1–2 produk paling cocok; produk ke-3 hanya ikut bila skornya setara (seri) dengan ke-2,
        # agar kecocokan yang sama kuat tidak terbuang acak.
        n = 3 if len(skor) > 2 and skor[2] >= skor[1] * 0.97 else 2
        products = [db.get(Product, pid) for pid in seen[:n]]
    if not products:
        return Draft(None, escalate=True, escalate_reason="Tidak ada produk di katalog yang cocok (tanpa sumber).",
                     staff_draft=None)
    konteks_produk = {"last_product_ids": [p.id for p in products]}
    if not any(_ada_fakta_lolos(db, p) for p in products):
        return _draf_tertahan(f"Data {_gabung_nama(products)}", [p.id for p in products], konteks=konteks_produk)
    sources = [_product_source(db, p, hits) for p in products]
    # LLM menerima lembar fakta lengkap per produk (tetap tertaut ke chunk sumbernya) + kebijakan pengiriman.
    llm_sources = [{**s, "kutipan": _product_facts(db, p)} for s, p in zip(sources, products)]
    if (policy := _policy_source(db)) is not None:
        llm_sources.append(policy)
    # Pertanyaan stok dijawab dari data, bukan dirangkai LLM: "ada/tidak" di sini bisa terbaca sebagai janji ketersediaan.
    tanya_stok = bool(_TANYA_STOK.search(text))
    res = None if tanya_stok else _llm_answer(
        text, llm_sources, "Sebutkan nama produk, nomor izin edar, klaim disetujui, harga grosir & MOQ.", conv)
    if res is not None:
        return Draft(res.text, sources=llm_sources, product_ids=[p.id for p in products],
                     konteks={"last_product_ids": [p.id for p in products]}, llm_result=res, template="llm")
    lines = ["Berikut info produk dan stoknya, Kak:" if tanya_stok
             else "Ada, Kak. Berikut produk dari katalog kami yang sesuai:"]
    lengkap = True
    for p in products:
        if all(_sar(db).boleh_produk(p, j) for j in ("produk", "izin_edar", "harga", "moq")) and not _ada_klaim_tertahan(db, p.id):
            klaim = " ".join(_claims(db, p.id)) or "Belum ada klaim yang disetujui."
            lines.append(
                f"\n• *{p.nama}*\n  {klaim}\n  Komposisi: {_atau_kosong(p.komposisi)}.\n"
                f"  Izin edar: {_atau_kosong(p.no_izin_edar)} · Kemasan: {p.kemasan}\n"
                f"  Harga grosir {rupiah(p.harga_dasar)}/{p.satuan_grosir}, MOQ {p.moq} {p.satuan_grosir}."
                + _kalimat_stok(p, text)
            )
        else:
            lengkap = False
            lines.append(_baris_sebagian(db, p, text))
    if not lengkap:
        lines.append(f"\n{TAWAR_STAF}")
        return Draft("\n".join(lines), sources=sources, product_ids=[p.id for p in products],
                     konteks={**konteks_produk, "tawar_staf": True}, template="fakta_tertahan")
    lines.append("\nMau saya buatkan penawaran untuk jumlah tertentu?")
    return Draft("\n".join(lines), sources=sources, product_ids=[p.id for p in products],
                 konteks={"last_product_ids": [p.id for p in products]}, template="tanya_produk")


def _ada_fakta_lolos(db: Session, p: Product) -> bool:
    sar = _sar(db)
    return any([sar.boleh_produk(p, j) for j in ("produk", "izin_edar", "harga", "moq")]) or bool(_claims(db, p.id))


_NAMA_FAKTA = {"produk": "komposisi dan kemasan", "izin_edar": "izin edar", "harga": "harga", "moq": "MOQ"}


def _baris_sebagian(db: Session, p: Product, text: str) -> str:
    """Hanya fakta yang lolos yang disebut; sisanya dinyatakan belum terverifikasi."""
    sar = _sar(db)
    baris, tertahan = [f"\n• *{p.nama}*"], [nama for j, nama in _NAMA_FAKTA.items() if not sar.boleh_produk(p, j)]
    if klaim := _claims(db, p.id):
        baris.append(f"  {' '.join(klaim)}")
    elif _ada_klaim_tertahan(db, p.id):
        tertahan.append("klaim")
    if sar.boleh_produk(p, "produk"):
        baris.append(f"  Komposisi: {_atau_kosong(p.komposisi)}. Kemasan: {p.kemasan}")
    if sar.boleh_produk(p, "izin_edar"):
        baris.append(f"  Izin edar: {_atau_kosong(p.no_izin_edar)}")
    if sar.boleh_produk(p, "harga"):
        baris.append(f"  Harga grosir {rupiah(p.harga_dasar)}/{p.satuan_grosir}")
    if sar.boleh_produk(p, "moq"):
        baris.append(f"  MOQ {p.moq} {p.satuan_grosir}")
    baris.append(f"  Data yang belum terverifikasi: {', '.join(tertahan)}.")
    return "\n".join(baris) + _kalimat_stok(p, text)


def draft_izin_edar(db: Session, text: str, conv: Conversation, hits: list[Hit], **_) -> Draft:
    products = _context_products(db, text, conv)
    if products:
        sar = _sar(db)
        tertahan = [p for p in products if p.no_izin_edar and not sar.boleh_produk(p, "izin_edar")]
        if len(tertahan) == len(products):
            return _draf_tertahan(f"Data izin edar {_gabung_nama(products)}", [p.id for p in products],
                                  konteks={"last_product_ids": [p.id for p in products]})
        if tertahan:
            products = [p for p in products if p not in tertahan]
        sources = [_product_source(db, p, hits) for p in products]
        lines = [f"• {p.nama}: *{p.no_izin_edar}*" if p.no_izin_edar
                 else f"• {p.nama}: belum ada datanya di katalog kami" for p in products]
        kosong = [p.nama for p in products if not p.no_izin_edar]
        body = "Nomor izin edar produk:\n" + "\n".join(lines)
        if len(kosong) < len(products):
            body += "\n\nNomor ini dapat dicek di situs Cek Produk BPOM."
        if tertahan:
            body += f"\n\nData izin edar {_gabung_nama(tertahan)} belum terverifikasi."
        if kosong:
            body += "\n\n" + HOLD_STAF
        return Draft(body, sources=sources, product_ids=[p.id for p in products], escalate=bool(kosong),
                     escalate_reason=f"Izin edar belum ada di katalog: {', '.join(kosong)}." if kosong else "",
                     konteks={"last_product_ids": [p.id for p in products]}, template="izin_edar")
    doc_hits = [h for h in hits if h.chunk.product_id is None]
    if doc_hits:
        return Draft(
            _best_sentences(doc_hits[0].chunk.teks, text) + "\n\nProduk mana yang ingin Kakak cek izin edarnya?",
            sources=[doc_hits[0].source()], template="izin_edar_umum",
        )
    return Draft("Produk mana yang ingin Kakak cek nomor izin edarnya?", sources=[_template_source("tanya_produk")],
                 template="izin_edar_tanya")


_TANYA_SYARAT = re.compile(r"\b(?:min|minimal|minimum|moq|campur\w*|tier|diskon)\b", re.I)
_KATA_HARGA = set("harga berapa brp hrg grosir moq minimal minimum min diskon dasar per box karton dus kalau kalo terus total "
                  "semua sekitar kira mahal murah segitu tadi itu tersebut".split())


def draft_harga(db: Session, text: str, conv: Conversation, slots: dict, hits: list[Hit], **_) -> Draft:
    if len(lines := sales.parse_order_lines(db, text)) >= 2:
        return _multi_quote(db, lines, hits)
    products = _context_products(db, text, conv)
    if not find_products(db, text) and not _TANYA_SYARAT.search(text) and (barang := [t for t in unknown_terms(db, text) if t.removesuffix("nya") not in _KATA_HARGA]):
        return _di_luar_katalog(db, text, barang)  # "harga kolagen berapa?": barangnya disebut dan tidak ada di katalog
    if not products and not slots.get("qty"):
        doc_hits = [h for h in hits if h.chunk.product_id is None]
        if doc_hits and doc_hits[0].score >= 0.3:
            best = doc_hits[0]
            return Draft(f"{_best_sentences(best.chunk.teks, text)}\n\nProduk mana yang ingin Kakak ketahui harganya?",
                         sources=[best.source()], template="harga_kebijakan")
    if not products:
        if terms := unknown_terms(db, text):
            return _di_luar_katalog(db, text, terms)
        # Tidak menebak produk: tanyakan balik dengan kandidat dari katalog.
        kandidat = list(dict.fromkeys(db.get(Product, h.chunk.product_id).nama for h in hits if h.chunk.product_id))[:3]
        tanya = (f"Maksud Kakak produk yang mana: {', '.join(kandidat[:-1])} atau {kandidat[-1]}?" if len(kandidat) > 1
                 else f"Maksud Kakak *{kandidat[0]}*?" if kandidat else "Produk mana yang ingin Kakak ketahui harganya?")
        return Draft(tanya + " Sebutkan juga jumlah box-nya ya.", sources=[_template_source("tanya_produk")],
                     template="harga_tanya")
    p = products[0]
    qty = slots.get("qty") or conv.konteks.get("last_qty")
    sar = _sar(db)
    if not sar.boleh_produk(p, "harga"):
        return _draf_tertahan(f"Data harga *{p.nama}*", [p.id], konteks={"last_product_ids": [p.id]})
    if not sar.boleh_produk(p, "tier_diskon") or not sar.boleh_produk(p, "moq"):
        # Harga dasar lolos, tetapi penawaran butuh tier dan MOQ: yang tertahan tidak ikut dihitung.
        moq = f", MOQ {p.moq} {p.satuan_grosir}" if sar.boleh_produk(p, "moq") else ""
        return Draft(f"Harga dasar grosir *{p.nama}*: {rupiah(p.harga_dasar)}/{p.satuan_grosir}{moq}. Data diskon volume dan "
                     f"syarat pembeliannya belum terverifikasi, jadi total penawaran dihitung staf kami. {TAWAR_STAF}",
                     sources=[_product_source(db, p, hits), _pricing_source(p)], product_ids=[p.id], template="fakta_tertahan",
                     konteks={"last_product_ids": [p.id], "tawar_staf": True})
    sources = [_product_source(db, p, hits), _pricing_source(p)]
    if qty:
        q = sales.quote(db, p, int(qty))
        body = sales.format_quote(q) + _info_tier_berikut(db, p, int(qty)) + _catatan_stok_qty(p, int(qty))
        if len(products) > 1:
            body += f"\n\nIngin penawaran untuk produk lain ({', '.join(x.nama for x in products[1:])})?"
        else:
            body += "\n\nBalas *pesan* bila ingin kami buatkan draf pesanan."
        return Draft(body, sources=sources, product_ids=[p.id], template="harga_qty",
                     konteks={"last_product_ids": [p.id] + [x.id for x in products[1:]], "last_qty": int(qty),
                              "last_quote": {"product_id": p.id, "qty": int(qty), "diskon": q.diskon}})
    body = (f"Harga grosir *{p.nama}*: {rupiah(p.harga_dasar)}/{p.satuan_grosir}, MOQ {p.moq} {p.satuan_grosir}.\n"
            f"Diskon volume: {sales.tier_table(db, p)}.\nBerapa box yang Kakak butuhkan?")
    return Draft(body, sources=sources, product_ids=[p.id], template="harga_dasar",
                 konteks={"last_product_ids": [p.id]})


def _harga_lolos(db: Session, p: Product) -> bool:
    sar = _sar(db)
    return all([sar.boleh_produk(p, j) for j in ("harga", "tier_diskon", "moq")])


def _multi_quote(db: Session, lines: list[tuple[Product, int]], hits: list[Hit]) -> Draft:
    if not all([_harga_lolos(db, p) for p, _ in lines]):
        return _draf_tertahan("Data harga sebagian produk yang Kakak sebutkan", [p.id for p, _ in lines],
                              konteks={"last_product_ids": [p.id for p, _ in lines]})
    items, total = sales.build_items(db, lines)
    rows = [f"• {it['nama']} × {it['qty']} {it['satuan']}"
            + (f" (diskon {it['diskon_persen']:g}%)" if it["diskon_persen"] else "") + f" = {rupiah(it['subtotal'])}"
            for it in items]
    note = sales.moq_note(lines, _min_campuran(db))
    body = (f"Penawaran untuk {len(items)} produk:\n" + "\n".join(rows)
            + f"\nTotal {rupiah(total)} (belum termasuk ongkos kirim)" + (f"\n{note}" if note else "")
            + "\n\nBalas *pesan* bila ingin kami buatkan draf pesanannya.")
    sources = [_product_source(db, p, hits) for p, _ in lines] + [_pricing_source(p) for p, _ in lines]
    return Draft(body, sources=sources, product_ids=[p.id for p, _ in lines], template="harga_multi",
                 konteks={"last_product_ids": [p.id for p, _ in lines], "last_lines": [[p.id, q] for p, q in lines]})


def draft_negosiasi(db: Session, text: str, conv: Conversation, slots: dict, hits: list[Hit], **_) -> Draft:
    if (slots.get("qty") or 0) >= PESANAN_BESAR_BOX:
        return Draft(f"Terima kasih, Kak 🙏 Untuk pembelian {slots['qty']} box, harga khusus disiapkan langsung oleh "
                     f"manajemen penjualan kami. " + HOLD_STAF, sources=[_template_source("pesanan skala besar")],
                     escalate=True, escalate_reason=f"Pesanan skala besar ({slots['qty']} box) di atas tier otomatis.",
                     staff_draft=None, template="nego_skala_besar")
    products = _context_products(db, text, conv)
    # "madu stamina diskon 20%" padahal produknya tidak ada di katalog → bukan tanya balik. Hanya bila memang menyebut
    # jenis produk; "kasih diskon dong" / "mahal" tetap ditanya balik.
    if not products and _SEBUT_JENIS.search(text) and (terms := unknown_terms(db, text)):
        return _di_luar_katalog(db, text, terms)
    if not products:
        return Draft(f"{_aturan_diskon(db)} Boleh disebutkan produk dan jumlah box yang ingin dinegosiasikan, Kak?",
                     sources=[_template_source("tanya_produk")], template="nego_tanya")
    p = products[0]
    qty = slots.get("qty") or conv.konteks.get("last_qty")
    if not _harga_lolos(db, p):
        return _draf_tertahan(f"Data harga dan diskon *{p.nama}*", [p.id], konteks={"last_product_ids": [p.id]})
    if not qty:
        return Draft(f"Diskon untuk *{p.nama}* mengikuti volume: {sales.tier_table(db, p)}. "
                     f"Berapa box yang Kakak rencanakan?", sources=[_pricing_source(p)],
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
    if not all([_harga_lolos(db, p) for p, _ in lines]):
        # Tanpa harga terverifikasi tidak ada total dan tidak ada draf pesanan; permintaannya tetap sampai ke staf.
        ringkas = ", ".join(f"{p.nama} × {q} {p.satuan_grosir}" for p, q in lines)
        return _draf_tertahan("Data harga produk yang Kakak pesan", [p.id for p, _ in lines], konteks={**konteks, "order_pending": None},
                              eskalasi=f"Permintaan pesanan ({ringkas}) belum bisa disusun karena data harga belum terverifikasi.")
    items, total = sales.build_items(db, lines)
    od = OrderDraft(contact_id=contact.id, conversation_id=conv.id, item=items, nama_toko=contact.nama_toko,
                    alamat=contact.alamat, total=total)
    db.add(od)
    db.flush()
    summary = sales.format_order(items, contact.nama_toko, contact.alamat, total)
    if note := sales.moq_note(lines, _min_campuran(db)):
        summary += f"\n{note}"
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
    parsed = sales.parse_order_lines(db, text)
    products = find_products(db, text)
    if len(parsed) >= 2:
        pending["lines"] = [[p.id, q] for p, q in parsed]
        pending["product_ids"] = [p.id for p, _ in parsed]
    elif products:
        pending.pop("lines", None)
        pending["product_ids"] = [p.id for p in products]
    elif not pending.get("product_ids") and conv.konteks.get("last_lines") and not slots.get("qty"):
        # "pesan" setelah penawaran multi-produk → pakai baris penawaran tersebut
        pending["lines"] = conv.konteks["last_lines"]
        pending["product_ids"] = [pid for pid, _ in pending["lines"]]
    elif not pending.get("product_ids"):
        lq = conv.konteks.get("last_quote")
        ids = [lq["product_id"]] if lq else (conv.konteks.get("last_product_ids") or [])[:1]
        if ids:
            pending["product_ids"] = ids
    if (not pending.get("product_ids") and not slots.get("nama_toko") and not slots.get("alamat")
            and (terms := unknown_terms(db, text))):
        return _di_luar_katalog(db, text, terms)
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
    if not pending.get("qty") and not pending.get("lines"):
        missing.append("jumlah box")
    if not contact.nama_toko:
        missing.append("nama toko")
    if not contact.alamat:
        missing.append("alamat pengiriman")
    if missing:
        return Draft(f"Siap, Kak. Untuk menyusun draf pesanan, mohon lengkapi: {', '.join(missing)}.",
                     sources=[_template_source("pesanan")], konteks={"order_pending": pending},
                     template="pesan_lengkapi")
    if pending.get("lines"):
        lines = [(p, int(q)) for pid, q in pending["lines"] if (p := db.get(Product, pid)) is not None]
    else:
        lines = [(db.get(Product, pid), int(pending["qty"])) for pid in pending["product_ids"][:1]]
    sources = [_product_source(db, p, hits) for p, _ in lines] + [_pricing_source(p) for p, _ in lines]
    return _finalize_order(db, conv, contact, lines, sources,
                           {"last_product_ids": pending["product_ids"], "last_lines": None},
                           "pesan" if len(lines) == 1 else "pesan_multi")


def _info_tier_berikut(db: Session, p: Product, qty: int) -> str:
    """Upsell jujur: hanya menyebut tier diskon berikutnya yang memang ada di data."""
    nxt = next((r for r in sales.tiers(db, p.id) if r.min_qty > qty), None)
    return f"\nInfo: mulai {nxt.min_qty} {p.satuan_grosir}, diskon bisa s.d. {nxt.diskon_maks_persen:g}%." if nxt else ""


def _catatan_stok_qty(p: Product, qty: int) -> str:
    """Urgensi hanya dari stok tercatat: bila jumlah melebihi stok, katakan apa adanya — tanpa kata menekan."""
    if p.stok is None or qty <= p.stok or not _sar(object_session(p)).boleh_produk(p, "stok"):
        return ""
    tgl = f" per {p.stok_per:%d/%m/%Y}" if p.stok_per else ""
    return f"\nCatatan: stok tercatat{tgl} {p.stok} {p.satuan_grosir}; sisanya dikonfirmasi staf saat pesanan."


def draft_tindak_lanjut(db: Session, text: str, conv: Conversation, **_) -> Draft:
    """Pembeli ingin menimbang dulu: hormati, tanpa tekanan, satu ajakan ringan."""
    ids = (conv.konteks or {}).get("last_product_ids") or []
    p = db.get(Product, ids[0]) if ids else None
    teks = "Siap, Kak 🙏 Silakan dipertimbangkan dulu, tidak perlu buru-buru."
    if p is not None and p.aktif:
        teks += f" Kalau sudah mantap dengan *{p.nama}*, cukup balas *pesan* dan jumlah box-nya, nanti saya rangkumkan."
    else:
        teks += " Kalau nanti ada yang ingin ditanyakan atau dipesan, chat saja di sini."
    return Draft(teks, sources=[_template_source("tindak lanjut")], template="tindak_lanjut",
                 konteks={"tawar_staf": False, "tindak_lanjut_pada": clock.now().isoformat()})


def draft_tunda_closing(**_) -> Draft:
    """Jalur sensitif menang atas closing: pesanan tidak didorong sebelum staf menangani pertanyaan kesehatan."""
    return Draft("Baik, Kak 🙏 Sebelum pesanan diproses, staf kami akan menghubungi Kakak dulu terkait pertanyaan "
                 "kesehatan tadi, agar produknya benar-benar sesuai. Permintaan pesanan Kakak sudah saya catat untuk staf.",
                 sources=[_template_source("tunda closing")], escalate=True, staff_draft=None, template="tunda_closing",
                 escalate_reason="Pembeli ingin memesan saat pertanyaan kesehatan belum ditangani staf — closing ditunda.")


def _riwayat_kosong(conv: Conversation, contact: Contact) -> Draft:
    """Riwayat tidak ditemukan: jangan menebak. Tanya ciri produk (dan nomor HP di Telegram); percobaan kedua → staf."""
    if (conv.konteks or {}).get("riwayat_kosong"):
        return Draft("Riwayat pesanan Kakak masih belum saya temukan, jadi saya tidak akan menebak. " + HOLD_STAF,
                     sources=[_template_source("riwayat tidak ditemukan")], escalate=True, staff_draft=None,
                     escalate_reason="Pembeli yakin pernah memesan, tetapi riwayatnya tidak ditemukan — staf mengecek.",
                     konteks={"cari_riwayat": False, "riwayat_kosong": False}, template="pesan_ulang_staf")
    minta_nomor = contact.channel == "telegram" and not contact.wa_number
    teks = ("Mohon maaf, Kak 🙏 Saya belum menemukan riwayat pesanan untuk kontak ini, jadi saya tidak akan menebak. "
            "Boleh ceritakan ciri produknya, misalnya kegunaan, bentuk atau rasa, ukuran, atau kira-kira kapan pesannya?")
    if minta_nomor:
        teks += (" Kalau dulu memesan lewat WhatsApp, tekan tombol *Bagikan nomor HP* di bawah agar riwayatnya bisa "
                 "saya cari.")
    teks += " Bila ingin staf yang mengecek riwayatnya, balas *ya*."
    return Draft(teks, sources=[_template_source("riwayat tidak ditemukan")], minta_nomor=minta_nomor,
                 konteks={"riwayat_kosong": True, "cari_riwayat": True, "tawar_staf": True}, template="pesan_ulang_kosong")


def draft_pesan_ulang(db: Session, text: str, conv: Conversation, contact: Contact, hits: list[Hit], **_) -> Draft:
    """Pesan ulang dari riwayat nyata (termasuk kanal lain dengan nomor HP yang sama). Produk yang sudah tidak aktif
    di katalog tidak dimasukkan ulang; riwayat kosong tidak pernah dikarang."""
    last = sales.riwayat_terakhir(db, contact)
    if last is None:
        return _riwayat_kosong(conv, contact)
    lines, hilang = [], []
    for it in last.item:
        p = db.get(Product, it["product_id"])
        if p is not None and p.aktif:
            lines.append((p, int(it["qty"])))
        else:
            hilang.append(it.get("nama") or "produk lama")
    selesai = {"cari_riwayat": False, "riwayat_kosong": False}
    if not lines:
        return Draft(f"Pesanan terakhir Kakak berisi produk yang sudah tidak ada di katalog ({', '.join(hilang)}). "
                     + HOLD_STAF, sources=[_template_source("riwayat pesanan")], escalate=True, staff_draft=None,
                     escalate_reason="Semua produk di pesanan terakhir sudah tidak aktif di katalog.", konteks=selesai,
                     template="pesan_ulang_tidak_aktif")
    sources = [{"jenis": "order_draft", "order_draft_id": last.id, "judul": f"Pesanan terakhir #{last.id}"}]
    sources += [_pricing_source(p) for p, _ in lines]
    if not contact.nama_toko and last.nama_toko:
        contact.nama_toko = last.nama_toko
    if not contact.alamat and last.alamat:
        contact.alamat = last.alamat
    d = _finalize_order(db, conv, contact, lines, sources, {"last_product_ids": [p.id for p, _ in lines], **selesai},
                        "pesan_ulang")
    if hilang:
        d.text = f"Catatan: {', '.join(hilang)} sudah tidak ada di katalog, jadi tidak saya masukkan.\n\n{d.text}"
    return d


def _kandidat(db: Session, text: str, hits: list[Hit]) -> list[Product]:
    """2–3 produk aktif yang paling cocok dengan ciri yang disebut pembeli (nama, kegunaan, kemasan)."""
    sar = _sar(db)
    out = [p for p in find_products(db, text) if p.aktif and sar.boleh_produk(p, "produk")]
    for h in hits:
        if len(out) >= 3:
            break
        p = db.get(Product, h.chunk.product_id) if h.chunk.product_id else None
        if p is not None and p.aktif and p not in out and h.score >= 0.2 and _berkaitan(h, text) and sar.boleh_produk(p, "produk"):
            out.append(p)
    return out[:3]


def draft_cari_riwayat(db: Session, text: str, conv: Conversation, hits: list[Hit], **_) -> Draft:
    kandidat = _kandidat(db, text, hits)
    if not kandidat:
        return Draft("Dari ciri itu saya belum menemukan produk yang cocok di katalog. " + HOLD_STAF,
                     sources=[_template_source("cari riwayat")], escalate=True, staff_draft=None,
                     escalate_reason="Pembeli mencari produk pesanan lama; ciri tidak cocok dengan katalog.",
                     konteks={"cari_riwayat": False}, template="cari_riwayat_kosong")
    daftar = "\n".join(f"• *{p.nama}*" + (f" ({p.kemasan.split(';')[0]})" if p.kemasan else "") for p in kandidat)
    return Draft(f"Dari ciri yang Kakak sebutkan, kemungkinan produknya:\n{daftar}\n\nYang mana, Kak? Kalau bukan salah "
                 "satunya, balas *ya* agar staf mengecek riwayat pesanan Kakak.",
                 sources=[_product_source(db, p, hits) for p in kandidat], product_ids=[p.id for p in kandidat],
                 konteks={"cari_riwayat": False, "last_product_ids": [p.id for p in kandidat], "tawar_staf": True},
                 template="cari_riwayat")


def draft_nomor_dibagikan(db: Session, text: str, conv: Conversation, contact: Contact, hits: list[Hit], **_) -> Draft:
    """Nomor HP dibagikan (Telegram). Bila sedang mencari riwayat → cari lagi memakai nomor itu."""
    terima = "Terima kasih, nomor HP Kakak sudah tercatat 🙏"
    k = conv.konteks or {}
    if k.get("riwayat_kosong") or k.get("cari_riwayat"):
        if sales.riwayat_terakhir(db, contact) is not None:
            d = draft_pesan_ulang(db=db, text=text, conv=conv, contact=contact, hits=hits)
            d.text = f"{terima}\n\n{d.text}"
            return d
        return Draft(f"{terima} Riwayat pesanan untuk nomor ini belum ada di sistem kami, jadi saya tidak akan menebak. "
                     + HOLD_STAF, sources=[_template_source("riwayat tidak ditemukan")], escalate=True, staff_draft=None,
                     escalate_reason="Nomor dibagikan, tetapi riwayat pesanan tidak ditemukan — staf mengecek.",
                     konteks={"cari_riwayat": False, "riwayat_kosong": False}, template="nomor_tanpa_riwayat")
    return Draft(f"{terima} Ini memudahkan kami mencari riwayat pesanan Kakak berikutnya. Ada produk yang bisa saya "
                 "bantu?", sources=[_template_source("nomor dibagikan")], template="nomor_dibagikan")


_MERUJUK = re.compile(r"\b(?:ini|itu|tadi|tersebut)\b", re.I)


def draft_klaim(db: Session, text: str, conv: Conversation, hits: list[Hit], **_) -> Draft:
    # Produk dari giliran lalu hanya disebut bila pembeli merujuknya; bila tidak, klaim yang ditolak terkesan terkait produk itu.
    products = find_products(db, text) or (_context_products(db, text, conv) if _MERUJUK.search(text) else [])
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
    lain = " Pertanyaan Kakak yang lain juga akan dijawab staf sekalian." if text.count("?") >= 2 else ""
    return Draft(
        "Mohon maaf atas ketidaknyamanannya, Kak 🙏 Keluhan Kakak sudah kami catat dan kami teruskan ke staf "
        "penjualan yang akan segera menghubungi untuk penyelesaian." + lain,
        sources=[_template_source("keluhan")] + ([retur.source()] if retur else []),
        escalate=True, escalate_reason="Keluhan pembeli selalu ditangani staf.", staff_draft=staff, template="keluhan",
    )


def draft_minta_staf(**_) -> Draft:
    return Draft("Baik, Kak. " + HOLD_STAF, sources=[_template_source("minta staf")], escalate=True,
                 escalate_reason="Pembeli meminta bicara dengan staf.",
                 staff_draft="Halo Kak, saya staf penjualan CV Arba'in. Ada yang bisa saya bantu?",
                 konteks={"tawar_staf": False}, template="minta_staf")


def draft_spesifikasi(db: Session, text: str, conv: Conversation, hits: list[Hit], **_) -> Draft:
    products = _context_products(db, text, conv)[:2]
    if not products:
        if terms := unknown_terms(db, text):
            return _di_luar_katalog(db, text, terms)
        return Draft("Produk mana yang ingin Kakak ketahui isi kemasan atau kandungannya?",
                     sources=[_template_source("tanya_produk")], template="spesifikasi_tanya")
    if not all([_sar(db).boleh_produk(p, "produk") for p in products]):
        return _draf_tertahan(f"Data kemasan dan kandungan {_gabung_nama(products)}", [p.id for p in products],
                              konteks={"last_product_ids": [p.id for p in products]})
    blocks = [f"*{p.nama}*\n• Kemasan: {p.kemasan.replace('; box isi', ', 1 box isi')}\n• Kandungan: {_atau_kosong(p.komposisi)}"
              for p in products]
    return Draft("\n\n".join(blocks) + "\n\nIngin sekalian info harga grosir dan MOQ-nya, Kak?",
                 sources=[_product_source(db, p, hits) for p in products], product_ids=[p.id for p in products],
                 konteks={"last_product_ids": [p.id for p in products]}, template="spesifikasi")


_KEBIJAKAN_TOPIK = [
    # (pola pertanyaan, [(judul bagian dokumen, kata wajib di kalimat)])
    (re.compile(r"ongkir|ongkos kirim|biaya kirim|biaya pengiriman|gratis", re.I),
     [("Pengiriman", "ongkos kirim"), ("Harga dan diskon volume", "ongkos kirim")]),
    (re.compile(r"\blama\b|\bhari\b|nyampe|estimasi|\b(?:di)?kirim\w*|pengiriman|ekspedisi|\b(?:sampai|sampe)\w*\s+(?:brp|berapa|kapan)", re.I),
     [("Pengiriman", "hari kerja")]),
    (re.compile(r"retur|refund|tukar|rusak|pecah|cacat|kedaluwarsa|expired", re.I), [("Retur", "")]),
    (re.compile(r"bayar|pembayaran|transfer|tempo|termin|lunas", re.I), [("Pembayaran", "")]),
    (re.compile(r"minimal|minimum|moq|min order|campur", re.I), [("Minimum order dan satuan", "")]),
    (re.compile(r"masa simpan|simpan|penyimpanan", re.I), [("Penyimpanan", "")]),
]
_DI_LUAR_KEBIJAKAN = [
    (re.compile(r"luar negeri|ekspor|export|internasional|malaysia|singapura|singapore|brunei|hong ?kong|taiwan|"
                r"timor leste|arab saudi", re.I), "pengiriman ke luar negeri", "Pengiriman"),
    (re.compile(r"\bcod\b|bayar di tempat|kartu kredit|credit card|paylater|pay later|giro|\bcek\b|cicil\w*|"
                r"\bkredit\b|qris|e-?wallet|\bovo\b|gopay|shopee ?pay", re.I), "metode pembayaran tersebut", "Pembayaran"),
    (re.compile(r"tidak laku|ga laku|gak laku", re.I), "pengembalian produk yang tidak laku", "Retur"),
]


def _policy_section(db: Session, judul: str) -> tuple[str, Hit] | None:
    from ..models import Chunk

    marker = f"{judul}: "
    sar = _sar(db)
    for ch in db.scalars(select(Chunk).where(Chunk.aktif.is_(True), Chunk.teks.like(f"%{marker}%")).order_by(Chunk.id)):
        if not sar.boleh_dokumen(ch.document_id):
            continue
        for line in ch.teks.split("\n"):
            # Potongan bisa diawali sisa (overlap) paragraf sebelumnya, jadi judul tidak selalu di awal baris.
            if marker in line:
                return line.split(marker, 1)[1].strip(), Hit(ch, 1.0)
    return None


def _policy_sentences(db: Session, sections: list[tuple[str, str]]) -> tuple[list[str], list[dict]]:
    sentences, sources = [], []
    for judul, kata in sections:
        found = _policy_section(db, judul)
        if found is None:
            continue
        para, hit = found
        picked = [s for s in split_sentences(para) if kata.lower() in s.lower()]
        sentences += [s for s in picked if s not in sentences]
        if picked and hit.chunk.id not in {s.get("chunk_id") for s in sources}:
            sources.append({**hit.source(), "kutipan": para})
    return sentences, sources


_SEBUT_JENIS = re.compile(r"\b(madu|kapsul|teh|minyak|vitamin|serbuk|sirup|tablet|jamu|suplemen)\b", re.I)
_PESANAN_SENDIRI = re.compile(r"\b(belum bayar|sudah transfer|udah transfer|tagihan|invoice|nota|pesanan saya)\b", re.I)


_kota = pemahaman.kota_dikenal
_TANYA_KIRIM = re.compile(r"ongkir|ongkos kirim|biaya kirim|biaya pengiriman|\b(?:di)?kirim\w*|pengiriman|nyampe|sampai|sampe", re.I)


def _kebijakan_tertahan(db: Session) -> bool:
    """Ada dokumen kebijakan aktif, tetapi tidak satu pun lolos verifikasi: jangan mengaku "belum diatur"."""
    from ..models import Chunk

    sar = _sar(db)
    dokumen = set(db.scalars(select(Chunk.document_id).where(Chunk.aktif.is_(True), Chunk.product_id.is_(None))))
    return bool(dokumen) and not any(sar.lolos_dokumen(d) for d in dokumen)


def draft_kebijakan(db: Session, text: str, conv: Conversation, hits: list[Hit], **kw) -> Draft:
    """Kebijakan dijawab per subtopik dari bagian dokumen yang tepat (bukan kalimat acak yang kebetulan mirip).
    Hal yang tidak diatur dokumen (COD, kartu kredit, luar negeri, nominal ongkir) diteruskan ke staf."""
    if _kebijakan_tertahan(db):
        return _draf_tertahan("Data kebijakan penjualan kami")
    for pola, label, judul in _DI_LUAR_KEBIJAKAN:
        diminta = pola.search(text)
        # Hanya "di luar kebijakan" bila istilah yang ditanya (COD, QRIS, luar negeri…) memang tidak disebut kebijakan.
        if diminta and diminta.group(0).lower() not in " ".join(_policy_sentences(db, [(judul, "")])[0]).lower():
            sentences, sources = _policy_sentences(db, [(judul, "")])
            berlaku = f" Ketentuan yang berlaku saat ini: {sentences[0]}" if sentences else ""
            return Draft(f"Untuk {label}, belum ada ketentuannya di kebijakan penjualan kami.{berlaku} " + HOLD_STAF,
                         sources=sources or [_template_source("di luar kebijakan")], escalate=True,
                         escalate_reason=f"Di luar kebijakan penjualan: {label}.", staff_draft=None,
                         template="kebijakan_di_luar")
    data_sales = (conv.konteks or {}).get("sales") or {}
    profil = data_sales.get("profil")
    kota_lain = data_sales.get("kota") if profil else None
    kota = _kota(text) or (_kota(kota_lain) if kota_lain else None) or ((kota_lain, None) if kota_lain else None)
    sections = [sec for pola, secs in _KEBIJAKAN_TOPIK if pola.search(text) for sec in secs]
    if (_kota(text) or (kota and _TANYA_KIRIM.search(text))) and ("Pengiriman", "hari kerja") not in sections:
        sections.append(("Pengiriman", "hari kerja"))  # "ongkir ke sby?" → sertakan estimasi waktu kirim
    sentences, sources = _policy_sentences(db, sections)
    if kota and kota[1] is not None and not re.search(r"gratis", text, re.I):
        # Ketentuan gratis ongkir untuk area lain tidak relevan bagi pembeli di kota ini.
        sentences = [s for s in sentences if not re.search(r"gratis", s, re.I) or kota[0].lower() in s.lower()] or sentences
    if not sentences:
        return draft_dokumen(db=db, text=text, conv=conv, hits=hits, **kw)
    body = "Berikut ketentuan dari kebijakan penjualan kami:\n" + "\n".join(f"• {s}" for s in sentences)
    if kota and any("hari kerja" in s for s in sentences) and any("Jawa Tengah" in s for s in sentences):
        if kota[1] is None:  # wilayahnya tidak diketahui pasti: kedua estimasi disebut, tidak ditebak
            body += f"\n\nWilayah {kota[0]} belum bisa saya pastikan, jadi estimasinya dikonfirmasi staf kami."
        else:
            body += f"\n\n{kota[0]} termasuk {'wilayah Jawa Tengah' if kota[1] else 'luar Jawa Tengah'}."
    nominal = re.search(r"\b(brp|berapa)\b", text, re.I) and re.search(r"ongkir|ongkos kirim|biaya kirim|biaya pengiriman", text, re.I)
    if profil and re.search(r"ongkir|ongkos kirim|biaya", text, re.I):
        nominal = True  # profil diketahui: selalu jujur bahwa nominal ongkir dihitung staf
    gratis_di_kota = kota and any(kota[0].lower() in s.lower() and "ongkos kirim" in s.lower() for s in sentences)
    if nominal and not gratis_di_kota:
        tujuan = kota[0] if kota else "lokasi Kakak"
        if profil:  # profil pembeli diketahui: lanjutkan percakapan sales, staf menghitung ongkir saat konfirmasi
            return Draft(body + f"\n\nNominal ongkir ke {tujuan} akan dihitung staf kami saat konfirmasi pesanan 🙏",
                         sources=sources, template="kebijakan")
        return Draft(body + f"\n\nNominal ongkir ke {tujuan} akan dihitung staf kami saat konfirmasi pesanan 🙏",
                     sources=sources, escalate=True, staff_draft=None, template="kebijakan_ongkir",
                     escalate_reason=f"Nominal ongkir ke {tujuan} tidak ada di Knowledge Base.")
    if _PESANAN_SENDIRI.search(text):
        # Pembayaran/tagihan atas pesanan yang sudah ada: kebijakan umum saja tidak cukup, staf yang memegang tagihannya.
        return Draft(f"{body}\n\nUntuk tagihan pesanan Kakak, staf kami yang akan mengirimkan detailnya. {TAWAR_STAF}",
                     sources=sources, konteks={"tawar_staf": True}, template="kebijakan")
    return Draft(body, sources=sources, template="kebijakan")


def draft_aturan_pakai(db: Session, text: str, conv: Conversation, hits: list[Hit], **_) -> Draft:
    """Aturan pakai hanya dikutip dari data katalog. Tidak ada datanya → arahkan ke label dan tenaga kesehatan, tanpa angka."""
    disebut = find_products(db, text)
    ids = (conv.konteks or {}).get("last_product_ids") or []
    produk = disebut[:1] or [p for pid in ids if (p := db.get(Product, pid)) is not None]
    if not produk:
        return Draft("Boleh tahu produk mana yang Kakak maksud?", sources=[_template_source("tanya_produk")],
                     konteks={"langkah": "tanya_produk"}, template="aturan_tanya")
    if len(produk) > 1:
        nama = [p.nama for p in produk[:3]]
        return Draft(f"Produk yang mana, Kak: {', '.join(nama[:-1])} atau {nama[-1]}?",
                     sources=[_template_source("tanya_produk")], konteks={"langkah": "tanya_produk"}, template="aturan_tanya")
    p = produk[0]
    data = str((p.data_teknis or {}).get("aturan_pakai") or "").strip()
    if data and not _sar(db).boleh_produk(p, "aturan_pakai"):
        inti = (f"Aturan pakai *{p.nama}* di data kami belum terverifikasi, jadi tidak saya sebutkan. Silakan ikuti "
                "petunjuk pada label kemasan.")
    elif data:
        inti = f"Menurut data katalog, aturan pakai *{p.nama}*: {data.rstrip('.')}. Ikuti juga petunjuk pada label kemasan."
    else:
        inti = (f"Aturan pakai *{p.nama}* belum tercatat di data kami, jadi saya tidak akan menebak. Silakan ikuti "
                "petunjuk pada label kemasan.")
    return Draft(f"{inti} Untuk kondisi kesehatan tertentu, konsultasikan dengan dokter atau apoteker. {TAWAR_STAF}",
                 sources=[_product_source(db, p, hits)], product_ids=[p.id], template="aturan_pakai",
                 konteks={"last_product_ids": [p.id], "tawar_staf": True, "langkah": "tawar_staf"})


def draft_lokasi_cabang(db: Session, **_) -> Draft:
    """Data cabang tidak ada: akui dan teruskan ke staf, tidak mengarang lokasi."""
    gudang = _gudang(db)
    lokasi = f" Yang tercatat, pengiriman kami dilakukan dari gudang {gudang}." if gudang else ""
    return Draft(f"Mohon maaf, Kak 🙏 Informasi cabang atau lokasi penjualan belum ada di data kami, jadi saya tidak akan "
                 f"menebak.{lokasi} {HOLD_STAF}", sources=[_template_source("lokasi cabang")], escalate=True,
                 escalate_reason="Pembeli menanyakan cabang/lokasi penjualan; datanya tidak ada.", staff_draft=None,
                 konteks={"langkah": "serah_staf"}, template="lokasi_cabang")


def draft_serah_sales(conv: Conversation, contact: Contact, slots: dict, **_) -> Draft:
    """Data calon pembeli grosir sudah terkumpul: serah terima ke staf beserta ringkasannya."""
    sales.ensure_contact_details(contact, slots)
    data = (conv.konteks or {}).get("sales") or {}
    sapa = f"Kak {data['nama']}" if data.get("nama") else "Kak"
    return Draft(f"Terima kasih, {sapa} 🙏 Datanya sudah saya rangkum dan teruskan ke staf penjualan kami, yang akan "
                 "menghubungi Kakak untuk konfirmasi stok, tagihan, dan ongkos kirim.",
                 sources=[_template_source("serah terima sales")], escalate=True, staff_draft=None,
                 escalate_reason="Calon pembeli grosir: data lengkap, ditindaklanjuti staf.",
                 konteks={"langkah": "serah_staf"}, template="serah_sales")


def draft_perlu_staf(**_) -> Draft:
    return Draft("Terima kasih, Kak. Untuk hal ini kami perlu memastikan langsung dengan tim kami. " + HOLD_STAF,
                 sources=[_template_source("di luar wewenang AI")], escalate=True,
                 escalate_reason="Topik di luar wewenang AI (kemitraan/HET/sampel/sertifikat/opini).",
                 staff_draft=None, template="perlu_staf")


def draft_minta_dokumen(**_) -> Draft:
    return Draft("Baik, Kak. Katalog dan daftar harga lengkap akan dikirimkan oleh staf penjualan kami. Sambil "
                 "menunggu, Kakak bisa sebutkan nama produk untuk info harga & MOQ langsung di sini 🙏",
                 sources=[_template_source("minta katalog")], escalate=True,
                 escalate_reason="Pembeli meminta file katalog/daftar harga — dikirim staf.",
                 staff_draft=None, template="minta_dokumen")


def _atau_kosong(nilai: str | None) -> str:
    return nilai if nilai else "belum ada datanya"


def _aturan_diskon(db: Session) -> str:
    """Kalimat aturan diskon dari tier di katalog aktif (bukan angka tetap)."""
    awal = db.scalar(select(func.min(PricingRule.min_qty)).join(Product).where(Product.aktif.is_(True)))
    if awal is None:
        return "Saat ini belum ada tabel diskon volume otomatis; permintaan diskon ditinjau staf penjualan."
    sar = _sar(db)
    produk = db.scalars(select(Product).where(Product.aktif.is_(True)).options(selectinload(Product.pricing)))
    lolos = [r.min_qty for p in produk if p.pricing and sar.boleh_produk(p, "tier_diskon") for r in p.pricing]
    if not lolos:
        return "Data diskon volume kami belum terverifikasi; permintaan diskon ditinjau staf penjualan."
    awal = min(lolos)
    return f"Diskon kami mengikuti tabel diskon volume resmi (mulai {awal} box)."


def _min_campuran(db: Session) -> int | None:
    """Batas total pembelian campuran dari kebijakan "Minimum order" (None bila kebijakan tidak mengaturnya)."""
    teks = " ".join(_policy_sentences(db, [("Minimum order dan satuan", "")])[0])
    m = re.search(r"campuran[^.]*?total\s+minimal\s+(\d+)", teks, re.I)
    return int(m.group(1)) if m else None


def _gudang(db: Session) -> str | None:
    teks = " ".join(_policy_sentences(db, [("Pengiriman", "")])[0])
    m = re.search(r"\bgudang\s+([A-Z][\w]*(?:\s+[A-Z][\w]*)?)", teks)
    return m.group(1) if m else None


LAYANAN_AI = "Saya bisa bantu info produk herbal, izin edar, harga grosir, dan pemesanan."
TAWAR_STAF = "Kalau ingin bicara dengan staf penjualan, balas *ya*."


_IDENTITAS_KHUSUS = [
    (re.compile(r"perasaan", re.I), "Saya asisten AI, jadi tidak punya perasaan seperti manusia 🙏"),
    (re.compile(r"dibayar|digaji|gaji", re.I), "Saya asisten AI, jadi tidak digaji 🙂"),
    (re.compile(r"salah|keliru|tanggung jawab", re.I),
     "Saya asisten AI dan bisa saja keliru. Karena itu saya hanya menjawab dari katalog dan kebijakan resmi CV Arba'in, "
     "dan hal penting (pesanan, harga khusus, keluhan) selalu dikonfirmasi staf penjualan yang bertanggung jawab atas "
     "layanan kami."),
    (re.compile(r"bikin|buat|membuat|cipta|program", re.I),
     "Saya asisten AI yang disiapkan untuk melayani pembeli CV Arba'in, dan diawasi oleh staf penjualan."),
]


def draft_identitas(text: str = "", **_) -> Draft:
    khusus = next((jawab for pola, jawab in _IDENTITAS_KHUSUS if pola.search(text)), None)
    pembuka = khusus or "Halo Kak 🙏 Ini asisten AI (balasan otomatis) dari CV Arba'in."
    return Draft(f"{pembuka} {LAYANAN_AI} {TAWAR_STAF}", sources=[_template_source("identitas asisten")],
                 konteks={"tawar_staf": True}, template="identitas")


def draft_luar_topik(**_) -> Draft:
    """Di luar topik: tolak sopan & arahkan kembali — tidak membebani staf, tidak menawarkan produk yang tidak diminta."""
    return Draft("Mohon maaf, Kak 🙏 Untuk hal tersebut saya belum bisa membantu, karena saya asisten AI penjualan "
                 f"CV Arba'in. {LAYANAN_AI} Ada produk yang sedang Kakak cari?",
                 sources=[_template_source("di luar topik")], template="luar_topik")


def draft_media(**_) -> Draft:
    return Draft("Mohon maaf, Kak 🙏 Saya belum bisa membaca foto, stiker, atau pesan suara. Boleh ditulis lewat teks "
                 f"pertanyaannya? {TAWAR_STAF}", sources=[_template_source("media tidak didukung")],
                 konteks={"tawar_staf": True}, template="media")


def draft_manipulasi(**_) -> Draft:
    """Upaya mengubah aturan/peran asisten atau meminta akses: ditolak tanpa mengulang isi permintaannya."""
    return Draft("Mohon maaf, Kak 🙏 Permintaan tersebut tidak bisa saya lakukan. Saya asisten AI penjualan CV Arba'in "
                 "dan hanya bekerja sesuai kebijakan resmi perusahaan: harga dan diskon mengikuti daftar resmi, dan "
                 "akses sistem hanya diberikan oleh tim internal. Untuk pertanyaan kesehatan, silakan konsultasi dengan "
                 f"dokter atau apoteker. {LAYANAN_AI}", sources=[_template_source("tolak manipulasi")],
                 template="manipulasi")


_RAGU_PERUSAHAAN = re.compile(r"penipu|tipu|asli|resmi|legal|terpercaya|amanah", re.I)
_LOKASI = re.compile(r"alamat|lokasi|kantor|dimana|di mana", re.I)


def draft_perusahaan(db: Session, text: str, **_) -> Draft:
    body = ("CV Arba'in melayani penjualan grosir (B2B) produk herbal dan suplemen untuk apotek dan toko. "
            f"{_kalimat_izin(db)} Saya asisten AI-nya, siap membantu info produk, harga grosir, dan pemesanan.")
    konteks = {}
    if _RAGU_PERUSAHAAN.search(text) or _LOKASI.search(text):
        gudang = _gudang(db)
        lokasi = f" Pengiriman kami dilakukan dari gudang {gudang}." if gudang and _LOKASI.search(text) else ""
        body = ("Pertanyaan yang wajar, Kak 🙏 " + body + lokasi + " Untuk verifikasi data perusahaan (alamat lengkap, "
                f"dokumen usaha), staf kami siap membantu. {TAWAR_STAF}")
        konteks = {"tawar_staf": True}
    return Draft(body, sources=[_template_source("profil perusahaan")], konteks=konteks, template="perusahaan")


def draft_pembanding(**_) -> Draft:
    return Draft("Mohon maaf, Kak 🙏 Kami tidak membandingkan produk kami dengan merek lain. Yang bisa saya bantu adalah "
                 "info resmi produk kami: izin edar, komposisi, kemasan, dan harga grosir. Produk mana yang ingin Kakak "
                 "ketahui?", sources=[_template_source("tanpa pembanding merek")], template="pembanding")


_KATEGORI_PRODUK = ("madu", "kapsul", "teh", "minyak", "vitamin", "serbuk", "sirup", "tablet")


def draft_ambigu(db: Session, text: str, **_) -> Draft:
    """Produk tidak jelas → tanya balik, jangan menebak. Bila ada kata kategori ("madu"), sebutkan pilihannya."""
    low = text.lower()
    kat = next((k for k in _KATEGORI_PRODUK if re.search(rf"\b{k}\b", low)), None)
    if kat:
        names = [p.nama for p in db.scalars(select(Product).where(Product.aktif.is_(True)).order_by(Product.id))
                 if re.search(rf"\b{kat}\b", p.nama.lower()) and _sar(db).boleh_produk(p, "produk")]
        if names:
            daftar = ", ".join(names[:6]) + (f", dan {len(names) - 6} lainnya" if len(names) > 6 else "")
            return Draft(f"{kat.capitalize()} yang mana, Kak? Di katalog kami ada: {daftar}. Boleh disebutkan nama "
                         "produknya? 🙏", sources=[_template_source("tanya balik produk")], template="ambigu_kategori")
    return Draft("Boleh disebutkan nama produk yang Kakak maksud? Kalau belum tahu namanya, ceritakan saja "
                 "kebutuhannya, nanti saya bantu carikan 🙏", sources=[_template_source("tanya balik produk")],
                 template="ambigu")


def draft_darurat(**_) -> Draft:
    """Darurat: peduli, arahkan ke layanan darurat. Tidak ada saran medis dan tidak ada produk."""
    return Draft("Kak, ini terdengar darurat 🙏 Mohon segera hubungi layanan gawat darurat 119 atau 112, atau bawa ke "
                 "IGD rumah sakit terdekat sekarang juga. Saya asisten AI dan tidak bisa memberi saran medis. Pesan "
                 "Kakak juga sudah saya teruskan ke staf kami.", sources=[_template_source("darurat")], escalate=True,
                 escalate_reason="Kondisi darurat kesehatan — pembeli diarahkan ke layanan darurat.", staff_draft=None,
                 template="darurat")


def draft_sensitif(**_) -> Draft:
    return Draft("Terima kasih sudah mau bercerita, Kak 🙏 Kalau beban terasa berat, berbicara dengan orang terdekat atau "
                 "tenaga profesional seperti dokter atau psikolog bisa sangat membantu. Bila Kakak merasa tidak aman, "
                 "segera hubungi layanan darurat 119 atau IGD terdekat. Saya asisten AI sehingga tidak bisa memberi saran "
                 f"medis. {TAWAR_STAF}", sources=[_template_source("peduli")], konteks={"tawar_staf": True},
                 template="sensitif")


def draft_marah(**_) -> Draft:
    return Draft("Mohon maaf atas ketidaknyamanannya, Kak 🙏 Saya mengerti Kakak kecewa. Pesan Kakak sudah saya teruskan "
                 "ke staf penjualan agar segera ditangani langsung oleh tim kami.", sources=[_template_source("empati")],
                 escalate=True, escalate_reason="Pembeli marah/kecewa — ditangani staf.",
                 staff_draft="Halo Kak, mohon maaf atas ketidaknyamanannya. Saya staf CV Arba'in, apa yang bisa saya bantu?",
                 template="marah")


def _data_teknis(db: Session, key: str) -> list[tuple[Product, dict]]:
    return [(p, (p.data_teknis or {}).get(key) or {})
            for p in db.scalars(select(Product).where(Product.aktif.is_(True)).order_by(Product.id))]


_NARKOBA = re.compile(r"narkoba|narkotika|obat terlarang|psikotropika|ganja|sabu|bko|bahan kimia", re.I)
_HUKUM = re.compile(r"lapor|polisi|somasi|tuntut", re.I)
_DITIPU = re.compile(r"\bditipu\b|\bkena tipu\b|\bmenipu (?:saya|kami)\b", re.I)


def _kalimat_izin(db: Session) -> str:
    """Pernyataan izin edar sesuai data: tidak mengklaim "setiap produk" bila ada yang kosong."""
    produk = list(db.scalars(select(Product).where(Product.aktif.is_(True))))
    sar = _sar(db)
    tercatat = [p for p in produk if p.no_izin_edar]
    n = sum([sar.boleh_produk(p, "izin_edar") for p in tercatat])
    if tercatat and not n:
        return "Data nomor izin edar produk kami belum terverifikasi."
    if n and n == len(produk):
        return "Setiap produk di katalog kami tercatat dengan nomor izin edar yang bisa Kakak cek di situs resmi BPOM."
    if n:
        return (f"{n} dari {len(produk)} produk di katalog kami tercatat dengan nomor izin edar yang bisa Kakak cek di "
                "situs resmi BPOM; produk lainnya belum ada datanya.")
    return "Data nomor izin edar produk belum ada di katalog kami."


def draft_tuduhan(db: Session, text: str, **_) -> Draft:
    """Tuduhan: tidak defensif, tidak mengaku salah — jawab dengan data katalog, tawarkan staf."""
    body = ("Kami memahami kekhawatiran Kakak 🙏 CV Arba'in melayani penjualan grosir (B2B) produk herbal dan suplemen "
            f"per box untuk apotek dan toko. {_kalimat_izin(db)}")
    eskalasi, alasan = False, ""
    if _NARKOBA.search(text):
        bko = _data_teknis(db, "status_bebas_bko")
        tercatat = [(p, d) for p, d in bko if d.get("hasil")]
        ada = [d for p, d in tercatat if _sar(db).boleh_produk(p, "bko")]
        negatif = sum(1 for d in ada if str(d["hasil"]).lower().startswith("negatif"))
        if not tercatat:
            body += " Data uji Bahan Kimia Obat (BKO) belum ada di katalog kami."
            eskalasi, alasan = True, "Data uji BKO belum ada di katalog."
        elif not ada:
            body += " Data uji Bahan Kimia Obat (BKO) kami belum terverifikasi."
            eskalasi, alasan = True, "Data uji BKO belum terverifikasi."
        else:
            body += (f" Menurut data uji di katalog kami, {negatif} dari {len(bko)} produk tercatat negatif Bahan Kimia "
                     "Obat (BKO)" + ("; produk lainnya belum ada data ujinya." if len(ada) < len(bko) else "."))
    if _HUKUM.search(text):
        eskalasi, alasan = True, "Pembeli menyinggung jalur hukum/polisi."
    elif _DITIPU.search(text):
        eskalasi, alasan = True, "Pembeli melapor merasa ditipu — ditangani staf."
    body += (" Pesan Kakak sudah saya teruskan ke staf kami untuk ditindaklanjuti." if eskalasi
             else " Bila ada pengalaman yang kurang baik, staf kami siap membantu. " + TAWAR_STAF)
    return Draft(body, sources=[_template_source("tanggapan tuduhan")], escalate=eskalasi, staff_draft=None,
                 escalate_reason=alasan, konteks={} if eskalasi else {"tawar_staf": True}, template="tuduhan")


_FATWA = re.compile(r"haram|riba|bid'?ah|syirik|syariat|syar'?i|fatwa|ustaz|ustad|ulama|hukum", re.I)
_ASLI = re.compile(r"\basli\b|demi allah|wallahi", re.I)
_HALAL = re.compile(r"halal|haram|riba|bid'?ah|syariat|syar'?i|sertifikat", re.I)


def draft_agama(db: Session, text: str, conv: Conversation, hits: list[Hit], **_) -> Draft:
    """Halal hanya dari data sertifikasi di katalog; tidak berfatwa soal hukum agama. Data kosong → "belum ada datanya"
    dan diteruskan ke staf (tidak pernah ditebak)."""
    parts, kosong = [], False
    if _FATWA.search(text):
        parts.append("Mohon maaf, Kak 🙏 Untuk pertanyaan hukum agama, kami tidak dalam kapasitas memberi fatwa; "
                     "silakan berkonsultasi dengan ustaz atau ulama yang Kakak percayai.")
    products = find_products(db, text) or [p for pid in (conv.konteks.get("last_product_ids") or [])
                                             if (p := db.get(Product, pid)) is not None]
    sources = [_template_source("data sertifikasi halal katalog")]
    if not _HALAL.search(text):
        pass  # mis. "demi Allah ini asli?" — data halal tidak disodorkan bila tidak ditanya
    elif products:
        for p in products[:2]:
            h = (p.data_teknis or {}).get("sertifikasi_halal") or {}
            if h.get("status") and not _sar(db).boleh_produk(p, "halal"):
                parts.append(f"Data sertifikasi halal *{p.nama}* belum terverifikasi, jadi belum bisa saya sampaikan.")
            elif h.get("status"):
                parts.append(f"Menurut data katalog, *{p.nama}* tercatat {h['status']}"
                             + (f" (No. {h['nomor_sertifikat']}, {h.get('lembaga') or 'lembaga belum ada datanya'})"
                                if h.get("nomor_sertifikat") else "") + ".")
            else:
                parts.append(f"Data sertifikasi halal untuk *{p.nama}* belum ada di katalog kami.")
                kosong = True
            sources.append(_product_source(db, p, hits))
    else:
        halal = _data_teknis(db, "sertifikasi_halal")
        tercatat = [(p, d) for p, d in halal if d.get("status")]
        ada = [d for p, d in tercatat if _sar(db).boleh_produk(p, "halal")]
        n = sum(1 for d in ada if d["status"] == "Bersertifikat Halal")
        lembaga = sorted({d.get("lembaga") for d in ada if d.get("lembaga")})
        if not tercatat:
            parts.append("Data sertifikasi halal belum ada di katalog kami.")
            kosong = True
        elif not ada:
            parts.append("Data sertifikasi halal kami belum terverifikasi, jadi belum bisa saya sampaikan.")
        else:
            parts.append(f"Menurut data katalog kami, {n} dari {len(halal)} produk tercatat Bersertifikat Halal"
                         + (f" dari {', '.join(lembaga)}" if lembaga else "")
                         + ("; produk lainnya belum ada datanya" if len(ada) < len(halal) else "")
                         + ". Sebutkan nama produknya bila Kakak ingin nomor sertifikatnya.")
    if _ASLI.search(text):
        parts.append(_kalimat_izin(db))
    parts.append(HOLD_STAF if kosong else TAWAR_STAF)
    return Draft(" ".join(parts), sources=sources, product_ids=[p.id for p in products[:2]], escalate=kosong,
                 escalate_reason="Data sertifikasi halal belum ada di katalog." if kosong else "",
                 konteks={} if kosong else {"tawar_staf": True}, template="agama")


def draft_sara(**_) -> Draft:
    return Draft("Mohon maaf, Kak 🙏 Kami tidak memberikan pandangan soal agama, politik, maupun SARA, dan kami melayani "
                 "semua pelanggan dengan setara. Saya asisten AI penjualan CV Arba'in. Ada produk yang bisa saya bantu?",
                 sources=[_template_source("netral")], template="sara")


def draft_daftar_produk(db: Session, text: str, **_) -> Draft:
    """Seluruh katalog aktif, dikelompokkan per kategori — selalu sama, tidak ada yang disembunyikan atau dikarang."""
    semua = list(db.scalars(select(Product).where(Product.aktif.is_(True)).order_by(Product.kategori, Product.id)))
    products = [p for p in semua if _sar(db).boleh_produk(p, "produk")]
    if semua and not products:
        return _draf_tertahan("Data daftar produk kami")
    if not semua:
        return Draft(f"Mohon maaf, Kak 🙏 {KATALOG_KOSONG} {TAWAR_STAF}", sources=[_template_source("katalog kosong")],
                     konteks={"tawar_staf": True}, template="katalog_kosong")
    groups: dict[str, list[str]] = {}
    for p in products:
        groups.setdefault(p.kategori or "Lainnya", []).append(p.nama)
    # Hanya barang yang ditanyakan eksplisit ("ada kopi?", "jual rokok?"), bukan kata percakapan lain.
    vocab = _catalog_vocab(db)[0]
    diminta = re.findall(r"\b(?:ada|jual|punya|sedia\w*)\s+([a-z]+)", text.lower())
    terms = [w for w in dict.fromkeys(diminta) if w not in _KATA_TANYA and stem(w) not in vocab]
    lines = []
    if terms:
        lines.append(f"Untuk {', '.join(terms)}: belum ada di katalog kami.\n")
    lines.append(f"Berikut semua produk di katalog CV Arba'in ({len(products)} produk):")
    for kat, names in groups.items():
        lines.append(f"\n*{kat} ({len(names)})*\n" + "\n".join(f"• {n}" for n in names))
    lines.append("\nSebutkan nama produknya untuk info harga grosir, MOQ, dan izin edar 🙏")
    return Draft("\n".join(lines), sources=[_template_source("daftar katalog aktif")],
                 product_ids=[p.id for p in products], template="daftar_produk", permintaan=terms)


def draft_gratis(db: Session, **_) -> Draft:
    return Draft(f"Mohon maaf, Kak 🙏 Kami belum bisa memberikan produk secara gratis. {_aturan_diskon(db)} Kalau "
                 f"ingin dibantu mencari pilihan yang sesuai anggaran, staf kami siap membantu. {TAWAR_STAF}", sources=[_template_source("tanpa janji gratis")],
                 konteks={"tawar_staf": True}, template="gratis")


_PAMIT = re.compile(r"bye|dadah|sampai jumpa|makasih|terima kasih|thanks|thx|udahan|cukup", re.I)


def draft_basa_basi(text: str, **_) -> Draft:
    if _PAMIT.search(text):
        return Draft("Terima kasih sudah menghubungi CV Arba'in, Kak 🙏 Kalau ada yang ingin ditanyakan lagi, silakan "
                     "chat kapan saja.", sources=[_template_source("penutup")], template="penutup")
    return Draft("Siap, Kak 🙏 Ada produk atau info yang bisa saya bantu? Saya bisa bantu info produk herbal, izin edar, "
                 "harga grosir, dan pemesanan.", sources=[_template_source("basa-basi")], template="basa_basi")


def _klarifikasi(conv: Conversation) -> Draft:
    """Pesan tidak dipahami & tanpa sumber: minta penjelasan dulu; baru diteruskan ke staf bila dua kali berturut-turut."""
    masuk = sum(1 for m in conv.messages if m.arah == "masuk")
    if (conv.konteks or {}).get("klarifikasi_ke") == masuk - 1:
        return Draft("Terima kasih, Kak. " + HOLD_STAF, sources=[_template_source("eskalasi")], escalate=True,
                     escalate_reason="Dua pesan berturut-turut tidak dipahami AI dan tidak ada sumber di Knowledge Base.",
                     staff_draft=None, template="tanpa_sumber")
    return Draft(f"Mohon maaf, Kak 🙏 Saya belum menangkap maksudnya. {LAYANAN_AI} Boleh dijelaskan produk atau "
                 f"kebutuhannya? {TAWAR_STAF}", sources=[_template_source("klarifikasi")],
                 konteks={"klarifikasi_ke": masuk, "tawar_staf": True}, template="klarifikasi")


def _berkaitan(h: Hit, text: str) -> bool:
    """Potongan dokumen dianggap relevan hanya bila berbagi kata isi dengan pertanyaan selain nama kota
    ("cuaca semarang" tidak boleh mengutip kebijakan pengiriman hanya karena kata "Semarang")."""
    q = {stem(t) for t in content_tokens(text)
         if t not in _KATA_TANYA and t not in KOTA_JATENG and t not in KOTA_LUAR_JATENG}
    return bool(q & {stem(t) for t in content_tokens(h.chunk.teks)})


def draft_dokumen(db: Session, text: str, conv: Conversation, hits: list[Hit], **_) -> Draft:
    strong = [h for h in hits if h.score >= MIN_SKOR_DOKUMEN and _berkaitan(h, text)]
    sar = _sar(db)
    lolos = [h for h in strong if sar.boleh_kutip(h.chunk)]
    doc_hits = [h for h in lolos if h.chunk.product_id is None] or lolos
    if not doc_hits:
        # Sumbernya ada tetapi tertahan: katakan apa adanya, jangan berpura-pura tidak paham.
        if strong or any(h.score >= MIN_SKOR_DOKUMEN and _berkaitan(h, text) for h in retrieve(db, text, k=4, saring=False)):
            return _draf_tertahan("Data yang Kakak tanyakan")
        return _klarifikasi(conv)
    best = doc_hits[0]
    sources = [best.source()]
    res = _llm_answer(text, sources, "Jawab pertanyaan kebijakan/umum secara ringkas.", conv)
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
    "kebijakan": draft_kebijakan,
    "spesifikasi": draft_spesifikasi,
    "perlu_staf": draft_perlu_staf,
    "minta_dokumen": draft_minta_dokumen,
    "identitas": draft_identitas,
    "luar_topik": draft_luar_topik,
    "media": draft_media,
    "manipulasi": draft_manipulasi,
    "perusahaan": draft_perusahaan,
    "pembanding": draft_pembanding,
    "ambigu": draft_ambigu,
    "darurat": draft_darurat,
    "sensitif": draft_sensitif,
    "marah": draft_marah,
    "tuduhan": draft_tuduhan,
    "agama": draft_agama,
    "sara": draft_sara,
    "daftar_produk": draft_daftar_produk,
    "gratis": draft_gratis,
    "basa_basi": draft_basa_basi,
    "cari_riwayat": draft_cari_riwayat,
    "nomor_dibagikan": draft_nomor_dibagikan,
    "tindak_lanjut": draft_tindak_lanjut,
    "tunda_closing": draft_tunda_closing,
    "aturan_pakai": draft_aturan_pakai,
    "lokasi_cabang": draft_lokasi_cabang,
    "serah_sales": draft_serah_sales,
    "lainnya": draft_dokumen,
}
