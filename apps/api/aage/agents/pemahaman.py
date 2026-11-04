"""Lapisan pemahaman konteks: profil pembeli, kota, dan data sales yang terkumpul selama percakapan. Murni aturan.

Lapisan ini hanya berjalan sesudah aturan keras router dan tidak bisa membelokkan jalur sensitif: pengalihan intent hanya
berlaku untuk pesan yang oleh router dinilai jualan biasa atau tidak dikenali. Profil usaha ("kios obat saya") tidak
melonggarkan pemeriksaan klaim; yang disamarkan hanya frasa nama usahanya, klaim lain di pesan yang sama tetap terdeteksi.
"""

import re

# Wilayah untuk menjelaskan bagian kebijakan pengiriman mana yang berlaku (Jawa Tengah vs luar Jawa Tengah).
KOTA_JATENG = {
    "semarang": "Semarang", "smg": "Semarang", "solo": "Solo", "surakarta": "Surakarta", "magelang": "Magelang",
    "salatiga": "Salatiga", "kudus": "Kudus", "pati": "Pati", "klaten": "Klaten", "boyolali": "Boyolali",
    "sragen": "Sragen", "karanganyar": "Karanganyar", "wonogiri": "Wonogiri", "sukoharjo": "Sukoharjo",
    "purwokerto": "Purwokerto", "banyumas": "Banyumas", "tegal": "Tegal", "pekalongan": "Pekalongan",
    "kendal": "Kendal", "demak": "Demak", "jepara": "Jepara", "rembang": "Rembang", "blora": "Blora",
    "grobogan": "Grobogan", "purworejo": "Purworejo", "kebumen": "Kebumen", "cilacap": "Cilacap",
    "wonosobo": "Wonosobo", "temanggung": "Temanggung", "batang": "Batang", "pemalang": "Pemalang",
    "brebes": "Brebes", "ungaran": "Ungaran", "banjarnegara": "Banjarnegara", "purbalingga": "Purbalingga",
}
KOTA_LUAR_JATENG = {
    "jakarta": "Jakarta", "jkt": "Jakarta", "surabaya": "Surabaya", "sby": "Surabaya", "bandung": "Bandung",
    "jogja": "Yogyakarta", "yogyakarta": "Yogyakarta", "yogya": "Yogyakarta", "malang": "Malang", "bekasi": "Bekasi",
    "bogor": "Bogor", "depok": "Depok", "tangerang": "Tangerang", "bali": "Bali", "denpasar": "Denpasar",
    "medan": "Medan", "makassar": "Makassar", "palembang": "Palembang", "lampung": "Lampung", "cirebon": "Cirebon",
    "kediri": "Kediri", "madiun": "Madiun", "banjarmasin": "Banjarmasin", "balikpapan": "Balikpapan",
    "aceh": "Aceh", "padang": "Padang", "pekanbaru": "Pekanbaru", "jambi": "Jambi", "pontianak": "Pontianak",
    "samarinda": "Samarinda", "manado": "Manado", "ambon": "Ambon", "kupang": "Kupang", "mataram": "Mataram",
    "jayapura": "Jayapura", "garut": "Garut", "tasikmalaya": "Tasikmalaya",
}
_BUKAN_KOTA = set(
    "sini sana situ mana rumah toko kios apotek apotik warung pasar kota daerah luar dalam tempat kami saya aku kakak "
    "gudang lokasi atas bawah depan situs katalog staf kantor".split()
)
_DI_KE = re.compile(r"\b(ke|di)\s+([a-z]{3,})", re.I)

_SAYA = r"(?:saya|sy|aku|aq|kami|kita|gue)"
_USAHA = r"(?:kios|warung|toko|apotek|apotik|apoteker|reseller|distributor|agen|gudang|minimarket|jualan)"
_RESELLER = re.compile(
    rf"\b{_SAYA}\s+(?:\w+\s+){{0,2}}?{_USAHA}\b|\b{_USAHA}(?:\s+\w+)?\s+{_SAYA}\b|\bnyetok\b|\bbuat\s+(?:apotek|kios|toko|warung)\b",
    re.I,
)
_KONSUMEN = re.compile(
    r"\b(?:buat|untuk|dipakai|dikonsumsi|konsumsi)\s+sendiri\b|\bpribadi\b|\b(?:satu|1)\s*(?:botol|aja|saja|biji|pcs)\b|"
    r"\beceran\b|\b(?:buat|untuk)\s+(?:ibu|bapak|ayah|suami|istri|anak)\b",
    re.I,
)
# Frasa nama usaha yang memuat kata "obat" bukan permintaan klaim. "mau jadi distributor obat" tetap topik kemitraan.
_NAMA_USAHA = re.compile(
    r"\b(?:kios|warung|gudang|agen|jualan)\s+obat\b|(?<!jadi )\bdistributor\s+obat\b|"
    rf"\b{_SAYA}\s+(?:adalah\s+)?distributor(?:\s+obat)?\b(?!\s+eksklusif)",
    re.I,
)
_NAMA_ORANG = re.compile(r"\b[Nn]ama\s+(?:saya|sy|aku)\s+([A-Za-z]{2,})\b|\b(?:[Ss]aya|[Aa]ku)\s+([A-Z][a-z]+)\b")
_ARAH_SALES = {"lainnya", "tanya_produk"}


