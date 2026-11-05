"""Ganti Katalog: seluruh katalog berganti lewat satu unggahan, agent langsung memakai data baru, dan Ledger, percakapan,
serta kontak tidak tersentuh. Setiap tes memulihkan katalog simulasi sesudahnya."""

import logging
from pathlib import Path

import pytest
from sqlalchemy import func, select

from aage import approvals, main, settings_store
from aage.agents import drafter
from aage.agents.graph import handle_inbound
from aage.agents.memori import produk_usang
from aage.channels import registry
from aage.config import sumber_database
from aage.db import DatabaseOnlineError, SessionLocal, init_db
from aage.kb import ganti_katalog as g
from aage.kb import katalog_impor as k
from aage.kb import retriever
from aage.models import (
    Approval,
    ApprovedClaim,
    Chunk,
    Contact,
    ContentDraft,
    Conversation,
    Document,
    KatalogImpor,
    LedgerEvent,
    MarketingDraft,
    Message,
    PricingRule,
    Product,
    User,
    VerifikasiFakta,
)
from aage.seed import seed_base

KATALOG_B = Path(__file__).resolve().parents[1] / "eval" / "katalog" / "katalog_uji_b.xlsx"
PRODUK_DEMO = "Propolis Tetes 30 ml"


def _isi_ulang() -> None:
    init_db(drop=True)
    with SessionLocal() as db:
        seed_base(db)
        settings_store.pasang_mode_data(db, "demo")


@pytest.fixture(scope="module", autouse=True)
def mulai_bersih(seeded):
    """Tes berkas lain bisa meninggalkan produk yang dirujuk audit. Hitungan di sini perlu katalog seed yang persis."""
    _isi_ulang()
    yield


@pytest.fixture
def pulihkan(seeded):
    yield
    _isi_ulang()


def _hitung_terlindungi(db) -> dict:
    return {m.__name__: db.scalar(select(func.count()).select_from(m)) for m in (Conversation, Message, Contact)}


def _pratinjau(client, auth, isi: bytes = None, nama: str = "katalog_b.xlsx") -> dict:
    isi = isi if isi is not None else KATALOG_B.read_bytes()
    r = client.post("/api/katalog/impor", headers=auth, files={"file": (nama, isi)})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def admin(client):
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.role == "admin"))
    from aage.security import create_token

    return {"Authorization": f"Bearer {create_token(u)}"}


def test_nonaktif_mengganti_seluruh_katalog_dan_agent_langsung_memakainya(client, admin, pulihkan):
    with SessionLocal() as db:
        cid = handle_inbound(db, channel="telegram", external_user_id="tg-ganti-1", text=f"harga {PRODUK_DEMO} berapa?").conversation_id
        awal = _hitung_terlindungi(db)
        ledger_awal = db.scalar(select(func.max(LedgerEvent.id)))
        nama_lama = set(db.scalars(select(Product.nama).where(Product.aktif.is_(True))))

    data = _pratinjau(client, admin)
    dampak = client.get(f"/api/katalog/ganti/ringkasan?token={data['token']}", headers=admin).json()["dampak"]
    assert dampak["produk"] > 0 and PRODUK_DEMO in dampak["produk_nama"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Product).where(Product.nama == PRODUK_DEMO, Product.aktif.is_(True)))

    r = client.post(f"/api/katalog/ganti/{data['token']}", headers=admin, json={"mode": "nonaktif"})
    assert r.status_code == 202, r.text
    st = client.get(f"/api/katalog/ganti/{data['token']}", headers=admin).json()
    assert st["status"] == "diterapkan" and st["hasil"]["disingkirkan"]["mode"] == "nonaktif", st

    with SessionLocal() as db:
        aktif = set(db.scalars(select(Product.nama).where(Product.aktif.is_(True))))
        assert len(aktif) == 8 and not (aktif & nama_lama)
        # Pencarian vektor hanya melihat data baru, dan dokumen berlabel contoh tidak lagi aktif.
        chunks = list(db.scalars(select(Chunk).where(Chunk.aktif.is_(True))))
        assert chunks and all(c.embedding is not None for c in chunks)
        assert not any(c.teks and PRODUK_DEMO in c.teks for c in chunks)
        assert not db.scalars(select(Document).where(Document.aktif.is_(True), Document.judul.like("%data contoh%"))).first()
        hits = retriever.retrieve(db, "propolis tetes", k=5)
        assert not any(h.chunk.teks and PRODUK_DEMO in h.chunk.teks for h in hits)
        # Pesan berikutnya di percakapan lama: konteks produk lama tidak terbawa.
        res = handle_inbound(db, channel="telegram", external_user_id="tg-ganti-1", text="yang tadi harganya berapa?")
        balasan = " ".join(m.teks for m in res.replies)
        assert PRODUK_DEMO not in balasan
        assert db.get(Conversation, cid).konteks.get("last_product_ids") in ([], None)
        # Ledger, percakapan, pesan, dan kontak: tidak ada yang berkurang atau berubah.
        assert db.scalar(select(func.count()).select_from(Conversation)) == awal["Conversation"]
        assert db.scalar(select(func.count()).select_from(Contact)) == awal["Contact"]
        assert db.scalar(select(func.count()).select_from(Message)) >= awal["Message"]
        assert db.scalar(select(func.count()).select_from(LedgerEvent).where(LedgerEvent.id <= ledger_awal)) == ledger_awal
        assert db.scalar(select(LedgerEvent).where(LedgerEvent.tipe_event == "katalog_diganti")) is not None


