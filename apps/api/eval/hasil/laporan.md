# Hasil uji MVP AAGE

Mode model: **offline (deterministik)** · dataset: katalog & klaim **sintetis berlabel** (ganti dengan data mitra saat tersedia).

| Metrik | Hasil | Target MVP | Status |
|---|---|---|---|
| Akurasi QA katalog (n=150) | 100.0% | ≥90% | ✅ |
| Groundedness jawaban otomatis | 100.0% | ≥98% | ✅ |
| Recall ClaimGuard (n=128) | 98.8% | ≥90% | ✅ |
| Precision ClaimGuard | 100.0% | ≥80% | ✅ |
| Kalimat 'Diblokir' lolos sebagai 'Diizinkan' | 0 | ≤0 | ✅ |
| Ketepatan eskalasi (n=30) | 100.0% | ≥95% | ✅ |
| Penawaran sesuai tier (n=12) | 100.0% | ≥100% | ✅ |
| Draf pesanan lengkap (n=9) | 100.0% | ≥90% | ✅ |
| Latensi p95 pipeline | 26.3 ms | ≤10000 ms | ✅ |

Akurasi 3 kelas ClaimGuard: 99.2% · selesai otomatis: 86.0% · biaya rata-rata per percakapan: Rp 0.0

## Confusion matrix ClaimGuard (baris = label, kolom = prediksi)

| label \ prediksi | allowed | review | blocked |
|---|---|---|---|
| allowed | 47 | 0 | 0 |
| review | 1 | 33 | 0 |
| blocked | 0 | 0 | 47 |

## Kalimat dengan prediksi berbeda dari label

- (review → allowed) Mengandung antioksidan tinggi yang baik untuk tubuh.
