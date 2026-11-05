"""Content/Search Agent tahap 2: referensi sumber, versi draf, kata kunci, internal link, canonical dan robots."""

import httpx
import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select

from aage import clock, llm, settings_store
from aage.config import get_settings
from aage.content import audit as audit_svc
from aage.content import studio
from aage.db import SessionLocal, init_db
from aage.kb import retriever, verifikasi
from aage.models import Chunk, ContentDraft, ContentVersion, Document, LedgerEvent, Product, VerifikasiFakta
from aage.seed import seed_base

_KLIEN_ASLI = httpx.Client


def _token(client, email: str, sandi: str) -> dict:
    return {"Authorization": f"Bearer {client.post('/api/auth/login', json={'email': email, 'password': sandi}).json()['token']}"}


@pytest.fixture
def marketing(client):
    return _token(client, "marketing@aage.local", "marketing123")


@pytest.fixture
def admin(client):
    return _token(client, "admin@aage.local", "admin123")


@pytest.fixture
def staf(client):
    return _token(client, "staf@aage.local", "staf123")


def _isi_ulang() -> None:
    init_db(drop=True)
    with SessionLocal() as db:
        seed_base(db)
        settings_store.pasang_mode_data(db, "demo")


@pytest.fixture(scope="module", autouse=True)
def bersihkan(seeded):
    """Dokumen buatan tes tidak boleh terbawa ke retriever tes lain."""
    _isi_ulang()
    yield
    _isi_ulang()


@pytest.fixture(scope="module")
def pid(bersihkan) -> int:
    with SessionLocal() as db:
        return db.scalar(select(Product.id).where(Product.aktif.is_(True), Product.komposisi != "", Product.harga_dasar.is_not(None)).order_by(Product.id))


def _gen(client, h, pid, tipe="artikel", topik="kebutuhan apotek"):
    r = client.post("/api/content/generate", headers=h, json={"product_id": pid, "topik": topik, "target": "apotek", "tipe": tipe})
    assert r.status_code == 200, r.text
    return r.json()


def _versi(client, h, did):
    return client.get(f"/api/content/{did}/versi", headers=h).json()["items"]


# ------------------------------------------------------------------ versi


def test_draf_baru_punya_versi_pertama_dan_edit_menambah_versi(client, marketing, pid):
    d = _gen(client, marketing, pid)
    assert [v["nomor"] for v in _versi(client, marketing, d["id"])] == [1]
    assert client.patch(f"/api/content/{d['id']}", headers=marketing, json={"isi": d["isi"] + "\n\nTambahan."}).status_code == 200
    v = _versi(client, marketing, d["id"])
    assert [(x["nomor"], x["perubahan"]) for x in v] == [(2, "diedit"), (1, "dibuat")]
    assert v[0]["aktor"].startswith("staf:")


def test_simpan_tanpa_perubahan_tidak_menambah_versi(client, marketing, pid):
    d = _gen(client, marketing, pid)
    assert client.patch(f"/api/content/{d['id']}", headers=marketing, json={"judul": d["judul"], "isi": d["isi"]}).status_code == 200
    assert len(_versi(client, marketing, d["id"])) == 1


def test_draf_lama_tanpa_riwayat_isinya_disimpan_sebelum_diedit(client, marketing, pid):
    with SessionLocal() as db:
        d = ContentDraft(product_id=pid, tipe="artikel", topik="lama", judul="Judul lama", isi="Isi lama", faq=[], meta={}, json_ld=[], claim_report={})
        db.add(d)
        db.commit()
        did = d.id
    assert _versi(client, marketing, did) == []
    assert client.patch(f"/api/content/{did}", headers=marketing, json={"isi": "Isi baru"}).status_code == 200
    v = _versi(client, marketing, did)
    assert [(x["nomor"], x["perubahan"]) for x in v] == [(2, "diedit"), (1, "sebelum_riwayat")]
    assert "Isi lama" in client.get(f"/api/content/{did}/versi/1", headers=marketing).json()["isi"]


