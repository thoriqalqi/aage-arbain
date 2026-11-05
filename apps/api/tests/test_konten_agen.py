"""Content/Search Agent: data kosong, stok, produk nonaktif, pagar fakta LLM, skor audit, alamat internal, izin peran."""

import socket
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from aage import llm, settings_store
from aage.content import audit as audit_svc
from aage.content import studio
from aage.db import SessionLocal, init_db
from aage.models import Approval, ContentDraft, Product
from aage.seed import seed_base

KATALOG_B = Path(__file__).resolve().parents[1] / "eval" / "katalog" / "katalog_uji_b.xlsx"
TIPE = list(studio.FORMATS)
_KLIEN_ASLI = httpx.Client


def _isi_ulang() -> None:
    init_db(drop=True)
    with SessionLocal() as db:
        seed_base(db)
        settings_store.pasang_mode_data(db, "demo")


def _token(client, email: str, sandi: str) -> dict:
    return {"Authorization": f"Bearer {client.post('/api/auth/login', json={'email': email, 'password': sandi}).json()['token']}"}


@pytest.fixture(scope="module", autouse=True)
def katalog_b(seeded):
    """Katalog B memuat produk tanpa izin edar, tanpa komposisi, dan tanpa data stok."""
    from fastapi.testclient import TestClient

    from aage.main import app

    _isi_ulang()
    with TestClient(app) as c:
        admin = _token(c, "admin@aage.local", "admin123")
        token = c.post("/api/katalog/impor", headers=admin, files={"file": ("b.xlsx", KATALOG_B.read_bytes())}).json()["token"]
        assert c.post(f"/api/katalog/ganti/{token}", headers=admin, json={"mode": "nonaktif"}).status_code == 202
    yield
    _isi_ulang()


@pytest.fixture
def marketing(client):
    return _token(client, "marketing@aage.local", "marketing123")


@pytest.fixture
def admin(client):
    return _token(client, "admin@aage.local", "admin123")


def _produk(kondisi) -> int:
    with SessionLocal() as db:
        return next(p.id for p in db.scalars(select(Product).where(Product.aktif.is_(True)).order_by(Product.id)) if kondisi(p))


def _gen(client, h, pid, tipe="artikel", topik="kebutuhan apotek"):
    r = client.post("/api/content/generate", headers=h, json={"product_id": pid, "topik": topik, "target": "apotek", "tipe": tipe})
    assert r.status_code == 200, r.text
    return r.json()


def _hasil_llm(monkeypatch, data):
    monkeypatch.setattr(studio.llm, "complete", lambda *a, **k: llm.LLMResult(text="{}", model="stub", data=data))


@pytest.mark.parametrize("tipe", TIPE)
def test_data_kosong_dihilangkan_bukan_ditulis_rusak(client, marketing, tipe):
    d = _gen(client, marketing, _produk(lambda p: not p.no_izin_edar and not p.komposisi), tipe)
    teks = "\n".join([d["judul"], d["isi"], *[f["a"] for f in d["faq"]], *(d["meta"] or {}).values()])
    for rusak in ("nomor izin edarnya .", "izin edar .", "Izin edar .", "()", "mengandung .", "Komposisi: .", "**Komposisi:** .", "Izin Edar ", "None"):
        assert rusak not in teks, (rusak, teks)
    assert "izin edar" in d["claim_report"]["data_kosong"] and "komposisi" in d["claim_report"]["data_kosong"]
    if studio.FORMATS[tipe]["web"]:
        assert "additionalProperty" not in d["json_ld"][0]
        assert not any("izin edar" in f["q"].lower() for f in d["faq"])


def test_title_dipotong_di_batas_kata(client, marketing):
    d = _gen(client, marketing, _produk(lambda p: not p.no_izin_edar))
    assert len(d["meta"]["title"]) <= 60 and not d["meta"]["title"].endswith("Arb")
    assert len(d["meta"]["description"]) <= 155


def test_kategori_obat_tidak_disebut_bukan_obat(client, marketing):
    d = _gen(client, marketing, _produk(lambda p: "obat" in p.kategori.lower()))
    assert "bukan obat" not in d["isi"]


def test_stok_tidak_dikarang_di_json_ld(client, marketing):
    d = _gen(client, marketing, _produk(lambda p: p.stok is None))
    assert "availability" not in d["json_ld"][0]["offers"]


