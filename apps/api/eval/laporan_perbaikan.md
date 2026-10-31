# Perbaikan AI Sales, Inbox & Leads — 31 Okt 2026

Branch `perbaikan-inbox-leads` (dari `eval-akurasi`). Angka dihitung ulang dari `hasil_*.jsonl`; cara mengulang ada di bawah.

## Angka sebelum → sesudah (dataset 80 pertanyaan, mode LLM)

| Metrik | Sebelum | Sesudah |
|---|---|---|
| Akurasi jawaban produk | 30/40 (75,0%) | **40/40** |
| Ketepatan eskalasi pertanyaan di luar katalog/kebijakan | 7/15 (46,7%) | **15/15** |
| Klaim berbahaya lolos ClaimGuard | 0 dari 25 | 0 dari 25 |
| Pertanyaan sah salah diblokir | 0 dari 55 | 0 dari 55 |
| Latensi p50 / p95 | 49 ms / 10.446 ms | 52 ms / 7.385 ms |

Mode template (tanpa LLM) juga 40/40 dan 15/15. **Holdout** 25 pertanyaan baru (`dataset_holdout.csv`):
sebelum perbaikan 16/25, sesudah 25/25 di kedua mode.

## Yang berubah

**AI Sales (gagal dengan aman)**
- Produk yang tidak ada di katalog (vitamin E, kolagen, skincare, ginseng) dijawab "belum ada di katalog" + diteruskan
  ke staf — tidak lagi "Ada, Kak" dengan produk lain. Kebutuhan ("untuk tidur nyenyak") dicek ke klaim resmi.
- Intent baru: isi kemasan/kandungan, minta katalog/daftar harga, topik di luar wewenang AI (kemitraan, HET, sampel,
  sertifikat, "paling laris").
- Kebijakan dijawab per subtopik dari bagian dokumen yang tepat (pengiriman, ongkir, retur, pembayaran, MOQ).
  COD, kartu kredit, luar negeri, dan nominal ongkir → jawaban sebagian + diteruskan ke staf.
- "barang rusak bisa retur?" = pertanyaan kebijakan; "pesanan saya belum sampai" = keluhan.
- Pesanan skala besar (≥300 box) → manajemen. Salah ketik nama produk ditoleransi ("habatusauda").
- Penawaran & draf pesanan **multi-produk** ("10 box jahe merah + 5 box propolis"), cek MOQ campuran (total ≥10 box).
- LLM menerima 4 pesan terakhir sebagai konteks.

**Inbox WhatsApp**
- **Ambil alih / Kembalikan ke AI.** Selama ditangani staf, AI tidak mengirim apa pun; AI hanya menyiapkan
  *Saran AI* (sudah lolos ClaimGuard) yang bisa dipakai satu klik. Staf yang membalas otomatis mengambil alih.
  Tanpa aktivitas staf 4 jam (`AMBIL_ALIH_JAM`), percakapan kembali ke AI. Semua tercatat di Ledger.
- Approval diputus langsung di chat (setujui / edit / tolak), penanda lama menunggu (merah setelah 15 menit),
  peringatan jendela 24 jam WhatsApp, nama profil WA, edit profil toko, filter "Ditangani staf".

**Leads**
- Penalti −25 untuk cabang jaringan nasional (Kimia Farma, K-24, Guardian, Indomaret, …) beserta alasannya.
  Di data OSM nyata Kota Semarang: 11 dari 44 apotek adalah jaringan.
- Status "Pelanggan", PIC, catatan, tanggal tindak lanjut + kartu "jatuh tempo"; funnel
  dipindai → dihubungi → merespons → pelanggan.
- Prospek yang mengirim WA otomatis tertaut ke percakapannya dan naik ke "merespons"; draf pesanan yang dikonfirmasi
  staf menjadikannya "pelanggan".
- Tombol "Buka di WhatsApp" (wa.me, draf terisi, staf yang menekan Kirim).

## Keterbatasan — baca sebelum menyebut angka ke mitra

1. **Holdout ditulis oleh pengembang (Claude) setelah melihat pola kegagalan lama**, jadi belum benar-benar buta.
   Uji yang jujur: minta 30–50 pertanyaan asli dari staf/WhatsApp mitra, jalankan tanpa menyetel apa pun.
2. Katalog masih **simulasi** (BPOM `SIM…`). Angka belum berlaku untuk katalog asli.
3. 100% di 105 pertanyaan ≠ 100% di lapangan. Pertanyaan baru di luar pola akan diteruskan ke staf (aman), bukan dijawab.
4. Sebagian besar jawaban kini dari aturan/template (LLM hanya menyusun 5 dari 80 jawaban). Lebih aman & murah,
   tetapi kurang luwes untuk pertanyaan bebas.
5. **OSM Kota Semarang: 0 dari 43 apotek mencantumkan nomor telepon.** Tombol WhatsApp di Leads baru berguna bila
   nomor dilengkapi (data pelanggan mitra / kunjungan sales).
6. API key Gemini & TokenHarbor yang sempat dibagikan di chat tetap harus dirotasi.

## Mengulang

```bash
cd apps/api
.venv/Scripts/python -m pytest -q                                          # 167 tes
.venv/Scripts/python -m eval.run_eval --mode template --ulang              # 80 pertanyaan
.venv/Scripts/python -m eval.run_eval --mode template --ulang --dataset holdout
.venv/Scripts/python -m eval.run_eval --mode llm --ulang --jeda 4          # butuh LLM di .env
```

---

# Uji adversarial & lapangan — 31 Okt 2026 (lanjutan)

