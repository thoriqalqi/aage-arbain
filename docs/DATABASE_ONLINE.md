# Database online (Supabase)

Panduan memakai database online AAGE: menyambungkan komputer baru, mengubah skema, serta mencadangkan dan memulihkan data.

Semua perintah dijalankan dari `apps/api` di PowerShell, memakai `.venv/Scripts/python`.

## Ringkasan

| Hal | Keadaan |
|---|---|
| Layanan | Supabase, paket gratis, region `ap-southeast-1` (Singapura), Postgres 17 |
| Alamat dan sandi | Hanya di `apps/api/.env`, tidak pernah di git |
| Perubahan skema | Lewat Alembic (`migrations/`) |
| Backup | Tidak otomatis di paket gratis. Dibuat sendiri dengan `scripts/cadangan_db.py` |
| Mode lokal | Tanpa `DATABASE_URL`, API memakai SQLite `aage.db` |

## Menyambungkan komputer baru

Ikuti `docs/PINDAH_KOMPUTER.md` untuk memasang kode dan dependensi. Lalu:

1. Salin `apps/api/.env` dari komputer lama lewat jalur aman, bukan chat atau email. Atau ambil alamatnya di Supabase: buka proyek, klik **Connect**.
2. Pilih salah satu bentuk `DATABASE_URL` di bawah.
3. Lewati `python -m aage.seed`. Perintah itu menghapus isi database, dan ditolak pada database online.
4. Pastikan versi skema cocok, lalu jalankan API:

```powershell
.venv/Scripts/python -m alembic current
.venv/Scripts/python -m uvicorn aage.main:app --port 8000
```

`alembic current` harus menampilkan `(head)`. Kalau versinya berbeda, API berhenti saat start dengan pesan yang menjelaskan langkahnya.

### Bentuk DATABASE_URL

```
# Session pooler: bisa di semua jaringan (IPv4). Disarankan untuk komputer baru.
DATABASE_URL=postgresql+psycopg://postgres.PROJECT_REF:SANDI@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require

# Koneksi langsung: hanya jaringan yang punya IPv6.
DATABASE_URL=postgresql+psycopg://postgres:SANDI@db.PROJECT_REF.supabase.co:5432/postgres?sslmode=require
```

- Usernya berbeda: pooler memakai `postgres.PROJECT_REF`, koneksi langsung memakai `postgres`.
- Karakter khusus di sandi harus ditulis dalam bentuk URL (`@` menjadi `%40`, `#` menjadi `%23`). Sandi berisi huruf dan angka saja lebih aman.
- Sandi tidak bisa dilihat lagi di Supabase. Kalau hilang, reset di **Database → Settings**, lalu perbarui `.env` di semua komputer.
- Beberapa kali gagal login bisa membuat IP diblokir sementara, jadi jangan diulang terus.

### Jangan jalankan API di dua komputer sekaligus

Webhook Telegram hanya mengarah ke satu alamat. Keduanya juga menulis ke database dan Ledger yang sama.

## Mengubah skema

Satu-satunya jalur perubahan skema di database online adalah Alembic. API tidak pernah mengubah skema online saat start. Jangan mengubah tabel lewat SQL Editor Supabase.