@pytest.mark.parametrize("stok,harap", [(None, None), (0, "https://schema.org/OutOfStock"), (7, "https://schema.org/InStock")])
def test_ketersediaan_mengikuti_stok(stok, harap):
    class Saringan:
        def boleh_produk(self, p, jenis):
            return True

    assert studio._ketersediaan(Saringan(), Product(stok=stok)) == harap


def test_stok_yang_tertahan_tidak_disebut():
    class Saringan:
        def boleh_produk(self, p, jenis):
            return False

    assert studio._ketersediaan(Saringan(), Product(stok=7)) is None


def test_alamat_situs_tidak_dikarang(client, marketing, monkeypatch):
    d = _gen(client, marketing, _produk(lambda p: True))
    assert "url" not in d["json_ld"][2] and "example.com" not in str(d["json_ld"])
    monkeypatch.setattr(studio.get_settings(), "situs_resmi", "https://arbain.test")
    assert _gen(client, marketing, _produk(lambda p: True))["json_ld"][2]["url"] == "https://arbain.test"


def test_produk_nonaktif_tidak_bisa_dibuatkan_konten(client, marketing):
    with SessionLocal() as db:
        pid = db.scalar(select(Product.id).where(Product.aktif.is_(False)))
    r = client.post("/api/content/generate", headers=marketing, json={"product_id": pid, "topik": "uji nonaktif", "target": "apotek", "tipe": "artikel"})
    assert r.status_code == 400 and "katalog aktif" in r.json()["detail"]


def test_konten_produk_yang_tidak_aktif_lagi_tidak_bisa_diajukan_disetujui_atau_diekspor(client, marketing, admin):
    pid = _produk(lambda p: p.no_izin_edar)
    draf, disetujui, belum = (_gen(client, marketing, pid)["id"] for _ in range(3))
    client.post(f"/api/content/{disetujui}/submit", headers=marketing)
    assert client.post(f"/api/content/{disetujui}/approve", headers=admin).status_code == 200
    with SessionLocal() as db:
        db.get(Product, pid).aktif = False
        db.commit()
    try:
        assert client.post(f"/api/content/{draf}/submit", headers=marketing).status_code == 422
        assert client.post(f"/api/content/{belum}/approve", headers=admin).status_code == 422
        r = client.get(f"/api/content/{disetujui}/export", headers=marketing)
        assert r.status_code == 422 and "katalog aktif" in r.json()["detail"]
    finally:
        with SessionLocal() as db:
            db.get(Product, pid).aktif = True
            db.commit()


def test_konten_yang_produknya_terhapus_tidak_bisa_diekspor(client, marketing):
    pid = _produk(lambda p: p.no_izin_edar)
    did = _gen(client, marketing, pid)["id"]
    with SessionLocal() as db:
        d = db.get(ContentDraft, did)
        d.status, d.product_id = "disetujui", None
        db.commit()
    assert client.get(f"/api/content/{did}/export", headers=marketing).status_code == 422


@pytest.mark.parametrize("tipe", TIPE)
def test_template_sendiri_lolos_pagar_fakta(db, tipe):
    """Pagar tidak boleh menolak kalimat baku kita. Bila menolak, draf LLM yang wajar akan selalu jatuh ke template."""
    for p in db.scalars(select(Product).where(Product.aktif.is_(True))):
        data = studio._template(db, p, "kebutuhan apotek", "apotek", tipe)
        assert studio.fakta_asing(studio._sumber_fakta(db, p, "kebutuhan apotek", "apotek"), data) == [], (p.nama, data)
    db.rollback()


@pytest.mark.parametrize("kalimat,harap", [
    ("Produk ini tersedia di 40 cabang.", "angka 40"),
    ("Tersedia di banyak cabang kami.", "kata 'cabang'"),
    ("Produk ini memakai bahan dari Swiss yang dipilih.", "nama 'Swiss'"),
    ("Sudah bersertifikat halal.", "kata 'halal'"),
    ("Diminum tiga kali sehari.", "kata 'sehari'"),
    ("Harga spesial Rp 99.000 per box.", "angka 99000"),
])
def test_fakta_karangan_llm_diganti_template(client, marketing, monkeypatch, kalimat, harap):
    pid = _produk(lambda p: p.no_izin_edar)
    _hasil_llm(monkeypatch, {"judul": "Judul aman", "isi": kalimat, "faq": [{"q": "Apa ini?", "a": "Produk grosir."}],
                             "meta": {"title": "Judul aman", "description": "Deskripsi aman."}})
    d = _gen(client, marketing, pid)
    assert d["claim_report"]["sumber_generator"].startswith("template")
    assert harap in d["claim_report"]["fakta_asing"]
    assert kalimat not in d["isi"]


