"""Router intent (Sales Agent, langkah 1). Aturan dulu agar cepat, murah, dan bisa dijelaskan;
LLM hanya dipakai untuk pesan yang tidak tertangkap aturan."""

import re
from dataclasses import dataclass, field

from .. import llm

INTENTS = {
    "salam": "Salam",
    "tanya_produk": "Tanya produk",
    "izin_edar": "Izin edar",
    "harga_moq": "Harga & MOQ",
    "negosiasi": "Negosiasi",
    "pesan": "Pesan",
    "pesan_ulang": "Pesan ulang",
    "klaim_kesehatan": "Klaim kesehatan",
    "medis_personal": "Pertanyaan medis personal",
    "keluhan": "Keluhan",
    "minta_staf": "Minta bicara dengan staf",
    "kebijakan": "Kebijakan (kirim/bayar/retur)",
    "lainnya": "Lainnya",
}


def _r(expr: str) -> re.Pattern:
    return re.compile(expr, re.IGNORECASE)


MEDIS_PERSONAL = _r(
    r"\b(saya|aku|sy|aq|anak saya|ibu saya|bapak saya|suami saya|istri saya|ortu saya|orang tua saya)\b.{0,30}"
    r"\b(sakit|menderita|punya (?:penyakit|riwayat)|kena|didiagnosa|diagnosis|lagi minum obat|minum obat dokter|"
    r"demam|batuk|pilek|diare|muntah|pusing|sesak|nyeri|"
    r"hamil|menyusui|alergi|operasi|kemoterapi|cuci darah)\b|\b(ibu hamil|sedang hamil|menyusui|dosis (?:untuk|buat) (?:saya|anak))\b"
)
KELUHAN = _r(
    r"\b(rusak|bocor|pecah|penyok|kedaluwarsa|kadaluarsa|kadaluwarsa|expired|exp|telat|terlambat|belum (?:sampai|datang|diterima|dikirim)|"
    r"kecewa|komplain|complain|keluhan|retur|refund|salah kirim|kurang jumlah|jumlahnya kurang|tidak sesuai|gak sesuai|ga sesuai)\b"
)
KLAIM = _r(r"\b(sembuh\w*|menyembuhkan|(?<!toko )obat(?:i|in)?|mengobati|ampuh|manjur|mencegah|cegah|terapi|khasiat(?:nya)? untuk)\b")
KONDISIONAL = _r(r"\b(kalau|kalo|jika|apabila|bila|seandainya|misal(?:nya)?)\b")
PESAN_ULANG = _r(
    r"\b(pesan ulang|order ulang|repeat order|pesan lagi|order lagi|ambil lagi|seperti (?:bulan lalu|kemarin|sebelumnya|biasa)|"
    r"sama (?:seperti|kayak|kaya) (?:kemarin|sebelumnya|biasa|bulan lalu)|kayak (?:kemarin|biasa)|kaya biasa)\b"
)
NEGO = _r(r"\b(diskon|disc|disk|potongan|nego|negosiasi|kurangi|lebih murah|harga khusus|bisa kurang|kurang lagi|harga spesial|harga pas|kasih murah)\b")
PESAN = _r(r"\b(pesan|pesen|order|beli|ambil|kirimkan|kirimin|checkout|po)\b")
HARGA = _r(r"\b(harga\w*|hrg|berapa|brp|moq|minimal|minimum|min order|grosir|price|pricelist|daftar harga)\b")
IZIN = _r(r"\b(izin|ijin|bpom|pom|edar|registrasi|nie|terdaftar|legal)\b")
KEBIJAKAN = _r(r"\b(pengiriman|ongkir|ongkos kirim|kirim ke|ekspedisi|pembayaran|bayar|transfer|tempo|retur|garansi|masa simpan|kedaluwarsa berapa)\b")
PRODUK = _r(r"\b(ada|produk|untuk|buat|stok|ready|katalog|komposisi\w*|kandungan\w*|isi\w*|manfaat\w*|khasiat\w*|varian|jual|rekomendasi|cocok|tersedia)\b")
MINTA_STAF = _r(r"\b(bicara|ngobrol|hubungkan|sambungkan|telepon|telpon|chat|minta)\b.{0,20}\b(staf|staff|admin|cs|orang|manusia|sales|petugas)\b")
YA = _r(r"^\s*(ya|iya|iyaa|boleh|mau|oke|ok|okay|baik|siap|silakan|yes)\b")
SALAM = _r(r"^\s*(halo|hallo|hai|hi|assalamu'?alaikum|assalamualaikum|selamat (?:pagi|siang|sore|malam)|pagi|siang|sore|malam|permisi|p)\W*\s*(kak|min|gan|pak|bu)?\W*$")