1. Ubah `aage/models.py`.
2. Buat migrasi terhadap Postgres **lokal** yang sudah ada di versi terbaru, lalu periksa isi filenya:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://postgres@127.0.0.1:55432/aage_alembic"
.venv/Scripts/python -m alembic revision --autogenerate -m "tambah kolom x"
```

3. Periksa di Postgres lokal. `alembic check` harus berakhir dengan `No new upgrade operations detected`:

```powershell
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m alembic check
Remove-Item Env:DATABASE_URL
```

4. Jalankan semua tes dan dataset di SQLite dan Postgres lokal (lihat bagian Tes).
5. Setelah di-commit, di database online: hentikan API, cadangkan, baru jalankan migrasi.

```powershell
.venv/Scripts/python scripts/cadangan_db.py buat
.venv/Scripts/python -m alembic upgrade head
```

6. Jalankan API lagi. Komputer lain harus `git pull` lebih dulu, karena API menolak start kalau versi kodenya berbeda.

Catatan:
- Tabel baru wajib diberi RLS di file migrasinya: `op.execute('ALTER TABLE "nama" ENABLE ROW LEVEL SECURITY')`. Alembic tidak mendeteksi RLS atau trigger, jadi keduanya ditulis sendiri.
- Tabel `ledger_events`, `ledger_hashes`, dan `compliance_audits` bersifat append-only. Migrasi tidak boleh mengubah isinya.
- Migrasi awal `0001` tidak bisa dibatalkan, karena membatalkannya berarti menghapus semua data. Untuk kembali ke keadaan sebelumnya, pulihkan dari cadangan.
- Migrasi awal di Supabase sudah ditandai dengan `alembic stamp 0001`. Riwayat `skema_awal_aage` di dashboard Supabase berasal dari pembuatan pertama dan tidak dipakai lagi.

### Migrasi 0003: verifikasi knowledge

Migrasi ini membuat tabel `verifikasi_fakta` dengan RLS aktif dan memberi status `simulasi` pada data yang bersumber simulasi. Tidak ada baris yang menjadi `terverifikasi`, dan tabel lain tidak diubah. Mode data berada di tabel `settings`, dengan bawaan produksi bila belum diisi.

Sesudah migrasi, mode produksi membuat bot tidak mengutip harga, izin, dan klaim dari katalog simulasi. Admin perlu memilih mode demo selama masih memakai data simulasi.

`alembic downgrade 0002` menghapus tabel itu dan pilihan mode, termasuk hasil verifikasi yang sudah dicatat admin. Jejaknya tetap ada di Ledger.

## Backup dan restore

**Paket gratis Supabase tidak punya backup otomatis.** Kalau proyek terhapus, datanya hilang permanen. Skrip di bawah tidak butuh `pg_dump`, dan sudah diuji dengan data asli.

### Membuat cadangan

```powershell
.venv/Scripts/python scripts/cadangan_db.py buat
```

Hasilnya `cadangan/db-<waktu>.zip`. Buat seminggu sekali dan sebelum setiap migrasi. Jadwal otomatis belum dibuat, jadi perintah ini harus dijalankan sendiri.

Yang perlu dijaga:
- File ini memuat data pelanggan dan hash sandi, dan **tidak terenkripsi**. Simpan salinannya di luar komputer ini, di tempat yang aman dan terbatas aksesnya.
- Folder `cadangan/` sudah masuk `.gitignore`. Jangan pindahkan file ini ke folder lain di dalam repo.
- Cadangan hanya berisi data. Skema dibuat oleh Alembic, dan `.env` harus disimpan terpisah.

Untuk memastikan file masih utuh, tanpa menyentuh database:

```powershell
.venv/Scripts/python scripts/cadangan_db.py periksa cadangan/db-<waktu>.zip
```

### Memulihkan

Pemulihan hanya mau mengisi database yang **kosong**, dan tidak pernah menimpa data. Jadi untuk database yang rusak, pulihkan ke proyek Supabase baru:

1. Hentikan API.
2. Buat proyek Supabase baru, lalu ganti `DATABASE_URL` di `.env` ke proyek baru itu.
3. Buat skemanya, dan pulihkan. Ganti `<host>` dengan host di `DATABASE_URL`:

```powershell
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python scripts/cadangan_db.py pulihkan cadangan/db-<waktu>.zip --konfirmasi-host <host>
```

4. Pastikan pesan akhirnya `Pemulihan selesai. Rantai hash utuh`. Kalau gagal di tengah, semua isi dibatalkan dan database tetap kosong.
5. Jalankan API, lalu pasang ulang webhook Telegram kalau alamat tunnel berubah.

Sandi login pengguna tetap sama seperti saat cadangan dibuat.

**Yang sudah diuji** (4 Nov 2026): data asli Supabase (3.838 baris, cadangan 310 KB, 3 detik) dipulihkan ke Postgres 16 lokal. Isi semua tabel sama persis, rantai hash utuh, dan login serta chat berjalan di atasnya.

**Yang belum diuji:** memulihkan ke proyek Supabase baru. Langkahnya sama, tetapi belum pernah dijalankan di sana.

Selain skrip ini, Supabase menganjurkan pengguna paket gratis mengekspor data dengan `supabase db dump`. Perintah itu butuh Docker dan tidak dipakai di sini.

## Batas paket gratis

Dari dokumentasi resmi Supabase, dicek 4 Nov 2026. Angka ini bisa berubah; lihat [halaman harga](https://supabase.com/pricing).

| Batas | Nilai | Akibat | Sumber |
|---|---|---|---|
| Ukuran database | 500 MB per proyek | Database menjadi **hanya-baca**: API tidak bisa menyimpan pesan | [Database size](https://supabase.com/docs/guides/platform/database-size) |
| Disk | 1 GB | | [Database size](https://supabase.com/docs/guides/platform/database-size) |
| Tidak aktif | Aktivitas rendah selama 7 hari | Proyek **dijeda**. Dikirim email peringatan. Bisa dilanjutkan sampai 90 hari | [Project pausing](https://supabase.com/docs/guides/platform/free-project-pausing) |
| Backup otomatis | Tidak ada | Wajib buat cadangan sendiri | [Backups](https://supabase.com/docs/guides/platform/backups) |
| Egress | 5 GB | | [Billing](https://supabase.com/docs/guides/platform/billing-on-supabase) |
| Jumlah proyek | 2 proyek gratis | | [Billing](https://supabase.com/docs/guides/platform/billing-on-supabase) |
| Koneksi database | 60 | Koneksi baru ditolak | [Compute](https://supabase.com/docs/guides/platform/compute-and-disk) |
| Klien pooler | 200 | Koneksi baru ditolak | [Compute](https://supabase.com/docs/guides/platform/compute-and-disk) |

Keadaan saat ini (4 Nov 2026): database 15 MB. API memakai paling banyak 15 koneksi.

Pantau ukurannya di **Reports → Database**. Proyek baru sudah terpakai sekitar 40–60 MB menurut dokumentasi Supabase, dan pemakaian di dashboard bisa berbeda dari angka di atas. Kalau proyek dijeda, API gagal tersambung sampai proyek dilanjutkan dengan **Resume project** di dashboard.

## Keamanan

- **Rahasia:** `.env`, `aage.db`, dan `cadangan/` tidak masuk git. Kalau sandi database terlanjur tersebar, reset di Supabase dan perbarui `.env`.
- **SSL:** wajib `?sslmode=require`. Skrip pindah dan restore menolak database online tanpa itu. Isi `sslmode=require` mengenkripsi koneksi, tetapi tidak memeriksa sertifikat server; untuk itu pakai `verify-full` dengan sertifikat dari Supabase.
- **Hak akses:** API tersambung sebagai `postgres`, pemilik tabel, jadi tidak terkena RLS. Siapa pun yang memegang `DATABASE_URL` bisa membaca dan mengubah semua data.
- **Akses publik:** kunci publishable Supabase memang boleh terlihat publik. Semua tabel memakai RLS tanpa policy, jadi kunci itu membaca 0 baris dan tidak bisa menulis. Security advisor akan menampilkan info `rls_enabled_no_policy`; itu disengaja. Jangan menambahkan policy tanpa alasan yang jelas.
- **Kunci `service_role` / `sb_secret_`:** melewati RLS. AAGE tidak memakainya, jadi jangan dimasukkan ke kode atau `.env`.
- **`JWT_SECRET`:** wajib diisi dengan nilai acak di `.env`. Tanpa itu API memakai kunci bawaan yang tertulis di kode, sehingga sesi login bisa dipalsukan. Nilainya sama di semua komputer yang memakai database ini.
- **Data pelanggan di pihak ketiga:** nomor, nama, dan percakapan pembeli sekarang tersimpan di server Supabase di Singapura. Pastikan ini sesuai dengan kebijakan privasi CV Arba'in dan kewajiban pelindungan data pribadi yang berlaku. Dokumen ini bukan nasihat hukum.

## Tes

Tes dan eval tidak pernah memakai database online. `conftest.py` dan `run_eval.py` berhenti kalau alamatnya online, dan tes memakai database sementara.

```powershell
# SQLite
.venv/Scripts/python -m pytest -q

