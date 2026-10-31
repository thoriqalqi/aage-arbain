"""Impor katalog Excel/CSV: validasi per baris, pratinjau tanpa efek, penerapan satu transaksi, dan data kosong yang
tidak dikarang agent. Setiap tes yang mengganti katalog memulihkan katalog simulasi sesudahnya."""

import csv
import io

import pytest
from sqlalchemy import select

from aage.agents.graph import handle_inbound
from aage.db import SessionLocal
from aage.kb import ingest, katalog_impor as k
from aage.models import Product

HEADER = [c.nama for c in k.KOLOM_PRODUK]


def _csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=HEADER)
    w.writeheader()
    for r in rows:
        w.writerow({h: r.get(h, "") for h in HEADER})
    return buf.getvalue().encode("utf-8")


BARU = [
    {"sku": "UJI-01", "nama": "Madu Klanceng Lereng 400 g", "harga_per_box": "Rp 1.500.000", "moq": "2", "stok": "9",
     "kemasan": "Botol 400 g; box isi 20 botol", "klaim_disetujui": "Membantu memelihara daya tahan tubuh",
     "izin_edar": "POM TR 999000001", "halal_status": "Bersertifikat Halal", "halal_nomor": "ID-UJI-1",
     "halal_lembaga": "BPJPH", "bko_hasil": "Negatif", "diskon_volume": "6:2|15:4"},
    {"sku": "UJI-02", "nama": "Kapsul Kunir Sehat 60", "harga_per_box": "800000", "klaim_disetujui": "Membantu menjaga kesehatan"},
]


@pytest.fixture
def pulihkan_katalog(seeded):
    with SessionLocal() as db:
        asli = k.ekspor_xlsx(db)
    yield
    with SessionLocal() as db:
        imp = k.buat_pratinjau(db, "pulihkan.xlsx", asli, "tes")
        k.terapkan(db, imp.token, "tes")


def _aktif(db) -> set[str]:
    return {p.nama for p in db.scalars(select(Product).where(Product.aktif.is_(True)))}


def test_templates_are_valid_imports(db):
    for nama, isi in (("t.xlsx", k.template_xlsx()), ("t.csv", k.template_csv())):
        produk, kebijakan = k.baca_file(nama, isi)
        valid, error, peringatan = k.validasi_produk(produk, db)
        assert len(valid) == 2 and error == []
        assert any(p["kolom"] == "halal_status" for p in peringatan)  # contoh baris kosong → peringatan, bukan error
    _, kebijakan = k.baca_file("t.xlsx", k.template_xlsx())
    valid_k, error_k = k.validasi_kebijakan(kebijakan)
    assert len(valid_k) == 5 and error_k == []


def test_row_errors_are_reported_with_row_column_reason(db):
    rows = [
        {"nama": "", "harga_per_box": "1000"},                                   # baris 2: nama kosong
        {"nama": "A Satu", "harga_per_box": "seribu"},                           # baris 3: harga bukan angka
        {"sku": "X-1", "nama": "A Dua", "harga_per_box": "1000"},
        {"sku": "X-1", "nama": "A Tiga", "harga_per_box": "1000"},               # baris 5: SKU ganda
        {"nama": "A Empat", "harga_per_box": "1000", "bko_hasil": "Positif"},    # baris 6: BKO positif
        {"nama": "A Lima", "harga_per_box": "1000", "diskon_volume": "10-3"},    # baris 7: format tier
        {"nama": "A Enam", "harga_per_box": "1000", "halal_nomor": "ID-1"},      # baris 8: nomor tanpa status
        {"nama": "A Tujuh", "harga_per_box": "1000", "stok": "-3"},              # baris 9: stok negatif
    ]
    valid, error, _ = k.validasi_produk(k.baca_file("x.csv", _csv(rows))[0], db)
    got = {(e["baris"], e["kolom"]) for e in error}
    assert got == {(2, "nama"), (3, "harga_per_box"), (5, "sku"), (6, "bko_hasil"), (7, "diskon_volume"),
                   (8, "halal_status"), (9, "stok")}
    assert [r["nama"] for r in valid] == ["A Dua"] and all(e["alasan"] for e in error)


def test_missing_required_column_and_bad_file(db):
    _, error, _ = k.validasi_produk(k.baca_file("x.csv", b"nama,kategori\nMadu,Herbal\n")[0], db)
    assert error[0]["kolom"] == "harga_per_box" and error[0]["baris"] == 1
    with pytest.raises(k.FileTidakValid):
        k.baca_file("katalog.pdf", b"%PDF")
    with pytest.raises(k.FileTidakValid):
        k.baca_file("rusak.xlsx", b"bukan excel")


def test_preview_changes_nothing_and_reports_diff(db):
    sebelum = _aktif(db)
    imp = k.buat_pratinjau(db, "baru.csv", _csv(BARU), "tes")
    r = imp.laporan["ringkasan"]
    assert (r["valid"], r["baru"], r["dinonaktifkan"], r["kebijakan"]) == (2, 2, len(sebelum), None)
    assert _aktif(db) == sebelum and imp.status == "pratinjau"


