"""Impor katalog mitra dari Excel/CSV: unggah → validasi per baris → pratinjau → konfirmasi → diterapkan.

- Satu unggahan mengganti katalog: produk di file di-upsert, produk aktif yang tidak ada di file dinonaktifkan (tidak
  dihapus — riwayat pesanan & Ledger tetap utuh). Sheet "Kebijakan" (bila ada) mengganti kebijakan kirim/bayar/retur.
- Baris yang salah tidak diterapkan dan selalu dilaporkan (nomor baris, kolom, alasan). Bila ada baris salah, konfirmasi
  harus eksplisit (`lewati_error`).
- Penerapan berjalan dalam SATU transaksi: gagal di tengah → rollback, katalog lama utuh.
- Kolom kosong disimpan kosong. Agent menjawab "belum ada datanya" untuk data yang kosong — tidak pernah dikarang.
"""

import csv
import io
import re
import secrets
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .. import clock, ledger, llm
from ..models import ApprovedClaim, Chunk, Document, KatalogImpor, PricingRule, Product
from . import ingest

KATALOG_JUDUL = "Katalog Produk"
KEBIJAKAN_JUDUL = "Kebijakan Penjualan"
MAKS_UKURAN = 5 * 1024 * 1024
MAKS_BARIS = 2000


@dataclass(frozen=True)
class Kolom:
    nama: str
    wajib: bool
    contoh: str
    contoh_kosong: str  # contoh baris kedua: memperlihatkan kolom opsional yang boleh kosong
    petunjuk: str


