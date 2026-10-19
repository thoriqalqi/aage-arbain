# PRD MVP AAGE — Arba'in Autonomous Growth Engine

Oct 19, 2026 · @ngorz · Tim Djuaraumm · ARB-01 CV Arba'in

## 1. Ringkasan produk

MVP AAGE adalah agen penjualan dan pemasaran AI untuk CV Arba'in yang menjawab calon pembeli B2B 24 jam lewat WhatsApp, menulis konten SEO/GEO, dan memetakan prospek apotek. Setiap jawaban dan konten diperiksa ClaimGuard agar tidak overclaim, dan setiap tindakan tercatat di Ledger. MVP harus bisa didemokan end-to-end pada demo day UMS Health Innovation Hackathon (awal–pertengahan November 2026).

**Tujuan MVP**

1. Memperagakan ketiga pilar ARB-01 dalam satu alur yang berjalan: AI Sales Assistant, konten SEO & AI-search, dan pemetaan prospek.
2. Membuktikan keunggulan inti: AI yang **tidak bisa overclaim** soal kesehatan, dengan alasan yang bisa diaudit.
3. Menyajikan angka uji nyata (akurasi, recall ClaimGuard, latensi, biaya) untuk aspek Fungsionalitas (25%) dan Kesesuaian (20%) di rubrik demo day.

**Definisi sukses (lulus MVP)**

- Juri bisa chat langsung ke nomor WhatsApp demo dan mendapat jawaban katalog bersumber dalam ≤10 detik.
- 0 jawaban berklaim terapi penyakit yang lolos terkirim pada seluruh skenario uji.
- Akurasi jawaban katalog ≥90% pada set uji MVP (target proposal ≥95% untuk versi April 2027).
- Recall ClaimGuard ≥90% pada dataset klaim berlabel.
- Dashboard menampilkan antrean approval, Ledger, KPI, daftar prospek, dan studio konten dari data yang sama.

## 2. Konteks

Demo day bernilai 80% dari Nilai Akhir, dan fungsionalitas adalah aspek terbesarnya. Karena itu MVP diprioritaskan pada fungsi yang benar-benar bisa diperagakan, bukan kelengkapan modul.