def test_apply_replaces_catalog_and_agent_uses_new_data(db, pulihkan_katalog):
    imp = k.buat_pratinjau(db, "baru.csv", _csv(BARU), "tes")
    hasil = k.terapkan(db, imp.token, "tes")
    assert hasil["produk"] == 2 and hasil["dinonaktifkan"] >= 50 and hasil["kebijakan_versi"] is None
    assert _aktif(db) == {"Madu Klanceng Lereng 400 g", "Kapsul Kunir Sehat 60"}

    ask = lambda t: handle_inbound(db, channel="webchat", external_user_id=f"t-impor-{abs(hash(t))}", text=t)  # noqa: E731
    assert "1.500.000" in ask("harga madu klanceng lereng berapa?").replies[0].teks
    lama = ask("brp hrg madu stamina perbox kak?")
    assert "belum ada di katalog" in lama.replies[0].teks and "2.340.000" not in lama.replies[0].teks
    stok = ask("stok kapsul kunir sehat ada?").replies[0].teks
    assert "Data stok belum ada" in stok and "Stok tercatat" not in stok
    halal = ask("kapsul kunir sehat halal ga?")
    assert halal.decision == "eskalasi" and "belum ada di katalog" in halal.replies[0].teks
    izin = ask("izin edar kapsul kunir sehat apa?")
    assert izin.decision == "eskalasi" and "belum ada datanya" in izin.replies[0].teks
    assert "mulai 6 box" in ask("kasih diskon dong").replies[0].teks


def test_errors_need_explicit_skip(db, pulihkan_katalog):
    imp = k.buat_pratinjau(db, "campur.csv", _csv(BARU + [{"nama": "Rusak", "harga_per_box": "x"}]), "tes")
    with pytest.raises(k.ImporDitolak, match="baris error"):
        k.terapkan(db, imp.token, "tes")
    assert k.terapkan(db, imp.token, "tes", lewati_error=True)["baris_dilewati"] == 1
    assert "Rusak" not in _aktif(db)


def test_failure_mid_apply_rolls_back_everything(db, monkeypatch):
    sebelum = _aktif(db)
    imp = k.buat_pratinjau(db, "baru.csv", _csv(BARU), "tes")

    def gagal(*a, **kw):
        raise RuntimeError("disk penuh")

    monkeypatch.setattr(ingest, "product_chunk_text", gagal)
    with pytest.raises(RuntimeError):
        k.terapkan(db, imp.token, "tes")
    with SessionLocal() as s2:
        assert _aktif(s2) == sebelum
        assert s2.scalar(select(k.KatalogImpor).where(k.KatalogImpor.token == imp.token)).status == "pratinjau"


def test_stale_preview_is_rejected(db, pulihkan_katalog):
    a = k.buat_pratinjau(db, "a.csv", _csv(BARU), "tes")
    b = k.buat_pratinjau(db, "b.csv", _csv(BARU[:1]), "tes")
    k.terapkan(db, a.token, "tes")
    with pytest.raises(k.ImporDitolak, match="berubah"):
        k.terapkan(db, b.token, "tes")
    with pytest.raises(k.ImporDitolak, match="sudah diterapkan"):
        k.terapkan(db, a.token, "tes")


def test_policy_sheet_replaces_policy(db, pulihkan_katalog):
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(k.template_xlsx()))
    ws = wb["Kebijakan"]
    for row in ws.iter_rows(min_row=2):
        if row[0].value == "pembayaran":
            row[1].value = "Pembayaran di muka melalui transfer bank atau QRIS. Tempo pembayaran 21 hari untuk pelanggan tetap."
    buf = io.BytesIO()
    wb.save(buf)
    imp = k.buat_pratinjau(db, "kebijakan.xlsx", buf.getvalue(), "tes")
    assert k.terapkan(db, imp.token, "tes")["kebijakan_versi"] is not None
    ask = lambda t: handle_inbound(db, channel="webchat", external_user_id=f"t-kebijakan-{abs(hash(t))}", text=t)  # noqa: E731
    assert "21 hari" in ask("bisa bayar tempo?").replies[0].teks
    qris = ask("bisa bayar pakai qris?")
    assert "QRIS" in qris.replies[0].teks and qris.decision == "kirim"  # disebut kebijakan → tidak dieskalasi
    assert ask("bisa COD?").decision == "eskalasi"                    # tidak disebut → staf


def test_api_requires_admin_and_flows(client, auth, pulihkan_katalog):
    files = {"file": ("baru.csv", _csv(BARU), "text/csv")}
    assert client.post("/api/katalog/impor", files=files, headers=auth).status_code == 403  # staf bukan admin
    admin = {"Authorization": "Bearer " + client.post("/api/auth/login", json={
        "email": "admin@aage.local", "password": "admin123"}).json()["token"]}
    r = client.post("/api/katalog/impor", files=files, headers=admin)
    assert r.status_code == 200 and r.json()["laporan"]["ringkasan"]["valid"] == 2
    token = r.json()["token"]
    assert client.post(f"/api/katalog/impor/{token}/terapkan", json={}, headers=admin).json()["produk"] == 2
    assert client.post(f"/api/katalog/impor/{token}/terapkan", json={}, headers=admin).status_code == 409
    assert client.get("/api/katalog/template.xlsx").status_code == 200
    assert client.get("/api/katalog/ekspor.xlsx", headers=admin).status_code == 200
    bad = client.post("/api/katalog/impor", files={"file": ("x.pdf", b"%PDF", "application/pdf")}, headers=admin)
    assert bad.status_code == 400
