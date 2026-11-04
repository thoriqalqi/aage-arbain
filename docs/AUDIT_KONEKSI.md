# Audit Koneksi AAGE

Tanggal audit: 4 November 2026. Cabang `database-online`, commit `61b12e1`, ditambah perubahan yang belum di-commit: `aage/db.py`, `aage/ledger_chain.py`, `scripts/pindah_ke_postgres.py`, `tests/test_database_online.py`.

## Kesimpulan

Alur inti dari kanal, AI, ClaimGuard, Ledger, sampai antrean staf tersambung dan teruji di SQLite. Empat hal belum siap untuk demo mitra:

1. **Database aktif kosong.** `aage.db` berisi 0 produk dan 0 pengguna, jadi bot menjawab "belum ada di katalog" untuk semua produk dan login dashboard gagal.
2. **Tunnel membuka API ke publik dengan pengaman mode dev.** `JWT_SECRET` tidak ada di `.env`, sehingga token ditandatangani dengan nilai bawaan dari `config.py`. Webhook WATI dan WhatsApp juga terbuka tanpa token.
3. **Staf tidak diberi tahu saat eskalasi.** Staf hanya tahu kalau membuka dashboard.
4. **Halaman yang tampak berhasil memakai data lama atau simulasi.** Halaman Evaluasi menampilkan hasil dataset lama mode offline, dan Command Center berjalan dalam mode simulasi.

## Cara audit dan batasannya

**Yang dijalankan:**
- Membaca kode dan menelusuri endpoint, penulis, serta pembaca tabel dengan pencarian pola.
- `pytest`: 396 lolos, semuanya di SQLite.
- Kompilasi DDL 21 tabel untuk dialek Postgres tanpa koneksi: berhasil. Ini hanya memeriksa sintaks pembuatan tabel, bukan perilaku di Postgres.

**Yang tidak dilakukan:**
- Tidak menghubungi Supabase. Status online berasal dari catatan sesi kerja: proyek `AAGE` dibuat dan hanya migrasi `aktifkan_vector` yang dijalankan.
- Tidak membuka halaman web di browser. Status frontend berasal dari kode dan pemeriksaan TypeScript.
- Tidak memanggil LLM, karena `LLM_API_KEY` kosong.

**Batasan:** penelusuran tabel memakai pola teks, jadi akses tidak langsung lewat relasi ORM bisa terlewat.

**Status di `.env` (nama kunci saja):** `DATABASE_URL`, `JWT_SECRET`, dan `ENV` tidak ada. `LLM_API_KEY` kosong.

**Istilah status:**

| Status | Arti |
|---|---|
| TERSAMBUNG-TERUJI | Ada tes otomatis atau sudah diuji langsung pada jalur ini |
| TERSAMBUNG-BELUM-TERUJI | Kodenya tersambung, tetapi belum ada tes atau uji langsung pada jalur itu |
| PUTUS | Salah satu ujung ada, tetapi tidak terhubung |
| DATA SIMULASI | Tersambung, tetapi isinya simulasi atau lama |
| BELUM ADA | Belum ada kodenya |

---

## 1. Peta koneksi

### 1a. Frontend ke backend

