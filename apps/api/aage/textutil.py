"""Utilitas teks bahasa Indonesia: normalisasi, stemming ringan, sinonim, embedding lokal.

Embedding lokal (hashing) dipakai saat tidak ada API key atau untuk uji offline. Hasilnya
deterministik, sehingga eval dan demo bisa diulang persis sama."""

import hashlib
import math
import re

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Bahasa informal → baku (percakapan WhatsApp)
INFORMAL = {
    "gk": "tidak", "ga": "tidak", "gak": "tidak", "nggak": "tidak", "ngga": "tidak", "tdk": "tidak",
    "yg": "yang", "utk": "untuk", "buat": "untuk", "brp": "berapa", "brapa": "berapa", "hrg": "harga",
    "dgn": "dengan", "sm": "sama", "aja": "saja", "ad": "ada", "kak": "", "min": "", "gan": "",
    "bs": "bisa", "bsa": "bisa", "krn": "karena", "pcs": "pcs", "ktn": "karton", "dus": "karton",
    "dos": "karton", "kardus": "karton", "kotak": "karton", "ctn": "karton", "bpom": "bpom",
    "skrg": "sekarang", "tp": "tapi", "jg": "juga", "lg": "lagi", "sy": "saya", "aq": "saya",
    "km": "kamu", "dr": "dari", "trs": "terus", "bln": "bulan", "kmrn": "kemarin", "disc": "diskon",
    "disk": "diskon", "potongan": "diskon", "nego": "negosiasi", "order": "pesan", "pesen": "pesan",
    "mesen": "pesan", "repeat": "ulang", "imun": "imunitas", "fit": "bugar",
}

# Sinonim konsep → memperluas query retrieval
SYNONYMS = {
    "stamina": ["stamina", "bugar", "energi", "tenaga", "vitalitas", "lelah"],
    "imunitas": ["imunitas", "daya", "tahan", "tubuh", "imun"],
    "pencernaan": ["pencernaan", "perut", "lambung", "kembung", "maag"],
    "tidur": ["tidur", "rileks", "tenang", "nyenyak", "istirahat"],
    "sendi": ["sendi", "pegal", "linu", "otot"],
    "masuk": ["masuk", "angin", "hangat", "meriang"],
    "kulit": ["kulit", "wajah", "rambut"],
    "anak": ["anak", "balita", "nafsu", "makan"],
    "izin": ["izin", "edar", "bpom", "registrasi", "pom"],
}

_PREFIXES = ("meng", "meny", "mem", "men", "me", "peng", "peny", "pem", "pen", "pe", "ber", "ter", "di", "ke", "se")
_SUFFIXES = ("kannya", "annya", "kan", "an", "nya", "lah", "kah")


def normalize(text: str) -> str:
    text = text.lower().replace("’", "'")
    text = re.sub(r"(\d)\s*(%|persen)", r"\1 persen", text)
    return text


def tokens(text: str) -> list[str]:
    out = []
    for tok in _TOKEN_RE.findall(normalize(text)):
        tok = INFORMAL.get(tok, tok)
        if tok:
            out.extend(tok.split())
    return out


def stem(word: str) -> str:
    if len(word) <= 4 or word.isdigit():
        return word
    for suf in _SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 4:
            word = word[: -len(suf)]
            break
    for pre in _PREFIXES:
        if word.startswith(pre) and len(word) - len(pre) >= 4:
            word = word[len(pre):]
            break
    return word


STOPWORDS = set(
    "yang dan di ke dari untuk dengan ada apa apakah ini itu saya kami kita mau ingin bisa tidak ya "
    "halo hai pak bu mas mbak kak tolong mohon info berapa gimana bagaimana kalau kalo juga sudah belum "
    "nya dong deh sih nih lah kah pun atau tapi jadi pada oleh produk".split()
)


def content_tokens(text: str) -> list[str]:
    return [t for t in tokens(text) if t not in STOPWORDS and len(t) > 1]


def expand(tokens_: list[str]) -> list[str]:
    out = list(tokens_)
    for t in tokens_:
        for key, syns in SYNONYMS.items():
            if t == key or t in syns:
                out.extend(syns)
    return out


def _bucket(feature: str, dim: int) -> tuple[int, float]:
    h = hashlib.blake2b(feature.encode(), digest_size=8).digest()
    idx = int.from_bytes(h[:4], "little") % dim
    sign = 1.0 if h[4] & 1 else -1.0
    return idx, sign


def local_embed(text: str, dim: int = 384) -> list[float]:
    vec = [0.0] * dim
    toks = content_tokens(text)
    feats: list[tuple[str, float]] = []
    for t in expand(toks):
        s = stem(t)
        feats.append(("w:" + s, 1.0))
        padded = f"#{s}#"
        for i in range(len(padded) - 2):
            feats.append(("c:" + padded[i : i + 3], 0.35))
    for a, b in zip(toks, toks[1:]):
        feats.append((f"b:{stem(a)}_{stem(b)}", 0.6))
    for feat, weight in feats:
        idx, sign = _bucket(feat, dim)
        vec[idx] += sign * weight
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def rupiah(value: float) -> str:
    return "Rp " + f"{value:,.0f}".replace(",", ".")
