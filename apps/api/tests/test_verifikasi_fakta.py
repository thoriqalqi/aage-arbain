"""Verifikasi knowledge: bot hanya menyajikan fakta terverifikasi yang masih berlaku; data simulasi hanya di mode demo berlabel."""
import csv
import io
from datetime import timedelta

import pytest
from sqlalchemy import select

from aage import clock, settings_store
from aage.agents import drafter, gerbang_fakta
from aage.agents.graph import handle_inbound
from aage.claimguard import service as cg
from aage.content import studio
from aage.db import SessionLocal
from aage.kb import katalog_impor as k
from aage.kb import verifikasi as v
from aage.models import Approval, ApprovedClaim, Document, LedgerEvent, OrderDraft, Product, Prospect, User, VerifikasiFakta
from aage.prospects import market_service

SKU = "ARB-002"  # Madu Stamina Plus 250 g
HARGA = "2.340.000"
LABEL = gerbang_fakta.LABEL_SIMULASI
N = {"i": 0}


def _tanya(db, teks: str):
    N["i"] += 1
    return handle_inbound(db, channel="webchat", external_user_id=f"t-verif-{N['i']}", text=teks)


def _teks(r) -> str:
    return "\n".join(m.teks for m in r.replies)


def _produk(db, sku: str = SKU) -> Product:
    return db.scalar(select(Product).where(Product.sku == sku))


def _admin(db) -> User:
    return db.scalar(select(User).where(User.email == "admin@aage.local"))


def _status(db, tipe, objek_id, jenis, status, bukti="Dokumen uji", berlaku=None):
    v.ubah_status(db, objek_tipe=tipe, objek_id=objek_id, jenis_fakta=jenis, status=status, sumber_bukti=bukti, berlaku_sampai=berlaku,
                  user=_admin(db))
    db.commit()


def _verifikasi_harga(db, p: Product, berlaku=None):
    for jenis in ("harga", "moq", "tier_diskon"):
        _status(db, v.PRODUK, p.id, jenis, v.TERVERIFIKASI, berlaku=berlaku)


@pytest.fixture
def pulihkan(seeded):
    """Status, nilai produk, dan mode kembali seperti semula: basis data tes dipakai bersama."""
    with SessionLocal() as db:
        baris = [(b.objek_tipe, b.objek_id, b.jenis_fakta, b.status_verifikasi) for b in db.scalars(select(VerifikasiFakta))]
        p = _produk(db)
        nilai = (p.harga_dasar, p.no_izin_edar, dict(p.data_teknis or {}), p.stok)
        pid = p.id
    yield
    with SessionLocal() as db:
        for b in db.scalars(select(VerifikasiFakta)):
            db.delete(b)
        db.flush()
        for tipe, oid, jenis, status in baris:
            db.add(VerifikasiFakta(objek_tipe=tipe, objek_id=oid, jenis_fakta=jenis, status_verifikasi=status, diubah_oleh="tes", diubah_pada=clock.now()))
        p = db.get(Product, pid)
        p.harga_dasar, p.no_izin_edar, p.data_teknis, p.stok = nilai
        db.commit()
        settings_store.pasang_mode_data(db, "demo")


@pytest.fixture
def produksi(pulihkan):
    with SessionLocal() as db:
        settings_store.pasang_mode_data(db, "produksi")
    yield


# ------------------------------------------------------------------ perilaku bot


def test_mode_bawaan_produksi_bila_belum_diatur(db, pulihkan):
    baris = db.get(settings_store.AppSetting, "mode_data")
    db.delete(baris)
    db.commit()
    assert settings_store.mode_data(db) == "produksi"


def test_terverifikasi_dijawab_biasa_tanpa_label(db, produksi):
    _verifikasi_harga(db, _produk(db))
    t = _teks(_tanya(db, "harga madu stamina plus 10 box berapa?"))
    assert HARGA in t and LABEL not in t and "belum terverifikasi" not in t


@pytest.mark.parametrize("tanya,terlarang", [
    ("harga madu stamina plus 10 box berapa?", HARGA),
    ("nomor izin edar madu stamina plus apa?", "SIM"),
    ("bisa bayar tempo?", "14 hari"),
    ("barang rusak bisa retur?", "3 hari"),
    ("madu stamina plus halal?", "ID-HALAL"),
])
def test_simulasi_di_produksi_tidak_disajikan(db, produksi, tanya, terlarang):
    r = _tanya(db, tanya)
    t = _teks(r)
    assert terlarang not in t and "belum terverifikasi" in t
    assert LABEL not in t
    assert "staf" in t