| Halaman atau komponen | Endpoint | Status | Bukti dan catatan |
|---|---|---|---|
| Login `app/(auth)/login/page.tsx` | `POST /auth/login` | **PUTUS saat ini** | Kode teruji (`tests/test_mvp.py`), tetapi tabel `users` di `aage.db` kosong |
| Ringkasan `app/(app)/page.tsx` | `/kpi`, `/approvals`, `/content` | TERSAMBUNG-BELUM-TERUJI | Backend teruji, tampilan belum dilihat. Isi dihitung dari Ledger |
| Panel "Dicari, belum ada di katalog" | `/kpi`, kunci `permintaan_tak_terpenuhi` | TERSAMBUNG-BELUM-TERUJI | Backend teruji (`test_luar_katalog.py`), panel belum dilihat di browser |
| Inbox `inbox/page.tsx`, `inbox-panels.tsx` | `/conversations`, `/reply`, `/ambil-alih`, `/kembalikan`, `/approvals/{id}/decide`, `PATCH /contacts/{id}` | TERSAMBUNG-TERUJI di backend | `test_inbox.py`. Pengujian antarmuka masih manual |
| Approval `approval/page.tsx` | `/approvals`, `/decide` | TERSAMBUNG-TERUJI di backend | `test_mvp.py` |
| Leads `leads/page.tsx`, `prospect-drawer.tsx` | `/prospects`, `/prospek/scout`, `/export.csv`, `/riset`, PATCH | TERSAMBUNG-TERUJI di backend | Data OSM nyata tetapi nomor telepon jarang ada. `/riset` perlu `SERPER_API_KEY`, yang tidak ada di `.env` |
| Katalog dan impor `katalog-manager.tsx`, `katalog-impor.tsx` | `/kb/*`, `/katalog/*` | TERSAMBUNG-TERUJI di backend | `test_katalog_impor.py`. Kolom `aturan_pakai` otomatis ikut di template, belum dicoba di layar |
| Konten `konten/page.tsx` | `/content/*` | TERSAMBUNG-TERUJI di backend | `test_content_studio.py`. Tanpa LLM memakai template |
| Compliance `compliance/page.tsx` | `/claimguard/check`, `/ledger*` | TERSAMBUNG-BELUM-TERUJI | Halaman hanya memuat ClaimGuard dan Ledger |
| Evaluasi `evaluasi/page.tsx` | `/eval/summary`, `/eval/run`, `/kpi`, `/status` | **DATA SIMULASI** | Membaca `eval/hasil/hasil.json`, mode `offline (deterministik)`, dataset lama. Dataset baru (emosi, konteks, luar katalog, dan lainnya) tidak tampil |
| Agen `agen/page.tsx` | `/agents/status` + SSE, `/settings`, `/approvals` | TERSAMBUNG-TERUJI di backend | Status dihitung dari Ledger (`test_agent_status.py`) |
| Command Center `app/dashboard/page.tsx` | `/agents`, `/agents/workday/stream`, `/agents/audit`, `/agents/negotiate`, `/agents/invoice/approve` | **DATA SIMULASI** | `resolve_mode()` memakai simulasi tanpa `ANTHROPIC_API_KEY`. Hanya ada catatan kecil "Data produk simulasi" di bawah halaman, belum ada label SIMULASI yang jelas. Invoice Fonnte juga simulasi |
| Arsitektur `arsitektur/page.tsx` | hanya `/agents/status` lewat hook | **Hardcode dan usang** | Menyebut `/api/v1`, `overview/*`, dan `ledger export.pdf`, yang tidak ada di backend |
| Web chat `app/chat/page.tsx` | `/chat/simulate`, `/messages` | TERSAMBUNG-TERUJI | Memakai `handle_inbound` yang sama |
| Pengaturan `pengaturan/page.tsx` | `/settings`, `/status`, katalog | TERSAMBUNG-TERUJI di backend | |

**Endpoint tanpa pemanggil di frontend:**

| Endpoint | Catatan |
|---|---|
| `/compliance/audit`, `/audits`, `/drafts`, `/drafts/{id}`, `apply-recommendation`, `approve`, `discard`, `registry` | Seluruh modul Compliance Check tanpa layar |
| `/compliance/latest-audit` | Hanya dipanggil `lib/use-latest-audit.ts`, dan hook itu tidak dipakai komponen mana pun |
| `/agents/content`, `/agents/leads` | Hanya alur CrewAI |
| `/reminders/repeat-order` | **Fitur penting tanpa tombol** |
| `/auth/me`, `/ledger-types`, `/content/sample-page`, `/prospects/search`, `/kb/products/import`, `POST /kb/claims` | Sisa atau alat bantu |
| `/webhook/*`, `/health` | Memang bukan untuk frontend |

**Fitur frontend tanpa endpoint:** tidak ditemukan. Dua panggilan yang tampak tanpa padanan sudah dicek dan ternyata ada: `/api/agents` memakai dekorator path kosong, dan `/api/content/{}/{}` adalah `approve`, `submit`, atau `arsip`.

**Data palsu di frontend:**
- Tidak ada daftar data palsu pada halaman utama.
- `ClaimGuardPlayground` punya kalimat contoh, wajar untuk alat uji.
- `lib/agents.ts` berisi definisi agen statis.
- `SampleNote` di `panel.tsx` tidak dipakai.

