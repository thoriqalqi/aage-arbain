"""ClaimGuard tahap 1: kamus pola deterministik. Keputusan "diblokir" dari tahap ini final —
tahap 2 dan LLM-judge tidak pernah boleh menurunkannya."""

import re
from dataclasses import dataclass

DISEASES = [
    "diabetes", "kencing manis", "hipertensi", "darah tinggi", "hipotensi", "kanker", "tumor", "kista",
    "mioma", "stroke", "jantung koroner", "penyakit jantung", "serangan jantung", "gagal ginjal",
    "batu ginjal", "ginjal", "liver", "hepatitis", "sirosis", "tbc", "tuberkulosis", "covid", "corona",
    "hiv", "aids", "asma", "asam urat", "gout", "kolesterol", "rematik", "reumatik", "osteoporosis",
    "gerd", "wasir", "ambeien", "hemoroid", "alzheimer", "parkinson", "autis", "autisme", "impotensi",
    "ejakulasi dini", "disfungsi ereksi", "infertilitas", "mandul", "lupus", "vertigo", "migrain",
    "insomnia", "depresi", "demam berdarah", "dbd", "tifus", "tipes", "malaria", "sinusitis", "polip",
    "katarak", "glaukoma", "psoriasis", "eksim", "obesitas", "anemia", "maag kronis", "tukak lambung",
    "radang", "infeksi", "virus", "bakteri", "kanker serviks", "kanker payudara", "leukemia", "epilepsi",
    "sakit gula", "gula darah tinggi", "penyakit kronis", "penyakit degeneratif", "tumor ganas",
]

BIOMARKERS = ["gula darah", "kolesterol", "tekanan darah", "asam urat", "trigliserida", "kadar gula", "tensi", "hb"]

THERAPY_CONTEXT = (
    r"menyembuhkan|sembuhkan|sembuh|penyembuh|mengobati|obati|obat|pengobatan|mengatasi|atasi|melawan|"
    r"membasmi|membunuh|menghancurkan|menurunkan|menormalkan|mencegah|cegah|terapi|ampuh|efektif|khusus|"
    r"penderita|pasien|untuk|bagi|bebas dari|terbebas|menghilangkan|hilangkan|meredakan|redakan|"
    r"mengurangi|mengontrol|mengendalikan|menangkal|anti"
)

NEGATORS = r"tidak|tak|bukan|belum|jangan|tidaklah|bukanlah"


@dataclass(frozen=True)
class Rule:
    id: str
    label: str
    severity: str  # blocked | review
    pattern: re.Pattern
    negatable: bool = True
    alasan: str = ""


def _p(expr: str) -> re.Pattern:
    return re.compile(expr, re.IGNORECASE)


_DIS = "|".join(sorted((re.escape(d) for d in DISEASES), key=len, reverse=True))
_BIO = "|".join(sorted((re.escape(b) for b in BIOMARKERS), key=len, reverse=True))

