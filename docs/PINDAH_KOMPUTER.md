# Pindah komputer

Panduan menyiapkan AAGE di komputer baru dari repositori private `thoriqalqi/aage-arbain`.

## Versi dan dependensi

| Komponen | Versi yang dipakai | File dependensi |
|---|---|---|
| Python | 3.12.2 | `apps/api/requirements.txt` |
| Node.js | 20.12.2 (npm 10.5.0) | `apps/web/package.json` + `apps/web/package-lock.json` |

## Yang tidak ada di repositori

Bagian ini tidak ikut git dan harus disiapkan sendiri:

| Yang tidak ikut | Cara menyiapkan di komputer baru |
|---|---|
| `apps/api/.env` | Salin manual lewat jalur aman (jangan lewat chat atau email), atau buat dari `.env.example` di root repo dan isi ulang. API membaca `.env` dari folder `apps/api`. |
| `apps/api/aage.db` | Buat ulang dengan `python -m aage.seed` (langkah 2). Data percakapan uji di komputer lama tidak ikut. |
| `apps/api/.venv` | Buat ulang (langkah 2). |
| `apps/web/node_modules`, `apps/web/.next` | Buat ulang dengan `npm ci` / `npm run dev`. |

Key Gemini dan TokenHarbor pernah dibagikan di chat, jadi sebaiknya diganti baru sebelum dipakai lagi.

## Langkah

Perintah di bawah untuk PowerShell di Windows. Di Linux/macOS, ganti `.venv/Scripts/` dengan `.venv/bin/`.

### 1. Ambil kode

```powershell
git clone https://github.com/thoriqalqi/aage-arbain.git aage
cd aage
git switch wip-pindah-komputer
```

### 2. Siapkan API

```powershell
cd apps/api
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
# letakkan file .env di apps/api/.env
.venv/Scripts/python -m aage.seed
```

`aage.seed` menghapus isi database lalu mengisi data demo. Jalankan hanya saat menyiapkan awal.

### 3. Jalankan API

Dari folder `apps/api`:

```powershell
.venv/Scripts/python -m uvicorn aage.main:app --port 8000
```

### 4. Jalankan web

Dari folder `apps/web`, di terminal lain:

```powershell
npm ci
npm run dev
```

Web terbuka di http://localhost:3000 dan meneruskan `/api` ke port 8000. Untuk API di alamat lain, set variabel `API_URL`.

Akun demo dari seed: `admin@aage.local` / `admin123` dan `staf@aage.local` / `staf123`.

### 5. Telegram (bila dipakai)

URL Cloudflare Tunnel berubah setiap dijalankan, jadi webhook harus diset ulang. Langkahnya ada di `docs/UJI_TELEGRAM.md`.

## Memeriksa hasil pemindahan

Dari folder `apps/api`:

```powershell
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m eval.run_percakapan
```

## Status pekerjaan di cabang ini

Cabang `wip-pindah-komputer` adalah simpanan kerja, **belum disetujui untuk digabung ke `main`**. Isinya:

- Impor katalog Excel/CSV dan AI sales fase 1–3.
- Fase 4: gaya bahasa LLM dengan kunci fakta dan memori percakapan.
- `eval/dataset_konteks.csv`: dataset konteks, belum ada kode perbaikannya.

Uji LLM fase 4b di `apps/api/eval/hasil_fase4b/` mungkin belum lengkap saat commit dibuat. Untuk melanjutkan baris yang belum selesai:

```powershell
.venv/Scripts/python -m eval.run_regresi_llm --keluaran hasil_fase4b --emosi 8
```

Database eval ada di folder temp komputer lama dan tidak ikut, jadi statistik kunci fakta di `laporan.txt` hanya menghitung baris yang dijalankan di komputer baru. Hasil baris tetap lengkap.