### 1b. Backend ke database dan agent

| Kelompok endpoint | Tabel | Agent atau layanan | Status SQLite | Status Postgres |
|---|---|---|---|---|
| Webhook Telegram, WATI, Meta; `/chat/simulate` | Semua tabel percakapan | `handle_inbound` | TERSAMBUNG-TERUJI | Belum teruji |
| `/auth/*` | `users` | `security.py` | TERSAMBUNG-TERUJI | Belum teruji |
| `/conversations/*`, `/contacts` | `conversations`, `messages`, `contacts`, `approvals`, `ledger_events` | `inbox.py`, `sender.py` | TERSAMBUNG-TERUJI | Belum teruji |
| `/approvals/*` | `approvals`, `order_drafts`, `content_drafts`, `prospects` | `approvals.py`, ClaimGuard | TERSAMBUNG-TERUJI | Belum teruji |
| `/kb/*`, `/katalog/*` | `products`, `approved_claims`, `pricing_rules`, `documents`, `chunks`, `katalog_impor` | `ingest.py`, `katalog_impor.py` | TERSAMBUNG-TERUJI | Belum teruji |
| `/ledger*` | `ledger_events`, `ledger_hashes` | `ledger_chain.py` | TERSAMBUNG-TERUJI | Belum teruji. Payload hash sudah dibuat tidak tergantung zona waktu |
| `/kpi`, `/agents/status`, `/status` | `ledger_events`, `permintaan_tak_terpenuhi`, `approvals` | `kpi.py`, `agent_status.py` | TERSAMBUNG-TERUJI | Belum teruji |
| `/prospects/*`, `/prospek/scout` | `prospects`, `ledger_events` | Overpass, Serper | TERSAMBUNG-TERUJI dengan fixture | Belum teruji |
| `/content/*` | `content_drafts`, `approvals` | `studio.py`, ClaimGuard | TERSAMBUNG-TERUJI | Belum teruji |
| `/compliance/*` | `marketing_drafts`, `compliance_audits` | `src/compliance` | TERSAMBUNG-TERUJI | Belum teruji |
| `/agents/*` | `approvals`, `ledger_events` | `src/agents_crew.py` | Teruji mode simulasi | Belum teruji |
| `/eval/*` | Ledger; proses terpisah di DB sementara | `eval.run` | TERSAMBUNG-TERUJI | Membaca file, bukan database |
| `/settings` | `settings` | `settings_store.py` | TERSAMBUNG-TERUJI | Belum teruji |

**Query yang hanya jalan di SQLite:** tidak ditemukan pada jalur runtime.
- `PRAGMA` dan `_rebuild_sqlite_table` (`aage/db.py`) sudah dijaga pemeriksaan dialek.
- Query `group_by` memuat kolom yang valid di Postgres (`kpi.py:77`, `routes.py:206,214,538,841`).
- `LIKE` dan `substr` berlaku di kedua database.

**Yang berbeda di Postgres dan baru terbukti saat dijalankan:**

| Hal | Lokasi | Risiko |
|---|---|---|
| Pencarian `<=>` pgvector | `kb/retriever.py:48-53` | Jalur ini tidak pernah dijalankan; urutan hasil bisa berbeda dari SQLite |
| Batas panjang `VARCHAR` ditegakkan | mis. `messages.arah(8)`, `status_kirim(16)`, `prospects.tipe(24)` | SQLite tidak menegakkannya; nilai kepanjangan baru gagal di Postgres |
| Trigger Ledger | `exec_driver_sql(LEDGER_GUARD_SQL)` | Belum dijalankan |
| `pg_advisory_xact_lock` | `ledger_chain.seal` | Belum dijalankan lewat Session Pooler |
| Koneksi per SSE | `agent_status.agents_status_stream` membuka sesi tiap tick | Bisa menekan batas koneksi paket gratis; pool tidak diatur (`db.py`) |
| Urutan `NULL` | `order_by` pada kolom nullable | Postgres menaruh `NULL` di posisi berbeda; perlu dicek pada daftar |
| Latensi | Tiap pesan banyak query ke Singapura | Belum diukur |

### 1c. Agent, kanal, katalog, tabel