RULES: list[Rule] = [
    Rule("R01", "Klaim menyembuhkan", "blocked",
         _p(r"\b(menyembuhkan|sembuhkan|disembuhkan|penyembuh|penyembuhan|kesembuhan|sembuh)\b"),
         alasan="Produk herbal/suplemen tidak boleh mengklaim menyembuhkan penyakit."),
    Rule("R02", "Klaim mengobati", "blocked",
         _p(r"\b(mengobati|obati|diobati|pengobatan|obat (?:untuk|bagi|segala|ampuh|mujarab|alami untuk)|obat kuat)\b"),
         alasan="Klaim pengobatan hanya untuk obat dengan izin edar obat, bukan herbal/suplemen."),
    Rule("R03", "Klaim mencegah penyakit", "blocked",
         _p(rf"\b(mencegah|cegah|pencegahan|menangkal|tangkal|terhindar dari|kebal|anti)\b\W+(?:\w+\W+){{0,3}}?(?:{_DIS}|penyakit)\b"
            rf"|\b(?:menurunkan|mengurangi|memperkecil|menekan)\s+risiko\W+(?:\w+\W+){{0,2}}?(?:{_DIS}|penyakit)\b"),
         alasan="Klaim pencegahan penyakit tidak diizinkan untuk produk herbal/suplemen."),
    Rule("R04", "Nama penyakit dalam konteks terapi", "blocked",
         _p(rf"\b(?:{THERAPY_CONTEXT})\b\W+(?:\w+\W+){{0,4}}?(?:{_DIS})\b|\b(?:{_DIS})\b\W+(?:\w+\W+){{0,3}}?(?:{THERAPY_CONTEXT})\b"),
         alasan="Menghubungkan produk dengan penyakit tertentu = klaim terapi."),
    Rule("R16", "Klaim mengubah parameter klinis", "blocked",
         _p(rf"\b(menurunkan|turunkan|menormalkan|normalkan|menstabilkan|mengontrol|mengendalikan|menetralkan|menyeimbangkan|menjaga|memelihara)\b\W+(?:\w+\W+){{0,2}}?(?:{_BIO})\b"),
         alasan="Klaim menurunkan/menormalkan parameter klinis (gula darah, kolesterol, tensi) adalah klaim obat."),
    Rule("R06", "Jaminan hasil", "blocked",
         _p(r"\b(dijamin|jaminan (?:sembuh|hasil)|garansi (?:sembuh|hasil|uang kembali)|pasti (?:sembuh|berhasil|ampuh|manjur|hilang)|terbukti (?:ampuh|manjur|klinis|secara klinis|menyembuhkan|100)|teruji (?:secara )?klinis|lolos uji klinis)\b"),
         alasan="Janji/jaminan hasil kesehatan tidak boleh diberikan."),
    Rule("R07", "Klaim absolut 100%", "blocked",
         _p(r"\b100\s*(?:%|persen)\s*(?:sembuh|ampuh|efektif|aman|berhasil|manjur|ampuh|bebas|tuntas|hilang)"),
         negatable=False, alasan="Klaim absolut 100% tentang hasil/keamanan tidak dapat dibuktikan."),
    Rule("R08", "Tanpa efek samping", "blocked",
         _p(r"\b(tanpa|tidak ada|tidak memiliki|tidak menimbulkan|bebas|nol|zero)\s+efek\s+samping"),
         negatable=False, alasan="Klaim 'tanpa efek samping' dilarang; setiap produk dapat menimbulkan reaksi."),
    Rule("R12", "Pengganti obat/dokter", "blocked",
         _p(r"\b(pengganti obat|menggantikan obat|ganti obat|tidak perlu (?:ke )?dokter|tak perlu (?:ke )?dokter|tanpa (?:perlu )?(?:resep|ke dokter)|berhenti minum obat|stop (?:minum )?obat|lepas obat|tidak perlu (?:minum )?(?:obat|lagi minum obat))\b"),
         alasan="Mendorong mengganti obat/dokter membahayakan konsumen."),
    Rule("R09", "Kata ajaib/mukjizat", "blocked",
         _p(r"\b(ajaib|mukjizat|mujizat|mujarab|ces pleng|cespleng|sakti|segala penyakit|semua penyakit|seribu penyakit|1000 penyakit)\b"),
         alasan="Klaim berlebihan (ajaib/segala penyakit) termasuk overclaim."),
    Rule("R15", "Klaim seksual/hormonal", "blocked",
         _p(r"\b(obat kuat|perkasa|keperkasaan|ereksi|ejakulasi|libido|gairah pria|vitalitas pria|tahan lama di ranjang|memperbesar)\b"),
         alasan="Klaim fungsi seksual tidak diizinkan untuk produk herbal umum."),
    Rule("R05", "Penyebutan nama penyakit", "review",
         _p(rf"\b(?:{_DIS})\b"),
         negatable=False, alasan="Ada nama penyakit; pastikan tidak dikaitkan dengan khasiat produk."),
    Rule("R10", "Superlatif/berlebihan", "review",
         _p(r"\b(ampuh|manjur|paling (?:ampuh|manjur|efektif|bagus|baik|aman)|nomor\s*1|no\.?\s*1|terbaik|terampuh|termanjur|instan|seketika|permanen|selamanya|tuntas|super ampuh|luar biasa|terlaris|paling laris|drastis|berlipat|signifikan|maksimal dalam waktu singkat|rahasia awet muda)\b"),
         alasan="Superlatif perlu bukti dan sering dianggap menyesatkan."),
    Rule("R11", "Perbandingan merek", "review",
         _p(r"\b(lebih (?:baik|bagus|ampuh|efektif|manjur|unggul|aman) (?:dari|daripada|dibanding)|dibanding(?:kan)? (?:merek|produk) (?:lain|sebelah)|merek lain|produk sebelah|kompetitor|mengalahkan)\b"),
         alasan="Perbandingan dengan merek lain memerlukan data pembanding yang sah."),
    Rule("R13", "Klaim detoks/peluruh", "review",
         _p(r"\b(detoks|detox|membuang racun|mengeluarkan racun|meluruhkan|peluruh|membersihkan darah|cuci darah)\b"),
         alasan="Klaim detoks/peluruh perlu dicocokkan dengan klaim terdaftar."),
    Rule("R18", "Klaim keamanan", "review",
         _p(r"\baman\s+(?:dikonsumsi|diminum|untuk)\b.{0,30}\b(?:setiap hari|jangka panjang|semua (?:usia|umur|orang)|anak|ibu hamil|selamanya)\b"),
         negatable=False, alasan="Klaim keamanan umum memerlukan bukti dan sebaiknya mengikuti label."),
    Rule("R19", "Endorsement tenaga kesehatan", "review",
         _p(r"\b((?:dokter|ahli|apoteker|spesialis)\s+(?:\w+\s+)?merekomendasikan|direkomendasikan (?:oleh )?(?:dokter|ahli|apoteker))\b"),
         alasan="Endorsement dokter/ahli dalam promosi memerlukan dasar yang sah."),
    Rule("R14", "Klaim 100% (umum)", "review",
         _p(r"\b100\s*(?:%|persen)"),
         negatable=False, alasan="Angka 100% perlu bukti (mis. sertifikat) yang dirujuk."),
]