def test_perbedaan_versi_menunjukkan_yang_berubah(client, marketing, pid):
    d = _gen(client, marketing, pid)
    client.patch(f"/api/content/{d['id']}", headers=marketing, json={"judul": "Judul baru sekali"})
    beda = client.get(f"/api/content/{d['id']}/versi/1", headers=marketing).json()["beda"]
    assert {"jenis": "tambah", "teks": "Judul: Judul baru sekali"} in beda
    assert {"jenis": "hapus", "teks": f"Judul: {d['judul']}"} in beda
    assert client.get(f"/api/content/{d['id']}/versi/99", headers=marketing).status_code == 404


def test_pulihkan_menjadi_versi_baru_dan_riwayat_tetap_ada(client, marketing, pid):
    d = _gen(client, marketing, pid)
    client.patch(f"/api/content/{d['id']}", headers=marketing, json={"isi": "Isi pengganti."})
    r = client.post(f"/api/content/{d['id']}/versi/1/pulihkan", headers=marketing)
    assert r.status_code == 200 and r.json()["isi"] == d["isi"]
    assert r.json()["claim_report"]["referensi"], "sumber versi lama ikut kembali"
    assert [(x["nomor"], x["perubahan"]) for x in _versi(client, marketing, d["id"])] == [(3, "dipulihkan"), (2, "diedit"), (1, "dibuat")]
    with SessionLocal() as db:
        e = db.scalars(select(LedgerEvent).where(LedgerEvent.objek_ref == f"content:{d['id']}", LedgerEvent.tipe_event == "konten_diedit")
                       .order_by(LedgerEvent.id.desc())).first()
        assert e.data["dipulihkan_dari"] == 1 and e.data["versi"] == 3


