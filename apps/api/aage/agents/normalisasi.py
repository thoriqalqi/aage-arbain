"""Perapi pesan pembeli sebelum dirutekan: singkatan, bahasa gaul, dan beberapa kata Inggris → bahasa Indonesia baku.

Deterministik (tanpa LLM) dan hanya mengganti kata utuh; huruf besar/kecil kata lain dipertahankan agar nama toko
dan alamat tidak rusak. Teks asli tetap disimpan di pesan & Ledger — hasil rapian hanya dipakai untuk memahami maksud.
"""

import re

SLANG = {
    # angka & harga
    "brp": "berapa", "brapa": "berapa", "hrg": "harga", "hrga": "harga", "hargane": "harganya",
    # kata ganti & sapaan
    "sy": "saya", "sya": "saya", "aq": "aku", "gw": "saya", "gue": "saya", "km": "kamu", "kmu": "kamu",
    # negasi
    "ga": "tidak", "gak": "tidak", "gk": "tidak", "g": "tidak", "nggak": "tidak", "ngga": "tidak", "ngak": "tidak",
    "enggak": "tidak", "engga": "tidak", "kagak": "tidak", "tdk": "tidak", "gaada": "tidak ada", "gada": "tidak ada",
    # kata kerja & penghubung
    "bs": "bisa", "bsa": "bisa", "mo": "mau", "pengen": "ingin", "pgn": "ingin", "yg": "yang", "utk": "untuk",
    "dgn": "dengan", "dg": "dengan", "krn": "karena", "tp": "tapi", "jg": "juga", "aja": "saja",
    "blm": "belum", "udh": "sudah", "udah": "sudah", "sdh": "sudah", "dah": "sudah", "bgt": "banget",
    "emg": "memang", "emang": "memang", "gmn": "gimana", "knp": "kenapa", "skrg": "sekarang", "tlg": "tolong",
    "pesen": "pesan", "mesen": "pesan", "psn": "pesan", "kirimin": "kirimkan", "sediain": "sediakan",
    "nyembuhin": "menyembuhkan", "sembuhin": "menyembuhkan", "ngobatin": "mengobati", "obatin": "mengobati",
    "gantiin": "menggantikan", "dikasih": "diberikan",
    # tempat & istilah
    "smg": "Semarang", "sby": "Surabaya", "jkt": "Jakarta", "cod": "COD",
    # Inggris yang sering dicampur
    "honey": "madu", "cough": "batuk", "price": "harga", "pricelist": "daftar harga",
}
# Sapaan & tawa tanpa makna untuk dipahami ("min" hanya bila bukan "min order").
_FILLER = re.compile(r"\b(?:wk(?:wk)+\w*|ha(?:ha)+\w*|he(?:he)+\w*|xi(?:xi)+\w*|bro|sis|gan|min(?!\s*(?:order|beli|pembelian|pesan)))\b",
                     re.IGNORECASE)
_WORD = re.compile(r"[A-Za-z]+")


_SATUAN = {"g", "km"}  # "250 g" / "5 km" adalah satuan, bukan "tidak" / "kamu"


def _ganti(m: re.Match) -> str:
    w = m.group(0)
    if w.lower() in _SATUAN and re.search(r"\d\s*$", m.string[:m.start()]):
        return w
    return SLANG.get(w.lower(), w)


def rapikan(text: str) -> str:
    """'brp hrg madu stamina ka' → 'berapa harga madu stamina ka'. Mengembalikan teks asli bila hasil kosong."""
    out = _WORD.sub(_ganti, _FILLER.sub(" ", text))
    out = re.sub(r"[ \t]{2,}", " ", out).strip()
    return out or text
