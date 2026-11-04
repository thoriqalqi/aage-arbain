"""Pagar Leads: izin per peran, samaran nomor, audit ekspor, consent, opt-out, dan asal data."""

import itertools
import json
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from aage import clock
from aage import db as db_mod
from aage.db import SessionLocal
from aage.models import LeadEvidence, LedgerEvent, Message, Prospect
from aage.prospects import lead_service, mapper, scoring_service

_nomor = itertools.count(1)
DRAF_AMAN = "Halo, bolehkah kami kirimkan katalog terbaru?"
CONSENT_SAH = {"status": "GRANTED", "sumber": "Formulir kunjungan", "cakupan": "promosi_whatsapp", "pada": "2026-10-01T09:00:00+07:00"}


def _token(client, email: str, sandi: str) -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": sandi})
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def admin(client):
    return _token(client, "admin@aage.local", "admin123")


@pytest.fixture
def marketing(client):
    return _token(client, "marketing@aage.local", "marketing123")


def _lead(telepon: str | None = "auto", **kolom) -> int:
    if telepon == "auto":
        telepon = f"0812-9000-{next(_nomor):04d}"
    with SessionLocal() as db:
        p = Prospect(nama=f"Apotek Uji {next(_nomor)}", wilayah="Kota Uji Pagar", tipe="Apotek", sumber="osm", telepon=telepon,
                     draf_pesan=DRAF_AMAN, **kolom)
        db.add(p)
        db.commit()
        return p.id


def _ambil(pid: int) -> Prospect:
    with SessionLocal() as db:
        return db.get(Prospect, pid)


def _jumlah_event(tipe: str, objek_ref: str | None = None) -> int:
    with SessionLocal() as db:
        stmt = select(func.count(LedgerEvent.id)).where(LedgerEvent.tipe_event == tipe)
        return db.scalar(stmt.where(LedgerEvent.objek_ref == objek_ref) if objek_ref else stmt)


def _promo(client, headers, pid: int):
    return client.post(f"/api/prospects/{pid}/kontak-promo", headers=headers)


def _consent(client, headers, pid: int, **isi):
    return client.put(f"/api/prospects/{pid}/consent", headers=headers, json=isi)


@pytest.mark.parametrize("metode,alamat", [
    ("get", "/api/prospects"), ("post", "/api/prospek/scout"), ("post", "/api/prospects/search"), ("patch", "/api/prospects/1"),
    ("put", "/api/prospects/1/consent"), ("post", "/api/prospects/1/kontak-promo"), ("post", "/api/prospects/1/riset"),
    ("get", "/api/prospects/export.csv"),
])
def test_marketing_tidak_punya_akses_leads(client, marketing, metode, alamat):
    isi = {"json": {}} if metode in ("put", "patch") or "scout" in alamat or "search" in alamat else {}
    assert getattr(client, metode)(alamat, headers=marketing, **isi).status_code == 403


def test_tanpa_login_ditolak(client):
    assert client.get("/api/prospects").status_code == 401
    assert client.get("/api/prospects/export.csv").status_code == 401


def test_nomor_disamarkan_untuk_staf_dan_utuh_untuk_admin(client, auth, admin):
    pid = _lead("0812-3456-7777")
    cari = {"wilayah": "Kota Uji Pagar", "tipe": "Apotek"}
    staf = next(i for i in client.get("/api/prospects", headers=auth, params=cari).json()["items"] if i["id"] == pid)
    assert staf["wa"] is None and staf["ada_wa"] is True
    assert "3456" not in staf["telepon"] and staf["telepon"].endswith("777")
    utuh = next(i for i in client.get("/api/prospects", headers=admin, params=cari).json()["items"] if i["id"] == pid)
    assert utuh["wa"] == "6281234567777" and utuh["telepon"] == "0812-3456-7777"