STAT_RE = _p(r"\b\d+(?:[.,]\d+)?\s*(?:%|persen|kali lipat|x lipat)|\b\d+\s+dari\s+\d+\b")
STAT_EXEMPT_RE = _p(r"\b(diskon|potongan|hemat|ppn|pajak|harga|cashback|bunga|dp|uang muka|kadar air|kemasan|isi)\b")
STAT_HEALTH_RE = _p(r"\b(meningkat\w*|peningkatan|menurun\w*|efektif|pasien|responden|pengguna|pelanggan|dokter|metabolisme|merasakan|tubuh|imun\w*|energi|stamina|sembuh\w*|penelitian|studi|riset|uji|terbukti|khasiat|manfaat|kesehatan|risiko)\b")
SOURCE_RE = _p(r"(\bsumber\s*:|\bmenurut\b|\bdikutip\b|\bjurnal\b|\(\s*\w[^)]*\d{4}\s*\)|\[\d+\]|https?://)")

BENEFIT_RE = _p(
    r"\b(membantu|memelihara|menjaga|meningkatkan|mendukung|menguatkan|memperkuat|melancarkan|meredakan|"
    r"mengurangi|menyegarkan|menambah|menghangatkan|bermanfaat|berkhasiat|khasiat|manfaat|baik untuk|"
    r"cocok untuk|berguna|ampuh|efektif|digunakan untuk|untuk kesehatan|untuk daya tahan|merawat|membuat|"
    r"menyeimbangkan|memperbaiki|diformulasikan untuk)\b"
)

HEALTH_OBJ_RE = _p(
    r"\b(tubuh|badan|kesehatan|sehat|stamina|daya tahan|imun\w*|pencernaan|perut|lambung|energi|kebugaran|bugar|"
    r"nafsu makan|tidur|rileks|pegal|linu|nyeri|otot|sendi|haid|batuk|tenggorokan|kulit|rambut|hati|liver|"
    r"ingat|konsentrasi|tulang|nutrisi|gizi|masuk angin|kembung|hangat|segar|organ|darah|jantung|ginjal|"
    r"metabolisme|vitalitas|fungsi|pemulihan|kolesterol|gula|tensi|berat badan|awet muda|penuaan|racun|"
    r"subur|kesuburan|hormon|sperma|kecantikan|langsing|lelah|konsentrasi|peredaran)\b"
)


def is_benefit_claim(sentence: str) -> bool:
    return bool(BENEFIT_RE.search(sentence) and HEALTH_OBJ_RE.search(sentence))


_NEG_BEFORE =re.compile(rf"\b(?:{NEGATORS})\b(?!\s+(?:hanya|cuma|saja|sekadar|cuman))", re.IGNORECASE)
_CLAUSE_BREAK = re.compile(r"[,;:]|\b(?:tetapi|tapi|namun|sedangkan|melainkan|dan juga)\b", re.IGNORECASE)


def is_negated(sentence: str, start: int) -> bool:
    """True bila kata kunci didahului negator dalam klausa yang sama (≤6 kata),
    kecuali bentuk 'tidak hanya'/'bukan cuma' yang justru menegaskan klaim."""
    prefix = sentence[:start]
    breaks = list(_CLAUSE_BREAK.finditer(prefix))
    clause = prefix[breaks[-1].end():] if breaks else prefix
    words = clause.split()
    window = " ".join(words[-7:])
    return bool(_NEG_BEFORE.search(window))


def stat_without_source(sentence: str) -> re.Match | None:
    m = STAT_RE.search(sentence)
    if not m:
        return None
    pre = sentence[max(0, m.start() - 30): m.start()]
    if STAT_EXEMPT_RE.search(pre) or STAT_EXEMPT_RE.search(sentence[m.end(): m.end() + 15]):
        return None
    if not STAT_HEALTH_RE.search(sentence):
        return None
    if SOURCE_RE.search(sentence):
        return None
    return m