KOLOM_PRODUK = [
    Kolom("sku", False, "ARB-101", "", "Kode unik produk. Kosongkan untuk dibuat otomatis dari nama. Dipakai mencocokkan "
          "produk lama saat impor ulang."),
    Kolom("nama", True, "Madu Stamina Plus 250 g", "Teh Daun Kelor 20 kantong", "Nama produk persis seperti di kemasan."),
    Kolom("kategori", False, "Obat Bahan Alam", "Obat Bahan Alam", "Mis. Obat Bahan Alam / Suplemen Kesehatan."),
    Kolom("harga_per_box", True, "2340000", "960000", "Harga grosir per satuan (angka, rupiah). Boleh 2.340.000 atau Rp 2.340.000."),
    Kolom("satuan", False, "box", "box", "Satuan grosir. Default: box."),
    Kolom("kemasan", False, "Botol 250 g; box isi 36 botol", "Kotak 20 kantong; box isi 40 kotak",
          "Isi kemasan & isi per box. AI memakai teks ini untuk pertanyaan isi kemasan."),
    Kolom("moq", False, "5", "5", "Minimum order per produk (angka). Default: 1."),
    Kolom("stok", False, "120", "", "Stok saat impor (angka, satuan grosir). Kosong = belum ada data stok."),
    Kolom("deskripsi", False, "Madu dengan ekstrak jahe merah.", "", "Deskripsi singkat (bukan klaim khasiat)."),
    Kolom("komposisi", False, "Madu; Ekstrak jahe merah; Ekstrak ginseng", "Daun kelor kering", "Bahan, pisahkan dengan titik koma."),
    Kolom("klaim_disetujui", False, "Membantu memelihara stamina", "",
          "Klaim resmi sesuai izin edar, pisahkan dengan |. Kosong = AI tidak menyebut manfaat apa pun."),
    Kolom("izin_edar", False, "POM TR 123456789", "", "Nomor izin edar BPOM. Kosong = AI menjawab belum ada datanya."),
    Kolom("halal_status", False, "Bersertifikat Halal", "",
          "Bersertifikat Halal / Dalam proses / Tidak bersertifikat. Kosong = belum ada data."),
    Kolom("halal_nomor", False, "ID12345678901234", "", "Nomor sertifikat halal."),
    Kolom("halal_lembaga", False, "BPJPH", "", "Lembaga penerbit sertifikat."),
    Kolom("bko_hasil", False, "Negatif", "", "Hasil uji Bahan Kimia Obat. Hanya 'Negatif' yang diterima; kosong = belum ada data."),
    Kolom("bko_nomor_laporan", False, "LHU-2026-0001", "", "Nomor laporan hasil uji BKO."),
    Kolom("diskon_volume", False, "10:3|25:5|50:8|100:10", "",
          "Tier diskon maksimal: minimal_box:persen, pisahkan dengan |. Kosong = tanpa diskon otomatis."),
    Kolom("kata_kunci", False, "stamina energi madu jahe", "kelor teh", "Kata pencarian tambahan (sinonim)."),
    Kolom("kata_terlarang", False, "menyembuhkan|obat kuat", "", "Frasa yang tidak boleh dipakai untuk produk ini, pisahkan |."),
    Kolom("het_per_botol", False, "78000", "", "Harga eceran tertinggi per botol (opsional)."),
]
KOLOM_KEBIJAKAN = [
    Kolom("topik", True, "pengiriman", "", "Salah satu: " + ", ".join(
        ["minimum_order", "harga_diskon", "pengiriman", "pembayaran", "retur", "pesan_ulang", "penyimpanan"])),
    Kolom("isi", True, "Pengiriman dari gudang Semarang ke seluruh Jawa Tengah dalam 1–3 hari kerja.", "",
          "Isi kebijakan dalam kalimat lengkap. AI mengutip kalimat dari sini."),
]
# Topik → judul bagian dokumen yang dicari agent saat menjawab kebijakan (agents/drafter._KEBIJAKAN_TOPIK).
TOPIK = {
    "minimum_order": "Minimum order dan satuan", "harga_diskon": "Harga dan diskon volume", "pengiriman": "Pengiriman",
    "pembayaran": "Pembayaran", "retur": "Retur", "pesan_ulang": "Pesan ulang (repeat order)", "penyimpanan": "Penyimpanan",
}
CONTOH_KEBIJAKAN = [
    ("minimum_order", "Pembelian grosir dihitung per box. Minimum order standar adalah 5 box per produk. Pembelian "
                      "campuran beberapa produk diperbolehkan selama total minimal 10 box."),
    ("harga_diskon", "Harga di katalog adalah harga dasar per box, belum termasuk ongkos kirim. Diskon di luar tabel "
                     "diskon volume memerlukan persetujuan manajemen penjualan."),
    ("pengiriman", "Pengiriman dilakukan dari gudang Semarang ke seluruh Jawa Tengah dalam 1–3 hari kerja dan ke luar "
                   "Jawa Tengah melalui ekspedisi dalam 3–7 hari kerja. Ongkos kirim gratis untuk area Kota Semarang "
                   "dengan pembelian minimal 25 box."),
    ("pembayaran", "Pembayaran untuk pesanan pertama dilakukan di muka melalui transfer bank. Pelanggan tetap dapat "
                   "mengajukan tempo pembayaran 14 hari setelah disetujui staf penjualan."),
    ("retur", "Retur diterima untuk produk rusak dalam pengiriman dengan melampirkan foto dalam 3 hari setelah barang "
              "diterima."),
]
ALIAS = {
    "nama_produk": "nama", "produk": "nama", "harga": "harga_per_box", "harga_dasar": "harga_per_box",
    "harga_box": "harga_per_box", "satuan_grosir": "satuan", "no_izin_edar": "izin_edar", "nie": "izin_edar",
    "izin_bpom": "izin_edar", "klaim": "klaim_disetujui", "status_halal": "halal_status", "nomor_halal": "halal_nomor",
    "lembaga_halal": "halal_lembaga", "hasil_bko": "bko_hasil", "uji_bko": "bko_hasil", "tier_diskon": "diskon_volume",
    "larangan": "kata_terlarang", "het": "het_per_botol", "minimal_order": "moq", "min_order": "moq",
}
STATUS_HALAL = {"bersertifikat halal": "Bersertifikat Halal", "halal": "Bersertifikat Halal",
                "dalam proses": "Dalam proses", "tidak bersertifikat": "Tidak bersertifikat"}


class FileTidakValid(ValueError):
    pass


# ------------------------------------------------------------------ membaca file


def _kunci(h) -> str:
    k = re.sub(r"[^a-z0-9]+", "_", str(h or "").strip().lower()).strip("_")
    return ALIAS.get(k, k)


