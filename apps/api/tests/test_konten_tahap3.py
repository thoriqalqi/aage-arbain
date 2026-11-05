"""Content/Search Agent tahap 3: satu mesin konten, bukti terbit manual, dan status sambungan mitra."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from aage import clock, ledger, ledger_chain, settings_store
from aage.config import get_settings
from aage.content import studio
from aage.db import SessionLocal, init_db
from aage.models import Approval, ContentDraft, LedgerEvent, Product
from aage.seed import seed_base


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
    _isi_ulang()
    yield
    _isi_ulang()


@pytest.fixture(scope="module")
def produk(bersihkan) -> dict:
    with SessionLocal() as db:
        p = db.scalars(select(Product).where(Product.aktif.is_(True), Product.harga_dasar.is_not(None)).order_by(Product.id)).first()
        return {"id": p.id, "nama": p.nama, "sku": p.sku}


def _hari_ini() -> str:
    return clock.now().astimezone(clock.WIB).date().isoformat()


def _draf_disetujui(client, marketing, admin, pid: int) -> int:
    r = client.post("/api/content/generate", json={"product_id": pid, "topik": "kebutuhan apotek", "target": "apotek", "tipe": "artikel"}, headers=marketing)
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    assert client.post(f"/api/content/{cid}/submit", headers=marketing).status_code == 200
    assert client.post(f"/api/content/{cid}/approve", headers=admin).status_code == 200
    return cid


def _terbit(client, h, cid, **isi):
    body = {"kanal": "situs", "alamat": "https://contoh.test/artikel", "tanggal": _hari_ini(), "catatan": "", **isi}
    return client.post(f"/api/content/{cid}/terbit", json=body, headers=h)


@pytest.fixture
def cid(client, marketing, admin, produk) -> int:
    return _draf_disetujui(client, marketing, admin, produk["id"])


# --- satu mesin konten


def test_rute_agen_memakai_katalog_aktif_dan_studio(client, marketing, produk):
    r = client.post("/api/agents/content", json={"produk": produk["nama"], "topik": "kebutuhan apotek"}, headers=marketing)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["product_id"] == produk["id"] and d["status"] == "draf" and d["claim_report"]["referensi"]
    assert "log" not in d and "audit" not in d
    assert any(x["id"] == d["id"] for x in client.get("/api/content", headers=marketing).json()["items"])
    assert client.get(f"/api/content/{d['id']}/versi", headers=marketing).json()["items"][0]["nomor"] == 1
    with SessionLocal() as db:
        ev = db.scalar(select(LedgerEvent).where(LedgerEvent.objek_ref == f"content:{d['id']}", LedgerEvent.tipe_event == "konten_dibuat"))
        assert ev is not None and ev.aktor.startswith("staf:")
        assert db.scalar(select(func.count()).select_from(Approval).where(Approval.objek_tipe == "agen_konten")) == 0


def test_rute_agen_menerima_sku(client, marketing, produk):
    r = client.post("/api/agents/content", json={"produk": produk["sku"], "topik": "kebutuhan apotek", "tipe": "caption_ig"}, headers=marketing)
    assert r.status_code == 200 and r.json()["product_id"] == produk["id"] and r.json()["tipe"] == "caption_ig"


def test_rute_agen_produk_tidak_ada(client, marketing):
    r = client.post("/api/agents/content", json={"produk": "Produk Zzz Qqq", "topik": "kebutuhan apotek"}, headers=marketing)
    assert r.status_code == 404
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ContentDraft).where(ContentDraft.topik == "Produk Zzz Qqq")) == 0


def test_rute_agen_nama_ambigu_tidak_ditebak(client, marketing):
    with SessionLocal() as db:
        db.add_all([Product(sku="AMBIGU-1", nama="Rimpang Khusus Kapsul", aktif=True), Product(sku="AMBIGU-2", nama="Rimpang Khusus Instan", aktif=True)])
        db.commit()
    def jumlah() -> int:
        with SessionLocal() as db:
            return db.scalar(select(func.count()).select_from(ContentDraft))

    sebelum = jumlah()
    r = client.post("/api/agents/content", json={"produk": "rimpang khusus", "topik": "kebutuhan apotek"}, headers=marketing)
    assert r.status_code == 409
    assert "Rimpang Khusus Kapsul" in r.text and "Rimpang Khusus Instan" in r.text
    assert jumlah() == sebelum
    with SessionLocal() as db:
        for p in db.scalars(select(Product).where(Product.sku.in_(["AMBIGU-1", "AMBIGU-2"]))):
            p.aktif = False
        db.commit()


def test_rute_agen_produk_nonaktif_tidak_dipakai(client, marketing):
    with SessionLocal() as db:
        db.add(Product(sku="NONAKTIF-9", nama="Temulawak Nonaktif Unik", aktif=False))
        db.commit()
    assert client.post("/api/agents/content", json={"produk": "NONAKTIF-9", "topik": "kebutuhan apotek"}, headers=marketing).status_code == 404


def test_rute_agen_staf_ditolak(client, staf, produk):
    assert client.post("/api/agents/content", json={"produk": produk["nama"], "topik": "kebutuhan apotek"}, headers=staf).status_code == 403


def test_workday_tidak_membuat_approval_konten_dan_angkanya_cocok(client, admin):
    with SessionLocal() as db:
        sebelum = db.scalar(select(func.count()).select_from(Approval))
    with client.stream("GET", "/api/agents/workday/stream", headers=admin, params={"speed": 8}) as r:
        events = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith('data: {"')]
    selesai = events[-1]
    assert selesai["level"] == "done"
    assert not [e for e in events if e["level"] == "hitl" and (e.get("item") or {}).get("jenis") == "konten"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Approval).where(Approval.objek_tipe == "agen_konten")) == 0
        dibuat = db.scalar(select(func.count()).select_from(Approval)) - sebelum
    assert dibuat == sum(e["level"] == "hitl" for e in events) and dibuat >= 1
    assert f"{dibuat} item menunggu" in selesai["message"]


# --- bukti terbit


def test_catat_terbit_masuk_ledger_tanpa_mengubah_status(client, marketing, cid):
    r = _terbit(client, marketing, cid, catatan="halaman artikel")
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["kanal_label"] == "Situs web" and t["versi"] == 1 and t["versi_berbeda"] is False and t["dibatalkan"] is None
    assert client.get(f"/api/content/{cid}", headers=marketing).json()["status"] == "disetujui"
    with SessionLocal() as db:
        ev = db.get(LedgerEvent, t["event_id"])
        assert ev.tipe_event == "konten_diterbitkan" and ev.objek_ref == f"content:{cid}" and ev.outcome == "diterbitkan"
        assert ev.data["alamat"] == "https://contoh.test/artikel" and ev.data["tanggal"] == _hari_ini()
        assert ledger.boleh_dibaca_marketing(ev)
        hasil = ledger_chain.verify(db)
        assert hasil["utuh"] is True, hasil


def test_alamat_tidak_pernah_dibuka(client, marketing, cid, monkeypatch):
    import httpx

    def dilarang(*a, **k):
        raise AssertionError("alamat bukti terbit tidak boleh dibuka")

    monkeypatch.setattr(httpx.Client, "send", dilarang)
    assert _terbit(client, marketing, cid, alamat="https://contoh.test/tidak-dibuka").status_code == 200


@pytest.mark.parametrize("status_baru", ["draf", "menunggu_approval", "ditolak", "diarsipkan"])
def test_hanya_konten_disetujui(client, marketing, cid, status_baru):
    with SessionLocal() as db:
        db.get(ContentDraft, cid).status = status_baru
        db.commit()
    assert _terbit(client, marketing, cid).status_code == 422


def test_konten_diblokir_ditolak(client, marketing, cid):
    with SessionLocal() as db:
        db.get(ContentDraft, cid).claim_verdict = "blocked"
        db.commit()
    assert _terbit(client, marketing, cid).status_code == 422


def test_produk_nonaktif_ditolak(client, marketing, cid):
    with SessionLocal() as db:
        pid = db.get(ContentDraft, cid).product_id
        db.get(Product, pid).aktif = False
        db.commit()
    try:
        r = _terbit(client, marketing, cid)
        assert r.status_code == 422 and "katalog aktif" in r.text
    finally:
        with SessionLocal() as db:
            db.get(Product, pid).aktif = True
            db.commit()


@pytest.mark.parametrize("alamat", [
    "javascript:alert(1)", "ftp://contoh.test/a", "contoh.test/artikel", "https://", "https://user:rahasia@contoh.test/a",
    "https://contoh.test/a b", "https://[bad/", "https://contoh.test/" + "a" * 500, "https://wa.me/6281234567890",
])
def test_alamat_tidak_valid(client, marketing, cid, alamat):
    assert _terbit(client, marketing, cid, alamat=alamat).status_code == 422


@pytest.mark.parametrize("kanal", ["situs", "instagram", "marketplace"])
def test_kanal_ini_wajib_alamat(client, marketing, cid, kanal):
    assert _terbit(client, marketing, cid, kanal=kanal, alamat="", catatan="ada catatan").status_code == 422


@pytest.mark.parametrize("kanal", ["whatsapp", "cetak", "lainnya"])
def test_kanal_tanpa_alamat_wajib_catatan(client, marketing, cid, kanal):
    assert _terbit(client, marketing, cid, kanal=kanal, alamat="").status_code == 422
    assert _terbit(client, marketing, cid, kanal=kanal, alamat="", catatan="brosur cetak batch pertama").status_code == 200


def test_kanal_tidak_dikenal(client, marketing, cid):
    assert _terbit(client, marketing, cid, kanal="tiktok").status_code == 422


def test_tanggal_masa_depan_dan_sebelum_draf_ditolak(client, marketing, cid):
    hari = clock.now().astimezone(clock.WIB).date()
    assert _terbit(client, marketing, cid, tanggal=(hari + timedelta(days=1)).isoformat()).status_code == 422
    assert _terbit(client, marketing, cid, tanggal=(hari - timedelta(days=1)).isoformat()).status_code == 422
    assert _terbit(client, marketing, cid, tanggal="bukan-tanggal").status_code == 422


def test_tanggal_memakai_wib(cid):
    """Pukul 01.00 WIB tanggal UTC masih kemarin. Tanggal hari itu di WIB tetap sah."""
    with SessionLocal() as db:
        d = db.get(ContentDraft, cid)
        besok = clock.aware(d.dibuat_pada).astimezone(clock.WIB).date() + timedelta(days=1)
        with clock.frozen_at(datetime(besok.year, besok.month, besok.day, 1, 0, tzinfo=clock.WIB).astimezone(timezone.utc)):
            t = studio.catat_terbit(db, d, kanal="cetak", alamat="", tanggal=besok, catatan="brosur batch uji", aktor="staf:Uji")
        assert t["tanggal"] == besok.isoformat()


def test_nomor_telepon_di_catatan_ditolak(client, marketing, cid):
    r = _terbit(client, marketing, cid, kanal="whatsapp", alamat="", catatan="dikirim ke 0812-3456-7890")
    assert r.status_code == 422 and "nomor telepon" in r.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(LedgerEvent).where(LedgerEvent.objek_ref == f"content:{cid}", LedgerEvent.tipe_event == "konten_diterbitkan")) == 0


def test_alamat_ganda_409_tetapi_kanal_lain_boleh(client, marketing, cid):
    assert _terbit(client, marketing, cid).status_code == 200
    assert _terbit(client, marketing, cid, alamat="https://contoh.test/artikel/").status_code == 409
    assert _terbit(client, marketing, cid, kanal="marketplace").status_code == 200


def test_batal_terbit_append_only_dan_alamat_bisa_dicatat_lagi(client, marketing, cid):
    eid = _terbit(client, marketing, cid).json()["event_id"]
    assert client.post(f"/api/content/{cid}/terbit/{eid}/batal", json={"alasan": ""}, headers=marketing).status_code == 422
    r = client.post(f"/api/content/{cid}/terbit/{eid}/batal", json={"alasan": "alamat keliru"}, headers=marketing)
    assert r.status_code == 200 and r.json()["dibatalkan"]["alasan"] == "alamat keliru"
    assert client.post(f"/api/content/{cid}/terbit/{eid}/batal", json={"alasan": "dua kali"}, headers=marketing).status_code == 409
    with SessionLocal() as db:
        ev = db.get(LedgerEvent, eid)
        assert ev.tipe_event == "konten_diterbitkan"
        hasil = ledger_chain.verify(db)
        assert hasil["utuh"] is True, hasil
    assert _terbit(client, marketing, cid).status_code == 200
    items = client.get(f"/api/content/{cid}/terbit", headers=marketing).json()["items"]
    assert len(items) == 2 and items[1]["dibatalkan"] is not None and items[0]["dibatalkan"] is None


def test_batal_event_draf_lain_404(client, marketing, admin, produk, cid):
    lain = _draf_disetujui(client, marketing, admin, produk["id"])
    eid = _terbit(client, marketing, lain).json()["event_id"]
    assert client.post(f"/api/content/{cid}/terbit/{eid}/batal", json={"alasan": "salah draf"}, headers=marketing).status_code == 404
    # Event Ledger bertipe lain pada draf yang sama juga bukan catatan terbit.
    with SessionLocal() as db:
        bukan = db.scalar(select(LedgerEvent.id).where(LedgerEvent.objek_ref == f"content:{cid}", LedgerEvent.tipe_event == "konten_dibuat"))
    assert client.post(f"/api/content/{cid}/terbit/{bukan}/batal", json={"alasan": "bukan terbit"}, headers=marketing).status_code == 404


def test_edit_sesudah_terbit_menandai_versi_berbeda(client, marketing, admin, cid):
    assert _terbit(client, marketing, cid).status_code == 200
    d = client.get(f"/api/content/{cid}", headers=marketing).json()
    assert client.patch(f"/api/content/{cid}", json={"isi": d["isi"] + "\n\nCatatan tambahan untuk apotek."}, headers=marketing).status_code == 200
    data = client.get(f"/api/content/{cid}/terbit", headers=marketing).json()
    assert data["versi_sekarang"] == 2
    assert data["items"][0]["versi"] == 1 and data["items"][0]["versi_berbeda"] is True
    # Draf yang sudah diedit perlu disetujui ulang sebelum dicatat terbit lagi.
    assert _terbit(client, marketing, cid, alamat="https://contoh.test/baru").status_code == 422
    # Catatan lama tetap bisa dikoreksi walau draf belum disetujui ulang.
    eid = data["items"][0]["event_id"]
    assert client.post(f"/api/content/{cid}/terbit/{eid}/batal", json={"alasan": "alamat keliru"}, headers=marketing).status_code == 200


def test_daftar_konten_menghitung_terbit_aktif(client, marketing, cid):
    def hitung():
        return next(x for x in client.get("/api/content", headers=marketing).json()["items"] if x["id"] == cid)["terbit"]

    assert hitung() == 0
    eid = _terbit(client, marketing, cid).json()["event_id"]
    assert _terbit(client, marketing, cid, kanal="marketplace").status_code == 200
    assert hitung() == 2
    client.post(f"/api/content/{cid}/terbit/{eid}/batal", json={"alasan": "alamat keliru"}, headers=marketing)
    assert hitung() == 1


def test_staf_tidak_boleh_mengakses_bukti_terbit(client, marketing, staf, cid):
    assert client.get(f"/api/content/{cid}/terbit", headers=staf).status_code == 403
    assert _terbit(client, staf, cid).status_code == 403
    assert client.post(f"/api/content/{cid}/terbit/1/batal", json={"alasan": "uji peran"}, headers=staf).status_code == 403
    assert client.get("/api/content/integrasi", headers=staf).status_code == 403


def test_draf_tidak_ada_404(client, marketing):
    assert client.get("/api/content/999999/terbit", headers=marketing).status_code == 404
    assert _terbit(client, marketing, 999999).status_code == 404


def test_marketing_melihat_event_terbit_di_ledger(client, marketing, cid):
    assert _terbit(client, marketing, cid).status_code == 200
    r = client.get("/api/ledger", params={"limit": 50}, headers=marketing)
    assert r.status_code == 200
    assert "konten_diterbitkan" in r.text


# --- sambungan mitra


def test_integrasi_jujur_saat_belum_diisi(client, marketing, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "situs_resmi", "")
    monkeypatch.setattr(s, "pola_url_produk", "")
    items = {x["id"]: x for x in client.get("/api/content/integrasi", headers=marketing).json()["items"]}
    assert set(items) == {"domain", "pola_url", "cms", "search_console"}
    assert not any(x["siap"] for x in items.values())
    assert "SITUS_RESMI" in items["domain"]["detail"]


def test_integrasi_cms_dan_search_console_tetap_belum_walau_domain_terisi(client, marketing, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "situs_resmi", "https://contoh.test")
    monkeypatch.setattr(s, "pola_url_produk", "https://contoh.test/produk/{sku}")
    items = {x["id"]: x for x in client.get("/api/content/integrasi", headers=marketing).json()["items"]}
    assert items["domain"]["siap"] and items["pola_url"]["siap"]
    assert items["domain"]["detail"] == "https://contoh.test"
    assert not items["cms"]["siap"] and not items["search_console"]["siap"]