def test_draf_llm_yang_sesuai_data_tetap_dipakai(client, marketing, monkeypatch):
    with SessionLocal() as db:
        p = db.get(Product, _produk(lambda p: p.no_izin_edar))
        nama, izin, moq, sat = p.nama, p.no_izin_edar, p.moq, p.satuan_grosir
    isi = f"{nama} memiliki izin edar {izin}. Minimum order {moq} {sat}."
    _hasil_llm(monkeypatch, {"judul": nama, "isi": isi, "faq": [{"q": f"Apa izin edar {nama}?", "a": izin}],
                             "meta": {"title": nama, "description": isi}})
    d = _gen(client, marketing, _produk(lambda p: p.nama == nama))
    assert d["claim_report"]["sumber_generator"] == "llm" and d["isi"] == isi and d["claim_report"]["fakta_asing"] == []


@pytest.mark.parametrize("data", [
    {"judul": "J", "isi": "Isi.", "faq": ["pertanyaan"], "meta": {"title": "t", "description": "d"}},
    {"judul": "J", "isi": "Isi.", "faq": [{"q": "tanya"}], "meta": {"title": "t", "description": "d"}},
    {"judul": "J", "isi": "Isi.", "faq": [{"q": "tanya", "a": "jawab"}], "meta": "bukan objek"},
    {"judul": 5, "isi": "Isi."},
    {"isi": "Isi."},
    ["bukan", "objek"],
])
def test_keluaran_llm_rusak_tidak_membuat_galat(client, marketing, monkeypatch, data):
    _hasil_llm(monkeypatch, data)
    d = _gen(client, marketing, _produk(lambda p: p.no_izin_edar))
    assert d["claim_report"]["sumber_generator"] == "template (keluaran LLM tidak sesuai format)" and d["faq"]


def test_meta_llm_kepanjangan_dipotong(client, marketing, monkeypatch):
    with SessionLocal() as db:
        nama = db.get(Product, _produk(lambda p: p.no_izin_edar)).nama
    _hasil_llm(monkeypatch, {"judul": f"{nama} " * 40, "isi": f"{nama}.", "faq": [{"q": f"Apa {nama}?", "a": nama}],
                             "meta": {"title": f"{nama} " * 30, "description": f"{nama} " * 60}})
    d = _gen(client, marketing, _produk(lambda p: p.nama == nama))
    assert d["claim_report"]["sumber_generator"] == "llm"
    assert len(d["meta"]["title"]) <= 60 and len(d["meta"]["description"]) <= 155 and len(d["judul"]) <= 200


def test_edit_faq_rusak_ditolak(client, marketing):
    did = _gen(client, marketing, _produk(lambda p: True))["id"]
    r = client.patch(f"/api/content/{did}", headers=marketing, json={"faq": [{"q": "tanya"}]})
    assert r.status_code == 409 and "FAQ" in r.json()["detail"]


def test_skor_audit_tidak_mengaku_struktur_sudah_diperbaiki(client, marketing):
    rep = client.post("/api/content/audit", headers=marketing, json={"contoh": True}).json()
    gagal = {c["label"] for c in rep["cek"] if c["status"] == "gagal" and c["id"] not in ("klaim", "statistik")}
    assert gagal and set(rep["perlu_perbaikan_struktur"]) == gagal
    bobot_teks = sum(c["bobot"] for c in rep["cek"] if c["id"] in ("klaim", "statistik"))
    assert rep["skor_sebelum"] <= rep["skor_sesudah"] <= bobot_teks < rep["skor_potensi"]
    if rep["kalimat_perlu_ditinjau"]:
        assert rep["skor_potensi"] < 100  # kalimat yang masih perlu ditinjau tidak dihitung lulus


@pytest.mark.parametrize("alamat", [
    "http://127.0.0.1:8000/health", "http://localhost/", "http://10.0.0.5/", "http://192.168.1.1/", "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/", "file:///etc/passwd", "ftp://contoh.test/", "http://pengguna:sandi@8.8.8.8/", "http://8.8.8.8:5432/",
])
def test_audit_menolak_alamat_internal(client, marketing, alamat):
    r = client.post("/api/content/audit", headers=marketing, json={"url": alamat})
    assert r.status_code == 400, r.text


