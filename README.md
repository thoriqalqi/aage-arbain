# AAGE — Arba'in Autonomous Growth Engine

Agen penjualan & pemasaran AI untuk **CV Arba'in** (tantangan ARB-01, UMS Health Innovation Hackathon 2026).
AAGE menjawab pembeli B2B 24 jam lewat WhatsApp, menulis konten SEO/GEO, dan memetakan prospek apotek —
setiap kalimat diperiksa **ClaimGuard** agar tidak overclaim, dan setiap aksi tercatat di **Evidence-to-Action Ledger**.

> Data katalog, harga, klaim, dan prospek di repo ini adalah **data sintetis berlabel** (nomor izin edar berformat
> `POM TR-CONTOH-…`). Ganti dengan katalog resmi mitra lewat menu Katalog → Unggah katalog.

Dokumen acuan: [`docs/PRD.md`](docs/PRD.md) (fungsi) · [`docs/design.md`](docs/design.md) (tampilan) · [`docs/PANDUAN.md`](docs/PANDUAN.md) (panduan staf 1 halaman).

## Modul MVP (PRD §4)

| Kode | Modul | Lokasi kode |
|---|---|---|
| M1 | Knowledge Base: impor katalog CSV/XLSX, dokumen PDF/DOCX/URL, versi + jejak | `apps/api/aage/kb/` |
| M2 | AI Sales Assistant WhatsApp + web chat cadangan (FAQ, tier diskon, draf pesanan, pesan ulang, eskalasi) | `apps/api/aage/agents/`, `channels/` |
| M3 | ClaimGuard 3 tahap: aturan → pencocokan klaim disetujui → LLM-judge | `apps/api/aage/claimguard/` |
| M4 | Evidence-to-Action Ledger (append-only: listener ORM + trigger Postgres) | `apps/api/aage/ledger.py` |
| M5 | Dashboard: Ringkasan KPI, Inbox, Approval, Ledger, Playground, login admin/staf | `apps/web/app/(app)/` |
| M6 | Content & GEO Studio: artikel + FAQ + meta + JSON-LD, audit halaman sebelum/sesudah | `apps/api/aage/content/`, `apps/web/app/(app)/konten` |
| M7 | Prospect Mapper: Google Places → OpenStreetMap → sintetis, skor 0–100 transparan, ekspor CSV | `apps/api/aage/prospects/` |

### Pipeline agen (graf LangGraph terkendali)

```
pesan WA / web chat
   → router (intent + ClaimGuard atas klaim yang diminta)
   → retriever (RAG hibrida: embedding + kata kunci, pgvector di Postgres)
   → drafter (jawaban HANYA dari sumber KB, tabel harga, riwayat pesanan)
   → claimguard (Diizinkan / Perlu review / Diblokir)
   → policy ─┬─ kirim     : bersumber + lolos ClaimGuard + dalam wewenang
             ├─ eskalasi  : diskon di atas tier, keluhan, medis personal, tanpa sumber → antrean approval
             └─ tahan     : ClaimGuard review/diblokir → antrean approval + pesan tunggu
```

Tidak ada jalur yang mengirim teks ke pembeli tanpa ClaimGuard: `channels/sender.py` menolak teks yang verdict-nya bukan *Diizinkan* — termasuk balasan yang diedit staf.

## Menjalankan secara lokal (tanpa Docker)

Prasyarat: Python 3.12, Node 20.

```bash
cd apps/api
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # Linux/macOS: .venv/bin/pip
.venv/Scripts/python -m aage.seed          # reset + seed data demo (SQLite ./aage.db)
.venv/Scripts/python -m uvicorn aage.main:app --port 8000
```

```bash
cd apps/web
npm install
npm run dev                                # http://localhost:3000 (proxy /api → :8000)
```

Akun demo (dibuat oleh seed): `admin@aage.local` / `admin123` dan `staf@aage.local` / `staf123`.
Web chat pembeli (cadangan WhatsApp, tanpa login): `http://localhost:3000/chat`.

Tanpa `GEMINI_API_KEY`, AAGE berjalan dalam **mode offline deterministik** (template bersumber + aturan) —
seluruh demo tetap jalan dan biaya AI = Rp 0. Dengan API key, LLM dipakai untuk merangkai jawaban, konten,
dan LLM-judge ClaimGuard; draf LLM yang gagal ClaimGuard otomatis diganti template.

