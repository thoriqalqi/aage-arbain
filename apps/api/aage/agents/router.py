"""Router intent (Sales Agent, langkah 1). Aturan dulu agar cepat, murah, dan bisa dijelaskan;
LLM hanya dipakai untuk pesan yang tidak tertangkap aturan."""

import re
from dataclasses import dataclass, field

from .. import llm
from ..channels.base import TEKS_NOMOR_DIBAGIKAN

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
    "spesifikasi": "Isi kemasan & kandungan",
    "minta_dokumen": "Minta katalog/daftar harga",
    "perlu_staf": "Di luar wewenang AI",
    "identitas": "Tanya identitas asisten",
    "luar_topik": "Di luar topik penjualan",
    "perusahaan": "Tanya tentang CV Arba'in",
    "manipulasi": "Upaya manipulasi/injeksi perintah",
    "pembanding": "Membandingkan dengan merek lain",
    "ambigu": "Produk tidak jelas (tanya balik)",
    "media": "Foto/stiker/suara",
    "darurat": "Darurat kesehatan",
    "sensitif": "Curhat / kondisi sensitif",
    "marah": "Pembeli marah/kecewa",
    "tuduhan": "Tuduhan (penipuan/ilegal)",
    "agama": "Agama & halal",
    "sara": "Politik/SARA/opini",
    "daftar_produk": "Minta daftar semua produk",
    "gratis": "Minta gratis / tekanan",
    "basa_basi": "Basa-basi / penutup",
    "nomor_dibagikan": "Nomor HP dibagikan",
    "cari_riwayat": "Mencari produk pesanan lama dari ciri",
    "lainnya": "Lainnya",
}


def _r(expr: str) -> re.Pattern:
    return re.compile(expr, re.IGNORECASE)


MEDIS_PERSONAL = _r(
    r"\b(saya|aku|sy|aq|gue|anak saya|anakku|anaknya|ibu saya|ibuku|bapak saya|bapakku|ayahku|suami saya|suamiku|"
    r"istri saya|istriku|ortu saya|ortuku|orang tua saya|mama saya|mamaku|papaku|nenek saya|nenekku|kakek saya|adik saya|"
    r"adikku|kakak saya|kakakku|keluarga saya)\b.{0,30}"
    r"\b(sakit|menderita|punya (?:penyakit|riwayat)|kena|didiagnosa|diagnosis|lagi minum obat|minum obat dokter|"
    r"demam|batuk|pilek|diare|muntah|pusing|sesak|nyeri|"
    r"hamil|menyusui|alergi|operasi|kemoterapi|cuci darah)\b|\b(ibu hamil|sedang hamil|menyusui|dosis (?:untuk|buat) (?:saya|anak))\b|"
    # keamanan pemakaian untuk kelompok rentan / bersama obat → selalu staf/tenaga kesehatan
    r"\b(bayi|balita|efek samping\w*|kontraindikasi|interaksi obat|(?:di)?campur\w*\s+(?:dengan\s+|sama\s+)?obat)\b"
)
KELUHAN = _r(
    r"\b(?:tidak|belum)\s+(?:diproses|diproses\w*|direspon\w*|dibalas|ditanggapi)\b|\b(rusak|bocor|pecah|penyok|kedaluwarsa|kadaluarsa|kadaluwarsa|expired|exp|telat|terlambat|belum (?:sampai|datang|diterima|dikirim)|"
    r"kecewa|komplain|complain|keluhan|retur|refund|salah kirim|kurang jumlah|jumlahnya kurang|tidak sesuai|gak sesuai|ga sesuai)\b"
    r"|\b(?:blm|belum)\s+(?:dtg|datang|sampe|nyampe|sampai|nyampai|diterima)\b"
)
# "barang rusak bisa retur?" = bertanya kebijakan, bukan melapor keluhan atas pesanan sendiri.
TANYA = _r(r"\?|\b(bisa|bisakah|boleh|apakah|gimana|bagaimana|gmn|syarat\w*|ketentuan\w*)\b")
LAPOR_PRIBADI = _r(
    r"\b(pesanan|paket|barang|kiriman|order\w*)\s*(saya|sy|aku|kami|kmi)\b|\b(saya|sy|aku|kami)\s+(terima|dapat|dapet|udah|sudah)\b|"
    r"\b(kemarin|kmrn|tadi|udah|udh|sudah|sdh|seminggu)\b"
)
RETUR_KATA = _r(r"\w*retur\w*|\brefund\b|\btukar\b")
KLAIM = _r(r"\b(sembuh\w*|nyembuh\w*|menyembuhkan|menggantikan obat|ganti\w* obat|(?<!toko )obat(?:i|in)?|mengobati|ampuh|manjur|mencegah|cegah|terapi|khasiat(?:nya)? untuk|"
              r"(?:sudah\s+|teruji\s+)?uji klinis|teruji klinis|terbukti (?:ampuh|efektif|klinis)|"
              # janji hasil fisik ("langsing 5 kg seminggu", "bikin anak tinggi") = klaim, diputuskan aturan, bukan LLM
              r"langsing\w*|melangsingkan|kurus\w*|turun\w*\s+berat|berat badan|"
              r"\d+\s*kg\s+(?:dalam|seminggu|sebulan|per\s+(?:minggu|bulan))|"
              r"(?:bikin|membuat)\s+(?:anak\s+)?(?:pinter|pintar|tinggi|langsing|kurus|gemuk|kuat)|"
              r"(?<!diskon )(?<!potongan )(?<!disc )\d+\s*%\s*efektif(?!\s+(?:kapan|mulai|tanggal|berlaku|per))|"
              r"efektif\s*\d+\s*%)")
