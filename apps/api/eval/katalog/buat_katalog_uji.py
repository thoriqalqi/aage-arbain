"""Bangun katalog uji B (berbeda total dari katalog simulasi) + dataset_katalog_uji.csv.

Tujuan: membuktikan agent menjawab dari katalog yang sedang aktif, bukan hafalan produk lama:
nama, harga, MOQ, tier diskon, gudang, ongkir, metode bayar, dan retur semuanya berbeda; beberapa kolom sengaja
kosong (halal, izin edar, BKO, stok) untuk menguji bahwa data kosong tidak dikarang.

    python -m eval.katalog.buat_katalog_uji
"""

import csv
from pathlib import Path

from aage.kb.katalog_impor import KOLOM_PRODUK, _workbook

HERE = Path(__file__).resolve().parent
H = "Bersertifikat Halal"
# sku, nama, kategori, harga, kemasan, moq, stok, klaim, izin, halal_status, halal_nomor, bko, diskon, kata_kunci
PRODUK = [
    ("KB-01", "Madu Kelulut Hutan 300 g", "Obat Bahan Alam", 1850000, "Botol 300 g; box isi 24 botol", 3, 40,
     "Membantu memelihara daya tahan tubuh", "POM TR 223300001", H, "ID-HALAL-KB-0001", "Negatif", "12:2|30:4",
     "kelulut trigona madu hutan"),
    ("KB-02", "Kapsul Jintan Hitam Premium 90", "Obat Bahan Alam", 2150000, "Botol 90 kapsul; box isi 40 botol", 3, 25,
     "Membantu memelihara kesehatan", "POM TR 223300002", H, "ID-HALAL-KB-0002", "Negatif", "12:2|30:4",
     "jintan hitam habbatussauda"),
    ("KB-03", "Sirup Temulawak Anak 120 ml", "Obat Bahan Alam", 1320000, "Botol 120 ml; box isi 48 botol", 3, None,
     "Membantu memelihara nafsu makan anak", "POM TR 223300003", "", "", "Negatif", "12:2", "temulawak anak sirup"),
    ("KB-04", "Teh Rosella Seduh 25 kantong", "Obat Bahan Alam", 780000, "Kotak 25 kantong; box isi 40 kotak", 3, 60,
     "Membantu menyegarkan badan", "", "Dalam proses", "", "", "12:2", "rosella teh"),
    ("KB-05", "Kapsul Ekstrak Meniran 60", "Suplemen Kesehatan", 1540000, "Botol 60 kapsul; box isi 40 botol", 3, 30,
     "Membantu memelihara daya tahan tubuh", "POM TR 223300005", H, "ID-HALAL-KB-0005", "Negatif", "12:2|30:4",
     "meniran"),
    ("KB-06", "Minyak Zaitun Murni 250 ml", "Suplemen Kesehatan", 2400000, "Botol 250 ml; box isi 24 botol", 3, 15,
     "Membantu memelihara kesehatan kulit", "POM SD 223300006", H, "ID-HALAL-KB-0006", "", "12:2|30:4",
     "zaitun olive oil"),
    ("KB-07", "Serbuk Jahe Emprit 15 sachet", "Obat Bahan Alam", 690000, "Kotak 15 sachet; box isi 50 kotak", 3, 80,
     "Membantu menghangatkan badan", "POM TR 223300007", H, "ID-HALAL-KB-0007", "", "12:2|30:5", "jahe emprit wedang"),
    ("KB-08", "Madu Klanceng Super 500 g", "Obat Bahan Alam", 3100000, "Botol 500 g; box isi 20 botol", 3, 12,
     "Membantu memelihara daya tahan tubuh", "POM TR 223300008", H, "ID-HALAL-KB-0008", "Negatif", "12:2|30:5",
     "klanceng madu"),
]
KEBIJAKAN = [
    ("minimum_order", "Pembelian grosir dihitung per box. Minimum order standar adalah 3 box per produk. Pembelian "
                      "campuran beberapa produk diperbolehkan selama total minimal 8 box."),
    ("harga_diskon", "Harga di katalog adalah harga dasar per box, belum termasuk ongkos kirim. Diskon di luar tabel "
                     "diskon volume memerlukan persetujuan pemilik usaha."),
    ("pengiriman", "Pengiriman dilakukan dari gudang Yogyakarta ke DIY dan Jawa Tengah dalam 1–2 hari kerja dan ke luar "
                   "Jawa Tengah melalui ekspedisi dalam 2–5 hari kerja. Ongkos kirim gratis untuk area Kota Yogyakarta "
                   "dengan pembelian minimal 20 box."),
    ("pembayaran", "Pembayaran dilakukan di muka melalui transfer bank atau QRIS. Pelanggan tetap dapat mengajukan tempo "
                   "pembayaran 30 hari setelah disetujui pemilik usaha."),
    ("retur", "Retur diterima untuk produk rusak atau bocor dalam pengiriman dengan melampirkan video unboxing dalam 2 "
              "hari setelah barang diterima."),
]