## Menjalankan di VPS (Docker Compose)

```bash
cp .env.example .env        # isi JWT_SECRET, GEMINI_API_KEY, kredensial WhatsApp, dsb.
docker compose up -d --build
docker compose exec api python -m aage.seed
```

Postgres 16 + pgvector, API FastAPI (:8000), dashboard Next.js (:3000). Langfuse opsional:
`docker compose --profile observability up -d` lalu isi `LANGFUSE_*` di `.env`.

### WhatsApp Cloud API

1. Buat app Meta → produk WhatsApp → nomor uji. Isi `WA_ACCESS_TOKEN`, `WA_PHONE_NUMBER_ID`, `WA_APP_SECRET`.
2. Ekspos API (mis. `cloudflared tunnel --url http://localhost:8000`) dan daftarkan webhook
   `https://…/api/webhook/whatsapp` dengan verify token `WA_VERIFY_TOKEN`; subscribe field `messages`.
3. Signature `X-Hub-Signature-256` diverifikasi bila `WA_APP_SECRET` diisi.

## Evaluasi (PRD §9)

```bash
cd apps/api
.venv/Scripts/python -m eval.run --offline   # hasil: eval/hasil/laporan.md + hasil.json
.venv/Scripts/python -m pytest -q tests      # 22 tes acceptance criteria
```

Hasil terakhir (mode offline, dataset di `apps/api/eval/datasets/`):

| Metrik | Hasil | Target MVP |
|---|---|---|
| Akurasi QA katalog (150 pertanyaan) | 100% | ≥90% |
| Groundedness jawaban otomatis | 100% | ≥98% |
| Recall / precision ClaimGuard (128 kalimat) | 98,8% / 100% | ≥90% / ≥80% |
| Kalimat "Diblokir" lolos sebagai "Diizinkan" | 0 | 0 |
| Ketepatan eskalasi (30 skenario) | 100% | ≥95% |
| Penawaran sesuai tier (12) / draf pesanan lengkap (9) | 100% / 100% | 100% / ≥90% |
| Latensi p95 pipeline (offline) | ±25 ms | ≤10 dtk |

**Catatan jujur:** dataset ini disusun oleh tim developer bersamaan dengan aturan ClaimGuard, sehingga angkanya
optimistis. Sesuai PRD, dataset klaim harus dilabeli ulang oleh 2 anggota tim + dosen pendamping, dan QA katalog
diganti pertanyaan nyata dari mitra, sebelum angka dipakai di slide demo day.

## Struktur repo

```
apps/api/            FastAPI + LangGraph + LiteLLM (Python 3.12)
  aage/              kode aplikasi (lihat tabel modul)
  data/              katalog & dokumen sintetis untuk seed
  eval/              dataset uji + eval/run.py
  tests/             pytest
apps/web/            Next.js 15 + Tailwind v4 + shadcn/ui (Base UI) + Motion + Three.js
  app/(app)/         Ringkasan, Inbox, Approval, Ledger, Konten, Prospek, ClaimGuard, Katalog
  app/(auth)/login   login dengan orb kaca cair 3D
  app/chat           web chat cadangan (mobile)
  components/aage/   GlassCard, VerdictBadge, ClaimHighlight, LedgerTimeline, KpiTile, ScoreBar, FunnelChart, …
docs/                PRD, design, panduan staf
infra/               init Postgres
```

## Status & batasan yang diketahui

- Diuji end-to-end di **SQLite + mode offline**. Jalur **Postgres/pgvector**, **Gemini via LiteLLM**, dan
  **WhatsApp Cloud API** sudah ditulis tetapi belum diuji dengan kredensial/instans nyata di mesin pengembang.
- Overpass (OSM) publik sering penuh; Prospect Mapper mencoba 3 mirror dengan backoff lalu jatuh ke data sintetis
  berlabel. Untuk demo, isi `GOOGLE_PLACES_API_KEY` atau jalankan pemetaan lebih awal agar hasilnya ter-cache.
- Skema dibuat dengan `create_all` (belum Alembic). Pengingat repeat order dipicu manual (P1 terjadwal belum).
- Biaya AI di KPI = Rp 0 pada mode offline; angka biaya nyata muncul setelah API key diisi.