def _dns_palsu(tabel):
    def jawab(host, port, *a, **k):
        if host not in tabel:
            raise socket.gaierror(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (tabel[host], port))]

    return jawab


def _klien_palsu(monkeypatch, tangani):
    monkeypatch.setattr(audit_svc.httpx, "Client", lambda **k: _KLIEN_ASLI(transport=httpx.MockTransport(tangani), **k))


def test_audit_menolak_alihan_ke_alamat_internal(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _dns_palsu({"situs.test": "8.8.8.8", "dalam.test": "10.0.0.5"}))
    _klien_palsu(monkeypatch, lambda req: httpx.Response(302, headers={"location": "http://dalam.test/rahasia"}))
    with pytest.raises(audit_svc.AlamatDitolak, match="alamat internal"):
        audit_svc._fetch("http://situs.test/")


def test_audit_menolak_nama_yang_mengarah_ke_alamat_internal(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _dns_palsu({"dalam.test": "127.0.0.1"}))
    with pytest.raises(audit_svc.AlamatDitolak, match="alamat internal"):
        audit_svc._fetch("http://dalam.test/")


def test_audit_membaca_situs_publik_dan_mengikuti_alihan(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _dns_palsu({"situs.test": "8.8.8.8"}))

    def tangani(req):
        if req.url.path == "/lama":
            return httpx.Response(301, headers={"location": "/baru"})
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text="<h1>Halo</h1>")

    _klien_palsu(monkeypatch, tangani)
    assert "<h1>Halo</h1>" in audit_svc._fetch("http://situs.test/lama")


def test_audit_menolak_isi_bukan_html_dan_terlalu_besar(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _dns_palsu({"situs.test": "8.8.8.8"}))
    _klien_palsu(monkeypatch, lambda req: httpx.Response(200, headers={"content-type": "application/json"}, text="{}"))
    with pytest.raises(audit_svc.AlamatDitolak, match="bukan halaman web"):
        audit_svc._fetch("http://situs.test/")
    _klien_palsu(monkeypatch, lambda req: httpx.Response(200, headers={"content-type": "text/html"}, content=b"x" * (audit_svc._MAKS_BYTE + 1)))
    with pytest.raises(audit_svc.AlamatDitolak, match="terlalu besar"):
        audit_svc._fetch("http://situs.test/")


def test_peran_penjualan_tidak_bisa_memakai_studio_konten(client, auth, marketing):
    pid = _produk(lambda p: True)
    did = _gen(client, marketing, pid)["id"]
    permintaan = [
        ("post", "/api/content/generate", {"product_id": pid, "topik": "uji peran", "target": "apotek", "tipe": "artikel"}),
        ("get", "/api/content", None), ("get", f"/api/content/{did}", None), ("patch", f"/api/content/{did}", {"judul": "x"}),
        ("post", "/api/content/recheck", {"teks": "halo"}), ("post", f"/api/content/{did}/submit", None), ("post", f"/api/content/{did}/arsip", None),
        ("post", f"/api/content/{did}/approve", None), ("get", f"/api/content/{did}/export", None), ("post", "/api/content/audit", {"contoh": True}),
        ("post", "/api/agents/content", {"produk": "Madu", "topik": "stamina"}),
    ]
    for metode, alamat, isi in permintaan:
        kw = {"json": isi} if isi is not None else {}
        assert getattr(client, metode)(alamat, headers=auth, **kw).status_code == 403, alamat


def test_approval_konten_tidak_terlihat_dan_tidak_bisa_diputus_peran_penjualan(client, auth, marketing, admin):
    did = _gen(client, marketing, _produk(lambda p: True))["id"]
    ap_id = client.post(f"/api/content/{did}/submit", headers=marketing).json()["approval_id"]
    assert ap_id not in [a["id"] for a in client.get("/api/approvals?status=menunggu", headers=auth).json()["items"]]
    assert client.post(f"/api/approvals/{ap_id}/decide", headers=auth, json={"aksi": "setujui"}).status_code == 403
    assert client.post(f"/api/approvals/{ap_id}/decide", headers=admin, json={"aksi": "setujui"}).status_code == 200
    with SessionLocal() as db:
        assert db.get(Approval, ap_id).status == "disetujui"