def test_klaim_simulasi_di_produksi_tidak_dikutip(db, produksi):
    p = _produk(db)
    klaim = [c.teks_klaim for c in p.claims]
    t = _teks(_tanya(db, "madu stamina plus manfaatnya apa?"))
    assert klaim and not any(x.rstrip(".") in t for x in klaim)


@pytest.mark.parametrize("tanya,harus", [("harga madu stamina plus 10 box berapa?", HARGA), ("bisa bayar tempo?", "14 hari")])
def test_simulasi_di_demo_dijawab_dengan_label(db, pulihkan, tanya, harus):
    t = _teks(_tanya(db, tanya))
    assert harus in t and LABEL in t


@pytest.mark.parametrize("mode", ["produksi", "demo"])
def test_kedaluwarsa_tidak_dikutip_di_mode_apa_pun(db, pulihkan, mode):
    settings_store.pasang_mode_data(db, mode)
    p = _produk(db)
    _verifikasi_harga(db, p, berlaku=clock.now().date() + timedelta(days=30))
    assert HARGA in _teks(_tanya(db, "harga madu stamina plus 10 box berapa?"))
    baris = db.scalar(select(VerifikasiFakta).where(VerifikasiFakta.objek_id == p.id, VerifikasiFakta.jenis_fakta == "harga",
                                                    VerifikasiFakta.objek_tipe == v.PRODUK))
    baris.berlaku_sampai = clock.now().date() - timedelta(days=1)
    db.commit()
    assert v.Saringan(db).status_produk(p, "harga") == v.KEDALUWARSA
    t = _teks(_tanya(db, "harga madu stamina plus 10 box berapa?"))
    assert HARGA not in t and "belum terverifikasi" in t


@pytest.mark.parametrize("mode", ["produksi", "demo"])
def test_belum_diverifikasi_tidak_dikutip_di_mode_apa_pun(db, pulihkan, mode):
    settings_store.pasang_mode_data(db, mode)
    p = _produk(db)
    _status(db, v.PRODUK, p.id, "harga", v.BELUM)
    t = _teks(_tanya(db, "harga madu stamina plus 10 box berapa?"))
    assert HARGA not in t and "belum terverifikasi" in t


def test_fakta_tanpa_baris_dianggap_belum_diverifikasi(db, pulihkan):
    p = _produk(db)
    db.delete(db.scalar(select(VerifikasiFakta).where(VerifikasiFakta.objek_id == p.id, VerifikasiFakta.jenis_fakta == "harga",
                                                      VerifikasiFakta.objek_tipe == v.PRODUK)))
    db.commit()
    assert v.Saringan(db).status_produk(p, "harga") == v.BELUM


def test_nilai_berubah_membatalkan_verifikasi(db, produksi):
    p = _produk(db)
    _verifikasi_harga(db, p)
    assert v.Saringan(db).status_produk(p, "harga") == v.TERVERIFIKASI
    p.harga_dasar = 2_500_000
    db.commit()
    assert v.Saringan(db).status_produk(p, "harga") == v.BELUM
    t = _teks(_tanya(db, "harga madu stamina plus 10 box berapa?"))
    assert "2.500.000" not in t and "belum terverifikasi" in t


def test_pesanan_tanpa_harga_terverifikasi_tidak_jadi_draf_dan_sampai_ke_staf(db, produksi):
    sebelum = db.query(OrderDraft).count()
    r = _tanya(db, "saya mau pesan 10 box madu stamina plus")
    if r.decision != "eskalasi":  # alur meminta data toko lebih dulu
        r = handle_inbound(db, channel="webchat", external_user_id=f"t-verif-{N['i']}", text="Apotek Sehat, Jl. Pemuda 1 Semarang")
    t = _teks(r)
    assert HARGA not in t and "Total" not in t
    assert db.query(OrderDraft).count() == sebelum
    assert r.decision == "eskalasi" and r.approval_id
    assert db.get(Approval, r.approval_id) is not None


@pytest.mark.parametrize("pesan", ["produk ini bisa menyembuhkan diabetes?", "saya alergi setelah minum, sesak napas"])
def test_jalur_sensitif_sama_di_kedua_mode(db, pulihkan, pesan):
    hasil = {}
    for mode in ("demo", "produksi"):
        settings_store.pasang_mode_data(db, mode)
        r = _tanya(db, pesan)
        hasil[mode] = (r.intent, r.decision)
    assert hasil["demo"] == hasil["produksi"]


