"""Aturan ClaimGuard 2.2.0: kebocoran yang ditutup, jebakan penjualan yang harus tetap lolos, dan bot sama dengan Compliance."""

import csv
from collections import Counter

import pytest

from aage import claimguard
from aage.claimguard import registry
from eval.run_klaim import DATASET, HOLDOUT, baca_dataset
from src.compliance import ClaimGuardEngine

OBA = "ARB-001"


def _cek(db, teks):
    return claimguard.check(db, teks, use_llm=False)


@pytest.mark.parametrize("teks,verdict,aturan", [
    ("Asam lambung tidak akan kambuh lagi.", "blocked", "R22"),
    ("Membersihkan sumbatan pembuluh darah.", "blocked", "R22"),
    ("Bebas risiko untuk semua usia.", "blocked", "R21"),
    ("Tidak mungkin gagal.", "blocked", "R21"),
    ("Semua pemakai pasti merasakan manfaatnya.", "blocked", "R21"),
    ("Uang kembali bila tidak terasa manfaatnya.", "blocked", "R21"),
    ("Mengandung antioksidan tinggi yang baik untuk tubuh.", "review", "R23"),
    ("Sembilan dari sepuluh ibu puas dengan hasilnya.", "review", "R17"),
    ("Mayoritas pemakai merasakan perubahan dalam sepekan.", "review", "R17"),
    ("Sudah dipakai lebih dari 10.000 pasien.", "review", "R17"),
    ("Lebih murni dari madu di supermarket.", "review", "R11"),
    ("Tidak seperti produk lain yang penuh bahan kimia.", "review", "R11"),
    ("Konsumsi rutin setiap hari.", "review", "X02"),
    ("Kata pelanggan kami, keluhannya hilang dalam seminggu.", "review", "X03"),
    ("Membuat kulit tampak awet muda.", "blocked", "X01"),
    ("Sering dicari orang yang punya maag.", "review", "R05"),
])
def test_kebocoran_tertutup(db, teks, verdict, aturan):
    r = _cek(db, teks)
    assert r.verdict == verdict, r.rules_triggered
    assert aturan in r.rules_triggered


@pytest.mark.parametrize("teks", [
    "Uang kembali bila barang rusak saat pengiriman.",
    "Pesanan lebih dari 10 karton mendapat harga grosir.",
    "Harga ini lebih murah dari harga eceran.",
    "Stok tersedia lebih banyak dari bulan lalu.",
    "Pengiriman tanpa risiko kerusakan karena dikemas rapat.",
    "Tiga dari sepuluh varian sedang kosong.",
    "Harga Rp 2.880.000 per karton.",
    "Diskon 10 persen untuk pembelian 5 karton.",
])
def test_kalimat_penjualan_tetap_lolos(db, teks):
    r = _cek(db, teks)
    assert r.verdict == "allowed", r.rules_triggered


def test_peringatan_efek_samping_tidak_diblokir(db):
    r = _cek(db, "Efek samping yang mungkin: Rasa panas di lambung pada penderita maag.")
    assert r.verdict == "allowed", r.rules_triggered
    # Kalimat peringatan tidak boleh jadi celah klaim terapi.
    assert _cek(db, "Efek samping yang mungkin: maag sembuh total.").verdict == "blocked"


def test_titik_di_antara_angka_bukan_akhir_kalimat(db):
    teks = "Harga Rp 2.880.000 per karton. Simpan di tempat sejuk."
    r = _cek(db, teks)
    assert [s.text for s in r.sentences] == ["Harga Rp 2.880.000 per karton.", "Simpan di tempat sejuk."]
    assert all(teks[s.start:s.end] == s.text for s in r.sentences)


def test_semua_klaim_resmi_tetap_lolos(db):
    from sqlalchemy import select

    from aage.models import ApprovedClaim

    for c in db.scalars(select(ApprovedClaim)):
        r = claimguard.check(db, c.teks_klaim, use_llm=False, product_ids=[c.product_id])
        assert r.verdict == "allowed", (c.teks_klaim, r.rules_triggered)


def test_aturan_baru_tercatat_belum_ditinjau_dan_tidak_memutus_compliance(db):
    for rid in ("R21", "R22", "R23"):
        assert registry.rule(rid)["status_aturan"] == "BELUM_DITINJAU"
        assert not registry.is_decisive(rid, "Obat Bahan Alam")
    r = ClaimGuardEngine(db, None).verify_content(OBA, "Tidak mungkin gagal.")
    assert r.status == "NEED_REVIEW"
    assert [m.rule_id for m in r.matched_rules] == ["R21"]
    assert (r.matched_rules[0].kategori, r.matched_rules[0].risiko) == ("GUARANTEE", "HIGH")


def test_aturan_frasa_berlaku_sama_di_bot_dan_compliance(db):
    teks = "Konsumsi rutin setiap hari."
    assert "X02" in _cek(db, teks).rules_triggered
    assert [m.rule_id for m in ClaimGuardEngine(db, None).verify_content(OBA, teks).matched_rules] == ["X02"]
    # Aturan frasa tidak berlaku pada penafian.
    assert "X01" not in _cek(db, "Produk ini bukan untuk awet muda.").rules_triggered


def test_dataset_lama_hanya_dua_baris_lebih_ketat_dari_label(db):
    """Ekspektasi lama tidak diubah. X01 memblokir frasa awet muda, sedangkan label lama menulis review."""
    with open(DATASET.parent / "klaim_berlabel.csv", encoding="utf-8", newline="") as f:
        beda = {r["kalimat"]: (r["label"], _cek(db, r["kalimat"]).verdict) for r in csv.DictReader(f)
                if _cek(db, r["kalimat"]).verdict != r["label"]}
    assert beda == {"Membuat kulit awet muda.": ("review", "blocked"), "Rahasia awet muda para artis.": ("review", "blocked")}


def test_holdout_valid_dan_terpisah():
    holdout, utama = baca_dataset(HOLDOUT), baca_dataset(DATASET)
    assert not {b["kalimat"] for b in holdout} & {b["kalimat"] for b in utama}
    jumlah = Counter(b["keputusan"] != "PASS" for b in holdout)
    assert jumlah[True] == 30 and jumlah[False] == 15
    for b in holdout:
        assert (b["keputusan"] == "PASS") == (b["kategori"] in {"SUPPORTED_CLAIM", "SAFE_PRODUCT_DESCRIPTION"}), b["kalimat"]