| Komponen | Dipanggil dari `handle_inbound`? | Status | Tabel atau data |
|---|---|---|---|
| Router aturan keras `agents/router.py` | Ya | TERSAMBUNG-TERUJI | Baca katalog |
| Kamus slang `normalisasi.py` | Ya | TERSAMBUNG-TERUJI | |
| Pemahaman konteks `pemahaman.py` | Ya | TERSAMBUNG-TERUJI di template | `conversations.konteks["sales"]` |
| Peta tindakan `tindakan.py` | Ya | TERSAMBUNG-TERUJI di template | Kebijakan, `konteks["langkah"]` |
| Penjaga topik LLM `penjaga.py` | Ya, bila LLM aktif | **Tidak aktif sekarang** | Fitur mati karena key kosong |
| Drafter `drafter.py` | Ya | TERSAMBUNG-TERUJI | Katalog, kebijakan, `order_drafts` |
| Rewrite gaya dan fact-lock `gaya.py` | Ya, bila LLM aktif | **Tidak aktif; regresi LLM 4b belum selesai** | Ledger |
| Pencari produk `find_products` | Ya | TERSAMBUNG-TERUJI | `products` |
| Retrieval dan pgvector `retriever.py` | Ya | Teruji SQLite, **belum teruji pgvector** | `chunks` |
| ClaimGuard tahap aturan | Ya | TERSAMBUNG-TERUJI | `approved_claims` |
| ClaimGuard juri LLM | Ya, bila LLM aktif | **Tidak aktif** | |
| Pelacak tahap `tahap.py`, memori `memori.py` | Ya | TERSAMBUNG-TERUJI | `conversations.konteks` |
| Ledger dan rantai hash | Ya | TERSAMBUNG-TERUJI | `ledger_events`, `ledger_hashes` |
| Ambil alih staf `inbox.py` | Ya | TERSAMBUNG-TERUJI | `conversations` |
| Eskalasi `escalate_node` | Ya | TERSAMBUNG-TERUJI, **tanpa notifikasi** | `approvals` |
| Follow-up otomatis | Tidak | **BELUM ADA** | Hanya `konteks["tindak_lanjut_pada"]` (`drafter.py:532`), tidak ada penjadwal |
| Pengingat repeat order | Tidak | **PUTUS** | `POST /reminders/repeat-order` manual, tanpa tombol, tanpa jadwal |
| CrewAI `src/agents_crew.py` | **Tidak, hanya `/api/agents/*`** | DATA SIMULASI | Alur terpisah dari bot |
| Compliance `src/compliance`, `compliance.py` | **Tidak, hanya `/api/compliance/*`** | Teruji backend, tanpa layar | `marketing_drafts`, `compliance_audits` |

**Hanya dipakai eval:** dataset `eval/*`, `run_eval.py`, `run_konteks.py`, `run_percakapan.py`, `run_regresi_llm.py`. Tidak ada kode produksi yang bergantung padanya, kecuali `/eval/run` yang menjalankan `eval.run`.

**Kanal:**

| Kanal | Masuk | Keluar | Status |
|---|---|---|---|
| Telegram | Webhook dengan secret, allowlist | `sendMessage` | Keluar terbukti live. Masuk dari server Telegram lewat tunnel aktif pada sesi ini hanya terbukti terjangkau (HTTP 401 tanpa secret), belum ada pesan asli sejak kode baru |
| Web chat | `/chat/simulate` | Tersimpan di database | TERSAMBUNG-TERUJI, tanpa autentikasi |
| WhatsApp WATI | `/webhook/wati` | `wati.py` | Teruji dengan mock, **belum live** |
| WhatsApp Meta | `/webhook/whatsapp` | `whatsapp.py` | Belum diuji dengan kredensial nyata |
| Fonnte | Tidak ada | Invoice di Command Center | Simulasi tanpa token |

**Katalog dan kebijakan:** tidak ada tabel kebijakan khusus. Kebijakan adalah `documents` dan `chunks`. Mengubahnya berarti lewat impor atau unggah dokumen. Kode mengambil bagian kebijakan dengan mencocokkan judul seperti `Pengiriman:` (`drafter.py`), jadi dokumen dengan judul lain membuat jawabannya kosong.

### 1d. Notifikasi, Leads, pesanan