def test_ekspor_hanya_admin_dan_tercatat(client, auth, admin):
    _lead()
    sebelum = _jumlah_event("prospek_diekspor")
    assert client.get("/api/prospects/export.csv", headers=auth).status_code == 403
    assert _jumlah_event("prospek_diekspor") == sebelum, "penolakan bukan ekspor"
    r = client.get("/api/prospects/export.csv", headers=admin, params={"wilayah": "Kota Uji Pagar"})
    assert r.status_code == 200 and "Apotek Uji" in r.text
    assert _jumlah_event("prospek_diekspor") == sebelum + 1


def test_tanpa_consent_promosi_diblokir_dan_tercatat(client, auth):
    pid = _lead()
    r = _promo(client, auth, pid)
    assert r.status_code == 409 and r.json()["detail"]["kode"] == "CONSENT_REQUIRED"
    assert "wa.me" not in r.text
    assert _ambil(pid).status == "baru", "status tidak naik kalau ditolak"
    assert _jumlah_event("prospek_kontak_ditolak", f"prospect:{pid}") == 1
    assert _jumlah_event("prospek_kontak_dibuka", f"prospect:{pid}") == 0


@pytest.mark.parametrize("isi", [
    {"status": "GRANTED"},
    {**CONSENT_SAH, "sumber": "   "},
    {**CONSENT_SAH, "pada": None},
    {**CONSENT_SAH, "cakupan": "semua"},
    {**CONSENT_SAH, "cakupan": None},
    {"status": "SETUJU"},
])
def test_consent_tidak_lengkap_ditolak(client, auth, isi):
    pid = _lead()
    assert _consent(client, auth, pid, **isi).status_code == 400
    p = _ambil(pid)
    assert p.consent_status == "UNKNOWN" and p.consent_sumber is None
    assert _promo(client, auth, pid).json()["detail"]["kode"] == "CONSENT_REQUIRED"


def test_consent_masa_depan_ditolak(client, auth):
    pid = _lead()
    besok = (clock.now() + timedelta(days=1)).isoformat()
    assert _consent(client, auth, pid, **{**CONSENT_SAH, "pada": besok}).status_code == 400


def test_consent_sah_membuka_tautan_tanpa_mengirim_pesan(client, auth):
    pid = _lead("0812-3456-0001")
    with SessionLocal() as db:
        pesan_awal = db.scalar(select(func.count(Message.id)))
    r = _consent(client, auth, pid, **CONSENT_SAH)
    assert r.status_code == 200 and r.json()["consent_status"] == "GRANTED" and r.json()["consent_sumber"] == "Formulir kunjungan"
    assert _jumlah_event("prospek_consent", f"prospect:{pid}") == 1
    assert _consent(client, auth, pid, **CONSENT_SAH).status_code == 200
    assert _jumlah_event("prospek_consent", f"prospect:{pid}") == 1, "simpan ulang tanpa perubahan tidak menambah Ledger"

    r = _promo(client, auth, pid)
    assert r.status_code == 200 and r.json()["tautan"].startswith("https://wa.me/6281234560001?text=Halo%2C")
    assert r.json()["prospek"]["status"] == "dihubungi"
    assert r.json()["prospek"]["wa"] is None, "respons untuk staf tetap tersamar"
    assert _jumlah_event("prospek_kontak_dibuka", f"prospect:{pid}") == 1
    with SessionLocal() as db:
        assert db.scalar(select(func.count(Message.id))) == pesan_awal


def test_opt_out_mengalahkan_consent_dan_hanya_admin_yang_bisa_membatalkan(client, auth, admin):
    pid = _lead()
    assert _consent(client, auth, pid, **CONSENT_SAH).status_code == 200
    r = _consent(client, auth, pid, status="OPTED_OUT", sumber="Pemilik menolak lewat telepon")
    assert r.status_code == 200 and r.json()["consent_pada"], "waktu opt-out terisi otomatis"
    assert _promo(client, auth, pid).json()["detail"]["kode"] == "OPTED_OUT"

    for isi in (CONSENT_SAH, {"status": "UNKNOWN"}):
        assert _consent(client, auth, pid, **isi).status_code == 403
    assert _ambil(pid).consent_status == "OPTED_OUT"
    assert _consent(client, admin, pid, **CONSENT_SAH).status_code == 200
    assert _promo(client, auth, pid).status_code == 200