QTY_RE = _r(r"(\d{1,5})\s*(karton|ktn|dus|dos|box|kardus|ctn|krt|carton)")
QTY_BARE_RE = _r(r"\b(\d{1,5})\b(?!\s*(?:%|persen|ml|g|gr|gram|kapsul|tablet|sachet|hari|jam|bulan))")
DISC_RE = _r(r"(\d{1,2}(?:[.,]\d+)?)\s*(?:%|persen)")
STORE_RE = re.compile(r"\b(?:[Aa]potek|[Aa]potik|[Tt]oko [Oo]bat|[Tt]oko|[Mm]inimarket|TO|Apt\.?)\s+([A-Z][\w'&.-]*(?:\s+[A-Z][\w'&.-]*){0,3})")
STORE_LABEL_RE = _r(r"nama toko\s*[:=]\s*([^\n,]+)")
ADDRESS_RE = _r(r"(?:alamat|almt|dikirim ke|kirim ke)\s*[:=]?\s*([^\n]+)|\b((?:jl|jln|jalan)\.?\s+[^\n]+)")


@dataclass
class RouteResult:
    intent: str
    reason: str
    slots: dict = field(default_factory=dict)
    model: str = llm.OFFLINE_MODEL
    llm_result: object | None = None


def extract_slots(text: str) -> dict:
    slots: dict = {}
    m = QTY_RE.search(text)
    if m:
        slots["qty"] = int(m.group(1))
        slots["qty_unit_explicit"] = True
    d = DISC_RE.search(text)
    if d:
        slots["diskon_diminta"] = float(d.group(1).replace(",", "."))
    addr = ADDRESS_RE.search(text)
    if "qty" not in slots:
        for mb in QTY_BARE_RE.finditer(text):
            if d and mb.start() <= d.start() < mb.end() + 2:
                continue
            if addr and addr.start() <= mb.start():
                continue  # angka di dalam alamat bukan jumlah
            slots["qty"] = int(mb.group(1))
            slots["qty_bare"] = True
            break
    s = STORE_LABEL_RE.search(text)
    if s:
        slots["nama_toko"] = s.group(1).strip()
    else:
        s2 = STORE_RE.search(text)
        if s2:
            slots["nama_toko"] = s2.group(0).strip().rstrip(",.")
    a = ADDRESS_RE.search(text)
    if a:
        slots["alamat"] = (a.group(1) or a.group(2)).strip().rstrip(".")
    return slots


def route(text: str, *, inbound_verdict: str, inbound_rules: list[str], konteks: dict) -> RouteResult:
    slots = extract_slots(text)
    t = text.strip()

    if MEDIS_PERSONAL.search(t):
        return RouteResult("medis_personal", "Pertanyaan menyangkut kondisi kesehatan pribadi → wajib staf.", slots)
    if MINTA_STAF.search(t) or (konteks.get("tawar_staf") and YA.match(t)):
        return RouteResult("minta_staf", "Pembeli meminta bicara dengan staf.", slots)
    if KELUHAN.search(t):
        if KONDISIONAL.search(t) and KEBIJAKAN.search(t):
            return RouteResult("kebijakan", "Pertanyaan kebijakan bersyarat (bukan keluhan aktual).", slots)
        return RouteResult("keluhan", "Ada kata kunci keluhan/komplain → wajib staf.", slots)
    if inbound_verdict == "blocked" or KLAIM.search(t) or "R05" in inbound_rules:
        return RouteResult("klaim_kesehatan", "Pesan meminta klaim terkait penyakit/khasiat terapi.", slots)
    if PESAN_ULANG.search(t):
        return RouteResult("pesan_ulang", "Permintaan pesan ulang.", slots)
    if NEGO.search(t) or ("diskon_diminta" in slots and HARGA.search(t)):
        return RouteResult("negosiasi", "Permintaan diskon/negosiasi harga.", slots)
    pending = konteks.get("order_pending")
    if PESAN.search(t) and not HARGA.search(t):
        return RouteResult("pesan", "Permintaan pemesanan.", slots)
    if pending and (slots.get("nama_toko") or slots.get("alamat") or slots.get("qty")):
        return RouteResult("pesan", "Melengkapi data pesanan yang tertunda.", slots)
    if KEBIJAKAN.search(t) and not QTY_RE.search(t):
        return RouteResult("kebijakan", "Pertanyaan kebijakan pengiriman/pembayaran/retur.", slots)
    if HARGA.search(t):
        return RouteResult("harga_moq", "Pertanyaan harga/MOQ.", slots)
    if IZIN.search(t):
        return RouteResult("izin_edar", "Pertanyaan izin edar.", slots)
    if SALAM.match(t):
        return RouteResult("salam", "Salam pembuka.", slots)
    if PRODUK.search(t):
        return RouteResult("tanya_produk", "Pertanyaan produk/katalog.", slots)

    res = llm.complete(
        [{"role": "user", "content": (
            "Klasifikasikan pesan pembeli B2B produk herbal ke salah satu intent: "
            + ", ".join(INTENTS) + f'. Pesan: "{t}". Jawab JSON {{"intent": "...", "alasan": "..."}}')}],
        json_mode=True, max_tokens=80, temperature=0,
    )
    if res is not None and isinstance(res.data, dict) and res.data.get("intent") in INTENTS:
        return RouteResult(res.data["intent"], f"LLM: {res.data.get('alasan', '')}", slots, res.model, res)
    return RouteResult("lainnya", "Tidak cocok dengan pola intent mana pun.", slots)
