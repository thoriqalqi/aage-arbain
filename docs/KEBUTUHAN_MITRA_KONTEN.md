# Kebutuhan dari mitra untuk Content/Search Agent

Daftar ini untuk diminta ke CV Arba'in. Selama belum ada, konten tetap bisa dibuat, disetujui, diekspor, dan diterbitkan manual. Bukti terbitnya dicatat staf di Studio Konten.

Status terbaru terlihat di panel **Sambungan mitra** pada Studio Konten.

## 1. Domain resmi

| Yang diminta | Dipakai untuk |
|---|---|
| Alamat situs resmi | `SITUS_RESMI`: JSON-LD Organization, pratinjau hasil pencarian, dan menghitung tautan internal |
| Pola alamat halaman produk, misalnya `https://domain/produk/{slug}` atau `.../{sku}` | `POLA_URL_PRODUK`: alamat pada saran internal link |
| Daftar halaman produk atau sitemap | Memastikan pola alamatnya benar untuk semua produk |

Setelah diisi di `.env`, API perlu di-restart. Tidak perlu perubahan kode bila pola alamat produknya seragam.

## 2. CMS

| Yang diminta | Alasan |
|---|---|
| Nama CMS dan versinya | Penghubung dibuat sesuai CMS yang dipakai, jadi belum bisa dibuat sekarang |
| Dokumentasi atau akses API | Untuk mengirim konten yang sudah disetujui |
| Akun khusus dengan izin menulis draf saja | Staf mitra tetap yang menekan tombol terbit di CMS |
| Situs uji, bila ada | Pengujian tidak menyentuh situs sungguhan |

Yang perlu diputuskan: apakah AAGE hanya mengirim draf ke CMS, atau boleh menerbitkan langsung. Saran kami, mulai dari draf saja.

## 3. Google Search Console

| Yang diminta | Alasan |
|---|---|
| Properti domain yang sudah diverifikasi pemilik situs | Verifikasi hanya bisa dilakukan oleh pengelola domain |
| Akses baca untuk akun layanan AAGE | Membaca kueri, klik, tayangan, dan status indeks |
| Keputusan siapa pemilik akun Google-nya | Akses tetap berada di tangan mitra |

Search Console baru berisi data setelah situs diverifikasi dan terindeks. Angkanya tidak boleh diperkirakan sebelum itu.

## Yang belum dibuat

Penghubung CMS dan Search Console belum ada di kode, dan tidak ada data peringkat atau trafik di AAGE. Bukti terbit manual adalah catatan staf: alamatnya tidak dibuka atau diperiksa oleh sistem.