def _sel(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _baris(header, rows) -> list[tuple[int, dict]]:
    keys = [_kunci(h) for h in header]
    out = []
    for n, r in enumerate(rows, start=2):  # baris 1 = judul kolom (penomoran sama dengan Excel)
        vals = {keys[i]: _sel(v) for i, v in enumerate(r) if i < len(keys) and keys[i]}
        if any(vals.values()):
            out.append((n, vals))
    return out


def baca_file(nama_file: str, isi: bytes) -> tuple[list[tuple[int, dict]], list[tuple[int, dict]] | None]:
    """Kembalikan (baris produk, baris kebijakan | None bila tidak ada). None kebijakan = kebijakan lama dipertahankan."""
    if len(isi) > MAKS_UKURAN:
        raise FileTidakValid(f"File terlalu besar ({len(isi) // 1024} KB, maksimal {MAKS_UKURAN // 1024 // 1024} MB).")
    nama = (nama_file or "").lower()
    if nama.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        try:
            wb = load_workbook(io.BytesIO(isi), read_only=True, data_only=True)
        except Exception as exc:  # noqa: BLE001 — file rusak / bukan xlsx
            raise FileTidakValid(f"File Excel tidak bisa dibaca ({type(exc).__name__}).") from None
        sheets = {s.lower(): wb[s] for s in wb.sheetnames}
        ws = sheets.get("produk") or next((wb[s] for s in wb.sheetnames if s.lower() not in ("petunjuk", "kebijakan")), None)
        if ws is None:
            raise FileTidakValid("Sheet 'Produk' tidak ditemukan.")
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            raise FileTidakValid("Sheet 'Produk' kosong.")
        produk = _baris(rows[0], rows[1:])
        kebijakan = None
        if "kebijakan" in sheets:
            krows = list(sheets["kebijakan"].iter_rows(values_only=True))
            kebijakan = _baris(krows[0], krows[1:]) if krows else []
        return produk, kebijakan
    if nama.endswith(".csv"):
        try:
            teks = isi.decode("utf-8-sig")
        except UnicodeDecodeError:
            teks = isi.decode("latin-1")
        dialek = csv.Sniffer().sniff(teks[:2048], delimiters=",;\t") if teks.strip() else csv.excel
        rows = list(csv.reader(io.StringIO(teks), dialek))
        if not rows:
            raise FileTidakValid("File CSV kosong.")
        header = [_kunci(h) for h in rows[0]]
        if {"topik", "isi"} <= set(header) and "nama" not in header:
            return [], _baris(rows[0], rows[1:])  # CSV kebijakan saja
        return _baris(rows[0], rows[1:]), None
    raise FileTidakValid("Format file harus .xlsx atau .csv.")


# ------------------------------------------------------------------ validasi


def _angka(teks: str) -> float | None:
    t = re.sub(r"(?i)rp\.?|\s", "", teks)
    if not t:
        return None
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", t):  # 2.340.000 / 2.340.000,50
        t = t.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d+,\d{1,2}", t):
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _bulat(teks: str) -> int | None:
    v = _angka(teks)
    return int(v) if v is not None and float(v).is_integer() else None


def _slug(nama: str) -> str:
    return ("AUTO-" + re.sub(r"[^A-Z0-9]+", "-", nama.upper()).strip("-"))[:40]


def _daftar(teks: str) -> list[str]:
    return [x.strip() for x in re.split(r"\||\n", teks) if x.strip()]


def validasi_produk(baris: list[tuple[int, dict]], db: Session) -> tuple[list[dict], list[dict], list[dict]]:
    """Kembalikan (produk valid, error, peringatan). Error/peringatan: {baris, kolom, alasan}."""
    error, peringatan, valid = [], [], []
    if not baris:
        error.append({"baris": 1, "kolom": "-", "alasan": "Tidak ada baris produk."})
        return valid, error, peringatan
    if len(baris) > MAKS_BARIS:
        error.append({"baris": 1, "kolom": "-", "alasan": f"Terlalu banyak baris ({len(baris)}, maksimal {MAKS_BARIS})."})
        return valid, error, peringatan
    kolom_ada = set().union(*(r.keys() for _, r in baris))
    for k in ("nama", "harga_per_box"):
        if k not in kolom_ada:
            error.append({"baris": 1, "kolom": k, "alasan": "Kolom wajib tidak ada di judul kolom."})
    if error:
        return valid, error, peringatan

    lama_nama = {p.nama.strip().lower(): p.sku for p in db.scalars(select(Product))}
    sku_dipakai, nama_dipakai = {}, {}
    for n, r in baris:
        salah = []

        def e(kolom, alasan):
            salah.append({"baris": n, "kolom": kolom, "alasan": alasan})

        def w(kolom, alasan):
            peringatan.append({"baris": n, "kolom": kolom, "alasan": alasan})

        nama = re.sub(r"\s+", " ", r.get("nama", "")).strip()
        if not nama:
            e("nama", "Nama produk wajib diisi.")
        elif len(nama) > 160:
            e("nama", "Nama produk maksimal 160 karakter.")
        elif nama.lower() in nama_dipakai:
            e("nama", f"Nama sama dengan baris {nama_dipakai[nama.lower()]}.")
        sku = r.get("sku", "").strip() or lama_nama.get(nama.lower()) or (_slug(nama) if nama else "")
        if sku and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{1,39}", sku):
            e("sku", "SKU hanya boleh huruf, angka, titik, garis bawah, atau tanda minus (2–40 karakter).")
        elif sku and sku.upper() in sku_dipakai:
            e("sku", f"SKU sama dengan baris {sku_dipakai[sku.upper()]}.")

        harga = _angka(r.get("harga_per_box", ""))
        if harga is None:
            e("harga_per_box", "Harga wajib diisi dengan angka (mis. 2340000 atau 2.340.000).")
        elif harga <= 0:
            e("harga_per_box", "Harga harus lebih dari 0.")
        moq = 1
        if r.get("moq"):
            moq = _bulat(r["moq"])
            if moq is None or moq < 1:
                e("moq", "MOQ harus bilangan bulat ≥ 1.")
        stok = None
        if r.get("stok"):
            stok = _bulat(r["stok"])
            if stok is None or stok < 0:
                e("stok", "Stok harus bilangan bulat ≥ 0 (kosongkan bila belum ada data).")
        het = None
        if r.get("het_per_botol"):
            het = _angka(r["het_per_botol"])
            if het is None or het <= 0:
                e("het_per_botol", "HET harus angka lebih dari 0.")

        halal = {}
        status = r.get("halal_status", "").strip()
        if status:
            if status.lower() not in STATUS_HALAL:
                e("halal_status", "Isi dengan: Bersertifikat Halal, Dalam proses, atau Tidak bersertifikat.")
            else:
                halal["status"] = STATUS_HALAL[status.lower()]
                if halal["status"] == "Bersertifikat Halal" and not r.get("halal_nomor"):
                    w("halal_nomor", "Status halal tanpa nomor sertifikat — AI tidak bisa menyebut nomornya.")
        elif r.get("halal_nomor") or r.get("halal_lembaga"):
            e("halal_status", "Nomor/lembaga halal diisi tetapi status halal kosong.")
        if halal:
            halal.update({k: v for k, v in (("nomor_sertifikat", r.get("halal_nomor", "")),
                                            ("lembaga", r.get("halal_lembaga", ""))) if v})
        else:
            w("halal_status", "Data halal kosong — AI akan menjawab 'belum ada datanya' dan meneruskan ke staf.")

        bko = {}
        hasil = r.get("bko_hasil", "").strip()
        if hasil:
            if hasil.lower().startswith("positif"):
                e("bko_hasil", "Produk dengan hasil uji BKO positif tidak boleh dijual.")
            elif not hasil.lower().startswith("negatif"):
                e("bko_hasil", "Hasil uji BKO harus diawali 'Negatif' (atau kosongkan bila belum ada data).")
            else:
                bko = {"hasil": hasil}
                if r.get("bko_nomor_laporan"):
                    bko["nomor_laporan_uji"] = r["bko_nomor_laporan"]
        elif r.get("bko_nomor_laporan"):
            e("bko_hasil", "Nomor laporan BKO diisi tetapi hasil uji kosong.")

        tiers = []
        for bagian in _daftar(r.get("diskon_volume", "")):
            m = re.fullmatch(r"(\d+)\s*:\s*(\d+(?:[.,]\d+)?)\s*%?", bagian)
            if not m:
                e("diskon_volume", f"'{bagian}' bukan format minimal_box:persen (mis. 10:3).")
                continue
            q, d = int(m.group(1)), float(m.group(2).replace(",", "."))
            if q < 1 or not 0 < d <= 50:
                e("diskon_volume", f"'{bagian}': minimal box ≥ 1 dan persen 0–50.")
            tiers.append([q, d])
        if len({q for q, _ in tiers}) != len(tiers):
            e("diskon_volume", "Ada minimal box yang sama dua kali.")

        if not r.get("izin_edar"):
            w("izin_edar", "Izin edar kosong — AI akan menjawab 'belum ada datanya'.")
        klaim = _daftar(r.get("klaim_disetujui", ""))
        if not klaim:
            w("klaim_disetujui", "Klaim kosong — AI tidak akan menyebut manfaat produk ini.")
        dikenal = {k.nama for k in KOLOM_PRODUK}
        for k in sorted(set(r) - dikenal):
            if r[k]:
                w(k, "Kolom tidak dikenal, diabaikan.")

        if salah:
            error.extend(salah)
            continue
        nama_dipakai[nama.lower()] = n
        sku_dipakai[sku.upper()] = n
        valid.append({
            "baris": n, "sku": sku, "nama": nama, "kategori": r.get("kategori", ""), "harga_dasar": harga,
            "satuan_grosir": r.get("satuan") or "box", "kemasan": r.get("kemasan", ""), "moq": moq, "stok": stok,
            "deskripsi": r.get("deskripsi", ""), "komposisi": r.get("komposisi", ""), "klaim": klaim,
            "no_izin_edar": r.get("izin_edar", ""), "halal": halal, "bko": bko, "tiers": sorted(tiers),
            "kata_kunci": r.get("kata_kunci", ""), "larangan": _daftar(r.get("kata_terlarang", "")),
            "het_per_botol": het,
        })
    return valid, error, peringatan


def validasi_kebijakan(baris: list[tuple[int, dict]]) -> tuple[list[dict], list[dict]]:
    valid, error, dipakai = [], [], {}
    judul_ke_kunci = {v.lower(): k for k, v in TOPIK.items()}
    for n, r in baris:
        topik = _kunci(r.get("topik", ""))
        topik = topik if topik in TOPIK else judul_ke_kunci.get(r.get("topik", "").strip().lower())
        isi = re.sub(r"\s+", " ", r.get("isi", "")).strip()
        if not topik:
            error.append({"baris": n, "kolom": "topik", "alasan": "Topik harus salah satu: " + ", ".join(TOPIK) + "."})
        elif topik in dipakai:
            error.append({"baris": n, "kolom": "topik", "alasan": f"Topik sama dengan baris {dipakai[topik]}."})
        elif len(isi) < 15:
            error.append({"baris": n, "kolom": "isi", "alasan": "Isi kebijakan terlalu pendek (minimal satu kalimat)."})
        else:
            dipakai[topik] = n
            valid.append({"baris": n, "topik": topik, "judul": TOPIK[topik], "isi": isi})
    return valid, error


# ------------------------------------------------------------------ pratinjau & penerapan


def _versi_katalog(db: Session) -> int:
    return max([d.versi for d in db.scalars(select(Document).where(Document.tipe == "katalog", Document.aktif.is_(True)))],
               default=0)


def _perubahan(p: Product, r: dict) -> list[str]:
    out = []
    if p.nama != r["nama"]:
        out.append(f"nama: {p.nama} → {r['nama']}")
    if abs((p.harga_dasar or 0) - r["harga_dasar"]) > 0.5:
        out.append(f"harga: {p.harga_dasar:,.0f} → {r['harga_dasar']:,.0f}".replace(",", "."))
    if p.moq != r["moq"]:
        out.append(f"MOQ: {p.moq} → {r['moq']}")
    if p.stok != r["stok"]:
        out.append(f"stok: {'-' if p.stok is None else p.stok} → {'-' if r['stok'] is None else r['stok']}")
    if (p.no_izin_edar or "") != r["no_izin_edar"]:
        out.append("izin edar")
    if {c.teks_klaim for c in p.claims} != set(r["klaim"]):
        out.append("klaim")
    if not p.aktif:
        out.append("diaktifkan kembali")
    return out


def buat_pratinjau(db: Session, nama_file: str, isi: bytes, aktor: str) -> KatalogImpor:
    produk_baris, kebijakan_baris = baca_file(nama_file, isi)
    if not produk_baris and kebijakan_baris is not None:
        raise FileTidakValid("File hanya berisi kebijakan. Unggah template lengkap (sheet Produk + Kebijakan) agar "
                             "katalog dan kebijakan diganti bersamaan.")
    produk, error, peringatan = validasi_produk(produk_baris, db)
    kebijakan, error_k = validasi_kebijakan(kebijakan_baris or [])
    for x in error_k:
        x["sheet"] = "Kebijakan"
    lama = {p.sku: p for p in db.scalars(select(Product))}
    aktif = {p.sku for p in lama.values() if p.aktif}
    baru = [r["nama"] for r in produk if r["sku"] not in lama]
    diubah = [{"nama": r["nama"], "perubahan": ch} for r in produk if r["sku"] in lama
              and (ch := _perubahan(lama[r["sku"]], r))]
    nonaktif = sorted(lama[s].nama for s in aktif - {r["sku"] for r in produk})
    laporan = {
        "ringkasan": {"baris": len(produk_baris), "valid": len(produk), "error": len({e["baris"] for e in error}),
                      "baru": len(baru), "diubah": len(diubah), "tetap": len(produk) - len(baru) - len(diubah),
                      "dinonaktifkan": len(nonaktif),
                      "kebijakan": len(kebijakan) if kebijakan_baris is not None else None,
                      "kebijakan_error": len(error_k)},
        "error": error + error_k, "peringatan": peringatan[:300], "jumlah_peringatan": len(peringatan),
        "baru": baru, "diubah": diubah, "dinonaktifkan": nonaktif,
        "contoh": [{k: r[k] for k in ("baris", "sku", "nama", "harga_dasar", "moq", "stok", "no_izin_edar")}
                   | {"halal": r["halal"].get("status"), "bko": r["bko"].get("hasil")} for r in produk[:15]],
        "versi_katalog": _versi_katalog(db),
    }
    imp = KatalogImpor(token=secrets.token_urlsafe(16), nama_file=nama_file[:300], produk=produk,
                       kebijakan=kebijakan if kebijakan_baris is not None else [], laporan=laporan, dibuat_oleh=aktor)
    imp.laporan["ganti_kebijakan"] = kebijakan_baris is not None and bool(kebijakan) and not error_k
    db.add(imp)
    ledger.record(db, "katalog_pratinjau", aktor=aktor, objek_ref=f"katalog_impor:{imp.token}", model=None,
                  ringkasan=f"{nama_file}: {len(produk)} valid, {laporan['ringkasan']['error']} baris error",
                  outcome="pratinjau")
    db.commit()
    return imp


class ImporDitolak(ValueError):
    pass


def _kebijakan_markdown(kebijakan: list[dict]) -> str:
    urut = {k: i for i, k in enumerate(TOPIK)}
    bagian = [f"## {k['judul']}\n\n{k['isi']}" for k in sorted(kebijakan, key=lambda k: urut[k["topik"]])]
    return f"# {KEBIJAKAN_JUDUL}\n\n" + "\n\n".join(bagian) + "\n"


def terapkan(db: Session, token: str, aktor: str, *, lewati_error: bool = False) -> dict:
    """Terapkan pratinjau dalam satu transaksi. Gagal di mana pun → rollback, katalog lama tetap."""
    imp = db.scalar(select(KatalogImpor).where(KatalogImpor.token == token))
    if imp is None:
        raise ImporDitolak("Pratinjau tidak ditemukan.")
    if imp.status != "pratinjau":
        raise ImporDitolak(f"Pratinjau ini sudah {imp.status}.")
    lap = imp.laporan or {}
    if not imp.produk:
        raise ImporDitolak("Tidak ada baris produk yang valid.")
    if lap.get("error") and not lewati_error:
        raise ImporDitolak(f"Ada {lap['ringkasan']['error']} baris error. Perbaiki file, atau konfirmasi untuk "
                           "melewati baris yang salah.")
    if lap.get("versi_katalog") != _versi_katalog(db):
        raise ImporDitolak("Katalog sudah berubah sejak pratinjau dibuat. Unggah ulang file untuk pratinjau baru.")
    try:
        hasil = _terapkan(db, imp, aktor)
        db.commit()
        return hasil
    except Exception:
        db.rollback()
        raise


def _terapkan(db: Session, imp: KatalogImpor, aktor: str) -> dict:
    now = clock.now()
    versi = max([d.versi for d in db.scalars(select(Document).where(Document.tipe == "katalog"))], default=0) + 1
    lama_doc = select(Document.id).where(Document.tipe == "katalog").scalar_subquery()
    db.execute(update(Chunk).where(Chunk.document_id.in_(lama_doc)).values(aktif=False))
    db.execute(update(Document).where(Document.tipe == "katalog").values(aktif=False))
    sumber = f"{KATALOG_JUDUL} v{versi} ({imp.nama_file})"
    doc = Document(judul=KATALOG_JUDUL, tipe="katalog", file=imp.nama_file, versi=versi)
    db.add(doc)
    db.flush()

    by_sku = {p.sku: p for p in db.scalars(select(Product))}
    dipakai = set()
    n_klaim = 0
    for r in imp.produk:
        p = by_sku.get(r["sku"])
        if p is None:
            p = Product(sku=r["sku"])
            db.add(p)
        p.nama, p.kategori, p.harga_dasar = r["nama"], r["kategori"], r["harga_dasar"]
        p.satuan_grosir, p.kemasan, p.moq = r["satuan_grosir"], r["kemasan"], r["moq"]
        p.stok, p.stok_per = r["stok"], (now if r["stok"] is not None else None)
        p.deskripsi, p.komposisi, p.no_izin_edar = r["deskripsi"], r["komposisi"], r["no_izin_edar"]
        p.kata_kunci, p.larangan, p.het_per_botol = r["kata_kunci"], r["larangan"], r["het_per_botol"]
        p.data_teknis = {k: v for k, v in (("sertifikasi_halal", r["halal"]), ("status_bebas_bko", r["bko"])) if v}
        p.sumber_data, p.aktif = "impor", True
        db.flush()
        dipakai.add(p.id)
        # Klaim & tier lama diganti seluruhnya: klaim yang tidak ada lagi di file tidak boleh tetap dipakai ClaimGuard.
        db.query(ApprovedClaim).filter(ApprovedClaim.product_id == p.id).delete()
        db.query(PricingRule).filter(PricingRule.product_id == p.id).delete()
        for teks in r["klaim"]:
            db.add(ApprovedClaim(product_id=p.id, teks_klaim=teks, sumber_dokumen=sumber, embedding=llm.embed(teks)))
            n_klaim += 1
        for q, d in r["tiers"]:
            db.add(PricingRule(product_id=p.id, min_qty=int(q), diskon_maks_persen=float(d)))
        db.flush()
        db.refresh(p)
        teks = ingest.product_chunk_text(p, r["klaim"])
        db.add(Chunk(document_id=doc.id, product_id=p.id, teks=teks, embedding=llm.embed(teks), versi=versi))

    nonaktif = list(db.scalars(select(Product).where(Product.aktif.is_(True), Product.id.not_in(dipakai))))
    for p in nonaktif:
        p.aktif = False

    kebijakan_doc = None
    if imp.laporan.get("ganti_kebijakan"):
        lama_k = select(Document.id).where(Document.judul.like(f"{KEBIJAKAN_JUDUL}%")).scalar_subquery()
        db.execute(update(Chunk).where(Chunk.document_id.in_(lama_k)).values(aktif=False))
        db.execute(update(Document).where(Document.judul.like(f"{KEBIJAKAN_JUDUL}%")).values(aktif=False))
        kebijakan_doc = ingest.ingest_document(db, judul=KEBIJAKAN_JUDUL, text=_kebijakan_markdown(imp.kebijakan),
                                               tipe="teks", aktor=aktor, commit=False)

    imp.status, imp.diterapkan_pada = "diterapkan", now
    ringkas = {"versi": versi, "produk": len(imp.produk), "klaim": n_klaim, "dinonaktifkan": len(nonaktif),
               "kebijakan_versi": kebijakan_doc.versi if kebijakan_doc else None,
               "baris_dilewati": imp.laporan["ringkasan"]["error"]}
    ledger.record(db, "katalog_diimpor", aktor=aktor, objek_ref=f"document:{doc.id}", outcome="sukses",
                  ringkasan=f"{sumber}: {len(imp.produk)} produk, {n_klaim} klaim, {len(nonaktif)} dinonaktifkan"
                  + (", kebijakan diganti" if kebijakan_doc else ""),
                  sumber_ref=[{"document_id": doc.id, "versi": versi, "judul": KATALOG_JUDUL}], data=ringkas,
                  model=llm.OFFLINE_MODEL)
    return ringkas


# ------------------------------------------------------------------ template & ekspor


def _isi_sheet(ws, kolom: list[Kolom], baris: list[list]) -> None:
    from openpyxl.styles import Font, PatternFill

    ws.append([k.nama for k in kolom])
    for c, k in zip(ws[1], kolom):
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F5130" if k.wajib else "4B7A5A")
    for b in baris:
        ws.append(b)
    for i, k in enumerate(kolom, start=1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = max(14, min(48, len(k.contoh) + 4))
    ws.freeze_panes = "A2"


def _workbook(produk: list[list], kebijakan: list[list]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Petunjuk"
    ws.append(["Template impor katalog AAGE"])
    ws["A1"].font = Font(bold=True, size=14)
    for teks in [
        "1. Isi sheet Produk (satu baris = satu produk) dan sheet Kebijakan (satu baris = satu topik).",
        "2. Unggah di dashboard → Pengaturan → Katalog. Sistem menampilkan pratinjau & error per baris sebelum apa pun diganti.",
        "3. Produk yang tidak ada di file akan dinonaktifkan (tidak dihapus). Hapus sheet Kebijakan bila kebijakan tidak diubah.",
        "4. Kolom opsional boleh kosong. Data kosong TIDAK dikarang: AI menjawab 'belum ada datanya' dan meneruskan ke staf.",
        "Judul kolom hijau tua = wajib.", "",
    ]:
        ws.append([teks])
    ws.append(["Sheet", "Kolom", "Wajib", "Contoh", "Petunjuk"])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    for sheet, kolom in (("Produk", KOLOM_PRODUK), ("Kebijakan", KOLOM_KEBIJAKAN)):
        for k in kolom:
            ws.append([sheet, k.nama, "ya" if k.wajib else "", k.contoh, k.petunjuk])
    for col, w in zip("ABCDE", (12, 22, 8, 40, 100)):
        ws.column_dimensions[col].width = w
    _isi_sheet(wb.create_sheet("Produk"), KOLOM_PRODUK, produk)
    _isi_sheet(wb.create_sheet("Kebijakan"), KOLOM_KEBIJAKAN, kebijakan)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _csv(kolom: list[Kolom], baris: list[list]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([k.nama for k in kolom])
    w.writerows(baris)
    return ("﻿" + buf.getvalue()).encode("utf-8")  # BOM agar Excel membaca UTF-8 dengan benar


def _contoh_produk() -> list[list]:
    return [[k.contoh for k in KOLOM_PRODUK], [k.contoh_kosong for k in KOLOM_PRODUK]]


def template_xlsx() -> bytes:
    return _workbook(_contoh_produk(), [list(x) for x in CONTOH_KEBIJAKAN])


def template_csv() -> bytes:
    return _csv(KOLOM_PRODUK, _contoh_produk())


def template_kebijakan_csv() -> bytes:
    return _csv(KOLOM_KEBIJAKAN, [list(x) for x in CONTOH_KEBIJAKAN])


def _baris_ekspor(p: Product) -> list:
    t = p.data_teknis or {}
    halal, bko = t.get("sertifikasi_halal") or {}, t.get("status_bebas_bko") or {}
    nilai = {
        "sku": p.sku, "nama": p.nama, "kategori": p.kategori, "harga_per_box": int(p.harga_dasar)
        if float(p.harga_dasar).is_integer() else p.harga_dasar, "satuan": p.satuan_grosir, "kemasan": p.kemasan,
        "moq": p.moq, "stok": "" if p.stok is None else p.stok, "deskripsi": p.deskripsi or "",
        "komposisi": p.komposisi, "klaim_disetujui": "|".join(c.teks_klaim for c in p.claims),
        "izin_edar": p.no_izin_edar, "halal_status": halal.get("status", ""),
        "halal_nomor": halal.get("nomor_sertifikat", ""), "halal_lembaga": halal.get("lembaga", ""),
        "bko_hasil": bko.get("hasil", ""), "bko_nomor_laporan": bko.get("nomor_laporan_uji", ""),
        "diskon_volume": "|".join(f"{r.min_qty}:{r.diskon_maks_persen:g}" for r in p.pricing),
        "kata_kunci": p.kata_kunci, "kata_terlarang": "|".join(p.larangan or []),
        "het_per_botol": "" if p.het_per_botol is None else p.het_per_botol,
    }
    return [nilai[k.nama] for k in KOLOM_PRODUK]


def _kebijakan_aktif(db: Session) -> list[list]:
    """Bagian kebijakan aktif (dari potongan dokumen berjudul "Kebijakan Penjualan…")."""
    out = []
    chunks = list(db.scalars(select(Chunk).join(Document).where(
        Chunk.aktif.is_(True), Document.judul.like(f"{KEBIJAKAN_JUDUL}%")).order_by(Chunk.id)))
    for kunci, judul in TOPIK.items():
        marker = f"{judul}: "
        isi = next((ln.split(marker, 1)[1].strip() for ch in chunks for ln in ch.teks.split("\n") if marker in ln), None)
        if isi:
            out.append([kunci, isi])
    return out


def ekspor_xlsx(db: Session) -> bytes:
    """Katalog aktif dalam format template — untuk diedit mitra lalu diunggah ulang."""
    produk = [_baris_ekspor(p) for p in db.scalars(select(Product).where(Product.aktif.is_(True)).order_by(Product.id))]
    return _workbook(produk, _kebijakan_aktif(db))
