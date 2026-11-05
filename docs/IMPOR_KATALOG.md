# Impor Katalog Mitra (Excel/CSV)

Dashboard → **Pengaturan → Katalog → Produk** (khusus admin).

## Alur
1. **Unduh template**: *Template Excel* (sheet Petunjuk, Produk, Kebijakan) atau *Template CSV produk* /
   *Template CSV kebijakan*. Untuk mengubah katalog yang sudah ada, pakai *Ekspor katalog aktif* lalu edit.
2. **Unggah** file `.xlsx` atau `.csv`. Sistem memvalidasi setiap baris dan menampilkan **pratinjau**:
   jumlah baris valid/error, produk baru/diubah/dinonaktifkan, tabel error (baris, kolom, alasan), dan peringatan.
   Katalog **belum berubah** pada tahap ini.
3. **Terapkan** atau **Batal**. Bila ada baris error, centang *Lewati N baris error* untuk mengimpor baris yang valid
   saja; atau perbaiki file dan unggah ulang.

## Aturan penting
- Satu unggahan **mengganti katalog**: produk yang tidak ada di file dinonaktifkan (tidak dihapus — riwayat pesanan dan
  Ledger tetap utuh). Klaim dan tier diskon produk yang diimpor diganti seluruhnya.
- Sheet **Kebijakan** (topik: `minimum_order`, `harga_diskon`, `pengiriman`, `pembayaran`, `retur`, `pesan_ulang`,
  `penyimpanan`) mengganti kebijakan kirim/bayar/retur. Hapus sheet itu bila kebijakan tidak diubah. CSV produk saja
  tidak mengubah kebijakan.
- Penerapan berjalan dalam **satu transaksi**: gagal di tengah → katalog lama tetap utuh.
- Pratinjau lama ditolak bila katalog sudah berubah sejak pratinjau dibuat (unggah ulang).
- **Data kosong tidak dikarang.** Halal, BKO, izin edar, stok, atau komposisi yang kosong dijawab AI
  "belum ada datanya"; untuk halal & izin edar pertanyaan langsung diteruskan ke staf.
- Kolom `aturan_pakai` opsional: AI hanya mengutip dosis dari kolom ini; bila kosong, pembeli diarahkan ke label dan dokter/apoteker.
- Hasil uji BKO **Positif** ditolak. Status halal harus *Bersertifikat Halal*, *Dalam proses*, atau *Tidak bersertifikat*.
- Angka di kebijakan dipakai AI apa adanya: MOQ campuran ("total minimal N box"), tier diskon awal, gudang, kota gratis
  ongkir, metode bayar (COD/QRIS hanya dianggap berlaku bila disebut di kebijakan).

## Status verifikasi

Kolom `status_verifikasi`, `sumber_bukti`, dan `berlaku_sampai` ada di sheet Produk dan Kebijakan.

- Isi yang diterima: `simulasi`, `belum_diverifikasi`, `kedaluwarsa`. Baris kosong dianggap `belum_diverifikasi` dan muncul sebagai peringatan.
- Impor tidak bisa menandai `terverifikasi`. Nilai itu dianggap `belum_diverifikasi` dan muncul sebagai peringatan.
- Nomor izin, halal, atau BKO berpola simulasi (`SIM…`, `-SIM-`) membuat baris itu berstatus `simulasi`.
- Admin memverifikasi per fakta di Pengaturan → Katalog → Verifikasi, dengan sumber bukti. Nama diambil dari akun yang login, dan perubahannya masuk Ledger.
- Impor ulang dengan nilai sama mempertahankan verifikasi lama. Nilai yang berubah membatalkannya.
- Kebijakan diverifikasi per versi dokumen. Satu baris tanpa status membuat seluruh dokumen `belum_diverifikasi`. Versi baru dengan isi sama membawa verifikasi versi lama.

Perilaku bot ada di `apps/api/aage/kb/verifikasi.py`. Fakta terverifikasi dan masih berlaku dijawab biasa. Data simulasi hanya dijawab di mode demo, dengan label. Fakta lain tidak dikutip dan bot menawarkan staf. Mode diatur admin di Pengaturan → Kebijakan, dengan bawaan produksi.

## API
| Endpoint | Fungsi |
|---|---|
| `GET /api/katalog/template.xlsx` · `template.csv` · `template-kebijakan.csv` | Template |
| `GET /api/katalog/ekspor.xlsx` (admin) | Katalog aktif dalam format template |
| `POST /api/katalog/impor` (admin, file) | Validasi + pratinjau → `token` |
| `POST /api/katalog/impor/{token}/terapkan` `{lewati_error}` | Terapkan (satu transaksi) |
| `POST /api/katalog/impor/{token}/batal` | Batalkan pratinjau |

## Uji
- `eval/run_eval.py --katalog FILE` mengganti katalog lewat jalur impor yang sama sebelum eval berjalan.
- `eval/katalog/katalog_simulasi.xlsx`: katalog simulasi yang diekspor lalu diimpor ulang — semua dataset harus tetap 100%.
- `eval/katalog/katalog_uji_b.xlsx` + `dataset_katalog_uji.csv`: katalog kecil yang berbeda total (nama, harga, MOQ,
  tier, gudang, kebijakan; beberapa data sengaja kosong) untuk membuktikan agent tidak menghafal katalog lama.