def test_hapus_permanen_butuh_konfirmasi_dan_membersihkan_semua_baris(client, admin, pulihkan):
    with SessionLocal() as db:
        lama = list(db.scalars(select(Product.id).where(Product.aktif.is_(True))))
        klaim_lama = list(db.scalars(select(ApprovedClaim.id).where(ApprovedClaim.product_id.in_(lama))))
        konten = ContentDraft(product_id=lama[0], tipe="artikel", topik="uji")
        db.add(konten)
        db.commit()
        kid = konten.id
        awal = _hitung_terlindungi(db)
        ledger_awal = db.scalar(select(func.count()).select_from(LedgerEvent))

    data = _pratinjau(client, admin)
    ditolak = client.post(f"/api/katalog/ganti/{data['token']}", headers=admin, json={"mode": "hapus", "konfirmasi": "ya"})
    assert ditolak.status_code == 409
    with SessionLocal() as db:
        assert db.scalar(select(KatalogImpor.status).where(KatalogImpor.token == data["token"])) == "pratinjau"
        assert db.get(Product, lama[0]) is not None

    r = client.post(f"/api/katalog/ganti/{data['token']}", headers=admin, json={"mode": "hapus", "konfirmasi": g.KONFIRMASI_HAPUS})
    assert r.status_code == 202, r.text
    st = client.get(f"/api/katalog/ganti/{data['token']}", headers=admin).json()
    assert st["status"] == "diterapkan", st

    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Product)) == 8
        assert not db.scalar(select(func.count()).select_from(ApprovedClaim).where(ApprovedClaim.id.in_(klaim_lama)
                                                                                    & ApprovedClaim.product_id.in_(lama)))
        assert not db.scalar(select(func.count()).select_from(PricingRule).where(PricingRule.product_id.in_(lama)))
        assert not db.scalar(select(func.count()).select_from(Chunk).where(Chunk.product_id.in_(lama)))
        assert not db.scalar(select(func.count()).select_from(VerifikasiFakta).where(
            VerifikasiFakta.objek_tipe == "produk", VerifikasiFakta.objek_id.in_(lama)))
        assert db.get(ContentDraft, kid).product_id is None  # draf tetap ada, kaitannya dilepas
        assert not db.scalars(select(Document).where(Document.judul.like("%data contoh%"))).first()
        assert _hitung_terlindungi(db) == awal
        assert db.scalar(select(func.count()).select_from(LedgerEvent)) > ledger_awal
        # Agent tetap menjawab wajar di percakapan baru.
        res = handle_inbound(db, channel="telegram", external_user_id="tg-ganti-2", text=f"ada {PRODUK_DEMO}?")
        assert PRODUK_DEMO not in " ".join(m.teks for m in res.replies).replace(PRODUK_DEMO.lower(), "")