# ------------------------------------------------------------------ yang diterima LLM dan ClaimGuard


def test_llm_hanya_menerima_fakta_yang_lolos(db, produksi):
    p = _produk(db)
    _status(db, v.PRODUK, p.id, "harga", v.TERVERIFIKASI)
    with v.sesi(db):
        fakta = drafter._product_facts(db, p)
    assert HARGA in fakta
    assert p.no_izin_edar not in fakta and "belum terverifikasi, jangan disebut" in fakta
    assert not any(c.teks_klaim in fakta for c in p.claims)


def test_rewrite_llm_yang_memunculkan_fakta_tertahan_diganti(db, produksi):
    ledger_sebelum = db.query(LedgerEvent).filter(LedgerEvent.tipe_event == "fakta_tertahan").count()
    d = drafter.Draft(f"Harganya Rp {HARGA} per box.", sources=[{"tipe": "x"}], template="harga_dasar")
    gerbang_fakta.terapkan(db, d, trace_id="t", conversation_id=0)
    db.commit()
    assert HARGA not in d.text and "belum terverifikasi" in d.text and d.template == "fakta_tertahan"
    assert db.query(LedgerEvent).filter(LedgerEvent.tipe_event == "fakta_tertahan").count() == ledger_sebelum + 1


def test_draf_staf_tidak_memuat_fakta_tertahan(db, produksi):
    d = drafter.Draft("Mohon tunggu.", sources=[], staff_draft=f"Harga Rp {HARGA}", template="x", escalate=True)
    gerbang_fakta.terapkan(db, d, trace_id="t", conversation_id=0)
    assert d.staff_draft is None


def test_gerbang_tidak_salah_tahan_angka_lebih_panjang(db, produksi):
    d = drafter.Draft(f"Total pesanan Anda Rp {HARGA}.000 saja.", sources=[], template="x")
    gerbang_fakta.terapkan(db, d, trace_id="t", conversation_id=0)
    assert d.template == "x"


def test_label_tidak_ganda_bila_gerbang_berjalan_dua_kali(db, pulihkan):
    d = drafter.Draft(f"Harga Rp {HARGA}.", sources=[], template="x")
    for _ in range(2):
        gerbang_fakta.terapkan(db, d, trace_id="t", conversation_id=0)
    assert d.text.count(LABEL) == 1


def test_claimguard_hanya_memakai_klaim_yang_lolos(db, produksi):
    p = _produk(db)
    assert cg._load_claims(db, [p.id]) == []
    assert len(cg._load_claims(db, [p.id], saring=False)) == len(p.claims)
    c = p.claims[0]
    _status(db, v.KLAIM, c.id, v.KLAIM, v.TERVERIFIKASI)
    assert [x.id for x in cg._load_claims(db, [p.id])] == [c.id]


# ------------------------------------------------------------------ impor


HEADER = [c.nama for c in k.KOLOM_PRODUK]
DASAR = {"sku": "VRF-01", "nama": "Madu Uji Verifikasi 100 g", "harga_per_box": "1000000", "moq": "2", "izin_edar": "POM TR 111222333",
         "klaim_disetujui": "Membantu memelihara stamina", "diskon_volume": "5:2"}


def _csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=HEADER)
    w.writeheader()
    w.writerows({h: r.get(h, "") for h in HEADER} for r in rows)
    return buf.getvalue().encode("utf-8")


def _validasi(db, **kolom):
    baris = [(2, {**DASAR, **kolom})]
    return k.validasi_produk(baris, db)


def test_impor_tidak_bisa_menandai_terverifikasi(db):
    valid, error, peringatan = _validasi(db, status_verifikasi="terverifikasi", sumber_bukti="Klaim sendiri")
    assert not error and valid[0]["verifikasi"]["status"] == v.BELUM
    assert any(w["kolom"] == "status_verifikasi" and "terverifikasi" in w["alasan"] for w in peringatan)


def test_baris_tanpa_status_jadi_peringatan(db):
    valid, error, peringatan = _validasi(db)
    assert not error and valid[0]["verifikasi"]["status"] == v.BELUM
    assert any(w["kolom"] == "status_verifikasi" for w in peringatan)


@pytest.mark.parametrize("kolom", [{"izin_edar": "POM SD SIM123"}, {"halal_status": "Bersertifikat Halal", "halal_nomor": "ID-HALAL-SIM-1"},
                                   {"bko_hasil": "Negatif", "bko_nomor_laporan": "LHU-SIM-1"}])