def samarkan_usaha(text: str) -> str:
    return _NAMA_USAHA.sub("usaha", text)


def profil_dari_teks(text: str) -> str | None:
    if _RESELLER.search(text):
        return "reseller"
    if _KONSUMEN.search(text):
        return "konsumen"
    return None


def kota_dikenal(text: str) -> tuple[str, bool] | None:
    """(nama kota, ada di Jawa Tengah) untuk kota yang wilayahnya diketahui pasti."""
    for tok in re.findall(r"[a-z]+", text.lower()):
        if tok in KOTA_JATENG:
            return KOTA_JATENG[tok], True
        if tok in KOTA_LUAR_JATENG:
            return KOTA_LUAR_JATENG[tok], False
    return None


def kota_disebut(text: str) -> str | None:
    """Nama tempat yang disebut pembeli, termasuk yang wilayahnya tidak diketahui. Tujuan ("ke") didahulukan."""
    if dikenal := kota_dikenal(text):
        return dikenal[0]
    kandidat = sorted(_DI_KE.findall(text), key=lambda x: x[0].lower() != "ke")
    for _, kata in kandidat:
        if kata.lower() not in _BUKAN_KOTA:
            return kata.capitalize()
    return None


def nama_pembeli(text: str) -> str | None:
    m = _NAMA_ORANG.search(text)
    return (m.group(1) or m.group(2)).capitalize() if m else None


def perbarui_sales(sales: dict | None, text: str, slots: dict, produk: list[str]) -> dict:
    """Data sales percakapan. Profil usaha bertahan; rincian hanya dikumpulkan setelah profil pembeli diketahui."""
    s = dict(sales or {})
    profil = profil_dari_teks(text)
    if profil and not (s.get("profil") == "reseller" and profil == "konsumen"):
        s["profil"] = profil
    if not s.get("profil"):
        return s
    if kota := kota_disebut(text):
        s["kota"] = kota
    if slots.get("qty") and slots.get("qty_unit_explicit"):
        s["qty"] = int(slots["qty"])
    if produk:
        s["produk"] = produk[0]
    if nama := nama_pembeli(text):
        s["nama"] = nama
    if slots.get("nama_toko"):
        s["toko"] = str(slots["nama_toko"])[:80]
    return s


def ringkasan_sales(sales: dict | None) -> str:
    if not sales or not sales.get("profil"):
        return ""
    bagian = [f"profil {sales['profil']}"]
    if sales.get("nama"):
        bagian.append(f"nama {sales['nama']}")
    if sales.get("toko"):
        toko = sales["toko"]  # nama dari pola pesan sudah memuat jenisnya ("toko Berkah", "Apotik Sejahtera")
        bagian.append(toko if re.match(r"(?:toko|apotek|apotik|minimarket|to|apt)\b", toko, re.I) else f"toko {toko}")
    if sales.get("kota"):
        bagian.append(f"kota {sales['kota']}")
    if sales.get("qty") or sales.get("produk"):
        bagian.append(" ".join(x for x in (f"{sales['qty']} box" if sales.get("qty") else "", sales.get("produk") or "") if x))
    return " · ".join(bagian)


def arahkan_sales(intent: str, text: str, slots: dict, sales: dict, langkah_lalu: str | None,
                  sebut_produk: bool) -> tuple[str, str] | None:
    """(intent baru, alasan) bila pesan ini menjawab tindakan sales giliran lalu. Jalur sensitif tidak pernah dialihkan."""
    if intent not in _ARAH_SALES or sales.get("profil") != "reseller":
        return None
    if langkah_lalu == "minta_kota" and kota_disebut(text):
        return "kebijakan", "Pembeli grosir menyebut kota yang ditanyakan."
    if langkah_lalu in ("gali_volume", "minta_kota") and slots.get("qty") and sebut_produk:
        return "harga_moq", "Pembeli grosir menyebut volume dan produk."
    if langkah_lalu == "minta_identitas" and (nama_pembeli(text) or slots.get("nama_toko")):
        return "serah_sales", "Data pembeli grosir sudah lengkap, serah ke staf."
    return None