def test_produk_yang_dirujuk_audit_tidak_dihapus_tetapi_tidak_terbaca_agent(client, admin, pulihkan):
    with SessionLocal() as db:
        p = db.scalar(select(Product).where(Product.aktif.is_(True)).order_by(Product.id))
        pid, nama = p.id, p.nama
        db.add(MarketingDraft(product_id=pid, teks="Draf pemasaran uji"))
        db.commit()

    data = _pratinjau(client, admin)
    dampak = client.get(f"/api/katalog/ganti/ringkasan?token={data['token']}", headers=admin).json()["dampak"]
    assert nama in dampak["produk_terkunci"]
    client.post(f"/api/katalog/ganti/{data['token']}", headers=admin, json={"mode": "hapus", "konfirmasi": g.KONFIRMASI_HAPUS})
    st = client.get(f"/api/katalog/ganti/{data['token']}", headers=admin).json()
    assert st["status"] == "diterapkan" and st["hasil"]["disingkirkan"]["produk_terkunci"] == 1, st

    with SessionLocal() as db:
        sisa = db.get(Product, pid)
        assert sisa is not None and sisa.aktif is False
        assert not db.scalar(select(func.count()).select_from(ApprovedClaim).where(ApprovedClaim.product_id == pid))


def test_gagal_di_tengah_jalan_katalog_lama_tetap_utuh(client, admin, pulihkan, monkeypatch):
    with SessionLocal() as db:
        lama = set(db.scalars(select(Product.nama).where(Product.aktif.is_(True))))

    def rusak(*a, **kw):
        raise RuntimeError("gagal buatan")

    monkeypatch.setattr(g, "_baris_verifikasi", rusak)
    data = _pratinjau(client, admin)
    assert client.post(f"/api/katalog/ganti/{data['token']}", headers=admin, json={"mode": "hapus", "konfirmasi": g.KONFIRMASI_HAPUS}).status_code == 202
    st = client.get(f"/api/katalog/ganti/{data['token']}", headers=admin).json()
    assert st["status"] == "pratinjau" and "tetap utuh" in st["gagal"] and "gagal buatan" not in st["gagal"]
    with SessionLocal() as db:
        assert set(db.scalars(select(Product.nama).where(Product.aktif.is_(True)))) == lama
        assert db.scalar(select(LedgerEvent).where(LedgerEvent.tipe_event == "katalog_ganti_gagal")) is not None


def test_pratinjau_lama_ditolak_setelah_katalog_berganti(client, admin, pulihkan):
    a = _pratinjau(client, admin)
    b = _pratinjau(client, admin)
    assert client.post(f"/api/katalog/ganti/{a['token']}", headers=admin, json={"mode": "nonaktif"}).status_code == 202
    assert client.post(f"/api/katalog/ganti/{a['token']}", headers=admin, json={"mode": "nonaktif"}).status_code == 409
    assert client.post(f"/api/katalog/ganti/{b['token']}", headers=admin, json={"mode": "nonaktif"}).status_code == 409


def test_hanya_admin_yang_bisa_mengganti(client, auth):
    assert client.get("/api/katalog/ganti/ringkasan", headers=auth).status_code == 403
    assert client.post("/api/katalog/ganti/apa-saja", headers=auth, json={"mode": "nonaktif"}).status_code == 403


def test_draf_dari_katalog_lama_tidak_bisa_disetujui_apa_adanya(client, admin, pulihkan):
    with SessionLocal() as db:
        cid = handle_inbound(db, channel="telegram", external_user_id="tg-ganti-3", text=f"harga {PRODUK_DEMO}?").conversation_id
        ap = Approval(objek_tipe="balasan", conversation_id=cid, draf=f"{PRODUK_DEMO} harganya Rp 3.960.000 per box.")
        db.add(ap)
        db.commit()
        ap_id = ap.id
        u = db.scalar(select(User).where(User.role == "admin"))
    data = _pratinjau(client, admin)
    client.post(f"/api/katalog/ganti/{data['token']}", headers=admin, json={"mode": "nonaktif"})
    with SessionLocal() as db:
        with pytest.raises(approvals.ApprovalError, match="sebelum katalog diganti"):
            approvals.decide(db, ap_id, aksi="setujui", user=u)
        db.rollback()
        assert approvals.decide(db, ap_id, aksi="tolak", user=u).status == "ditolak"
        assert db.get(Approval, ap_id).status == "ditolak"


def test_produk_usang_dibersihkan_dari_konteks(db):
    aktif = db.scalar(select(Product).where(Product.aktif.is_(True)).order_by(Product.id))
    konteks = {"last_product_ids": [aktif.id, 999999], "last_quote": {"product_id": 999999, "qty": 5}, "last_lines": [[999999, 2]],
               "order_pending": {"product_ids": [999999], "qty": 3}, "memori": {"produk": [aktif.nama, "Produk Lama"], "jumlah": {"Produk Lama": 3}},
               "sales": {"produk": "Produk Lama", "qty": 3}}
    bersih = produk_usang(db, konteks)
    assert bersih["last_product_ids"] == [aktif.id]
    assert bersih["last_quote"] is None and bersih["last_lines"] is None and bersih["order_pending"] is None
    assert bersih["memori"]["produk"] == [aktif.nama] and bersih["memori"]["jumlah"] == {}
    assert "produk" not in bersih["sales"] and bersih["sales"]["qty"] == 3
    assert produk_usang(db, {"last_product_ids": [aktif.id]}) == {}
    assert produk_usang(db, {}) == {}