def test_nomor_berpola_simulasi_otomatis_simulasi(db, kolom):
    valid, error, peringatan = _validasi(db, status_verifikasi="belum_diverifikasi", **kolom)
    assert not error and valid[0]["verifikasi"]["status"] == v.SIMULASI
    assert any("simulasi" in w["alasan"] for w in peringatan)


@pytest.mark.parametrize("kolom,salah", [({"status_verifikasi": "valid"}, "status_verifikasi"), ({"berlaku_sampai": "besok"}, "berlaku_sampai"),
                                         ({"berlaku_sampai": "31/13/2027"}, "berlaku_sampai")])
def test_kolom_verifikasi_salah_jadi_error(db, kolom, salah):
    _, error, _ = _validasi(db, **kolom)
    assert [e["kolom"] for e in error] == [salah]


@pytest.mark.parametrize("teks", ["2027-12-31", "31/12/2027", "2027-12-31 00:00:00"])
def test_tanggal_berlaku_diterima_dari_excel_dan_csv(db, teks):
    valid, error, _ = _validasi(db, berlaku_sampai=teks, status_verifikasi="simulasi")
    assert not error and valid[0]["verifikasi"]["berlaku_sampai"] == "2027-12-31"


def test_tanggal_lewat_jadi_peringatan_dan_terbaca_kedaluwarsa(db):
    _, error, peringatan = _validasi(db, berlaku_sampai="2020-01-01", status_verifikasi="simulasi")
    assert not error and any(w["kolom"] == "berlaku_sampai" for w in peringatan)


@pytest.fixture
def katalog_pulih(seeded):
    with SessionLocal() as db:
        asli = k.ekspor_xlsx(db)
    yield
    with SessionLocal() as db:
        imp = k.buat_pratinjau(db, "pulihkan.xlsx", asli, "tes")
        k.terapkan(db, imp.token, "tes")


def _impor(db, baris: list[dict]):
    imp = k.buat_pratinjau(db, "uji.csv", _csv(baris), "tes")
    k.terapkan(db, imp.token, "tes")
    db.expire_all()
    return _produk(db, "VRF-01")


def test_impor_ulang_nilai_sama_mempertahankan_verifikasi_nilai_baru_membatalkan(db, katalog_pulih):
    p = _impor(db, [DASAR])
    sar = v.Saringan(db)
    assert sar.status_produk(p, "harga") == v.BELUM and sar.status_klaim(p.claims[0]) == v.BELUM
    _status(db, v.PRODUK, p.id, "harga", v.TERVERIFIKASI)
    _status(db, v.PRODUK, p.id, "izin_edar", v.TERVERIFIKASI)
    _status(db, v.KLAIM, p.claims[0].id, v.KLAIM, v.TERVERIFIKASI)

    p = _impor(db, [DASAR])
    sar = v.Saringan(db)
    assert sar.status_produk(p, "harga") == v.TERVERIFIKASI and sar.status_produk(p, "izin_edar") == v.TERVERIFIKASI
    assert sar.status_klaim(p.claims[0]) == v.TERVERIFIKASI
    assert p.claims[0].diverifikasi_oleh

    p = _impor(db, [{**DASAR, "harga_per_box": "1200000", "klaim_disetujui": "Membantu menjaga kebugaran"}])
    sar = v.Saringan(db)
    assert sar.status_produk(p, "harga") == v.BELUM and sar.status_produk(p, "izin_edar") == v.TERVERIFIKASI
    assert sar.status_klaim(p.claims[0]) == v.BELUM


def test_kebijakan_satu_baris_lemah_melemahkan_dokumen_dan_isi_sama_mempertahankan(db, katalog_pulih):
    from openpyxl import load_workbook

    def berkas(ubah=None):
        wb = load_workbook(io.BytesIO(k.template_xlsx()))
        for i, row in enumerate(wb["Kebijakan"].iter_rows(min_row=2)):
            row[2].value = "simulasi" if i else None
            if ubah and row[0].value == "pembayaran":
                row[1].value = ubah
        for row in wb["Produk"].iter_rows(min_row=2):
            row[HEADER.index("status_verifikasi")].value = "simulasi"
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def aktif():
        db.expire_all()
        return db.scalar(select(Document).where(Document.aktif.is_(True), Document.judul.like("Kebijakan Penjualan%")).order_by(Document.id.desc()))

    def terapkan(isi):
        imp = k.buat_pratinjau(db, "kebijakan.xlsx", isi, "tes")
        k.terapkan(db, imp.token, "tes")

    terapkan(berkas())
    pertama = aktif()
    assert v.Saringan(db).status_dokumen(pertama.id) == v.BELUM
    _status(db, v.DOKUMEN, pertama.id, v.DOKUMEN, v.TERVERIFIKASI)

    terapkan(berkas())
    kedua = aktif()
    assert kedua.id != pertama.id and v.Saringan(db).status_dokumen(kedua.id) == v.TERVERIFIKASI

    terapkan(berkas("Pembayaran di muka melalui transfer bank. Tempo pembayaran 45 hari untuk pelanggan tetap."))
    assert v.Saringan(db).status_dokumen(aktif().id) == v.BELUM