def test_opt_out_berlaku_untuk_nomor_yang_sama_di_lead_lain(client, auth):
    a = _lead("0812-3456-0002")
    b = _lead("+62 812 3456 0002")
    assert _consent(client, auth, b, **CONSENT_SAH).status_code == 200
    assert _consent(client, auth, a, status="OPTED_OUT").status_code == 200
    assert _promo(client, auth, b).json()["detail"]["kode"] == "OPTED_OUT"


def test_status_menolak_memblokir_promosi(client, auth):
    pid = _lead()
    assert _consent(client, auth, pid, **CONSENT_SAH).status_code == 200
    assert client.patch(f"/api/prospects/{pid}", headers=auth, json={"status": "menolak"}).status_code == 200
    assert _promo(client, auth, pid).json()["detail"]["kode"] == "OPTED_OUT"


def test_tanpa_nomor_dan_klaim_terlarang_ditolak(client, auth):
    tanpa = _lead(None)
    assert _consent(client, auth, tanpa, **CONSENT_SAH).status_code == 200
    assert _promo(client, auth, tanpa).json()["detail"]["kode"] == "TANPA_NOMOR"

    klaim = _lead()
    with SessionLocal() as db:
        db.get(Prospect, klaim).draf_pesan = "Madu kami pasti menyembuhkan kanker dan diabetes."
        db.commit()
    assert _consent(client, auth, klaim, **CONSENT_SAH).status_code == 200
    assert _promo(client, auth, klaim).json()["detail"]["kode"] == "KLAIM_DITOLAK"


def test_lead_tidak_ada(client, auth):
    assert _promo(client, auth, 999999).status_code == 404
    assert _consent(client, auth, 999999, status="UNKNOWN").status_code == 404


def test_pindai_mencatat_asal_data_sekali_saja(client, auth, monkeypatch):
    fixture = json.loads((Path(__file__).parent / "fixtures" / "overpass_kota_semarang_apotek.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(lead_service, "_post", lambda url, query, timeout_s: fixture)
    tubuh = {"wilayah": "Kota Asal Data", "jenis_toko": "Apotek"}
    data = client.post("/api/prospek/scout", headers=auth, json=tubuh).json()
    lead = data["items"][0]
    assert lead["skor_versi"] == scoring_service.VERSI_SKOR and lead["consent_status"] == "UNKNOWN" and lead["verifikasi"] == "belum"
    assert lead["dikumpulkan_pada"]
    client.post("/api/prospek/scout", headers=auth, json=tubuh)
    with SessionLocal() as db:
        bukti = list(db.scalars(select(LeadEvidence).where(LeadEvidence.lead_id == lead["id"])))
    assert [(b.source_type, b.source_reference) for b in bukti] == [("osm", lead["osm_id"])]
    assert bukti[0].dikumpulkan_pada and bukti[0].metadata_sumber


def test_isi_kolom_leads_idempoten():
    pid = _lead()
    db_mod._isi_kolom_leads()
    db_mod._isi_kolom_leads()
    with SessionLocal() as db:
        bukti = list(db.scalars(select(LeadEvidence).where(LeadEvidence.lead_id == pid)))
        p = db.get(Prospect, pid)
    assert len(bukti) == 1 and bukti[0].source_reference == f"prospect:{pid}" and p.dikumpulkan_pada and p.skor_versi


def test_telepon_opt_out_tidak_bocor_lewat_pesan_blokir(client, auth):
    a = _lead("0812-3456-0003")
    b = _lead("0812-3456-0003")
    assert _consent(client, auth, b, **CONSENT_SAH).status_code == 200
    assert _consent(client, auth, a, status="OPTED_OUT").status_code == 200
    assert "3456" not in _promo(client, auth, b).text


def test_wa_number_tetap_dipakai_untuk_tautan():
    assert mapper.wa_number("0812-3456-0001") == "6281234560001"
