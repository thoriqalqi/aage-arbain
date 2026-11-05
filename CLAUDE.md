# AAGE (Arba'in Autonomous Growth Engine)

Asisten AI sales untuk CV Arba'in: produk herbal/suplemen, penjualan grosir B2B ke apotek dan toko.

- `apps/api`: backend FastAPI, LangGraph. Tanpa `DATABASE_URL` memakai SQLite (`aage.db`); data sungguhan ada di Supabase Postgres, lihat `docs/DATABASE_ONLINE.md`.
- `apps/web`: dashboard Next.js, meneruskan `/api` ke port 8000.
- LLM: lewat TokenHarbor (DeepSeek), memakai jalur `openai_compat`.
- Katalog di repo masih simulasi, bukan data resmi mitra.

Acuan lain: `docs/PRD.md`, `docs/WORKFLOW.md`, `docs/UJI_AI_SALES.md`, `docs/UJI_TELEGRAM.md`, `apps/api/eval/laporan_perbaikan.md`.
Di cabang WIP juga ada `docs/PINDAH_KOMPUTER.md` dan `docs/IMPOR_KATALOG.md`.

## Aturan yang tidak boleh dilanggar

- Tidak ada commit sebelum pemilik proyek menyetujui. Laporkan tiap tahap.
- Semua dataset dan tes tetap 100% di mode template dan LLM. Jangan mengubah ekspektasi dataset lama tanpa melaporkannya secara eksplisit.
- Jalur sensitif (klaim kesehatan, medis, darurat, komplain, manipulasi) diputuskan aturan keras dan menang atas dorongan closing.
- Dilarang mengarang harga, diskon, stok, ongkir, dosis, sertifikat, cabang, atau riwayat pembeli.
- Fakta hanya dikutip bila lolos `aage/kb/verifikasi.py`. Hanya admin yang bisa menandai terverifikasi, dan impor tidak bisa melakukannya. Tes dan eval berjalan di mode demo karena katalognya simulasi; bawaan aplikasi adalah produksi.
- `.env`, `aage.db`, token, dan kunci API tidak boleh ter-commit atau ditampilkan. Periksa nama kunci saja, jangan nilainya.

## Arsitektur

- Netral kanal: satu pintu masuk `handle_inbound(channel, external_user_id, ...)`, satu pintu keluar `channels/sender.py`.
- `sender.py` menolak teks yang verdict ClaimGuard-nya bukan Diizinkan, termasuk balasan yang diedit staf.
- Adapter Telegram aktif. Adapter WhatsApp/WATI ditunda; logika jendela 24 jam dan template hanya ada di adapter WA.
- Pipeline agen ada di `apps/api/aage/agents/` (router, penjaga, drafter, graph). ClaimGuard ada di `aage/claimguard/`.
- Urutan pemahaman: aturan keras di `router.py` lebih dulu, lalu profil dan data sales di `pemahaman.py`, lalu langkah sales di `tindakan.py`. `pemahaman.py` hanya boleh mengalihkan intent jualan biasa, tidak boleh jalur sensitif.
- Ledger bersifat append-only dengan rantai hash (`aage/ledger.py`, `aage/ledger_chain.py`).

## Cabang

- `main`: belum memuat impor katalog, fase 1-4 sales, atau `dataset_konteks.csv`.
- `origin/wip-pindah-komputer`: memuat semuanya, berstatus simpanan kerja, belum disetujui untuk digabung ke `main`.
- Periksa `git status` dan `git branch -a` di awal sesi. Opsi dan dataset di bawah yang bertanda WIP tidak ada di `main`.

## Menjalankan

Perintah dijalankan dari folder yang disebut, memakai PowerShell di Windows.

```powershell
# apps/api: API
.venv/Scripts/python -m uvicorn aage.main:app --port 8000

# apps/web: dashboard di http://localhost:3000
npm ci
npm run dev
npm run lint
npm run build
```

`python -m aage.seed` menghapus isi database lalu mengisi data demo. Jangan dijalankan pada database yang masih dipakai. Pada database online perintah ini ditolak.

### Database online

Skema online hanya diubah lewat Alembic (`migrations/`), dan API menolak start kalau versinya berbeda. Tes dan eval tidak boleh menyentuh database online. Paket gratis tidak punya backup otomatis: buat dengan `scripts/cadangan_db.py buat`. Langkah lengkap ada di `docs/DATABASE_ONLINE.md`.

### Konfigurasi LLM

API membaca `.env` dari folder kerja, yaitu `apps/api`. Mode LLM aktif hanya bila `LLM_API_KEY` dan `LLM_BASE_URL` terisi, atau `GEMINI_API_KEY` terisi. Nama model diatur oleh `LLM_MODEL` dan `LLM_JUDGE_MODEL`. Kode tidak membaca `DEEPSEEK_API_KEY`. Tanpa konfigurasi itu, API berjalan dalam mode template tanpa pesan error.

### Telegram

Lihat `docs/UJI_TELEGRAM.md`. Alamat tunnel `trycloudflare` berganti setiap tunnel dibuka ulang, dan webhook harus dipasang ulang setelahnya:

```powershell
# apps/api
.venv/Scripts/python scripts/telegram_bot.py set-webhook https://<alamat-tunnel>
.venv/Scripts/python scripts/telegram_bot.py info
```

Restart API setelah mengubah `.env`.

## Tes dan eval

Tes memakai database sementara dan mengosongkan kunci LLM.

```powershell
# apps/api
.venv/Scripts/python -m pytest -q
```

Eval memakai database sementara, stub pengiriman, dan memblokir domain kanal. Mode LLM memakai kuota sungguhan.

Tanpa `--keluaran`, eval menimpa `eval/hasil_*.jsonl` yang ter-track git. Di cabang WIP selalu pakai `--keluaran <folder>`. `main` belum punya opsi ini, jadi jalankan eval `main` pada salinan terpisah atau pulihkan file hasil sesudahnya.

```powershell
# apps/api, mode template. <d> = realistis | holdout | adversarial | lapangan | emosi
.venv/Scripts/python -m eval.run_eval --mode template --ulang --dataset <d> --keluaran hasil_kerja

# WIP: katalog pengganti (28 baris) dan percakapan multi-giliran (16 skenario, 34 giliran)
.venv/Scripts/python -m eval.run_eval --mode template --ulang --dataset katalog_uji --katalog eval/katalog/katalog_uji_b.xlsx --keluaran hasil_kerja
.venv/Scripts/python -m eval.run_percakapan --keluaran hasil_kerja

# WIP: regresi LLM. Bisa dilanjutkan; hanya baris ERROR yang diulang. Laporan ada di <folder>/laporan.txt
.venv/Scripts/python -m eval.run_regresi_llm --keluaran <folder> --emosi 8
```

Folder `--keluaran` tidak di-ignore git, jadi jangan ikut di-commit kecuali diminta.

Dataset konteks (WIP, 89 giliran) dijalankan dengan perintah di bawah. Baris `bagian=holdout` dilaporkan terpisah; baris `hanya_llm=ya` dilewati di mode template.

```powershell
# apps/api
.venv/Scripts/python -m eval.run_konteks --keluaran hasil_kerja
.venv/Scripts/python -m eval.run_konteks --dataset luar_katalog --keluaran hasil_kerja
```

## Catatan kejujuran angka

Dataset ditulis tim pengembang, dan aturannya disetel memakai dataset yang sama, jadi 100% bukan uji buta. Saat menyebut angka, sertakan batasan ini. Lihat bagian Keterbatasan di `apps/api/eval/laporan_perbaikan.md`.