KONDISIONAL = _r(r"\b(kalau|kalo|jika|apabila|bila|seandainya|misal(?:nya)?)\b")
PESAN_ULANG = _r(
    r"\b(pesan ulang|order ulang|repeat order|pesan lagi|order lagi|ambil lagi|seperti (?:bulan lalu|kemarin|sebelumnya|biasa)|"
    r"sama (?:seperti|kayak|kaya) (?:kemarin|sebelumnya|biasa|bulan lalu)|kayak (?:kemarin|biasa)|kaya biasa)\b"
)
NEGO = _r(r"\b(diskon|disc|disk|potongan|nego|negosiasi|kurangi|lebih murah|mahal|harga khusus|bisa kurang|kurang lagi|harga spesial|harga pas|kasih murah)\b")
PESAN = _r(r"\b(pesan|pesen|order|beli|ambil|kirimkan|kirimin|checkout|po)\b")
HARGA = _r(r"\b(harga\w*|hrg|berapa|brp|moq|minimal|minimum|min order|grosir|price|pricelist|daftar harga|how much|cost)\b")
IZIN = _r(r"\b(izin|ijin|bpom|pom|edar|registrasi|nie|terdaftar|legal)\b")
KEBIJAKAN = _r(
    r"\b(pengiriman|ongkir|ongkos kirim|kirim ke|ekspedisi|pembayaran|bayar|transfer|tempo|\w*retur|garansi|masa simpan|"
    r"kedaluwarsa berapa|cod|kartu kredit|paylater|giro|cicil\w*|luar negeri|ekspor|export|nyampe)\b"
)
SPESIFIKASI = _r(
    r"\bisi(?:nya)?\s*(?:brp|berapa|apa)\b|\b(?:brp|berapa)\s*(?:isi|mg|gram|gr|ml|kapsul|tablet|sachet|botol|biji)\b|"
    r"\b(kandungan\w*|komposisi\w*|ukuran\w*)\b"
)
# Topik yang memang di luar wewenang AI: kemitraan, harga eceran, sampel, sertifikat/batch, opini "paling laris".
PERLU_STAF = _r(
    r"\b(distributor|agen resmi|eksklusif|maklon|merek sendiri|merk sendiri|private label|het|harga eceran|harga ecer|"
    r"sampel|sample|tester|terlaris|best ?seller|paling (?:laris|laku|dicari|diminati|banyak (?:dicari|dibeli|diminati|terjual))|sertifikat\w*|halal|mui|"
    r"coa|batch|tanggal produksi|kerja ?sama|kemitraan|sponsor\w*)\b"
)
MINTA_DOKUMEN = _r(
    r"\b(minta|kirim\w*|share|bagi|send|liat|lihat)\b.{0,25}\b(katalog|brosur|price ?list|daftar harga|company profile|pdf)\b|"
    r"\b(katalog|brosur|price ?list|daftar harga)\b.{0,15}\b(pdf|lengkap|terbaru)\b"
)
PRODUK = _r(
    r"\b(ada|produk|untuk|buat|stok|ready|katalog|komposisi\w*|kandungan\w*|isi\w*|manfaat\w*|khasiat\w*|fungsi\w*|kegunaan|"
    r"varian|jual|rekomendasi|cocok|tersedia|have|sell|available|stock)\b"
)
MINTA_STAF = _r(r"\b(bicara|ngobrol|hubungkan|sambungkan|telepon|telpon|chat|minta)\b.{0,20}\b(staf|staff|admin|cs|orang|manusia|sales|petugas)\b")
# "kamu bot ya?", "ini siapa?", "dengan siapa saya bicara" → dijawab jujur sebagai asisten AI.
IDENTITAS = _r(
    r"\b(kamu|anda|km|kau)\s+(?:itu\s+)?(siapa|bot|robot|ai|mesin|manusia|orang beneran)\b|"
    r"\b(kamu|anda)\b.{0,25}\b(ngapain|tugas\w*|fungsi\w*|bisa apa|kerjanya|perasaan|dibayar|digaji|gaji\w*|bisa salah|"
    r"pernah salah|keliru)\b|\b(siapa|yang)\b.{0,10}\b(bikin|buat|membuat|ciptain|ciptakan|program\w*)\s+(kamu|anda)\b|"
    r"\b(jawab|bales|balas)\w*\s+(?:ini\s+)?(manusia|bot|robot|ai|orang)\b|"
    r"\bini\s+(bot|robot|ai|mesin)\b|"
    r"\b(dibalas|dijawab|dibales)\s+(?:sama\s+|oleh\s+)?(bot|robot|ai|mesin|manusia|otomatis|orang)\b|"
    r"\b(?:bicara|berbicara|chat|ngobrol|ini)\s+(?:dengan|dgn|sama|sm)\s+siapa\b|"
    r"\b(?:dengan|dgn|sama|sm)\s+siapa\s+(?:ini|saya|aku|sy)\b|^\W*(?:ini\s+)?siapa\s*(?:ini|ya|kamu|anda)?\W*$"
)
# Topik yang jelas bukan urusan penjualan. Hanya dipakai bila pesan tidak menyebut produk/harga/pesanan/kebijakan.
LUAR_TOPIK = _r(
    r"\b(cuaca|presiden|menteri|gubernur|politik|pemilu|pilpres|capres|partai|berita|sepak ?bola|bola|piala dunia|"
    r"film|drakor|anime|lagu|musik|game|lelucon|jokes?|lawak|candaan|pantun|puisi|dongeng|cerpen|tugas sekolah|pr|"
    r"pekerjaan rumah|matematika|fisika|skripsi|tempat makan|restoran|kuliner|wisata|liburan|hotel|pacar|jodoh|"
    r"zodiak|ramalan|horoskop|saham|crypto|kripto|bitcoin|coding|ngoding|terjemah\w*|translate|"
    r"bumi (?:itu )?datar|flat earth|ad[zh]?an|maghrib|magrib|subuh|dzuhur|zuhur|ashar|isya|jadwal (?:sholat|salat)|"
    r"sholat|shalat|selingkuh\w*|gosip|artis|seleb\w*|pacaran|mantan)\b"
)
# Perintah yang mencoba mengubah peran/aturan asisten atau meminta akses — ditolak, tidak dijalankan.
MANIPULASI = _r(
    r"\b(abaikan|lupakan|ignore|forget)\b.{0,30}\b(instruksi|perintah|aturan|instructions?|rules|prompt)\b|"
    r"\b(system prompt|prompt (?:sistem|kamu|anda)|instruksi (?:sistem|kamu|anda)|jailbreak|developer mode|"
    r"mode (?:developer|pengembang|admin)|act as|roleplay|berpura.pura|anggap (?:kamu|dirimu))\b|"
    r"\b(kamu|anda)\s+(?:sekarang\s+)?(?:jadi|menjadi|adalah|berperan)\s+(?:seorang\s+)?(dokter|apoteker|admin|owner|manusia)\b|"
    r"\b(akses|hak)\s+(admin|dashboard|database|sistem)\b|\b(password|kata sandi)\b|"
    r"\bbilang\s+(?:saja|aja)\s+(iya|ya|bisa|setuju|aman|halal|asli)\b|\b(instruksi|prompt)\b.{0,30}\b(kamu|anda)\b"
)
# Pertanyaan tentang perusahaan (bukan produk): "arbain itu apa", "apakah arbain penipuan".
PERUSAHAAN = _r(
    r"\b(?:cv\s+)?arba'?\s?in\b.{0,25}\b(apa|siapa|penipu\w*|tipu\w*|asli|resmi|legal|terpercaya|amanah|alamat|lokasi|"
    r"kantor|dimana|di mana|profil)\b|\b(apa|siapa|penipu\w*|tipu\w*)\b.{0,20}\b(?:cv\s+)?arba'?\s?in\b"
)
# Membandingkan dengan merek lain / menuduh produk lain palsu — tidak dijawab dengan menjelekkan.
PEMBANDING = _r(
    r"\b(merek|merk|brand)\s+(?!sendiri\b)(lain|sebelah|\w+)|\b(madu|produk)\s+lain\b|\bdibanding\w*|\bbandingin\b|"
    r"\b(lain|merek|merk|brand|sebelah)\b.{0,30}\b(palsu|abal\w*|oplosan)\b|"
    r"\b(lebih|paling)\s+(bagus|baik|ampuh|manjur|unggul)\s+(dari|daripada)\b"
)
# Janji yang tidak ada di data (stok, uang kembali, waktu sampai, keaslian) → staf, AI tidak menjanjikan.
JANJI = _r(
    r"\b(janji\w*|jamin\w*|dijamin|uang\w*\s+(?:kembali|balik)|balikin uang|pasti (?:sampai|ada|asli|nyampe)|"
    r"asli\s+100|100\s*%\s+asli|tanpa campuran|(?:stok|stock)\w*\s+(?:masih\s+)?(?:ada\s+)?\d+)"
)
# Merujuk produk tanpa menyebutnya ("yang tadi", "segitu", "harganya") → tanya balik bila tidak ada konteks produk.
RUJUKAN = _r(
    r"\b(yang|yg)\s+(tadi|kemarin|itu|sama|[a-z])\b|\bsegitu\b|\bharganya\b|"
    r"\b(yang|yg)\s+(paling\s+)?(murah|mahal|bagus|besar|kecil|enak|laku)\b|\bbeda\w*\b.{0,15}\b(yang|yg)\b"
)
# Darurat: tanggapi dengan peduli, arahkan ke layanan darurat — sebelum aturan lain apa pun.
DARURAT = _r(
    r"\b(sesak\s*na[fp]as|susah\s*na[fp]as|tidak bisa\s*na[fp]as|pingsan|tidak sadar\w*|kejang\w*|sekarat|kritis|"
    r"pendarahan|perdarahan|keracunan|overdosis|bunuh diri|ingin mati|mau mati|pengen mati|akhiri hidup|"
    r"serangan jantung|stroke)\b"
)
SENSITIF = _r(
    r"\b(saya|aku|gue|sy)\b.{0,20}\b(stres\w*|stress|depresi|putus asa|capek (?:sakit|hidup)|lelah (?:sakit|hidup)|"
    r"(?:tidak|gak|ga) kuat lagi|hancur|hopeless|sedih\w*|galau)\b|^\W*(lagi\s+)?(stres\w*|depresi|putus asa|sedih\w*)\b"
)
MARAH = _r(
    r"\b(goblok|goblog|bodoh|bodo|tolol|bego|dungu|idiot|anjing|anjir|bangsat|kampret|brengsek|sialan|bajingan|taik?)\b|"
    r"\b(?:tidak|gak|ga)\s+(?:guna|becus|jelas)\b|\b(becus|payah|ngeselin|nyebelin|kesel|kesal)\b|\bpercuma\b|\bniat jualan\b|\blambat\b|\blelet\b|\blama\s+(?:banget|amat|sekali)\b|"
    r"\b(woi|woy)\b|\bjawab\s+(?:dong|woi|cepat|cepetan)\b|\bmana\s+(?:orang|manusia|admin|cs|staf)\w*"
)
# Tuduhan penipuan/ilegal terhadap kami sendiri (bukan membandingkan merek lain).
TUDUHAN = _r(
    r"\b(penipu\w*|tipu\w*|scam\w*|abal\w*|palsu|narkoba|narkotika|obat terlarang|psikotropika|ganja|sabu|ilegal|mlm|"
    r"money game|ponzi|lapor\w*\s+polisi|polisi|somasi|tuntut\w*)\b"
)
AGAMA = _r(r"\b(halal|haram|riba|bid'?ah|syirik|syariat|syar'?i|fatwa|ustaz\w*|ustad\w*|ulama|demi allah|wallahi)\b")
SARA = _r(
    r"\bagama\b.{0,25}\b(mana|paling|benar|bener|terbaik)\b|\b(partai|capres|cawapres|pilpres|politik)\b|"
    r"\b(israel|palestina|zionis|yahudi|boikot|boycott)\b|\b(china|cina|tionghoa|chinese|pribumi|aseng)\b|\b(kafir|sara)\b"
)
ASAL_PRODUK = _r(
    r"\b(barang|produk|madu|kapsul|ini)\b.{0,15}\b(dari|buatan|asal|produksi|made in|impor)\b.{0,10}\b(cina|china|tiongkok|"
    r"luar negeri|negara mana|mana)\b|\b(buatan|asal|made in)\s+(cina|china|tiongkok|mana)\b"
)
DAFTAR = _r(
    r"\b(produk|jual\w*|barang|dagangan)\b.{0,20}\bapa\s+(?:saja|aja)\b|\bapa\s+(?:saja|aja)\b.{0,25}\b(produk|jual\w*|dijual|barang)\b|"
    r"\b(list|daftar)\s+(semua|seluruh|produk|barang)\b|\bsemua\s+(produk|barang|yang ada)\b|\bkasih list\b|"
    r"\b(yang|yg)\s+lain\s+selain\b|\bselain\s+\w+\b.{0,10}\b(ada|apa)\b"
)
GRATIS = _r(r"\bgratis(?!\s*ongkir)\w*|\bcuma.cuma\b|\bgratisin\b|\bfree\b")
BASA_BASI = _r(
    r"^\W*(bercanda|becanda|canda|serius|oke+|ok|okay|sip|siap|mantap|makasih|terima kasih|thanks|thx|bye|dadah|"
    r"sampai jumpa|udahan|cukup)(\s+(kak|ya|dong|deh|saja|kok|sih|nih|min))*\W*$"
)
# "aku pernah pesan", "riwayat pesanan saya" → jalur repeat order (riwayat dicari, tidak pernah ditebak).
RIWAYAT = _r(r"\b(?:pernah|udah|sudah)\s+(?:pesan|order|beli)\b|\briwayat\s+(?:pesanan|order|belanja|pembelian)\b")
KATEGORI_SAJA = _r(r"^\W*(madu|kapsul|teh|minyak|vitamin|serbuk|sirup|tablet|herbal|jamu|suplemen)\W*$")
MEDIA = re.compile(r"^\s*\[(\w+) tidak didukung\]\s*$")
# "bisa bantu saya ga" / "mau tanya dong" → sapaan pembuka.
BANTUAN = _r(r"^\W*(bisa|boleh|tolong|mau|minta|numpang)\s+(bantu|tanya|nanya)\w*(\s+\w+){0,3}\W*$")
YA = _r(r"^\s*(ya|iya|iyaa|boleh|mau|oke|ok|okay|baik|siap|silakan|yes)\b")
SALAM = _r(r"^\s*(halo|hallo|hai|hi|assalamu'?alaikum|assalamualaikum|selamat (?:pagi|siang|sore|malam)|pagi|siang|sore|malam|permisi|p)\W*\s*(kak|min|gan|pak|bu)?\W*$")