**Masalah mitra ([ARB-01](https://ihub.ums.ac.id/hackathon/tantangan/arb-01-agen-ai-untuk-otomatisasi-pemasaran-dan-penjualan-b2b))**: CV Arba'in menjual produk kesehatan/herbal secara B2B ke apotek, toko obat, dan minimarket dengan tim marketing dan sales yang kecil. Pemasaran daring belum optimal karena algoritma berubah dan pencarian bergeser ke AI search (GEO). Konten wajib patuh aturan klaim dan biaya API harus terjangkau.

**Pemetaan permintaan mitra ke fitur MVP**

| Permintaan ARB-01 | Fitur MVP | Modul |
| --- | --- | --- |
| Konten SEO & AI-search ready | Content & GEO Studio: draf artikel/deskripsi + FAQ + schema JSON-LD, audit halaman | M6 |
| Layanan pertanyaan katalog | Jawaban RAG bersumber via WhatsApp | M2 |
| Negosiasi awal | Penawaran harga/diskon dalam batas tabel yang disetujui manajemen | M2 |
| Repeat order | Pencatatan draf pesanan + pengingat repeat order ke kontak opt-in | M2 |
| Pemetaan prospek otomatis | Prospect Mapper: data apotek per wilayah, skor, draf pesan pembuka | M7 |
| Dashboard performa & konversi leads | Dashboard KPI + funnel lead | M5 |
| Tidak overclaim | ClaimGuard di setiap jawaban dan konten | M3 |
| Biaya API efisien | AI gateway dengan budget cap + log biaya | Infrastruktur |
| Panduan penggunaan | Panduan singkat 1 halaman + video demo | Dokumen |

**Bobot penilaian demo day** ([Pedoman Peserta](https://ums.id/PEDOMANUMSHIHACK26)): Fungsionalitas 25%, Kesesuaian masalah–solusi 20%, Inovasi 15%, Dampak & skalabilitas 15%, Komponen lokal & KI 10%, Kesiapan hilirisasi 10%, Presentasi 5%. Nilai Akhir = 20% nilai proposal + 80% nilai demo, dengan ambang minimal 2,80.

## 3. Persona dan user stories

Empat persona dilayani MVP; pembeli B2B memakai WhatsApp, tiga lainnya memakai dashboard web.

| Persona | Kanal | Kebutuhan utama |
| --- | --- | --- |
| Pembeli B2B (pemilik/pengelola apotek, toko obat, minimarket) | WhatsApp | Info produk, izin edar, harga grosir, MOQ, pesan ulang dengan cepat kapan saja |
| Staf sales B2B | Dashboard | Hanya menangani chat yang perlu manusia; daftar prospek siap dihubungi |
| Staf marketing | Dashboard | Konten SEO/GEO yang aman klaim tanpa menulis dari nol |
| Manajemen | Dashboard | KPI, biaya AI, dan jejak keputusan yang bisa diaudit |

**User stories MVP**

1. Sebagai pembeli, saya bertanya "ada produk untuk daya tahan tubuh?" dan mendapat jawaban dari katalog beserta nomor izin edar, tanpa klaim menyembuhkan.
2. Sebagai pembeli, saya meminta harga untuk 50 karton dan langsung mendapat penawaran sesuai tier diskon; jika saya minta di bawah batas, chat diteruskan ke sales.
3. Sebagai pembeli, saya mengetik "pesan ulang seperti bulan lalu" dan AI menyusun draf pesanan untuk dikonfirmasi staf.
4. Sebagai pembeli, saya bertanya "bisa sembuhkan diabetes?" dan AI menolak klaim itu dengan sopan, memberi info yang disetujui, lalu menawarkan bicara dengan staf.
5. Sebagai staf sales, saya melihat antrean eskalasi dengan ringkasan chat dan draf balasan, lalu menyetujui, mengedit, atau menolak dengan satu klik.
6. Sebagai staf sales, saya memilih wilayah (misalnya Kota Semarang) dan mendapat daftar apotek berperingkat beserta alasan skor dan draf pesan pembuka.
7. Sebagai staf marketing, saya memilih produk dan topik, lalu mendapat draf artikel, FAQ, dan schema JSON-LD yang sudah lolos ClaimGuard.
8. Sebagai staf marketing, saya menempel URL atau teks lama dan melihat kalimat berisiko ditandai merah/kuning beserta alasannya.
9. Sebagai manajemen, saya membuka satu jawaban di Ledger dan melihat sumber dokumen, aturan yang terpicu, model, biaya, dan siapa yang menyetujui.

## 4. Lingkup MVP

MVP berisi tujuh modul P0 yang semuanya muncul di demo; fitur di luar itu masuk roadmap dan hanya ditampilkan di slide.

| Kode | Modul | Prioritas | Masuk demo |
| --- | --- | --- | --- |
| M1 | Knowledge Base (katalog, izin edar, klaim disetujui, tabel harga) | P0 | Ya |
| M2 | AI Sales Assistant WhatsApp (FAQ, negosiasi awal, draf pesanan, repeat order, eskalasi) | P0 | Ya |
| M3 | ClaimGuard | P0 | Ya |
| M4 | Evidence-to-Action Ledger | P0 | Ya |
| M5 | Dashboard (Inbox & Approval, Ledger, KPI, Playground) | P0 | Ya |
| M6 | Content & GEO Studio | P0 | Ya |
| M7 | Prospect Mapper | P0 | Ya |
| — | Pengingat repeat order terjadwal otomatis | P1 | Dipicu manual saat demo |
| — | Integrasi Google Search Console | P1 | Tidak |
| — | Publikasi langsung ke CMS situs mitra | P1 | Tidak |
| — | Causal Growth Optimizer, integrasi CRM, multi-tenant SaaS | P2 | Tidak |

**Sengaja di luar lingkup MVP**

- Pesan massal ke kontak yang belum opt-in. Prospect Mapper hanya menyiapkan draf; staf yang mengirim.
- Pembayaran dan pemrosesan pesanan final. AI hanya membuat draf pesanan yang dikonfirmasi staf.
- Nasihat medis. Pertanyaan medis personal selalu dialihkan ke tenaga kesehatan atau staf.
- Data penjualan riil mitra. Selama data belum diberikan, dipakai katalog publik dan data sintetis yang diberi label jelas.

## 5. Kebutuhan fungsional

Setiap modul punya acceptance criteria (AC) yang diuji sebelum demo; modul dianggap selesai hanya jika semua AC-nya lulus.

### M1 — Knowledge Base

- Admin mengunggah katalog (CSV/XLSX) dan dokumen (PDF/DOCX/URL): nama produk, komposisi, kemasan, nomor izin edar, klaim yang disetujui, harga dasar, MOQ.
- Sistem memecah dokumen menjadi potongan, membuat embedding, dan menyimpan versi serta waktu unggah.
- Tabel `approved_claims` per produk diisi manual atau dari dokumen, lalu diverifikasi staf.
- Tabel `pricing_rules`: tier volume → diskon maksimal yang boleh ditawarkan AI.

AC: unggah 1 katalog CSV berisi ≥20 produk selesai <1 menit; setiap potongan menyimpan sumber + versi; mengganti versi katalog tidak menghapus jejak versi lama di Ledger.

### M2 — AI Sales Assistant WhatsApp

- Kanal utama: WhatsApp Cloud API (nomor uji Meta). Kanal cadangan: web chat bergaya WhatsApp di dashboard, memakai pipeline yang sama.
- Intent yang ditangani: tanya produk, izin edar, harga & MOQ, negosiasi, pesan/pesan ulang, klaim kesehatan, keluhan, lainnya.
- Negosiasi awal: AI boleh menawarkan diskon sampai batas tier di `pricing_rules`. Permintaan di luar batas → eskalasi.
- Pesanan: AI mengumpulkan produk, jumlah, nama toko, alamat → membuat `order_draft` berstatus "menunggu konfirmasi staf". "Pesan ulang" memakai pesanan terakhir kontak tersebut.
- Eskalasi: ringkasan chat + intent + draf balasan masuk antrean; pembeli diberi tahu bahwa staf akan menghubungi.
- Jawaban tanpa sumber dari Knowledge Base tidak pernah dikirim otomatis.

AC: jawaban katalog terkirim ≤10 detik (p95); 100% permintaan diskon di atas batas tier tereskalasi; 100% jawaban otomatis menyertakan rujukan sumber di Ledger; percakapan berbahasa Indonesia informal dipahami pada set uji.

### M3 — ClaimGuard

- Tahap 1, aturan deterministik: kamus pola (menyembuhkan, mengobati, mencegah penyakit X, dijamin, 100%, tanpa efek samping, nama penyakit, statistik tanpa sumber, perbandingan merek).
- Tahap 2, pencocokan klaim: setiap klaim di teks dicocokkan ke `approved_claims` produk terkait (kemiripan embedding + aturan).
- Tahap 3, LLM-judge: output JSON terstruktur `{claims[], verdict, reasons[]}` untuk kasus ambigu. LLM tidak boleh menurunkan keputusan "diblokir" dari tahap 1.
- Keputusan: Diizinkan / Perlu review / Diblokir, beserta aturan yang terpicu dan saran kalimat pengganti yang aman.
- Dipakai oleh M2 (sebelum kirim), M6 (sebelum terbit), dan Playground.

AC: recall ≥90% dan precision ≥80% pada dataset klaim berlabel; 0 kalimat berlabel "diblokir" lolos sebagai "diizinkan"; waktu pemeriksaan ≤3 detik per jawaban.

### M4 — Evidence-to-Action Ledger

- Mencatat event: pesan masuk, retrieval, draf jawaban, keputusan ClaimGuard, approval, pesan keluar, draf pesanan, konten dibuat/terbit, prospek dibuat.
- Setiap event menyimpan: sumber + versi, alasan, aturan terpicu, model, token, biaya (Rp), aktor (AI/staf), outcome.
- Event hanya bisa ditambah, tidak bisa diubah (append-only).

AC: dari satu pesan keluar, staf bisa menelusuri seluruh rantai event sampai dokumen sumber dalam ≤3 klik; total biaya per percakapan tampil.

### M5 — Dashboard

- Inbox & Approval: daftar chat, status (otomatis/eskalasi/ditahan), tombol setujui, edit, tolak; balasan yang disetujui langsung terkirim ke WhatsApp.
- Ledger viewer dengan filter per percakapan, produk, keputusan ClaimGuard.
- KPI: jumlah chat, % dijawab otomatis vs eskalasi, klaim diblokir/ditahan, waktu respons rata-rata, biaya AI per percakapan, funnel lead (prospek → dihubungi → merespons → minta penawaran → draf pesanan).
- ClaimGuard Playground: tempel teks/URL → sorotan merah/kuning/hijau + alasan.
- Login dengan dua peran: admin dan staf.

AC: approve di dashboard terkirim ke WhatsApp ≤5 detik; semua angka KPI dihitung dari tabel Ledger, bukan hard-code.

### M6 — Content & GEO Studio

- Input: produk + topik/kata kunci + target pembaca (apotek, konsumen).
- Output: draf artikel atau deskripsi produk bersumber, blok FAQ (format tanya-jawab yang mudah dikutip AI search), meta title/description, dan schema JSON-LD (`Product`, `FAQPage`, `Organization`).
- Audit halaman: masukkan URL situs mitra → cek meta, heading, schema, statistik tanpa sumber, dan klaim berisiko → laporan sebelum/sesudah.
- Semua draf melewati ClaimGuard dan hanya bisa diekspor setelah disetujui staf.

AC: satu draf artikel + FAQ + JSON-LD selesai ≤60 detik; JSON-LD lolos validasi sintaks; 0 draf berstatus "diblokir" bisa diekspor.

### M7 — Prospect Mapper

- Input: wilayah (kota/kecamatan) + jenis toko (apotek, toko obat, minimarket).
- Sumber data: Google Places API (Text Search), dengan OpenStreetMap (Overpass) sebagai cadangan gratis. Hasil di-cache.
- Skor prospek 0–100 yang dapat dijelaskan, berdasarkan aturan transparan: jenis toko, jarak ke gudang/distributor, rating & jumlah ulasan, kelengkapan kontak, sudah/belum pelanggan.
- Output: tabel prospek berperingkat + alasan skor + draf pesan pembuka (lolos ClaimGuard) + status (baru, dihubungi, merespons, menolak).

AC: satu kota menghasilkan ≥30 prospek dengan skor dan alasan dalam ≤30 detik; ekspor CSV; perubahan status tercatat di Ledger dan masuk funnel KPI.

## 6. Arsitektur dan tech stack

AAGE dibangun sebagai satu modular monolith Python dengan pipeline agen yang terkendali, bukan agen otonom bebas. Setiap "agen" adalah satu node berperan jelas di graf LangGraph, sehingga alurnya bisa diuji, di-debug, dan dijelaskan ke juri.

&#91;embedded content: pipeline agen AAGE · 5 langkah, 3 keputusan ClaimGuard\]

Permintaan harga di luar tier, keluhan, dan pertanyaan medis personal ditandai Router dan selalu berakhir di antrean approval. Konten dari Content & GEO Studio dan draf pesan dari Prospect Mapper melewati ClaimGuard dan Ledger yang sama.

**Pemetaan agen di presentasi ke kode**

| Nama di proposal | Implementasi MVP |
| --- | --- |
| Growth Orchestrator | Graf LangGraph + Policy (aturan otorisasi: apa boleh otomatis, apa wajib approval) |
| Sales Agent | Router intent + Drafter jawaban + logika tier diskon dan draf pesanan |
| Knowledge/Evidence | Retriever RAG atas `chunks` pgvector |
| Compliance Agent | ClaimGuard |
| Content/Search Agent | Content & GEO Studio |
| Opportunity Agent | Prospect Mapper |
| Evaluation Agent | Skrip evaluasi + KPI dari Ledger |

**Tech stack**

| Lapisan | Pilihan | Alasan |
| --- | --- | --- |
| Backend & AI core | Python 3.12, FastAPI, LangGraph | Ekosistem AI lengkap; graf eksplisit dengan titik human-in-the-loop |
| LLM | Gemini Flash (default), model lebih kuat untuk LLM-judge; via LiteLLM | Murah, bahasa Indonesia baik; budget cap, fallback, dan log biaya bawaan |
| Embedding | Model embedding multilingual (Gemini embedding atau bge-m3) | Mendukung bahasa Indonesia |
| Database | PostgreSQL 16 + pgvector | Data, vektor, dan Ledger di satu tempat |
| Antrian/job | Background task FastAPI (MVP); Redis + worker bila perlu | Cukup untuk volume demo |
| WhatsApp | WhatsApp Cloud API (nomor uji Meta); cloudflared untuk webhook saat dev | Gratis untuk uji, demo di HP asli |
| Frontend | Next.js + Tailwind + shadcn/ui | Cepat untuk tabel, antrean, dan grafik |
| Prospek | Google Places API (Text Search); OpenStreetMap Overpass sebagai cadangan | Data apotek per wilayah |
| Observability | Langfuse (self-host) | Trace tiap langkah, membantu evaluasi |
| Deploy | Docker Compose di satu VPS | Sederhana, murah, satu perintah |

**Tidak dipakai di produk:** Hermes Agent (dirancang sebagai asisten pribadi berizin luas, tidak cocok untuk sistem terkendali yang bisa diaudit) dan 9router (gateway untuk tool coding; risiko akun dan perilaku fallback). Keduanya boleh dipakai tim sebagai alat bantu ngoding.

## 7. Model data dan API

Semua data ada di satu database Postgres dengan pgvector; `ledger_events` menjadi sumber tunggal untuk KPI dan audit.

**Tabel inti**

| Tabel | Kolom utama | Dipakai modul |
| --- | --- | --- |
| `users` | id, nama, email, role (admin/staf) | M5 |
| `products` | id, nama, komposisi, kemasan, no\_izin\_edar, harga\_dasar, moq, aktif | M1, M2, M6 |
| `approved_claims` | id, product\_id, teks\_klaim, sumber\_dokumen, diverifikasi\_oleh | M3 |
| `pricing_rules` | id, product\_id, min\_qty, diskon\_maks\_persen | M2 |
| `documents` | id, judul, tipe, url/file, versi, diunggah\_pada | M1 |
| `chunks` | id, document\_id, product\_id, teks, embedding vector, versi | M1, M2 |
| `contacts` | id, wa\_number, nama\_toko, tipe\_toko, opt\_in, prospect\_id | M2, M7 |
| `conversations` | id, contact\_id, kanal, status, intent\_terakhir | M2, M5 |
| `messages` | id, conversation\_id, arah, teks, status\_kirim, wa\_message\_id | M2 |
| `approvals` | id, objek\_tipe, objek\_id, draf, status, ditinjau\_oleh, catatan | M5 |
| `order_drafts` | id, contact\_id, item (jsonb), total, status | M2 |
| `content_drafts` | id, product\_id, tipe, isi, faq, json\_ld, claim\_verdict, status | M6 |
| `prospects` | id, nama, alamat, lat, lng, tipe, rating, skor, alasan\_skor, status, sumber | M7 |
| `ledger_events` | id, waktu, tipe\_event, objek\_ref, sumber\_ref (jsonb), alasan, verdict, aturan\_terpicu, model, token\_in, token\_out, biaya\_rp, aktor, outcome | M4, M5 |

**Endpoint API (FastAPI, prefix `/api`)**

| Method | Path | Fungsi |
| --- | --- | --- |
| GET, POST | `/webhook/whatsapp` | Verifikasi webhook Meta dan terima pesan masuk |
| POST | `/chat/simulate` | Kanal web chat cadangan, memakai pipeline yang sama |
| POST | `/kb/products/import` | Unggah katalog CSV/XLSX |
| POST | `/kb/documents` | Unggah dokumen atau URL, lalu ingest |
| POST | `/claimguard/check` | Periksa teks, kembalikan verdict + sorotan |
| GET | `/approvals?status=pending` | Antrean approval |
| POST | `/approvals/{id}/decide` | Setujui, edit, atau tolak; kirim jika disetujui |
| GET | `/conversations/{id}` | Detail chat + event Ledger terkait |
| GET | `/ledger?filter=…` | Daftar event Ledger |
| GET | `/kpi?from=&to=` | Angka KPI dan funnel |
| POST | `/content/generate` | Buat draf artikel + FAQ + JSON-LD |
| POST | `/content/audit` | Audit URL atau teks |
| POST | `/prospects/search` | Cari dan skor prospek per wilayah |
| PATCH | `/prospects/{id}` | Ubah status prospek |
| POST | `/reminders/repeat-order` | Kirim pengingat repeat order (template, kontak opt-in) |

## 8. Kebutuhan non-fungsional

MVP harus murah, cepat, dan aman dipakai UMKM; angka biaya final ditetapkan setelah uji beban di sprint 3.

| Aspek | Kebutuhan MVP |
| --- | --- |
| Latensi | Jawaban WhatsApp p95 ≤10 detik; ClaimGuard ≤3 detik; dashboard memuat halaman ≤2 detik |
| Biaya AI | Budget cap harian dan bulanan di LiteLLM; model murah (Flash) sebagai default, model lebih kuat hanya untuk LLM-judge kasus ambigu; cache jawaban FAQ yang sering ditanya; biaya per percakapan tampil di KPI |
| Kemudahan | Staf non-teknis bisa memakai dashboard tanpa pelatihan lebih dari 15 menit; bahasa antarmuka Indonesia; tombol aksi utama maksimal 1 klik |
| Keandalan demo | Kanal web chat cadangan bila WhatsApp bermasalah; seed data demo bisa di-reset dengan satu perintah; fallback model bila provider utama gagal |
| Keamanan | Login wajib untuk dashboard; peran admin/staf; secret di environment variable, tidak di repo; verifikasi signature webhook Meta |
| Privasi (UU PDP) | Hanya kontak inbound/opt-in yang dikirimi pesan; data kontak minimal; nomor dimasking di tampilan Ledger untuk peran staf; data disimpan di server dalam negeri bila memungkinkan |
| Kepatuhan klaim | Tidak ada jalur yang mengirim teks ke pembeli atau mengekspor konten tanpa lewat ClaimGuard |
| Keterlacakan | Setiap aksi AI dan staf tercatat di `ledger_events`, append-only |
| Portabilitas model | Model diganti cukup lewat konfigurasi LiteLLM tanpa mengubah kode modul |

## 9. Rencana evaluasi

Empat dataset uji disusun di sprint 1–2 dan dijalankan otomatis lewat skrip `eval/run.py`; hasilnya menjadi slide "Hasil uji" di demo day.

| Dataset | Ukuran | Isi | Metrik dan target MVP |
| --- | --- | --- | --- |
| QA katalog | 150 pertanyaan | Pertanyaan pembeli (formal dan informal) + jawaban benar + produk sumber | Akurasi ≥90%; groundedness (jawaban otomatis menyertakan sumber valid) ≥98% |
| Klaim berlabel | 120 kalimat | Kalimat dari situs/konten herbal, dilabeli Diizinkan / Perlu review / Diblokir oleh 2 anggota tim + dosen | Recall ≥90%; precision ≥80%; 0 kalimat "Diblokir" lolos |
| Skenario eskalasi | 30 skenario | Harga di luar tier, keluhan, pertanyaan medis personal, nego agresif | Ketepatan eskalasi ≥95% |
| Skenario negosiasi & pesanan | 20 skenario | Permintaan diskon dalam/luar batas, pesan ulang, data pesanan tidak lengkap | Penawaran sesuai tier 100%; draf pesanan lengkap ≥90% |

**Metrik operasional** yang diukur saat uji: latensi p95, biaya rata-rata per percakapan (Rp), dan persentase chat yang selesai otomatis.

**Uji pengguna singkat** (bila mitra bersedia sebelum demo day): 3–5 staf atau mahasiswa sebagai proxy mencoba dashboard, lalu mengisi System Usability Scale (target ≥68).

**Pembanding** untuk slide demo: 20 pertanyaan klaim yang sama dijawab chatbot LLM polos tanpa ClaimGuard vs AAGE, lalu dihitung berapa jawaban yang overclaim.

## 10. Skenario demo day

Demo berdurasi sekitar 7 menit dan memakai WhatsApp asli di HP juri; durasi final menyesuaikan petunjuk panitia.

1. **Masalah (30 detik):** angka audit situs mitra (berapa halaman berisi klaim berisiko atau statistik tanpa sumber) + chat di luar jam kerja yang tidak terbalas.
2. **Tanya katalog (1 menit):** juri memindai QR dan chat "ada produk untuk stamina?". Jawaban muncul dengan nama produk, izin edar, dan klaim yang disetujui.
3. **Uji overclaim (1 menit):** juri mengetik "bisa sembuhkan hipertensi?". AI menolak dengan sopan. Di dashboard terlihat ClaimGuard: Diblokir, aturan yang terpicu, dan saran kalimat aman.
4. **Negosiasi dan pesanan (1 menit):** "harga 50 karton berapa?" → penawaran sesuai tier. "Bisa diskon 30%?" → eskalasi. Staf menyetujui draf di dashboard, balasan masuk ke HP juri.
5. **Ledger (45 detik):** klik jawaban tadi → sumber dokumen, versi katalog, model, biaya Rp, siapa yang menyetujui.
6. **Konten GEO (1 menit):** pilih produk → draf artikel + FAQ + JSON-LD dalam satu menit, lalu tampilan audit sebelum/sesudah halaman situs mitra.
7. **Prospek (45 detik):** pilih "Kota Semarang, apotek" → tabel prospek berperingkat dengan alasan skor dan draf pesan pembuka.
8. **Bukti dan penutup (1 menit):** slide hasil uji (akurasi, recall ClaimGuard, latensi, biaya per percakapan), perbandingan dengan LLM polos, batasan yang belum selesai, dan rencana pilot bersama mitra sampai April 2027.

**Cadangan:** bila sinyal atau WhatsApp bermasalah, langkah 2–4 dijalankan di web chat dashboard; video rekaman demo lengkap disiapkan sebagai cadangan terakhir.

## 11. Timeline dan pembagian tugas

Target tim: MVP siap demo 9 November 2026, dengan code freeze 7 November; tanggal demo day resmi masih menunggu panitia.

&#91;embedded content: timeline MVP · 3 sprint menuju demo day\]

Sprint 1 membangun jalur pesan sampai jawaban bersumber, sprint 2 menambah ClaimGuard dan modul lain, sprint 3 hanya untuk evaluasi, perbaikan, dan latihan demo.

| Anggota | Sprint 1 (21–27 Okt) | Sprint 2 (28 Okt–3 Nov) | Sprint 3 (4–9 Nov) |
| --- | --- | --- | --- |
| Muchamad Faris Chakim (AI & Agent) | Ingest + RAG, Router intent, Drafter, setup LiteLLM | ClaimGuard 3 tahap, negosiasi tier, generator konten GEO | Tuning prompt dan aturan dari hasil eval, budget cap |
| Muhammad Fiqri Zulfikar (Backend & Data) | Skema DB + migrasi, webhook WhatsApp, endpoint chat | Ledger, approvals, order\_drafts, Prospect Mapper (Places + OSM) | Deploy VPS, Langfuse, seed/reset data demo, hardening |
| A Thoriq Alqi Ighafur (Frontend) | Layout dashboard, login, Inbox, web chat cadangan | Halaman Approval, Ledger viewer, Playground ClaimGuard, Studio konten | KPI + funnel, tabel prospek, polish UI, panduan 1 halaman |
| Aqib Ainun Najib (Product & Business) | Kumpulkan katalog publik mitra, susun approved\_claims dan pricing\_rules contoh | Dataset uji: 150 QA, 120 klaim berlabel, 50 skenario; audit situs mitra | Jalankan eval, slide demo dan hasil uji, latihan pitch, video cadangan |
| Basirudin Ansor (Dosen pendamping) | Review rancangan aturan ClaimGuard | Validasi label dataset klaim | Review slide dan jawaban juri |

**Ritme kerja:** stand-up 15 menit tiap malam, satu task board dengan satu penanggung jawab per kartu, dan demo internal di akhir setiap sprint. Kartu dianggap selesai hanya jika acceptance criteria di bagian 5 lulus.

## 12. Risiko, asumsi, dan pertanyaan terbuka

Risiko terbesar MVP adalah lingkup yang terlalu lebar untuk waktu sekitar tiga minggu, jadi setiap modul punya versi minimum yang tetap bisa didemokan.

| Risiko | Dampak | Mitigasi |
| --- | --- | --- |
| Lingkup tidak selesai sebelum demo day | Fungsionalitas (25%) turun | Urutan bangun: M1→M2→M3→M4→M5 dulu; M6 dan M7 versi minimum; code freeze H-3 |
| Data katalog resmi mitra terlambat | Jawaban kurang akurat | Pakai katalog publik situs mitra + data sintetis berlabel; ingest ulang saat data datang |
| Nomor uji WhatsApp gagal saat demo | Demo macet | Web chat cadangan + video rekaman |
| Halusinasi jawaban | Klaim salah ke pembeli | RAG wajib sumber; tanpa sumber → eskalasi; eval sebelum tiap rilis |
| ClaimGuard melewatkan klaim | Kepercayaan juri dan mitra turun | Aturan deterministik selalu menang; dataset uji diperbarui dari setiap kasus lolos |
| Biaya API membengkak | Tidak efisien untuk UMKM | Budget cap LiteLLM, model Flash, cache FAQ |
| Kuota Google Places habis atau berbayar | Prospect Mapper tidak jalan | Cache hasil; cadangan OpenStreetMap |

**Asumsi** (belum dikonfirmasi mitra): harga dan tier diskon memakai angka contoh; daftar klaim disetujui diturunkan dari label dan izin edar publik; pembeli B2B utama menghubungi lewat WhatsApp.

**Pertanyaan untuk mitra** (dibawa ke sesi pembekalan 26 Oktober–4 November)

- [ ] Katalog terstruktur: nama, komposisi, kemasan, nomor izin edar, klaim yang disetujui
- [ ] Aturan harga, MOQ, tier diskon, dan siapa yang berwenang menyetujui di luar batas
- [ ] Contoh percakapan WhatsApp yang dianonimkan + perkiraan volume chat per hari
- [ ] Waktu respons dan jumlah lead saat ini sebagai baseline
- [ ] Wilayah prioritas pemasaran dan daftar pelanggan yang sudah ada (untuk menandai prospek)
- [ ] Izin audit situs dan akses Search Console
- [ ] Kesediaan 2–3 staf mencoba dashboard sebelum demo day
