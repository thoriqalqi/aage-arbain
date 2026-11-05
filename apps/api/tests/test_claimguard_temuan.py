"""ClaimGuard Tahap 1: kategori, tingkat risiko, temuan terstruktur, versi aturan, dan metrik dataset kategori."""

import csv
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select

from aage import claimguard, ledger_chain, llm
from aage.claimguard import registry
from aage.claimguard import service as cg
from aage.claimguard.rules import RULES
from aage.models import LedgerEvent
from eval.metrik_klaim import biner, macro_f1, per_kategori
from eval.run_klaim import DATASET, baca_dataset, nilai, prediksi_kategori

KATEGORI = {"SUPPORTED_CLAIM", "SAFE_PRODUCT_DESCRIPTION", "UNSUPPORTED_CLAIM", "THERAPEUTIC_CLAIM", "GUARANTEE",
            "STATISTICAL_CLAIM", "COMPARATIVE_CLAIM", "UNCERTAIN_CLAIM"}


def _periksa(db, teks, **kw):
    return claimguard.check(db, teks, use_llm=False, **kw)


def test_semua_aturan_terdaftar_punya_kategori_dan_risiko_valid():
    reg = registry.load()
    assert set(reg["kategori_klaim"]) == KATEGORI
    assert reg["tingkat_risiko"] == ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    for rid, r in reg["rules"].items():
        assert r["kategori"] in KATEGORI - {"SUPPORTED_CLAIM", "SAFE_PRODUCT_DESCRIPTION"}, rid
        assert r["risiko"] in reg["tingkat_risiko"], rid
    # Aturan di kode tidak boleh jatuh diam-diam ke kategori cadangan.
    assert {r.id for r in RULES} | {"R17", "R20", "KLAIM_TIDAK_TERDAFTAR"} <= set(reg["rules"])


def test_aturan_tak_terdaftar_jatuh_ke_perlu_dinilai_manusia():
    assert registry.klasifikasi("R99") == ("UNCERTAIN_CLAIM", "MEDIUM")


@pytest.mark.parametrize("teks,kategori,risiko,keputusan,aturan", [
    ("Menyembuhkan diabetes.", "THERAPEUTIC_CLAIM", "HIGH", "BLOCK", "R01"),
    ("Bisa menggantikan obat dari dokter.", "THERAPEUTIC_CLAIM", "CRITICAL", "BLOCK", "R12"),
    ("Tanpa efek samping sama sekali.", "GUARANTEE", "HIGH", "BLOCK", "R08"),
    ("Lebih bagus dari merek lain untuk menjaga stamina.", "COMPARATIVE_CLAIM", "HIGH", "NEEDS_REVIEW", "R11"),
    ("87% pelanggan merasa lebih bugar setelah dua minggu.", "STATISTICAL_CLAIM", "MEDIUM", "NEEDS_REVIEW", "R17"),
    ("Membantu meningkatkan kesuburan.", "UNSUPPORTED_CLAIM", "MEDIUM", "NEEDS_REVIEW", "KLAIM_TIDAK_TERDAFTAR"),
])
def test_kategori_risiko_dan_temuan_per_contoh(db, teks, kategori, risiko, keputusan, aturan):
    r = _periksa(db, teks)
    assert r.keputusan == keputusan
    assert r.sentences[0].kategori == kategori
    assert r.sentences[0].risiko == risiko
    temuan = next(t for t in r.temuan if t.rule_id == aturan)
    assert temuan.claim_type == kategori
    assert temuan.severity == risiko
    assert temuan.decision == keputusan
    assert temuan.reason
    assert temuan.evidence_gap
    assert temuan.suggested_correction


def test_kalimat_aman_tanpa_temuan(db):
    terdukung = _periksa(db, "Membantu menghangatkan tubuh.")
    assert (terdukung.keputusan, terdukung.sentences[0].kategori, terdukung.sentences[0].risiko) == ("PASS", "SUPPORTED_CLAIM", "LOW")
    assert terdukung.temuan == []
    deskripsi = _periksa(db, "Simpan di tempat sejuk dan kering.")
    assert (deskripsi.keputusan, deskripsi.sentences[0].kategori) == ("PASS", "SAFE_PRODUCT_DESCRIPTION")
    assert deskripsi.temuan == []


def test_rentang_temuan_menunjuk_teks_asli(db):
    teks = "Simpan di tempat sejuk. Produk ini MENYEMBUHKAN diabetes."
    r = _periksa(db, teks)
    t = next(x for x in r.temuan if x.rule_id == "R01")
    assert t.matched_text.lower() == "menyembuhkan"
    assert teks[t.start:t.end] == t.matched_text
    tanpa_aturan = _periksa(db, "Lalu membantu meningkatkan kesuburan.").temuan[0]
    assert tanpa_aturan.matched_text == "Lalu membantu meningkatkan kesuburan."
    assert (tanpa_aturan.start, tanpa_aturan.end) == (0, len(tanpa_aturan.matched_text))