| Sambungan | Status | Bukti |
|---|---|---|
| Eskalasi ke staf | **BELUM ADA** | `escalate_node` hanya membuat `approvals` dan event Ledger. Staf hanya melihat lencana di `app-shell.tsx` yang memuat ulang tiap 8 detik saat dashboard terbuka |
| Leads ke percakapan, WhatsApp | TERSAMBUNG-TERUJI | `prospects/mapper.py:link_contact` mencocokkan nomor |
| Leads ke percakapan, Telegram | **PUTUS kecuali nomor dibagikan** | Kontak Telegram tanpa `wa_number` tidak ditautkan. Tombol "Bagikan nomor HP" hanya muncul di alur riwayat kosong |
| Data pembeli grosir (`konteks["sales"]`) ke Leads | **PUTUS** | Profil, kota, dan volume hanya ada di konteks percakapan dan ringkasan antrean; tidak membuat atau memperbarui `prospects` |
| Draf pesanan ke antrean staf | TERSAMBUNG-TERUJI | `_order_approval`, `approvals.decide` |
| Pesanan ke riwayat dan repeat order | TERSAMBUNG-TERUJI | `sales.riwayat_terakhir`, `test_repeat.py`. Termasuk draf yang belum dikonfirmasi, karena hanya mengecualikan status `ditolak` |
| Pesanan ke halaman daftar | **BELUM ADA** | `serializers.order` ada, tetapi tidak ada endpoint atau halaman daftar pesanan |
| Status pesanan setelah konfirmasi | **PUTUS** | Hanya `menunggu`, `dikonfirmasi staf`, `ditolak`. Status `selesai` hanya ditulis seed |
| Persetujuan kontak (`opt_in`) ke pengingat | **PUTUS** | `reminders` hanya mengirim ke `opt_in=True`, nilai itu hanya diisi seed, dan kontak baru selalu `False`. Pembeli nyata tidak akan pernah menerima pengingat |

---

## 2. Tabel database

Berlaku untuk semua 21 tabel:
- **Postgres online:** belum ada. Pemindahan belum dijalankan karena `DATABASE_URL` belum diisi. DDL hanya lolos kompilasi offline.
- **RLS:** belum aktif. Kodenya ada di `init_db` dan belum di-commit, dan aktif saat `init_db` berjalan pada database online.
- **Migrasi:** tidak ada alat migrasi versi. Skema memakai `create_all` ditambah `_add_missing_columns`, yang hanya bisa menambah kolom. Alembic belum dipasang.

| Tabel | Ditulis oleh | Dibaca oleh | Prioritas | Alasan | Usaha |
|---|---|---|---|---|---|
| `products` | `kb/ingest.py`, `kb/katalog_impor.py` | drafter, ClaimGuard, Katalog, Konten | 5 | Tanpa isi, bot tidak berguna; sekarang 0 baris | Kecil |
| `documents` | ingest, katalog_impor | retriever, Katalog | 5 | Sumber kebijakan kirim, bayar, retur; sekarang 0 baris | Kecil |
| `chunks` | ingest, katalog_impor | retriever, drafter, Konten | 5 | Jalur pgvector belum pernah jalan | Sedang |
| `approved_claims` | ingest, katalog_impor, `/kb/claims` | ClaimGuard, drafter | 5 | Dasar kepatuhan klaim | Kecil |
| `pricing_rules` | ingest, katalog_impor | sales, drafter | 5 | Tier diskon tidak boleh salah | Kecil |
| `users` | **hanya `seed.py`** | login, `security.py` | 5 | Sekarang 0 baris; tidak ada kelola pengguna; akun demo bersandi lemah | Sedang |
| `ledger_events` | `ledger.py` | KPI, Agen, Ledger | 5 | Bukti audit harus pindah utuh | Kecil |
| `ledger_hashes` | `ledger_chain.py` | `verify` | 5 | Rantai harus cocok setelah pindah | Kecil |
| `contacts` | `graph.py`, seed, `/contacts` | Inbox, sales, Leads | 5 | Identitas pembeli; memuat data pribadi | Kecil |
| `conversations` | `graph.py`, `routes.py` | Inbox, approvals | 5 | Konteks pembeli | Kecil |
| `messages` | `graph.py`, `sender.py` | Inbox, web chat | 5 | Riwayat chat; memuat data pribadi | Kecil |
| `approvals` | graph, agents_api, studio | Approval, Inbox, Agen | 5 | Antrean staf | Kecil |
| `order_drafts` | drafter, seed | sales, approvals | 4 | Satu-satunya riwayat pesanan; **ditulis tetapi tanpa halaman daftar** | Sedang |
| `permintaan_tak_terpenuhi` | `graph.py` | `kpi.py`, panel Ringkasan | 4 | Fitur baru, panel belum dilihat | Kecil |
| `settings` | `settings_store.py` | Agen, graph, llm | 4 | Mode otonomi dan budget harus terbawa | Kecil |
| `katalog_impor` | katalog_impor | routes | 3 | Riwayat impor; tidak ada halaman riwayat | Kecil |
| `prospects` | `mapper.py` | Leads, approvals | 3 | Penting untuk fungsi Leads, belum terhubung ke data sales | Sedang |
| `content_drafts` | `studio.py` | Konten, approvals | 2 | Bukan alur inti demo sales | Kecil |
| `marketing_drafts` | `compliance.py` | `compliance.py` | 1 | **Ditulis tetapi tidak pernah ditampilkan**; tanpa layar | Sedang bila diberi layar |
| `compliance_audits` | `compliance.py` | `compliance.py` | 1 | **Ditulis tetapi tidak pernah ditampilkan**; hook frontend tak terpakai | Sedang bila diberi layar |
| `prospect_cache` | **tidak ada** | **tidak ada** | 1 | **Tabel yatim**: hanya definisi model | Kecil (hapus) |