def test_pulihkan_membatalkan_persetujuan_dan_pemulih_tidak_boleh_menyetujui(client, marketing, admin, pid):
    d = _gen(client, marketing, pid)
    client.patch(f"/api/content/{d['id']}", headers=marketing, json={"isi": d["isi"] + "\n\nTambahan."})
    assert client.post(f"/api/content/{d['id']}/submit", headers=marketing).status_code == 200
    assert client.post(f"/api/content/{d['id']}/approve", headers=admin).status_code == 200
    r = client.post(f"/api/content/{d['id']}/versi/1/pulihkan", headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "draf"
    assert client.get(f"/api/content/{d['id']}/export", headers=admin).status_code == 422
    assert client.post(f"/api/content/{d['id']}/submit", headers=admin).status_code == 200
    assert client.post(f"/api/content/{d['id']}/approve", headers=admin).status_code == 422, "aturan dua orang berlaku untuk pemulih"


def test_pulihkan_diperiksa_ulang_claimguard(client, marketing, pid):
    d = _gen(client, marketing, pid)
    client.patch(f"/api/content/{d['id']}", headers=marketing, json={"isi": "Produk ini terbukti menyembuhkan diabetes dalam 7 hari."})
    client.patch(f"/api/content/{d['id']}", headers=marketing, json={"isi": d["isi"]})
    r = client.post(f"/api/content/{d['id']}/versi/2/pulihkan", headers=marketing)
    assert r.status_code == 200 and r.json()["claim_verdict"] == "blocked"
    assert client.post(f"/api/content/{d['id']}/submit", headers=marketing).status_code == 422


def test_pulihkan_ditolak_saat_menunggu_approval_sama_atau_tidak_ada(client, marketing, pid):
    d = _gen(client, marketing, pid)
    assert client.post(f"/api/content/{d['id']}/versi/1/pulihkan", headers=marketing).status_code == 409, "isinya masih sama"
    assert client.post(f"/api/content/{d['id']}/versi/7/pulihkan", headers=marketing).status_code == 409
    client.patch(f"/api/content/{d['id']}", headers=marketing, json={"isi": d["isi"] + "\n\nTambahan."})
    client.post(f"/api/content/{d['id']}/submit", headers=marketing)
    assert client.post(f"/api/content/{d['id']}/versi/1/pulihkan", headers=marketing).status_code == 409
    with SessionLocal() as db:
        assert db.get(ContentDraft, d["id"]).status == "menunggu_approval"


def test_baris_versi_tidak_berubah_saat_draf_diedit(client, marketing, pid):
    d = _gen(client, marketing, pid)
    client.patch(f"/api/content/{d['id']}", headers=marketing, json={"isi": "Isi kedua."})
    with SessionLocal() as db:
        v1 = db.scalar(select(ContentVersion).where(ContentVersion.content_id == d["id"], ContentVersion.nomor == 1))
        assert v1.isi == d["isi"] and v1.judul == d["judul"]


@pytest.mark.parametrize("metode,akhir", [("get", "seo"), ("get", "versi"), ("get", "versi/1"), ("post", "versi/1/pulihkan")])
def test_staf_tidak_bisa_memakai_riwayat_dan_seo(client, marketing, staf, pid, metode, akhir):
    d = _gen(client, marketing, pid)
    assert getattr(client, metode)(f"/api/content/{d['id']}/{akhir}", headers=staf).status_code == 403


# ------------------------------------------------------------------ referensi


def _hasil_llm(monkeypatch, data, tangkap=None):
    def jawab(pesan, **k):
        if tangkap is not None:
            tangkap.append(pesan[0]["content"])
        return llm.LLMResult(text="{}", model="stub", data=data)

    monkeypatch.setattr(studio.llm, "complete", jawab)


def _dokumen(db, judul, teks, product_id=None, tipe="teks", status="simulasi") -> int:
    doc = Document(judul=judul, tipe=tipe)
    db.add(doc)
    db.flush()
    db.add(Chunk(document_id=doc.id, product_id=product_id, teks=teks, embedding=llm.embed(teks)))
    db.add(VerifikasiFakta(objek_tipe="dokumen", objek_id=doc.id, jenis_fakta="dokumen", status_verifikasi=status, diubah_oleh="tes", diubah_pada=clock.now()))
    db.commit()
    return doc.id


def test_template_mencatat_sumber_katalog_dan_klaim(client, marketing, pid):
    d = _gen(client, marketing, pid, tipe="caption_ig")
    rujukan = d["claim_report"]["referensi"]
    assert rujukan[0]["jenis"] == "katalog" and rujukan[0]["product_id"] == pid and "identitas" in rujukan[0]["fakta"]
    assert all(r["status"] for r in rujukan)
    with SessionLocal() as db:
        klaim = len(db.get(Product, pid).claims)
    assert sum(r["jenis"] == "klaim" for r in rujukan) == klaim


def test_template_tidak_mengaku_memakai_cuplikan_yang_tidak_dipakai(client, marketing, pid):
    with SessionLocal() as db:
        _dokumen(db, "Panduan tak terpakai", "Panduan khusus kebutuhan apotek yang tidak dipakai template.")
    rujukan = _gen(client, marketing, pid)["claim_report"]["referensi"]
    assert "Panduan tak terpakai" not in [r["judul"] for r in rujukan]


def test_cuplikan_hanya_dokumen_umum_atau_milik_produk_dan_yang_boleh_dikutip():
    with SessionLocal() as db:
        ids = sorted(db.scalars(select(Product.id).where(Product.aktif.is_(True))))
        p, lain = db.get(Product, ids[0]), ids[1]
        topik = "ketentuan retur grosir zeta"
        _dokumen(db, "Umum lolos", f"Dokumen {topik} untuk semua produk.")
        _dokumen(db, "Milik produk", f"Dokumen {topik} khusus produk ini.", product_id=p.id)
        _dokumen(db, "Milik produk lain", f"Dokumen {topik} khusus produk lain.", product_id=lain)
        _dokumen(db, "Belum diverifikasi", f"Dokumen {topik} yang belum diverifikasi.", status="belum_diverifikasi")
        judul = {h.chunk.document.judul for h in retriever.retrieve(db, f"{topik} {p.nama}", k=20, product_ids=[p.id], dokumen_saja=True, min_score=0)}
        assert {"Umum lolos", "Milik produk"} <= judul and "Milik produk lain" not in judul and "Belum diverifikasi" not in judul
        tipe = {h.chunk.document.tipe for h in retriever.retrieve(db, p.nama, k=20, product_ids=[p.id], dokumen_saja=True, min_score=0)}
        assert "katalog" not in tipe
        hits = studio._cari_dokumen(db, p, topik)
        assert hits and all(h.chunk.product_id in (None, p.id) for h in hits) and len(hits) <= studio.MAKS_CUPLIKAN


def test_llm_menerima_cuplikan_dan_sumbernya_tercatat(client, marketing, monkeypatch, pid):
    topik = "syarat retur grosir eta"
    with SessionLocal() as db:
        _dokumen(db, "Kebijakan retur eta", f"Dokumen {topik}: retur diterima paling lambat 14 hari sejak barang diterima.")
    tangkap = []
    _hasil_llm(monkeypatch, {"judul": "Syarat retur", "isi": "Retur diterima paling lambat 14 hari sejak barang diterima."}, tangkap)
    d = _gen(client, marketing, pid, tipe="caption_ig", topik=topik)
    assert d["claim_report"]["sumber_generator"] == "llm" and d["claim_report"]["fakta_asing"] == []
    assert "Kebijakan retur eta" in tangkap[0] and "14 hari" in tangkap[0]
    dok = [r for r in d["claim_report"]["referensi"] if r["jenis"] == "dokumen"]
    assert "Kebijakan retur eta" in [r["judul"] for r in dok] and all(r["chunk_id"] and r["kutipan"] for r in dok)
    with SessionLocal() as db:
        e = db.scalar(select(LedgerEvent).where(LedgerEvent.objek_ref == f"content:{d['id']}", LedgerEvent.tipe_event == "konten_dibuat"))
        assert "Kebijakan retur eta" in [s["judul"] for s in e.sumber_ref]


def test_fakta_yang_tidak_ada_di_dokumen_tetap_ditolak(client, marketing, monkeypatch, pid):
    with SessionLocal() as db:
        _dokumen(db, "Kebijakan retur theta", "Dokumen syarat retur grosir theta: retur diterima paling lambat 14 hari.")
    _hasil_llm(monkeypatch, {"judul": "Syarat retur", "isi": "Retur diterima paling lambat 30 hari di 40 cabang."})
    d = _gen(client, marketing, pid, tipe="caption_ig", topik="syarat retur grosir theta")
    laporan = d["claim_report"]
    assert laporan["sumber_generator"].startswith("template") and laporan["fakta_asing"]
    assert "Kebijakan retur theta" not in [r["judul"] for r in laporan["referensi"]], "template tidak memakai cuplikan itu"


def test_sumber_bertahan_setelah_edit(client, marketing, pid):
    d = _gen(client, marketing, pid)
    r = client.patch(f"/api/content/{d['id']}", headers=marketing, json={"isi": "Isi baru."}).json()
    assert r["claim_report"]["referensi"] == d["claim_report"]["referensi"]


# ------------------------------------------------------------------ kata kunci dan tautan


def _seo(client, h, did):
    return client.get(f"/api/content/{did}/seo", headers=h).json()


def _hasil(seo, cid):
    return next(c for c in seo["cek"] if c["id"] == cid)


def test_artikel_template_memuat_kata_kunci_di_tempat_penting(client, marketing, pid):
    d = _gen(client, marketing, pid, topik="stamina saat musim hujan")
    seo = _seo(client, marketing, d["id"])
    for cid in ("kunci_judul", "kunci_deskripsi", "kunci_paragraf", "kunci_heading"):
        assert _hasil(seo, cid)["lulus"], cid
    assert len(d["meta"]["title"]) <= studio.MAKS_TITLE and len(d["meta"]["description"]) <= studio.MAKS_DESKRIPSI


def test_panjang_artikel_template_dilaporkan_apa_adanya(client, marketing, pid):
    c = _hasil(_seo(client, marketing, _gen(client, marketing, pid, topik="panjang template")["id"]), "panjang")
    assert "kata" in c["detail"] and c["lulus"] is False and "Jangan mengisi" in c["saran"]


def test_kata_kunci_yang_hilang_dan_penjejalan_dilaporkan(client, marketing, pid):
    d = _gen(client, marketing, pid, topik="madu grosir kappa")
    client.patch(f"/api/content/{d['id']}", headers=marketing, json={"judul": "Judul lain", "isi": "Paragraf tanpa kata kuncinya."})
    seo = _seo(client, marketing, d["id"])
    assert not _hasil(seo, "kunci_judul")["lulus"] and not _hasil(seo, "kunci_paragraf")["lulus"]
    client.patch(f"/api/content/{d['id']}", headers=marketing, json={"isi": "madu grosir kappa " * 20})
    assert not _hasil(_seo(client, marketing, d["id"]), "kepadatan")["lulus"]


def test_kata_kunci_ganda_dilaporkan(client, marketing, pid):
    a = _gen(client, marketing, pid, topik="kata kunci lambda")
    assert _hasil(_seo(client, marketing, a["id"]), "kunci_ganda")["lulus"]
    b = _gen(client, marketing, pid, topik="Kata Kunci Lambda")
    assert not _hasil(_seo(client, marketing, b["id"]), "kunci_ganda")["lulus"]
    client.post(f"/api/content/{a['id']}/arsip", headers=marketing)
    assert _hasil(_seo(client, marketing, b["id"]), "kunci_ganda")["lulus"]


def test_format_non_web_tidak_diperiksa_meta_dan_tanpa_saran_tautan(client, marketing, pid):
    d = _gen(client, marketing, pid, tipe="broadcast_wa", topik="info mu")
    seo = _seo(client, marketing, d["id"])
    ids = {c["id"] for c in seo["cek"]}
    assert "kunci_title" not in ids and "panjang" in ids and seo["tautan"]["saran"] == []


def test_harga_berbeda_dengan_katalog_dilaporkan(client, marketing, pid):
    d = _gen(client, marketing, pid, topik="harga nu")
    assert _seo(client, marketing, d["id"])["harga_beda"] == []
    client.patch(f"/api/content/{d['id']}", headers=marketing, json={"isi": d["isi"] + "\n\nHarga khusus Rp 1.234 per box."})
    assert _seo(client, marketing, d["id"])["harga_beda"] == ["Rp 1.234"]


def test_saran_tautan_tanpa_pola_tidak_mengarang_alamat(monkeypatch, seeded, pid):
    monkeypatch.setattr(get_settings(), "pola_url_produk", "")
    with SessionLocal() as db:
        p = db.get(Product, pid)
        saran = studio.saran_tautan(db, p)
        assert saran and len(saran) <= studio.MAKS_SARAN_TAUTAN
        assert all(s["url"] is None and s["product_id"] != pid and s["alasan"] for s in saran)


def test_saran_tautan_memakai_pola_dan_melewati_produk_nonaktif(monkeypatch, seeded, pid):
    monkeypatch.setattr(get_settings(), "pola_url_produk", "https://situs.test/produk/{slug}")
    with SessionLocal() as db:
        p = db.get(Product, pid)
        pertama = studio.saran_tautan(db, p)[0]
        assert pertama["url"].startswith("https://situs.test/produk/") and "{slug}" not in pertama["url"] and " " not in pertama["url"]
        lain = db.get(Product, pertama["product_id"])
        lain.aktif = False
        db.flush()
        try:
            assert pertama["product_id"] not in [s["product_id"] for s in studio.saran_tautan(db, p)]
        finally:
            db.rollback()


def test_saran_tautan_melewati_produk_yang_tidak_lolos_verifikasi(monkeypatch, seeded, pid):
    monkeypatch.setattr(get_settings(), "pola_url_produk", "")
    with SessionLocal() as db:
        p = db.get(Product, pid)
        pertama = studio.saran_tautan(db, p)[0]
        monkeypatch.setattr(verifikasi.Saringan, "boleh_produk", lambda self, prod, jenis: prod.id != pertama["product_id"])
        assert pertama["product_id"] not in [s["product_id"] for s in studio.saran_tautan(db, p)]


def test_pola_alamat_yang_salah_tidak_dipakai(monkeypatch, seeded, pid):
    monkeypatch.setattr(get_settings(), "pola_url_produk", "javascript:alert('{slug}')")
    with SessionLocal() as db:
        assert studio._url_produk(db.get(Product, pid)) is None


def test_ekspor_html_hanya_merender_tautan_http():
    keluar = studio._md_to_html("Lihat [Madu](https://situs.test/madu?a=1&b=2), [jahat](javascript:alert(1)), dan <script>x</script> [\"><img](https://a.test/\"onload=x).")
    halaman = BeautifulSoup(keluar, "html.parser")
    assert [a["href"] for a in halaman.find_all("a")][0] == "https://situs.test/madu?a=1&b=2"
    assert all(a["href"].startswith("https://") for a in halaman.find_all("a"))
    assert halaman.find("script") is None and halaman.find("img") is None and "javascript:" not in " ".join(a["href"] for a in halaman.find_all("a"))


def test_tautan_di_isi_dihitung_internal_bila_situs_diketahui(client, marketing, monkeypatch, pid):
    d = _gen(client, marketing, pid, topik="tautan xi")
    isi = d["isi"] + "\n\nLihat [Produk](https://situs.test/a) dan [Luar](https://lain.test/b)."
    client.patch(f"/api/content/{d['id']}", headers=marketing, json={"isi": isi})
    monkeypatch.setattr(get_settings(), "situs_resmi", "")
    t = _seo(client, marketing, d["id"])["tautan"]
    assert t["total"] == 2 and t["internal"] == 0 and t["situs_diketahui"] is False
    monkeypatch.setattr(get_settings(), "situs_resmi", "https://situs.test")
    t = _seo(client, marketing, d["id"])["tautan"]
    assert t["internal"] == 1 and t["situs_diketahui"] is True


# ------------------------------------------------------------------ audit canonical dan robots


def _html(kepala="") -> str:
    return f"<html><head>{kepala}<title>Judul</title></head><body><h1>Satu</h1><p>Isi halaman.</p></body></html>"


def _audit_html(db, kepala=""):
    rep = audit_svc.audit(db, html_doc=_html(kepala), aktor="tes")
    return {c["id"]: c for c in rep["cek"]}, rep


def test_canonical_diperiksa(seeded):
    with SessionLocal() as db:
        assert _audit_html(db)[0]["canonical"]["status"] == "gagal"
        assert _audit_html(db, '<link rel="canonical" href="/relatif">')[0]["canonical"]["status"] == "gagal"
        assert _audit_html(db, '<link rel="canonical" href="https://situs.test/a">')[0]["canonical"]["status"] == "lulus"


def test_noindex_di_halaman_terdeteksi(seeded):
    with SessionLocal() as db:
        assert _audit_html(db)[0]["robots"]["status"] == "lulus"
        assert "tidak diperiksa" in _audit_html(db)[0]["robots"]["detail"]
        assert _audit_html(db, '<meta name="robots" content="noindex,follow">')[0]["robots"]["status"] == "gagal"
        assert _audit_html(db, '<meta name="GOOGLEBOT" content="none">')[0]["robots"]["status"] == "gagal"
        assert _audit_html(db, '<meta name="robots" content="index,follow">')[0]["robots"]["status"] == "lulus"


def test_struktur_gagal_masuk_potensi_bukan_skor_sesudah(seeded):
    with SessionLocal() as db:
        _, rep = _audit_html(db)
    assert "Canonical" in rep["perlu_perbaikan_struktur"] and rep["skor_potensi"] > rep["skor_sesudah"]


def test_bobot_audit_tetap_berjumlah_100(seeded):
    with SessionLocal() as db:
        cek, _ = _audit_html(db)
    assert sum(c["bobot"] for c in cek.values()) == 100


def _situs(monkeypatch, tangani):
    monkeypatch.setattr(audit_svc, "periksa_alamat", lambda url: None)
    monkeypatch.setattr(audit_svc.httpx, "Client", lambda **k: _KLIEN_ASLI(transport=httpx.MockTransport(tangani), **k))


def _tangani(robots=None, status_robots=200, kepala_http=None, kepala_html='<link rel="canonical" href="https://situs.test/produk/a/">'):
    def jawab(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(status_robots, headers={"content-type": "text/plain"}, text=robots or "")
        return httpx.Response(200, headers={"content-type": "text/html", **(kepala_http or {})}, text=_html(kepala_html))

    return jawab


def _audit_url(url="https://situs.test/produk/a"):
    with SessionLocal() as db:
        return {c["id"]: c for c in audit_svc.audit(db, url=url, aktor="tes")["cek"]}


def test_canonical_dibandingkan_dengan_alamat_yang_dibuka(monkeypatch, seeded):
    _situs(monkeypatch, _tangani())
    assert _audit_url()["canonical"]["status"] == "lulus", "garis miring di akhir tidak dihitung beda"
    assert _audit_url("https://situs.test/produk/a?utm=1")["canonical"]["status"] == "lulus"
    _situs(monkeypatch, _tangani(kepala_html='<link rel="canonical" href="https://lain.test/x">'))
    c = _audit_url()["canonical"]
    assert c["status"] == "gagal" and "alamat lain" in c["detail"]


def test_robots_txt_melarang(monkeypatch, seeded):
    _situs(monkeypatch, _tangani(robots="User-agent: *\nDisallow: /produk/"))
    c = _audit_url()["robots"]
    assert c["status"] == "gagal" and "robots.txt" in c["detail"]


def test_robots_txt_mengizinkan_atau_tidak_ada(monkeypatch, seeded):
    _situs(monkeypatch, _tangani(robots="User-agent: *\nDisallow: /admin/"))
    c = _audit_url()["robots"]
    assert c["status"] == "lulus" and "mengizinkan" in c["detail"]
    _situs(monkeypatch, _tangani(status_robots=404))
    assert "mengizinkan" in _audit_url()["robots"]["detail"]


def test_robots_txt_galat_tidak_dianggap_melarang(monkeypatch, seeded):
    _situs(monkeypatch, _tangani(status_robots=500))
    c = _audit_url()["robots"]
    assert c["status"] == "lulus" and "tidak diperiksa" in c["detail"]


def test_header_x_robots_tag_terdeteksi(monkeypatch, seeded):
    _situs(monkeypatch, _tangani(kepala_http={"x-robots-tag": "noindex"}))
    c = _audit_url()["robots"]
    assert c["status"] == "gagal" and "X-Robots-Tag" in c["detail"]


def test_robots_txt_yang_mengalihkan_ke_alamat_internal_tidak_dibuka(monkeypatch, seeded):
    dibuka = []

    def jawab(req):
        dibuka.append(req.url.host)
        if req.url.path == "/robots.txt":
            return httpx.Response(302, headers={"location": "http://dalam.test/rahasia"})
        return httpx.Response(200, headers={"content-type": "text/html"}, text=_html())

    def periksa(url):
        if "dalam.test" in url:
            raise audit_svc.AlamatDitolak("internal")

    monkeypatch.setattr(audit_svc, "periksa_alamat", periksa)
    monkeypatch.setattr(audit_svc.httpx, "Client", lambda **k: _KLIEN_ASLI(transport=httpx.MockTransport(jawab), **k))
    assert "tidak diperiksa" in _audit_url()["robots"]["detail"]
    assert "dalam.test" not in dibuka