# Postgres lokal. Isi kedua database ini dihapus oleh tes.
$env:AAGE_TES_DATABASE_URL = "postgresql+psycopg://postgres@127.0.0.1:55432/aage_tes"
$env:AAGE_TES_PINDAH_URL = "postgresql+psycopg://postgres@127.0.0.1:55432/aage_pindah"
.venv/Scripts/python -m pytest -q
Remove-Item Env:AAGE_TES_DATABASE_URL, Env:AAGE_TES_PINDAH_URL

# Dataset di Postgres lokal, satu database per dataset
$env:AAGE_EVAL_DATABASE_URL = "postgresql+psycopg://postgres@127.0.0.1:55432/aage_realistis"
.venv/Scripts/python -m eval.run_eval --mode template --ulang --dataset realistis --keluaran hasil_kerja
Remove-Item Env:AAGE_EVAL_DATABASE_URL
```

Postgres lokal harus punya pgvector. Versi lokal yang dipakai untuk uji adalah 16, sedangkan Supabase 17.

## Memindahkan data dari aage.db

Pemindahan pertama sudah selesai pada 4 Nov 2026. Skrip ini hanya perlu lagi untuk mengisi database baru dari file `aage.db`. Isi skema dulu dengan `alembic upgrade head`, lalu:

```powershell
.venv/Scripts/python scripts/pindah_ke_postgres.py --sumber aage.db --cek
.venv/Scripts/python scripts/pindah_ke_postgres.py --sumber aage.db --konfirmasi-host <host>
```

Skrip membuat cadangan `aage.db` lebih dulu, mengganti sandi pengguna, dan menulis sandi baru ke folder `cadangan/`. Kalau ada baris yang berbeda dengan target, skrip berhenti tanpa menimpa apa pun.