**Tabel yang dibutuhkan tetapi belum ada:**

| Kebutuhan | Keadaan sekarang | Saran | Prioritas | Usaha |
|---|---|---|---|---|
| Notifikasi staf | Tidak ada | Tabel log kiriman dan pengiriman Telegram ke chat staf | 5 | Sedang |
| Jadwal follow-up | Hanya kolom `prospects.tindak_lanjut_pada` dan nilai di konteks | Tabel `tindak_lanjut` dan penjadwal | 3 | Besar |
| Pengingat repeat order | Hanya endpoint manual | Tabel jadwal, atau dihitung dari riwayat, plus persetujuan kontak | 3 | Sedang |
| Riwayat pesanan final | `order_drafts` dipakai ganda sebagai draf dan riwayat | Status yang lengkap dulu; tabel terpisah belum perlu | 3 | Sedang |
| Data calon pembeli grosir | Hanya JSON di konteks | Tautkan ke `prospects` atau kolom di `contacts` | 4 | Sedang |

---

## 3. Daftar pekerjaan

### a. Wajib sebelum demo mitra

| No | Celah | Dampak | File atau tabel | Usaha | Bergantung pada |
|---|---|---|---|---|---|
| 1 | Database aktif kosong | Bot dan login tidak berguna | Semua tabel; `pindah_ke_postgres.py` | Kecil | Anda mengisi `DATABASE_URL`, atau seed lokal |
| 2 | API terbuka lewat tunnel memakai `JWT_SECRET` bawaan dan mode dev | Token admin bisa dipalsukan oleh yang mengetahui nilai itu; webhook WATI dan Meta terbuka | `.env`, `config.py`, `security.py`, `routes.py:132` | Kecil | Sebelum No. 1 selesai diakses publik |
| 3 | Akun demo bersandi lemah | Login admin mudah ditebak | `seed.py`, `users` | Kecil | No. 1 |
| 4 | Jalur Postgres belum teruji | Bot bisa gagal saat demo | `retriever.py`, `db.py`, `ledger_chain.py` | Sedang | No. 1 |
| 5 | Regresi LLM belum dijalankan untuk kode baru | Aturan 100% belum terpenuhi | `run_regresi_llm.py`, `run_konteks.py` | Sedang | Key baru; jatah pulih menurut catatan 7 November, atau model berbayar |
| 6 | Staf tidak diberi tahu saat eskalasi | Pembeli menunggu tanpa ada yang tahu | `graph.py:escalate_node`, tabel baru | Sedang | Chat ID staf |
| 7 | Command Center tanpa label SIMULASI yang jelas | Mitra mengira agen sungguhan | `app/dashboard/page.tsx` | Kecil | Tidak ada |
| 8 | Halaman Evaluasi menampilkan hasil lama | Mitra melihat 100% dari dataset lama offline | `eval_api.py`, `evaluasi/page.tsx`, `eval.run` | Sedang | No. 5 untuk angka LLM |
| 9 | Katalog simulasi | Harga dan izin edar palsu tampil sebagai data | `mock_products.json`, impor | Kecil bagi kode | Katalog resmi mitra |
| 10 | Panel dan layar baru belum dilihat di browser | Bisa ada kesalahan tampilan | `page.tsx`, Inbox | Kecil | No. 1 |
| 11 | Halaman Arsitektur menyebut endpoint yang tidak ada | Tampak tidak jujur | `arsitektur/page.tsx` | Kecil | Tidak ada |