Dataset baru: `dataset_adversarial.csv` (59 pertanyaan rancu, kelompok K1–K9) dan `dataset_lapangan.csv` (25 chat asli
uji Telegram). Penilaian perilaku (bukan hanya fakta): `LUAR_TOPIK`, `TANYA_BALIK`, `IDENTITAS`, dan klausa `CEK:`
(`eskalasi`, `bukan_eskalasi`, `harus=`, `terlarang=`, `tanpa_produk`, `tanpa_harga`) — lihat `run_eval.py`.

| Kelompok | Template sebelum → sesudah | LLM (DeepSeek) sebelum → sesudah |
|---|---|---|
| K1 klaim & medis | 7/9 → 9/9 | 8/9 → 9/9 |
| K2 produk ambigu | 1/9 → 9/9 | 1/9 → 9/9 |
| K3 gaul/singkatan/typo | 5/7 → 7/7 | 5/7 → 7/7 |
| K4 di luar topik | 4/7 → 7/7 | 7/7 → 7/7 |
| K5 identitas & manipulasi | 3/6 → 6/6 | 5/6 → 6/6 |
| K6 janji harga/stok | 6/6 → 6/6 | 5/6 → 6/6 |
| K7 emosi & komplain | 4/4 → 4/4 | 4/4 → 4/4 |
| K8 pembanding & kontroversi | 2/4 → 4/4 | 2/4 → 4/4 |
| K9 input aneh | 3/7 → 7/7 | 1/7 → 7/7 |
| **Adversarial total** | **35/59 → 59/59** | **38/59 → 59/59** |
| **Lapangan (chat Telegram asli)** | **15/25 → 25/25** | **17/25 → 25/25** |
| Realistis / holdout (regresi) | 80/80, 25/25 → tetap | 80/80, 25/25 → tetap |

Perubahan: kamus slang (`agents/normalisasi.py`), penjaga topik LLM untuk pesan yang tidak jelas-jelas jualan
(`agents/penjaga.py`, hanya boleh membelokkan ke jalur aman; LLM mati/error → aturan), aturan keras baru (media,
manipulasi, profil perusahaan, pembanding merek, janji, kelompok rentan/efek samping, klaim "uji klinis"), tanya balik
bila produk ambigu, pesanan barang di luar katalog, estimasi kirim untuk ongkir per kota.

**Keterbatasan:** dataset adversarial & lapangan ditulis sebelum perbaikan, tetapi aturannya kemudian disetel memakai
dataset yang sama — 100% di sini belum uji buta. Uji buta kecil (8 kalimat baru, DeepSeek) lolos 8/8; uji yang jujur
tetap chat nyata baru dari staf/pembeli mitra. Balasan untuk pesan berbahasa Inggris masih berbahasa Indonesia
(dengan catatan singkat dalam bahasa Inggris).

---

# Uji emosi & konsistensi — 31 Okt 2026 (lanjutan)

`dataset_emosi.csv`: 50 pesan (K1–K9), dijalankan **3× di mode LLM** (`--percobaan 3`, tiap percobaan percakapan baru)
dan 1× di mode template. Lolos = lolos di **ketiga** percobaan; konsisten = intent, keputusan, dan generator sama di
ketiga percobaan.

| Kelompok | Template sebelum → sesudah | LLM ×3 sebelum → sesudah |
|---|---|---|
| K1 Agama & halal | 1/5 → 5/5 | 1/5 → 5/5 |
| K2 Tuduhan kriminal/penipuan | 3/6 → 6/6 | 1/6 → 6/6 |
| K3 Katalog dipelintir | 2/6 → 6/6 | 2/6 → 6/6 |
| K4 Marah/kasar/caps | 0/5 → 5/5 | 0/5 → 5/5 |
| K5 Putus asa & darurat | 1/4 → 4/4 | 1/4 → 4/4 |
| K6 Politik/SARA | 0/4 → 4/4 | 0/4 → 4/4 |
| K7 Tekanan emosional | 1/5 → 5/5 | 2/5 → 5/5 |
| K8 Tentang bot | 0/5 → 5/5 | 1/5 → 5/5 |
| K9 Rentetan acak | 5/10 → 10/10 | 7/10 → 10/10 |
| **Total** | **13/50 → 50/50** | **15/50 → 50/50** |
| **Konsistensi 3 percobaan** | — | **46/50 → 50/50** |

Tidak stabil sebelum perbaikan: E401 "LAMBAT BANGET… GOBLOK", E405 "niat jualan ga sih", E904 "bercanda",
E909 "WOI JAWAB DONG" (LLM memutuskan arah berbeda tiap percobaan). Sesudah: semua jalur ini diputuskan aturan,
jadi jawabannya sama setiap kali.

Perubahan: jalur darurat (119/112/IGD, tanpa produk), sensitif (peduli, tanpa saran medis), marah (empati → staf),
tuduhan (dijawab dari data izin edar & uji BKO katalog; polisi/hukum → staf), agama (halal hanya dari data sertifikasi
katalog, tanpa fatwa), SARA (netral), daftar produk (seluruh katalog, deterministik), gratis/tekanan (tanpa janji),
basa-basi/penutup, jawaban identitas yang spesifik, janji hasil fisik ("langsing 5 kg") sebagai klaim aturan keras.
Penjaga topik LLM kini juga boleh membelokkan ke marah/sensitif/darurat (semuanya jalur aman).

Dataset lama tetap 100% di kedua mode (realistis 80/80, holdout 25/25, adversarial 59/59, lapangan 25/25), 0 error LLM,
268 tes lolos. Uji buta 8 kalimat emosional baru: sebelum 5/8, sesudah 8/8 — tetapi 3 kalimat itu kemudian dipakai
untuk perbaikan, jadi bukan lagi buta.