def test_seed_dan_status_awal_tidak_pernah_terverifikasi(db):
    assert v.status_awal_produk("impor") == v.BELUM and v.status_awal_produk("simulasi") == v.SIMULASI
    assert v.status_awal_dokumen("Kebijakan Penjualan") == v.BELUM and v.status_awal_dokumen("Katalog (data contoh)") == v.SIMULASI
    with pytest.raises(v.StatusDitolak):
        v.PencatatImpor(db, "tes").dokumen(1, v.TERVERIFIKASI)
    db.rollback()


# ------------------------------------------------------------------ izin dan Ledger


def _token(client, email, sandi):
    r = client.post("/api/auth/login", json={"email": email, "password": sandi})
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def admin(client):
    return _token(client, "admin@aage.local", "admin123")


@pytest.fixture
def marketing(client):
    return _token(client, "marketing@aage.local", "marketing123")


def _isi(p, **lain):
    return {"objek_tipe": "produk", "objek_id": p.id, "jenis_fakta": "harga", "status": "terverifikasi", "sumber_bukti": "Daftar harga resmi", **lain}


def test_hanya_admin_yang_bisa_mengubah_status(client, db, auth, marketing, admin, pulihkan):
    p = _produk(db)
    assert client.put("/api/kb/verifikasi", json=_isi(p)).status_code == 401
    assert client.put("/api/kb/verifikasi", json=_isi(p), headers=auth).status_code == 403
    assert client.put("/api/kb/verifikasi", json=_isi(p), headers=marketing).status_code == 403
    db.expire_all()
    assert v.Saringan(db).status_produk(p, "harga") == v.SIMULASI
    r = client.put("/api/kb/verifikasi", json=_isi(p), headers=admin)
    assert r.status_code == 200 and r.json()["diverifikasi_oleh"]


def test_perubahan_status_tercatat_di_ledger_dengan_nama_dan_bukti(client, db, admin, pulihkan):
    p = _produk(db)
    assert client.put("/api/kb/verifikasi", json=_isi(p, berlaku_sampai="2030-01-01"), headers=admin).status_code == 200
    db.expire_all()
    ev = db.scalar(select(LedgerEvent).where(LedgerEvent.tipe_event == "fakta_status_diubah", LedgerEvent.objek_ref == f"produk:{p.id}:harga")
                   .order_by(LedgerEvent.id.desc()))
    assert ev.aktor.startswith("staf:") and ev.outcome == "terverifikasi"
    assert ev.data["sebelum"] == "simulasi" and ev.data["sumber_bukti"] == "Daftar harga resmi" and ev.data["berlaku_sampai"] == "2030-01-01"
    b = db.scalar(select(VerifikasiFakta).where(VerifikasiFakta.objek_tipe == "produk", VerifikasiFakta.objek_id == p.id, VerifikasiFakta.jenis_fakta == "harga"))
    assert b.diverifikasi_oleh == _admin(db).nama and b.diverifikasi_pada and b.sumber_bukti == "Daftar harga resmi"


@pytest.mark.parametrize("ubah,pesan", [
    ({"sumber_bukti": ""}, "bukti"),
    ({"sumber_bukti": None}, "bukti"),
    ({"berlaku_sampai": "2020-01-01"}, "lewat"),
    ({"jenis_fakta": "khayalan"}, "tidak ditemukan"),
    ({"status": "disahkan"}, "tidak dikenal"),
])
def test_verifikasi_ditolak_tanpa_syarat(client, db, admin, pulihkan, ubah, pesan):
    r = client.put("/api/kb/verifikasi", json=_isi(_produk(db), **ubah), headers=admin)
    assert r.status_code == 422 and pesan in r.text