def test_katalog_kosong_tidak_membuat_agent_mengarang(db, pulihkan):
    """Kriteria C: seluruh produk nonaktif. Agent tidak jatuh dan tidak menawarkan apa pun."""
    ids = list(db.scalars(select(Product.id).where(Product.aktif.is_(True))))
    nama = list(db.scalars(select(Product.nama).where(Product.aktif.is_(True))))
    db.query(Product).filter(Product.id.in_(ids)).update({"aktif": False}, synchronize_session=False)
    db.query(Chunk).filter(Chunk.product_id.in_(ids)).update({"aktif": False}, synchronize_session=False)
    db.commit()
    for i, tanya in enumerate(("produk apa saja yang ada?", "harga propolis berapa?", "mau pesan 10 box", "halo", "rekomendasi buat stamina dong")):
        res = handle_inbound(db, channel="telegram", external_user_id=f"tg-kosong-{i}", text=tanya)
        teks = " ".join(m.teks for m in res.replies)
        assert not any(n in teks for n in nama), (tanya, teks)
        assert "Rp" not in teks, (tanya, teks)
        assert "0 produk" not in teks and "*daftar produk*" not in teks, (tanya, teks)
    db.rollback()


def test_riwayat_llm_tidak_memuat_pesan_sebelum_katalog_diganti(db, pulihkan):
    handle_inbound(db, channel="telegram", external_user_id="tg-riwayat", text="harga propolis berapa?")
    conv = db.scalar(select(Conversation).join(Contact).where(Contact.external_user_id == "tg-riwayat"))
    settings_store.catat_katalog_diganti(db, {"pesan_id": max(m.id for m in conv.messages)}, "tes")
    handle_inbound(db, channel="telegram", external_user_id="tg-riwayat", text="halo lagi")
    db.refresh(conv)
    riwayat = drafter._history(conv)
    assert "halo lagi" in riwayat
    assert "propolis" not in riwayat.lower()
    db.rollback()  # transaksi terbuka akan memblokir DROP TABLE saat `pulihkan` berjalan di Postgres


def test_api_menolak_start_tanpa_database_online(monkeypatch, caplog):
    monkeypatch.setattr(main.settings, "database_url", "sqlite:///./aage.db")
    monkeypatch.setattr(main.settings, "izinkan_db_lokal", False)
    with pytest.raises(DatabaseOnlineError, match="menolak start"):
        main.pastikan_sumber_data()


def test_log_database_tidak_memuat_kredensial(monkeypatch, caplog):
    url = "postgresql+psycopg://pengguna-rahasia:sandi-rahasia@db.contoh.supabase.co:5432/postgres"
    monkeypatch.setattr(main.settings, "database_url", url)
    with caplog.at_level(logging.INFO, logger="aage"):
        main.pastikan_sumber_data()
    assert "db.contoh.supabase.co" in caplog.text
    assert "rahasia" not in caplog.text
    assert sumber_database(url) == {"jenis": "online", "host": "db.contoh.supabase.co", "nama": "postgres"}


def test_database_putus_pembeli_mendapat_pesan_aman(monkeypatch):
    from sqlalchemy.exc import OperationalError

    from aage import routes
    from aage.channels.base import InboundMessage

    terkirim = []

    class Adapter:
        def typing(self, _):
            pass

        def send_text(self, uid, teks, **_):
            terkirim.append((uid, teks))

    class SesiPutus:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def scalar(self, *_):
            raise OperationalError("select 1", {}, Exception("koneksi putus"))

        def rollback(self):
            pass

    monkeypatch.setattr(routes, "SessionLocal", SesiPutus)
    monkeypatch.setattr(registry, "get", lambda _: Adapter())
    routes._process_inbound([InboundMessage(channel="telegram", external_user_id="tg-putus", external_message_id="x1", text="harga madu?")])
    assert terkirim == [("tg-putus", routes.PESAN_DB_GANGGUAN)]
    assert "Rp" not in routes.PESAN_DB_GANGGUAN