QTY_RE = _r(r"(\d{1,5})\s*(karton|ktn|dus|dos|box|kardus|ctn|krt|carton)")
QTY_BARE_RE = _r(r"(?<![-\w])(\d{1,5})\b(?!\s*(?:%|persen|ml|g|gr|gram|mg|mcg|iu|kapsul|tablet|sachet|hari|jam|bulan))")
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


def route(text: str, *, inbound_verdict: str, inbound_rules: list[str], konteks: dict,
          mentions_product: bool = False, multi_item: bool = False) -> RouteResult:
    slots = extract_slots(text)
    t = text.strip()

    if t == TEKS_NOMOR_DIBAGIKAN:
        return RouteResult("nomor_dibagikan", "Pembeli membagikan nomor HP-nya sendiri.", slots)
    if DARURAT.search(t):
        return RouteResult("darurat", "Kondisi darurat kesehatan → arahkan ke layanan darurat + staf.", slots)
    if MEDIA.match(t):
        return RouteResult("media", "Foto/stiker/suara belum bisa dibaca AI.", slots)
    if SENSITIF.search(t):
        return RouteResult("sensitif", "Curhat/kondisi sensitif → peduli, tanpa saran medis, tanpa promosi.", slots)
    if MEDIS_PERSONAL.search(t):
        return RouteResult("medis_personal", "Pertanyaan menyangkut kondisi kesehatan pribadi → wajib staf.", slots)
    if MANIPULASI.search(t):
        return RouteResult("manipulasi", "Upaya mengubah aturan asisten / meminta akses — ditolak.", slots)
    if MINTA_STAF.search(t) or (konteks.get("tawar_staf") and YA.match(t)):
        return RouteResult("minta_staf", "Pembeli meminta bicara dengan staf.", slots)
    if KELUHAN.search(t):
        if KONDISIONAL.search(t) and KEBIJAKAN.search(t):
            return RouteResult("kebijakan", "Pertanyaan kebijakan bersyarat (bukan keluhan aktual).", slots)
        if RETUR_KATA.search(t) and TANYA.search(t) and not LAPOR_PRIBADI.search(t):
            return RouteResult("kebijakan", "Menanyakan aturan retur (bukan melapor pesanan sendiri).", slots)
        return RouteResult("keluhan", "Ada kata kunci keluhan/komplain → wajib staf.", slots)
    if MARAH.search(t):
        return RouteResult("marah", "Pembeli marah/kecewa → empati & teruskan ke staf.", slots)
    if TUDUHAN.search(t) and not PEMBANDING.search(t):
        return RouteResult("tuduhan", "Tuduhan penipuan/ilegal → jawab dari data, tawarkan staf.", slots)
    if inbound_verdict == "blocked" or KLAIM.search(t) or "R05" in inbound_rules:
        return RouteResult("klaim_kesehatan", "Pesan meminta klaim terkait penyakit/khasiat terapi.", slots)
    if JANJI.search(t):
        return RouteResult("perlu_staf", "Meminta janji/jaminan di luar data (stok, waktu, uang kembali, keaslian).", slots)
    if AGAMA.search(t):
        return RouteResult("agama", "Agama/halal → jawab sertifikasi dari data, tanpa fatwa.", slots)
    if PERUSAHAAN.search(t):
        return RouteResult("perusahaan", "Pertanyaan tentang CV Arba'in.", slots)
    if PEMBANDING.search(t):
        return RouteResult("pembanding", "Membandingkan dengan merek lain — tidak menjelekkan pihak lain.", slots)
    if PERLU_STAF.search(t):
        return RouteResult("perlu_staf", "Topik di luar wewenang AI (kemitraan/HET/sampel/sertifikat/opini).", slots)
    if ASAL_PRODUK.search(t):
        return RouteResult("perlu_staf", "Asal/negara produksi tidak ada di katalog → staf.", slots)
    if SARA.search(t) and not mentions_product and not any(r.search(t) for r in (HARGA, PESAN, KEBIJAKAN)):
        return RouteResult("sara", "Politik/SARA/opini → netral, kembali ke topik.", slots)
    if IDENTITAS.search(t):
        return RouteResult("identitas", "Pembeli menanyakan siapa/apa yang membalas.", slots)
    if LUAR_TOPIK.search(t) and not mentions_product and not any(
            r.search(t) for r in (HARGA, PESAN, KEBIJAKAN, IZIN, NEGO, SPESIFIKASI)):
        return RouteResult("luar_topik", "Topik di luar penjualan produk CV Arba'in.", slots)
    if MINTA_DOKUMEN.search(t):
        return RouteResult("minta_dokumen", "Meminta katalog/daftar harga lengkap dalam bentuk dokumen.", slots)
    if DAFTAR.search(t) and not mentions_product:
        return RouteResult("daftar_produk", "Meminta daftar produk → seluruh katalog aktif.", slots)
    if PESAN_ULANG.search(t) or RIWAYAT.search(t):
        return RouteResult("pesan_ulang", "Permintaan pesan ulang / menyinggung riwayat pesanan.", slots)
    if konteks.get("cari_riwayat") and not (PESAN.search(t) or HARGA.search(t)):
        return RouteResult("cari_riwayat", "Pembeli menjelaskan ciri produk pesanan lama.", slots)
    if BANTUAN.match(t) or SALAM.match(t):
        return RouteResult("salam", "Salam / permintaan bantuan umum.", slots)
    if BASA_BASI.match(t):
        return RouteResult("basa_basi", "Basa-basi / penutup percakapan.", slots)
    if GRATIS.search(t) and not KEBIJAKAN.search(t):
        return RouteResult("gratis", "Minta gratis → tidak menjanjikan, tawarkan staf.", slots)
    tanpa_konteks = not mentions_product and not konteks.get("last_product_ids") and not konteks.get("order_pending")
    if tanpa_konteks and (KATEGORI_SAJA.match(t) or RUJUKAN.search(t)):
        return RouteResult("ambigu", "Merujuk produk tanpa menyebut namanya & tidak ada konteks produk → tanya balik.", slots)
    if SPESIFIKASI.search(t) and not NEGO.search(t):
        return RouteResult("spesifikasi", "Pertanyaan isi kemasan/kandungan produk.", slots)
    if NEGO.search(t) or ("diskon_diminta" in slots and HARGA.search(t)):
        return RouteResult("negosiasi", "Permintaan diskon/negosiasi harga.", slots)
    pending = konteks.get("order_pending")
    if PESAN.search(t) and KEBIJAKAN.search(t) and not mentions_product and not pending:
        return RouteResult("kebijakan", "Pertanyaan kebijakan (mis. COD) di dalam niat memesan tanpa produk.", slots)
    if PESAN.search(t) and not HARGA.search(t):
        return RouteResult("pesan", "Permintaan pemesanan.", slots)
    if multi_item:
        return RouteResult("harga_moq", "Daftar beberapa produk + jumlah → penawaran gabungan.", slots)
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
    if mentions_product:
        return RouteResult("tanya_produk", "Menyebut nama produk di katalog.", slots)

    # Pesan yang tidak tertangkap aturan dinilai penjaga topik LLM di graph (agents/penjaga.py).
    return RouteResult("lainnya", "Tidak cocok dengan pola intent mana pun.", slots)


def jelas_jualan(text: str, *, mentions_product: bool, konteks: dict) -> bool:
    """Pesan yang jelas-jelas soal jualan tidak perlu dinilai penjaga topik LLM."""
    return (mentions_product or bool(konteks.get("order_pending"))
            or any(r.search(text) for r in (HARGA, PESAN, KEBIJAKAN, IZIN, NEGO, SPESIFIKASI, MINTA_DOKUMEN, PESAN_ULANG)))