def test_nomor_simulasi_tidak_bisa_diverifikasi(client, db, admin, pulihkan):
    p = _produk(db)
    p.no_izin_edar = "POM SD SIM999"
    db.commit()
    r = client.put("/api/kb/verifikasi", json=_isi(p, jenis_fakta="izin_edar"), headers=admin)
    assert r.status_code == 422 and "simulasi" in r.text


def test_daftar_verifikasi_dan_filter(client, auth, db):
    semua = client.get("/api/kb/verifikasi", headers=auth).json()
    assert semua["mode_data"] == "demo" and semua["ringkasan"]["simulasi"] > 0 and semua["ringkasan"]["terverifikasi"] == 0
    r = client.get("/api/kb/verifikasi?status=kedaluwarsa,terverifikasi", headers=auth).json()
    assert r["items"] == []
    jenis = {i["objek_tipe"] for i in semua["items"]}
    assert jenis == {"produk", "klaim", "dokumen"}


def test_lencana_status_ada_di_data_produk(client, auth):
    p = client.get("/api/kb/products", headers=auth).json()["items"][0]
    assert p["verifikasi"]["terlemah"] == "simulasi" and p["verifikasi"]["per_fakta"]["harga"] == "simulasi"
    assert p["klaim"][0]["status_verifikasi"] == "simulasi"


def test_mode_hanya_admin_tercatat_dan_tampil_di_status(client, db, auth, admin, pulihkan):
    assert client.put("/api/settings", json={"mode_data": "produksi"}, headers=auth).status_code == 403
    assert client.get("/api/status").json()["mode_data"] == "demo"
    assert client.put("/api/settings", json={"mode_data": "bebas"}, headers=admin).status_code == 422
    r = client.put("/api/settings", json={"mode_data": "produksi"}, headers=admin)
    assert r.status_code == 200 and r.json()["mode_data"] == "produksi"
    assert client.get("/api/status").json()["mode_data"] == "produksi"
    db.expire_all()
    ev = db.scalar(select(LedgerEvent).where(LedgerEvent.tipe_event == "pengaturan_diubah").order_by(LedgerEvent.id.desc()))
    assert "mode_data" in ev.ringkasan + str(ev.data)


# ------------------------------------------------------------------ pagar Studio, Leads, agen


def test_studio_menolak_data_belum_terverifikasi_di_produksi(db, produksi):
    p = _produk(db)
    with pytest.raises(studio.ContentError, match="belum terverifikasi"):
        studio.generate(db, product_id=p.id, topik="stamina saat musim hujan", target="apotek", tipe="artikel", aktor="tes")
    db.rollback()


def test_studio_lewat_api_memberi_alasan_jelas(client, db, produksi):
    auth = _token(client, "marketing@aage.local", "marketing123")
    r = client.post("/api/content/generate", headers=auth, json={"product_id": _produk(db).id, "topik": "stamina saat musim hujan", "target": "apotek", "tipe": "artikel"})
    assert r.status_code >= 400 and "belum terverifikasi" in r.text


@pytest.mark.parametrize("metode,alamat,isi", [
    ("post", "/api/agents/negotiate", {"produk": "Madu Stamina", "qty_box": 10}),
    ("post", "/api/agents/invoice/approve", {"produk": "Madu Stamina", "qty_box": 10, "diskon_disetujui": 0}),
])
def test_agen_data_contoh_ditolak_di_produksi(client, auth, produksi, metode, alamat, isi):
    r = getattr(client, metode)(alamat, json=isi, headers=auth)
    assert r.status_code == 409 and "mode demo" in r.text


def test_agen_konten_data_contoh_ditolak_di_produksi(client, produksi):
    auth = _token(client, "marketing@aage.local", "marketing123")
    r = client.post("/api/agents/content", json={"produk": "Madu Stamina", "topik": "stamina"}, headers=auth)
    assert r.status_code == 409 and "mode demo" in r.text


def test_rekomendasi_lead_tanpa_fakta_tertahan_di_produksi(db, produksi):
    lead = Prospect(nama="Apotek Uji", alamat="", wilayah="Kota Semarang", tipe="Apotek", skor=80, jarak_km=2, status="baru")
    hasil = market_service.next_best_action(db, lead, {"topik_utama": None, "topik": []})
    assert hasil["produk"] == [] and hasil["penawaran"]["diskon_persen"] == 0
    assert "belum terverifikasi" in hasil["teks"] and "gratis ongkir" not in hasil["teks"] and "%" not in hasil["teks"]
    assert not db.scalars(select(ApprovedClaim).where(ApprovedClaim.teks_klaim == hasil["klaim_ringkas"])).first()