def _baris(p) -> list:
    sku, nama, kat, harga, kemasan, moq, stok, klaim, izin, hs, hn, bko, diskon, kunci = p
    nilai = {"sku": sku, "nama": nama, "kategori": kat, "harga_per_box": harga, "satuan": "box", "kemasan": kemasan,
             "moq": moq, "stok": "" if stok is None else stok, "klaim_disetujui": klaim, "izin_edar": izin,
             "halal_status": hs, "halal_nomor": hn, "halal_lembaga": "BPJPH" if hn else "", "bko_hasil": bko,
             "bko_nomor_laporan": f"LHU-{sku}" if bko else "", "diskon_volume": diskon, "kata_kunci": kunci}
    return [nilai.get(k.nama, "") for k in KOLOM_PRODUK]


# id, pesan, kategori, harapan, riwayat
DATASET = [
    ("KU01", "brp hrg madu kelulut perbox?", "harga", "FAKTA: 1.850.000"),
    ("KU02", "kapsul jintan hitam 90 harganya brp", "harga", "FAKTA: 2.150.000"),
    ("KU03", "madu klanceng ready gk?", "produk", "FAKTA: Madu Klanceng Super"),
    ("KU04", "teh rosella 1 box isinya brp?", "spesifikasi", "FAKTA: 40 kotak"),
    ("KU05", "brp hrg madu stamina perbox kak?", "produk_lama", r"CEK: harus=belum ada di katalog ;; terlarang=2\.340\.000|Madu Stamina Plus"),
    ("KU06", "habatusauda 120 hrg nya brp ya", "produk_lama", r"CEK: terlarang=2\.880\.000|Kapsul Habbatussauda 120"),
    ("KU07", "propolis tetes ada?", "produk_lama", "CEK: harus=belum ada di katalog ;; terlarang=Propolis Tetes 30 ml"),
    ("KU08", "sirup temulawak anak halal ga?", "data_kosong", "CEK: eskalasi ;; harus=belum ada ;; terlarang=Bersertifikat Halal"),
    ("KU09", "madu kelulut halal?", "halal", "FAKTA: ID-HALAL-KB-0001"),
    ("KU10", "teh rosella izin edarnya apa?", "data_kosong", "CEK: eskalasi ;; harus=belum ada datanya ;; terlarang=POM"),
    ("KU11", "produk kalian halal semua?", "data_kosong", "CEK: harus=6 dari 8 ;; harus=belum ada datanya ;; terlarang=8 dari 8"),
    ("KU12", "ini ada narkoba nya ga?", "data_kosong", "CEK: harus=5 dari 8 ;; harus=belum ada data ;; terlarang=8 dari 8"),
    ("KU13", "kirim ke magelang brp lama?", "kebijakan", "FAKTA: 1–2 hari"),
    ("KU14", "ongkir ke jogja gratis?", "kebijakan", "FAKTA: 20 box"),
    ("KU15", "bisa bayar pakai qris?", "kebijakan", "CEK: bukan_eskalasi ;; harus=QRIS"),
    ("KU16", "bisa COD?", "kebijakan", "CEK: eskalasi ;; harus=transfer"),
    ("KU17", "bisa bayar tempo?", "kebijakan", "FAKTA: 30 hari"),
    ("KU18", "barang rusak bisa retur?", "kebijakan", "FAKTA: video unboxing && 2 hari"),
    ("KU19", "minimal order brp box?", "kebijakan", "FAKTA: 3 box"),
    ("KU20", "kasih diskon dong", "nego", "CEK: harus=mulai 12 box ;; terlarang=mulai 10 box"),
    ("KU21", "5 box madu kelulut + 2 box kapsul jintan hitam brp totalnya?", "multi", "FAKTA: minimal total 8 box"),
    ("KU22", "produk apa aja yang anda miliki??", "daftar", "CEK: semua_produk ;; terlarang=Madu Stamina|Propolis"),
    ("KU23", "madu", "ambigu", "CEK: harus=Madu Kelulut ;; harus=Madu Klanceng ;; harus=\\? ;; terlarang=Madu Stamina"),
    ("KU24", "ada produk untuk daya tahan tubuh?", "kebutuhan", "FAKTA: Madu Kelulut"),
    ("KU25", "apakah arbain penipuan ?", "tuduhan", "CEK: harus=7 dari 8 ;; harus=staf"),
    ("KU26", "stok madu kelulut masih ada?", "stok", "CEK: harus=40 box ;; harus=staf"),
    ("KU27", "stok sirup temulawak anak ada?", "data_kosong", "CEK: harus=stok belum ada ;; terlarang=Stok tercatat"),
    ("KU28", "arbain dimana alamatnya?", "perusahaan", "CEK: harus=gudang Yogyakarta ;; terlarang=Semarang"),
]


def main() -> None:
    (HERE / "katalog_uji_b.xlsx").write_bytes(_workbook([_baris(p) for p in PRODUK], [list(k) for k in KEBIJAKAN]))
    with (HERE.parent / "dataset_katalog_uji.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "pesan", "kategori", "jawaban_diharapkan", "harus_diblokir", "riwayat", "tipe"])
        for rid, pesan, kat, harap in DATASET:
            w.writerow([rid, pesan, f"KU/{kat}", harap, "tidak", "", ""])
    print(f"katalog_uji_b.xlsx: {len(PRODUK)} produk, {len(KEBIJAKAN)} kebijakan · dataset_katalog_uji.csv: {len(DATASET)}")


if __name__ == "__main__":
    main()