def test_nama_produk_tersamar_tidak_merusak_rentang(db):
    from aage.models import Product

    nama = db.scalars(select(Product.nama)).first()
    teks = f"{nama} menyembuhkan diabetes."
    t = next(x for x in _periksa(db, teks).temuan if x.rule_id == "R01")
    assert teks[t.start:t.end].lower() == "menyembuhkan"


def test_keputusan_mengikuti_verdict_lama(db):
    """Klasifikasi hanya label di atas verdict. Kecocokan verdict dengan label emas diukur eval, bukan dipatok di sini."""
    with open(Path(DATASET).parent / "klaim_berlabel.csv", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            r = _periksa(db, row["kalimat"])
            assert r.keputusan == cg.KEPUTUSAN[r.verdict]
            assert r.label == cg.LABELS[r.verdict]
            for s in r.sentences:
                assert s.keputusan == cg.KEPUTUSAN[s.verdict]


def test_kegagalan_llm_tidak_menjadi_pass(db):
    with patch.object(llm, "complete", return_value=None):
        r = claimguard.check(db, "Membantu meningkatkan kesuburan.", use_llm=True)
    assert r.keputusan == "NEEDS_REVIEW"
    assert r.temuan[0].rule_id == "KLAIM_TIDAK_TERDAFTAR"


def test_llm_memblokir_tanpa_aturan_tetap_ada_temuan_tinggi(db):
    jawab = llm.LLMResult(text="", model="uji", data={"verdict": "blocked", "reasons": ["Klaim berbahaya."]})
    with patch.object(llm, "complete", return_value=jawab):
        r = claimguard.check(db, "Membantu meningkatkan kesuburan.", use_llm=True)
    assert r.keputusan == "BLOCK"
    assert (r.temuan[0].claim_type, r.temuan[0].severity, r.temuan[0].decision) == ("UNSUPPORTED_CLAIM", "HIGH", "BLOCK")


def test_llm_meloloskan_klaim_tanpa_padanan_tetap_kategori_ragu(db):
    jawab = llm.LLMResult(text="", model="uji", data={"verdict": "allowed", "reasons": []})
    with patch.object(llm, "complete", return_value=jawab):
        r = claimguard.check(db, "Membantu meningkatkan kesuburan.", use_llm=True)
    assert r.keputusan == "PASS"
    assert r.sentences[0].kategori == "UNCERTAIN_CLAIM"
    assert r.temuan == []


def test_to_dict_memuat_temuan_dan_versi(db):
    d = _periksa(db, "Menyembuhkan diabetes.").to_dict()
    assert d["rules_version"] == registry.rules_version() == "2.2.0"
    assert d["keputusan"] == "BLOCK"
    assert set(d["temuan"][0]) == {"finding_id", "matched_text", "start", "end", "claim_type", "severity", "rule_id", "reason",
                                   "evidence_gap", "suggested_correction", "decision"}
    assert d["temuan"][0]["finding_id"] == "F1"


def _terakhir(db, tipe):
    db.expire_all()
    return db.scalars(select(LedgerEvent).where(LedgerEvent.tipe_event == tipe).order_by(LedgerEvent.id.desc())).first()


@pytest.fixture
def marketing(client):
    tok = client.post("/api/auth/login", json={"email": "marketing@aage.local", "password": "marketing123"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def admin(client):
    tok = client.post("/api/auth/login", json={"email": "admin@aage.local", "password": "admin123"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _draf(client, h):
    r = client.post("/api/content/generate", headers=h,
                    json={"product_id": 1, "topik": "stamina saat musim hujan", "target": "apotek", "tipe": "caption_ig"})
    assert r.status_code == 200, r.text
    return r.json()


def test_versi_aturan_di_playground(client, admin, db):
    r = client.post("/api/claimguard/check", json={"text": "Menyembuhkan diabetes.", "use_llm": False}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["rules_version"] == "2.2.0"
    assert r.json()["temuan"][0]["rule_id"] == "R01"
    assert _terakhir(db, "claimguard_playground").data["versi_aturan"] == "2.2.0"


def test_versi_aturan_di_percakapan_dan_rantai_utuh(db):
    from aage.agents.graph import handle_inbound

    handle_inbound(db, channel="webchat", external_user_id="uji-temuan-1", text="berapa harga madu?")
    assert _terakhir(db, "claimguard").data["versi_aturan"] == "2.2.0"
    assert ledger_chain.verify(db)["utuh"]


def test_versi_aturan_dan_temuan_di_draf_konten(client, marketing, admin, db):
    d = _draf(client, marketing)
    assert d["claim_report"]["rules_version"] == "2.2.0"
    assert "temuan" in d["claim_report"]
    assert _terakhir(db, "konten_dibuat").data["versi_aturan"] == "2.2.0"

    r = client.patch(f"/api/content/{d['id']}", headers=marketing, json={"isi": d["isi"] + " Madu ini menyembuhkan diabetes."})
    assert r.status_code == 200
    assert any(t["rule_id"] == "R01" for t in r.json()["claim_report"]["temuan"])
    assert _terakhir(db, "konten_diedit").data["versi_aturan"] == "2.2.0"


def test_versi_aturan_di_audit_halaman(client, marketing, db):
    assert client.post("/api/content/audit", headers=marketing, json={"contoh": True}).status_code == 200
    data = _terakhir(db, "audit_halaman").data
    assert data["versi_aturan"] == "2.2.0"


def test_draf_lama_tanpa_versi_diperiksa_ulang_saat_disetujui(client, marketing, admin, db):
    from aage.models import ContentDraft

    d = _draf(client, marketing)
    assert client.post(f"/api/content/{d['id']}/submit", headers=marketing).status_code == 200
    baris = db.get(ContentDraft, d["id"])
    baris.claim_report = {k: v for k, v in baris.claim_report.items() if k not in {"rules_version", "temuan", "keputusan"}}
    db.commit()
    r = client.post(f"/api/content/{d['id']}/approve", headers=admin)
    assert r.status_code == 200, r.text
    assert _terakhir(db, "konten_disetujui").data["versi_aturan"] == "2.2.0"
    assert ledger_chain.verify(db)["utuh"]


# --- dataset dan metrik -----------------------------------------------------


def test_dataset_kategori_valid():
    baris = baca_dataset()
    assert {"kalimat", "kategori", "keputusan", "catatan"} == set(baris[0])
    assert len({b["kalimat"] for b in baris}) == len(baris)
    jumlah = Counter(b["kategori"] for b in baris)
    assert set(jumlah) == KATEGORI
    assert all(n >= 12 for n in jumlah.values())
    for b in baris:
        assert b["keputusan"] in {"PASS", "NEEDS_REVIEW", "BLOCK"}
        assert (b["keputusan"] == "PASS") == (b["kategori"] in {"SUPPORTED_CLAIM", "SAFE_PRODUCT_DESCRIPTION"}), b["kalimat"]


def test_dataset_lama_tidak_berubah():
    with open(Path(DATASET).parent / "klaim_berlabel.csv", encoding="utf-8", newline="") as f:
        assert Counter(r["label"] for r in csv.DictReader(f)) == {"allowed": 47, "blocked": 47, "review": 34}


def test_metrik_dengan_angka_diketahui():
    assert biner(tp=8, fp=2, fn=2, tn=8) == {"f1": 80.0, "false_positive_rate": 20.0, "false_negative_rate": 20.0}
    assert biner(0, 0, 0, 0) == {"f1": 0.0, "false_positive_rate": 0.0, "false_negative_rate": 0.0}
    k = per_kategori([("A", "A"), ("A", "B"), ("B", "B"), ("B", "B")])
    assert k["A"] == {"n": 2, "precision": 100.0, "recall": 50.0, "f1": 66.7}
    assert k["B"] == {"n": 2, "precision": 66.7, "recall": 100.0, "f1": 80.0}
    assert macro_f1(k) == 73.3
    # Kategori yang hanya muncul di prediksi tidak ikut rata-rata.
    assert macro_f1(per_kategori([("A", "A"), ("A", "B")])) == 66.7


def test_nilai_memisahkan_positif_palsu_dan_kebocoran():
    b = lambda kal, k, p_k, kep, p_kep: {"kalimat": kal, "kategori": k, "prediksi_kategori": p_k, "keputusan": kep, "prediksi_keputusan": p_kep}  # noqa: E731
    r = nilai([
        b("a", "SUPPORTED_CLAIM", "SUPPORTED_CLAIM", "PASS", "PASS"),
        b("b", "SAFE_PRODUCT_DESCRIPTION", "UNCERTAIN_CLAIM", "PASS", "NEEDS_REVIEW"),
        b("c", "THERAPEUTIC_CLAIM", "SAFE_PRODUCT_DESCRIPTION", "BLOCK", "PASS"),
        b("d", "UNSUPPORTED_CLAIM", "UNSUPPORTED_CLAIM", "NEEDS_REVIEW", "NEEDS_REVIEW"),
    ])
    assert r["false_positive_rate"] == 50.0
    assert r["false_negative_rate"] == 50.0
    assert r["unsupported_claim_recall"] == 100.0
    assert r["blok_lolos"] == 1
    assert r["lolos_berisiko"] == ["c"]
    assert r["aman_tertahan"] == ["b"]
    assert r["akurasi_keputusan"] == 50.0


def test_prediksi_kategori_memakai_kalimat_terberat():
    assert prediksi_kategori([
        {"keputusan": "PASS", "risiko": "LOW", "kategori": "SAFE_PRODUCT_DESCRIPTION"},
        {"keputusan": "BLOCK", "risiko": "HIGH", "kategori": "GUARANTEE"},
        {"keputusan": "NEEDS_REVIEW", "risiko": "HIGH", "kategori": "COMPARATIVE_CLAIM"},
    ]) == "GUARANTEE"


def test_runner_berjalan_di_semua_baris(db):
    from eval.run_klaim import jalankan

    baris = jalankan(db)
    assert len(baris) == len(baca_dataset())
    assert all(b["prediksi_kategori"] in KATEGORI and b["versi_aturan"] == "2.2.0" for b in baris)