### b. Wajib sebelum produksi

| No | Celah | Dampak | File | Usaha | Bergantung pada |
|---|---|---|---|---|---|
| 12 | API masih di laptop dan tunnel berubah alamat | Bot mati bila laptop mati; webhook harus dipasang ulang | Hosting, `docker-compose.yml` | Besar | Keputusan hosting |
| 13 | Dashboard lokal | Staf tidak bisa mengakses dari tempat lain | `apps/web` | Sedang | No. 12 |
| 14 | Tidak ada alat migrasi skema | Perubahan kolom atau tipe di database online berisiko | Alembic | Sedang | No. 1 |
| 15 | Proyek gratis dapat dijeda bila tidak aktif | Data tidak terbaca sampai diaktifkan | Supabase | Kecil | Keputusan biaya |
| 16 | Backup belum diatur | Data bisa hilang | Supabase, skrip ekspor | Sedang | Keputusan biaya |
| 17 | Kelola pengguna tidak ada; hanya seed | Staf tidak bisa ditambah atau mengganti sandi | `routes.py`, `users` | Sedang | Tidak ada |
| 18 | `/chat/simulate` tanpa autentikasi dan batas | Siapa pun bisa memakai budget LLM dan membuat percakapan | `routes.py:177` | Kecil | Tidak ada |
| 19 | Data pribadi pembeli di database online | Perlu kebijakan retensi dan akses | `contacts`, `messages` | Sedang | Keputusan Anda |
| 20 | Adapter WhatsApp belum live | Kanal utama mitra belum terbukti | `wati.py` | Sedang | Akun WATI |
| 21 | Key lama pernah tertulis di chat | Bisa disalahgunakan | TokenHarbor, Gemini | Kecil | Anda mengganti key |
| 22 | Pool koneksi belum diatur | Batas koneksi bisa terlampaui | `db.py`, `agent_status.py` | Kecil | No. 4 |
| 23 | Ringkasan keterbatasan dan angka | Metrik "ketepatan eskalasi" tidak lagi tepat setelah perubahan barang di luar katalog | `laporan_perbaikan.md`, dataset | Kecil | Persetujuan mengubah ekspektasi |

### c. Boleh menyusul

| No | Celah | File atau tabel | Usaha |
|---|---|---|---|
| 24 | Data sales grosir ke Leads | `pemahaman.py`, `mapper.py`, `prospects` | Sedang |
| 25 | Impor CSV/Excel leads | `routes.py`, `prospects` | Sedang |
| 26 | Daftar pesanan dan status lengkap | `routes.py`, `order_drafts`, halaman baru | Sedang |
| 27 | Follow-up otomatis | Tabel baru, penjadwal | Besar |
| 28 | Pengingat repeat order terjadwal, tombol, dan persetujuan kontak | `routes.py`, `contacts.opt_in` | Sedang |
| 29 | Dashboard konversi nyata | `kpi.py` | Sedang |
| 30 | Layar Compliance Check, atau hapus modulnya | `compliance_api.py`, `use-latest-audit.ts` | Sedang |
| 31 | Hapus `prospect_cache` dan `SampleNote` | `models.py`, `panel.tsx` | Kecil |
| 32 | Pencarian produk terdekat yang lebih baik | `drafter.py:_produk_terdekat` | Sedang |

---

## 4. Risiko: tampak jalan, belum tentu siap

1. **Angka 100% bukan uji buta.** Dataset ditulis tim pengembang. Holdout konteks sudah terbaca sebelum aturan ditulis, dan `dataset_luar_katalog.csv` ditulis bersamaan dengan kodenya.
2. **100% hanya berlaku di mode template pada kode terbaru.** Mode LLM belum dijalankan. Emosi 4b tercatat 336 benar, 29 error, 35 belum diproses.
3. **Semua lolos di SQLite.** Tidak ada satu pun tes berjalan di Postgres.
4. **Halaman Evaluasi tampak hijau** dari dataset lama mode offline, bukan kondisi kode saat ini.
5. **Command Center tampak seperti agen bekerja,** padahal mode simulasi tanpa LLM dan terpisah dari bot.
6. **Invoice Fonnte tampak terkirim** dalam mode simulasi.
7. **Katalog, izin edar, sertifikat halal, uji BKO, dan kebijakan adalah data simulasi.** Nomor `POM SD SIM…` terlihat meyakinkan di balasan bot.
8. **Bot aktif sekarang berjalan tanpa LLM,** jadi penjaga topik, juri ClaimGuard, dan penulisan ulang gaya tidak jalan. Tanpa pesan error, karena mode template adalah cadangan yang diam.
9. **Uji Telegram sesi ini memakai update buatan** ke webhook lokal. Pengiriman keluar terbukti, tetapi jalur pesan asli dari server Telegram lewat tunnel belum dibuktikan dengan pesan nyata pada kode baru.
10. **WhatsApp tampak siap di kode,** tetapi baru teruji dengan mock, sedangkan kanal itu yang kemungkinan dipakai mitra.
11. **Supabase tidak membuat bot selalu online.** Data akan online, tetapi API tetap di laptop.
12. **Label "Terkirim" di web chat** hanya berarti tersimpan di database.
13. **Ringkasan untuk staf tampak lengkap,** tetapi staf tidak diberi tahu ada ringkasan baru.
14. **Riwayat repeat order menghitung draf yang belum dikonfirmasi** sebagai pesanan terakhir, sehingga pesan ulang bisa memakai pesanan yang belum pernah disetujui.

---

## 5. Lima langkah berikutnya

1. **Amankan API dulu, sebelum data masuk.** Isi `JWT_SECRET` acak dan `WATI_WEBHOOK_TOKEN`, setel `ENV` bukan `dev`, dan siapkan sandi akun selain demo.
2. **Selesaikan pemindahan ke Supabase.** Jalankan pemindahan, verifikasi rantai hash, RLS, advisor keamanan, pgvector, dan ukur latensi. Commit perubahan database setelah lolos.
3. **Pasang notifikasi eskalasi ke staf lewat Telegram.** Ini celah fungsional terbesar saat demo.
4. **Jalankan regresi LLM penuh,** termasuk dataset konteks dan luar katalog.
5. **Rapikan yang dilihat mitra.** Label SIMULASI di Command Center, Evaluasi yang memakai dataset terbaru, koreksi halaman Arsitektur, lalu periksa layar di browser.

**Keputusan yang butuh persetujuan Anda:**

| Keputusan | Pilihan | Saran |
|---|---|---|
| Urutan keamanan dan database | Amankan dulu, atau pindah dulu | Amankan dulu; `ENV` bukan dev juga mewajibkan token webhook |
| `DATABASE_URL` | Anda mengisi password di `.env` | Dibutuhkan untuk langkah 2 |
| Regresi LLM | Tunggu jatah pulih, atau model berbayar `deepseek-v4.1-flash` | Tunggu, kecuali demo mendesak; harga dicek dulu |
| Notifikasi staf | Chat ID staf mana | Satu grup atau chat staf |
| Tanggal demo dan katalog resmi | Katalog mitra tersedia kapan | Menentukan apakah No. 9 bisa selesai sebelum demo |
| Ekspektasi `ESKALASI` lama | Ubah ke klausa eksplisit | Ubah, dengan laporan per baris |
| Status `repeat order` | Hanya pesanan terkonfirmasi, atau semua kecuali ditolak | Hanya terkonfirmasi; bisa mengubah perilaku tes lama |
| Hosting API | Pilih layanan dan anggaran | Sebelum produksi, tidak harus sebelum demo |
