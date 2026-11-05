"""Lead masuk, dedupe, verifikasi, dan skor: input manual, impor dengan konfirmasi, keputusan duplikat, bobot, dan riwayat."""

import io
import itertools

import pytest
from openpyxl import Workbook
from sqlalchemy import func, select

from aage.db import SessionLocal
from aage.models import LeadDuplikat, LeadEvidence, LeadImpor, LeadSkorRiwayat, LedgerEvent, Message, Prospect
from aage.prospects import dedupe, scoring_service
from aage.prospects.mapper import to_csv

_urut = itertools.count(100)
JUDUL = "nama,tipe,wilayah,alamat,telepon,website,lat,lng,jam_buka,referensi"


def _token(client, email, sandi):
    return {"Authorization": f"Bearer {client.post('/api/auth/login', json={'email': email, 'password': sandi}).json()['token']}"}


@pytest.fixture
def admin(client):
    return _token(client, "admin@aage.local", "admin123")


@pytest.fixture
def marketing(client):
    return _token(client, "marketing@aage.local", "marketing123")


def _wilayah() -> str:
    return f"Kota Uji {next(_urut)}"


def _unggah(client, headers, isi: str | bytes, nama="daftar.csv", source_type="daftar_mitra", ref="Daftar dari CV Arba'in, Nov 2026"):
    data = isi.encode("utf-8") if isinstance(isi, str) else isi
    return client.post("/api/prospects/impor", headers=headers, files={"file": (nama, data)}, data={"source_type": source_type, "source_reference": ref})


def _terapkan(client, headers, token, **isi):
    return client.post(f"/api/prospects/impor/{token}/terapkan", headers=headers, json=isi)


def _manual(client, headers, **isi):
    return client.post("/api/prospects", headers=headers, json={"tipe": "Apotek", **isi})


def _baris_ledger(tipe):
    with SessionLocal() as db:
        return db.scalar(select(func.count(LedgerEvent.id)).where(LedgerEvent.tipe_event == tipe))


# ------------------------------------------------------------------ input manual


def test_input_manual_tersimpan_dengan_asal_data_dan_tanpa_consent(client, auth):
    w = _wilayah()
    r = _manual(client, auth, nama="  Apotek   Sehat  ", wilayah=w.lower(), alamat="Jl. Uji 1", telepon="0812-1111-0001", lat=-6.99, lng=110.42, referensi="Kunjungan 3 Nov")
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["nama"] == "Apotek Sehat" and d["wilayah"] == w and d["sumber"] == "manual"
    assert d["consent_status"] == "UNKNOWN" and d["skor_versi"] == client.get("/api/prospects/konfigurasi", headers=auth).json()["versi"] and d["skor_sementara"] is True
    assert d["confidence"] == 0.6 and d["wa"] is None
    detail = client.get(f"/api/prospects/{d['id']}", headers=auth).json()
    assert [(b["source_type"], b["source_reference"]) for b in detail["bukti"]] == [("manual", "Kunjungan 3 Nov")]
    assert detail["riwayat_skor"][0]["pemicu"] == "manual"
    assert any(a["tipe"] == "prospek_dibuat" for a in detail["aktivitas"])
    assert client.get("/api/prospects", headers=auth, params={"wilayah": w}).json()["total"] == 1


@pytest.mark.parametrize("isi,kolom", [
    ({"nama": "", "wilayah": "Kota A"}, "nama"),
    ({"nama": "=HYPERLINK(1)", "wilayah": "Kota A"}, "nama"),
    ({"nama": "Apotek A", "wilayah": ""}, "wilayah"),
    ({"nama": "Apotek A", "wilayah": "Kota A", "tipe": "Warung"}, "tipe"),
    ({"nama": "Apotek A", "wilayah": "Kota A", "telepon": "12345"}, "telepon"),
    ({"nama": "Apotek A", "wilayah": "Kota A", "website": "javascript:alert(1)"}, "website"),
    ({"nama": "Apotek A", "wilayah": "Kota A", "lat": 50.0, "lng": 110.0}, "lat"),
    ({"nama": "Apotek A", "wilayah": "Kota A", "lat": -6.9}, "lng"),
])
def test_input_manual_tidak_valid_ditolak_jelas(client, auth, isi, kolom):
    with SessionLocal() as db:
        awal = db.scalar(select(func.count(Prospect.id)))
    r = _manual(client, auth, **isi)
    assert r.status_code == 400 and r.json()["detail"]["kode"] == "VALIDASI"
    assert kolom in [k["kolom"] for k in r.json()["detail"]["kesalahan"]]
    with SessionLocal() as db:
        assert db.scalar(select(func.count(Prospect.id))) == awal


def test_duplikat_pasti_ditolak_dan_calon_duplikat_masuk_antrean(client, auth):
    w = _wilayah()
    a = _manual(client, auth, nama="Apotek Waras", wilayah=w, telepon="0812-1111-0002").json()
    r = _manual(client, auth, nama="apotek WARAS", wilayah=w, telepon="+62 812 1111 0002")
    assert r.status_code == 409 and r.json()["detail"]["lead_id"] == a["id"]

    b = _manual(client, auth, nama="Apotek Waras", wilayah=w, alamat="Jl. Cabang 2")
    assert b.status_code == 201 and b.json()["calon_duplikat"][0]["id"] == a["id"]
    assert b.json()["status_verifikasi"] == "perlu_tinjauan" and "Ada calon duplikat" in b.json()["alasan_tinjauan"]
    assert "nama_wilayah" in [x["aturan"] for x in b.json()["calon_duplikat"][0]["alasan"]]


def test_nomor_sama_nama_beda_tidak_pernah_pasti():
    a = dedupe.kandidat(1, {"nama": "Apotek Satu", "wilayah": "Kota X", "telepon": "081211110003"})
    b = dedupe.kandidat(2, {"nama": "Toko Obat Dua", "wilayah": "Kota Y", "telepon": "+6281211110003"})
    tingkat, alasan = dedupe.bandingkan(a, b)
    assert tingkat == "mungkin" and alasan[0]["aturan"] == "nomor"


def test_hasil_dedupe_deterministik_dan_nama_mirip_dikenali():
    daftar = [dedupe.kandidat(i, {"nama": n, "wilayah": "Kota X"}) for i, n in ((3, "Apotek Sumber Waras"), (1, "Apotek Sumber Waras"), (2, "Apotek Sumber Warass"), (4, "Apotek Lain"))]
    indeks = dedupe.Indeks(daftar)
    k = dedupe.kandidat(9, {"nama": "Apotik Sumber Waras", "wilayah": "kota x"})
    hasil = indeks.cari(k)
    assert [h["id"] for h in hasil] == [1, 2, 3] and hasil == indeks.cari(k)
    assert hasil[1]["alasan"][0]["aturan"] == "nama_mirip"


# ------------------------------------------------------------------ impor


def test_impor_pratinjau_tidak_menyimpan_sampai_dikonfirmasi(client, admin):
    w = _wilayah()
    isi = f"{JUDUL}\nApotek Impor Satu,Apotek,{w},Jl. Satu,0812-2222-0001,,-6.99,110.42,Senin-Sabtu,ID-1\nToko Impor Dua,Toko Obat,{w},,,,,,,ID-2\n"
    r = _unggah(client, admin, isi)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "pratinjau" and d["laporan"]["ringkasan"]["baru"] == 2 and d["laporan"]["ringkasan"]["error"] == 0
    assert "0812" not in str(d["laporan"]), "pratinjau tidak mengulang nomor"
    assert client.get("/api/prospects", headers=admin, params={"wilayah": w}).json()["total"] == 0

    h = _terapkan(client, admin, d["token"])
    assert h.status_code == 200 and h.json()["status"] == "diterapkan" and h.json()["hasil"]["baru"] == 2
    items = client.get("/api/prospects", headers=admin, params={"wilayah": w}).json()["items"]
    assert {i["sumber"] for i in items} == {"daftar_mitra"} and {i["consent_status"] for i in items} == {"UNKNOWN"}
    satu = next(i for i in items if i["nama"] == "Apotek Impor Satu")
    bukti = client.get(f"/api/prospects/{satu['id']}", headers=admin).json()["bukti"][0]
    assert bukti["source_type"] == "daftar_mitra" and bukti["source_reference"].endswith("ID-1") and bukti["dikumpulkan_pada"]
    with SessionLocal() as db:
        assert db.scalar(select(LeadImpor).where(LeadImpor.token == d["token"])).baris == [], "isi baris dihapus setelah diterapkan"


def test_impor_diulang_tidak_menggandakan(client, admin):
    w = _wilayah()
    isi = f"{JUDUL}\nApotek Ulang,Apotek,{w},,0812-2222-0002,,,,,\n"
    tok = _unggah(client, admin, isi).json()["token"]
    pertama = _terapkan(client, admin, tok).json()
    event = _baris_ledger("prospek_diimpor")
    assert _terapkan(client, admin, tok).json()["hasil"] == pertama["hasil"]
    assert _baris_ledger("prospek_diimpor") == event, "permintaan ulang tidak menambah Ledger"
    assert client.get("/api/prospects", headers=admin, params={"wilayah": w}).json()["total"] == 1

    kedua = _unggah(client, admin, isi).json()
    assert kedua["laporan"]["ringkasan"]["digabung"] == 1 and kedua["laporan"]["ringkasan"]["baru"] == 0
    assert any("sudah pernah" in p for p in kedua["laporan"]["peringatan"])
    assert _terapkan(client, admin, kedua["token"]).json()["hasil"]["digabung"] == 1
    assert client.get("/api/prospects", headers=admin, params={"wilayah": w}).json()["total"] == 1


def test_baris_salah_dilaporkan_dan_wajib_konfirmasi_melewati(client, admin):
    w = _wilayah()
    isi = (f"{JUDUL}\nApotek Benar,Apotek,{w},,,,,,,\n,Apotek,{w},,,,,,,\nApotek Nomor Salah,Apotek,{w},,123,,,,,\n"
           f"Warung Salah,Warung,{w},,,,,,,\n=SUM(1),Apotek,{w},,,,,,,\n")
    d = _unggah(client, admin, isi).json()
    assert d["laporan"]["ringkasan"]["error"] == 4 and d["laporan"]["ringkasan"]["valid"] == 1
    assert {(e["baris"], e["kolom"]) for e in d["laporan"]["error"]} == {(3, "nama"), (4, "telepon"), (5, "tipe"), (6, "nama")}
    r = _terapkan(client, admin, d["token"])
    assert r.status_code == 409 and "4 baris salah" in r.json()["detail"]
    assert client.get("/api/prospects", headers=admin, params={"wilayah": w}).json()["total"] == 0
    h = _terapkan(client, admin, d["token"], lewati_error=True).json()
    assert h["hasil"]["baru"] == 1 and h["hasil"]["dilewati_salah"] == 4


def test_kembar_dalam_file_dan_gabung_mengisi_yang_kosong(client, admin):
    w = _wilayah()
    lama = _manual(client, admin, nama="Apotek Lama", wilayah=w, telepon="0812-2222-0003").json()
    isi = (f"{JUDUL}\nApotek Lama,Apotek,{w},Jl. Baru 9,0812-2222-0003,,,,,\n"
           f"Apotek Kembar,Apotek,{w},,0812-2222-0004,,,,,\nApotek Kembar,Apotek,{w},,0812 2222 0004,,,,,\n")
    d = _unggah(client, admin, isi).json()
    assert d["laporan"]["ringkasan"] | {"baris": 0, "valid": 0} == {"baris": 0, "valid": 0, "error": 0, "baru": 1, "digabung": 1, "perlu_tinjauan": 0, "kembar_file": 1}
    assert d["laporan"]["kembar_file"][0]["sama_dengan_baris"] == 3
    assert d["laporan"]["digabung"][0]["alasan"] == ["Nomor, nama, dan wilayah sama"]
    _terapkan(client, admin, d["token"])
    detail = client.get(f"/api/prospects/{lama['id']}", headers=admin).json()
    assert detail["alamat"] == "Jl. Baru 9" and detail["alamat_jalan_ada"] is True
    assert {b["source_type"] for b in detail["bukti"]} == {"manual", "daftar_mitra"}
    assert client.get("/api/prospects", headers=admin, params={"wilayah": w}).json()["total"] == 2


def test_kolom_consent_di_file_diabaikan(client, admin):
    w = _wilayah()
    d = _unggah(client, admin, f"nama,tipe,wilayah,telepon,consent,kolom_aneh\nApotek Klaim Izin,Apotek,{w},0812-2222-0005,GRANTED,x\n").json()
    assert any("consent" in p.lower() for p in d["laporan"]["peringatan"]) and any("kolom_aneh" in p for p in d["laporan"]["peringatan"])
    _terapkan(client, admin, d["token"])
    item = client.get("/api/prospects", headers=admin, params={"wilayah": w}).json()["items"][0]
    assert item["consent_status"] == "UNKNOWN"
    assert client.post(f"/api/prospects/{item['id']}/kontak-promo", headers=admin).json()["detail"]["kode"] == "CONSENT_REQUIRED"


def test_impor_excel_dan_alias_kolom(client, admin):
    w = _wilayah()
    wb = Workbook()
    ws = wb.active
    ws.append(["Nama Toko", "Segmen", "Kota", "No HP"])
    ws.append(["Apotek Excel", "apotek", w, 81222220006])
    buf = io.BytesIO()
    wb.save(buf)
    d = _unggah(client, admin, buf.getvalue(), nama="daftar.xlsx").json()
    assert d["laporan"]["ringkasan"]["baru"] == 1, d
    _terapkan(client, admin, d["token"])
    item = client.get("/api/prospects", headers=admin, params={"wilayah": w}).json()["items"][0]
    assert item["tipe"] == "Apotek" and item["wa"] == "6281222220006"


@pytest.mark.parametrize("nama,isi,ref,sumber,pesan", [
    ("a.txt", "x", "Daftar mitra", "daftar_mitra", "harus .xlsx"),
    ("a.csv", "kolom\nx\n", "Daftar mitra", "daftar_mitra", "Kolom wajib"),
    ("a.csv", "nama,tipe,wilayah\n", "Daftar mitra", "daftar_mitra", "tidak berisi baris"),
    ("a.csv", "nama,tipe,wilayah\nA B,Apotek,Kota\n", "Daftar mitra", "scraping", "Sumber harus"),
    ("a.csv", "nama,tipe,wilayah\nA B,Apotek,Kota\n", "x", "daftar_mitra", "keterangan sumber"),
    ("a.xlsx", "bukan excel", "Daftar mitra", "daftar_mitra", "tidak bisa dibaca"),
])
def test_file_atau_sumber_ditolak(client, admin, nama, isi, ref, sumber, pesan):
    r = _unggah(client, admin, isi, nama=nama, source_type=sumber, ref=ref)
    assert r.status_code == 400 and pesan in r.json()["detail"]


def test_batal_menghapus_isi_dan_tidak_bisa_diterapkan(client, admin):
    w = _wilayah()
    tok = _unggah(client, admin, f"nama,tipe,wilayah\nApotek Batal,Apotek,{w}\n").json()["token"]
    assert client.post(f"/api/prospects/impor/{tok}/batal", headers=admin).json()["status"] == "dibatalkan"
    assert _terapkan(client, admin, tok).status_code == 409
    with SessionLocal() as db:
        assert db.scalar(select(LeadImpor).where(LeadImpor.token == tok)).baris == []


def test_izin_impor_dan_konfigurasi(client, auth, admin, marketing):
    isi = "nama,tipe,wilayah\nApotek Izin,Apotek,Kota Izin\n"
    assert _unggah(client, auth, isi).status_code == 403
    assert _unggah(client, marketing, isi).status_code == 403
    tok = _unggah(client, admin, isi).json()["token"]
    assert _terapkan(client, auth, tok).status_code == 403
    assert client.post(f"/api/prospects/impor/{tok}/batal", headers=auth).status_code == 403
    assert client.get("/api/prospects/impor/template.csv", headers=auth).status_code == 403
    assert client.put("/api/prospects/konfigurasi", headers=auth, json={"ambang_confidence": 0.1}).status_code == 403
    assert client.post("/api/prospects/skor/hitung-ulang", headers=auth).status_code == 403
    for metode, alamat in (("get", "/api/prospects/tinjauan"), ("get", "/api/prospects/1"), ("post", "/api/prospects/dedupe/pindai"), ("get", "/api/prospects/konfigurasi")):
        assert getattr(client, metode)(alamat, headers=marketing).status_code == 403
    assert client.post("/api/prospects", headers=marketing, json={"nama": "A B", "tipe": "Apotek", "wilayah": "K L"}).status_code == 403
    assert client.post("/api/prospects/duplikat/1/putuskan", headers=marketing, json={"keputusan": "bukan_duplikat"}).status_code == 403


def test_impor_tidak_mengirim_pesan(client, admin):
    with SessionLocal() as db:
        awal = db.scalar(select(func.count(Message.id)))
    tok = _unggah(client, admin, f"nama,tipe,wilayah,telepon\nApotek Sunyi,Apotek,{_wilayah()},0812-2222-0007\n").json()["token"]
    _terapkan(client, admin, tok)
    with SessionLocal() as db:
        assert db.scalar(select(func.count(Message.id))) == awal


# ------------------------------------------------------------------ keputusan duplikat dan verifikasi


def _pasangan(client, headers, w, telepon_a="0812-3333-0001"):
    a = _manual(client, headers, nama="Apotek Kembar", wilayah=w, telepon=telepon_a).json()
    b = _manual(client, headers, nama="Apotek Kembar", wilayah=w, alamat="Jl. Dua", website="contoh.id", referensi="Kunjungan kedua").json()
    antrean = client.get("/api/prospects/tinjauan", headers=headers).json()["duplikat"]
    d = next(x for x in antrean if {x["lead"]["id"], x["cocok"]["id"]} == {a["id"], b["id"]})
    return a, b, d


def test_gabung_memindahkan_data_dan_mencatat_alasan(client, auth):
    w = _wilayah()
    a, b, d = _pasangan(client, auth, w)
    assert d["tingkat"] == "mungkin" and d["alasan"][0]["aturan"] == "nama_wilayah"
    assert "3333" not in str(d["lead"]["telepon"]) + str(d["cocok"]["telepon"]), "nomor tetap tersamar di antrean"
    r = client.post(f"/api/prospects/duplikat/{d['id']}/putuskan", headers=auth, json={"keputusan": "digabung", "utama_id": a["id"]})
    assert r.status_code == 200
    utama = client.get(f"/api/prospects/{a['id']}", headers=auth).json()
    assert utama["alamat"] == "Jl. Dua" and utama["website"] == "https://contoh.id"
    assert {b_["source_type"] for b_ in utama["bukti"]} == {"manual"} and len(utama["bukti"]) == 2
    assert "Ada calon duplikat" not in utama["alasan_tinjauan"]
    assert utama["riwayat_skor"][0]["pemicu"] == "gabung"
    kedua = client.get(f"/api/prospects/{b['id']}", headers=auth).json()
    assert kedua["digabung_ke_id"] == a["id"]
    assert [i["id"] for i in client.get("/api/prospects", headers=auth, params={"wilayah": w}).json()["items"]] == [a["id"]]
    assert client.post(f"/api/prospects/{b['id']}/kontak-promo", headers=auth).json()["detail"]["kode"] == "DIGABUNG"
    with SessionLocal() as db:
        ev = db.scalar(select(LedgerEvent).where(LedgerEvent.tipe_event == "prospek_digabung", LedgerEvent.objek_ref == f"prospect:{a['id']}"))
        assert ev.alasan and ev.data["duplikat"] == b["id"]
    assert client.post(f"/api/prospects/duplikat/{d['id']}/putuskan", headers=auth, json={"keputusan": "bukan_duplikat"}).status_code == 400, "tidak bisa diputus dua kali"


def test_alamat_tidak_spesifik_diisi_saat_gabung_dan_impor(client, auth, admin):
    w = _wilayah()
    with SessionLocal() as db:
        kosong = Prospect(nama="Apotek Alamat Kosong", wilayah=w, tipe="Apotek", sumber="osm", alamat="Alamat tidak spesifik", alamat_jalan_ada=False, telepon="0812-3333-0011")
        lengkap = Prospect(nama="Apotek Alamat Kosong", wilayah=w, tipe="Apotek", sumber="osm", alamat="Jl. Lengkap 7", alamat_jalan_ada=True)
        db.add_all([kosong, lengkap])
        db.commit()
        id_kosong, id_lengkap = kosong.id, lengkap.id
    client.post("/api/prospects/dedupe/pindai", headers=auth)
    d = next(x for x in client.get("/api/prospects/tinjauan", headers=auth).json()["duplikat"] if x["lead"]["wilayah"] == w)
    assert client.post(f"/api/prospects/duplikat/{d['id']}/putuskan", headers=auth, json={"keputusan": "digabung", "utama_id": id_kosong}).status_code == 200
    hasil = client.get(f"/api/prospects/{id_kosong}", headers=auth).json()
    assert hasil["alamat"] == "Jl. Lengkap 7" and hasil["alamat_jalan_ada"] is True and "Alamat jalan kosong" not in hasil["alasan_tinjauan"]
    assert client.get(f"/api/prospects/{id_lengkap}", headers=auth).json()["digabung_ke_id"] == id_kosong

    w2 = _wilayah()
    with SessionLocal() as db:
        lama = Prospect(nama="Apotek Impor Alamat", wilayah=w2, tipe="Apotek", sumber="osm", alamat="Alamat tidak spesifik", alamat_jalan_ada=False, telepon="0812-3333-0012")
        db.add(lama)
        db.commit()
        id_lama = lama.id
    tok = _unggah(client, admin, f"nama,tipe,wilayah,alamat,telepon\nApotek Impor Alamat,Apotek,{w2},Jl. Dari File 3,0812-3333-0012\n").json()["token"]
    assert _terapkan(client, admin, tok).json()["hasil"]["digabung"] == 1
    hasil = client.get(f"/api/prospects/{id_lama}", headers=admin).json()
    assert hasil["alamat"] == "Jl. Dari File 3" and hasil["alamat_jalan_ada"] is True


def test_opt_out_ikut_saat_digabung(client, auth):
    w = _wilayah()
    a, b, d = _pasangan(client, auth, w, "0812-3333-0002")
    assert client.put(f"/api/prospects/{b['id']}/consent", headers=auth, json={"status": "OPTED_OUT", "sumber": "Menolak"}).status_code == 200
    client.post(f"/api/prospects/duplikat/{d['id']}/putuskan", headers=auth, json={"keputusan": "digabung", "utama_id": a["id"]})
    assert client.get(f"/api/prospects/{a['id']}", headers=auth).json()["consent_status"] == "OPTED_OUT"


def test_bukan_duplikat_tidak_diangkat_lagi(client, auth):
    w = _wilayah()
    _a, _b, d = _pasangan(client, auth, w, "0812-3333-0003")
    assert client.post(f"/api/prospects/duplikat/{d['id']}/putuskan", headers=auth, json={"keputusan": "bukan_duplikat"}).status_code == 200
    client.post("/api/prospects/dedupe/pindai", headers=auth)
    with SessionLocal() as db:
        assert db.get(LeadDuplikat, d["id"]).keputusan == "bukan_duplikat"
    assert d["id"] not in [x["id"] for x in client.get("/api/prospects/tinjauan", headers=auth).json()["duplikat"]]


def test_keputusan_tidak_sah_ditolak(client, auth):
    w = _wilayah()
    _a, _b, d = _pasangan(client, auth, w, "0812-3333-0004")
    url = f"/api/prospects/duplikat/{d['id']}/putuskan"
    assert client.post(url, headers=auth, json={"keputusan": "hapus"}).status_code == 400
    assert client.post(url, headers=auth, json={"keputusan": "digabung", "utama_id": 999999}).status_code == 400
    assert client.post("/api/prospects/duplikat/999999/putuskan", headers=auth, json={"keputusan": "bukan_duplikat"}).status_code == 404


def test_pindai_duplikat_menemukan_data_lama_dan_idempoten(client, auth):
    w = _wilayah()
    with SessionLocal() as db:
        for nama, tel in (("Apotek Lama Kembar", "0812-3333-0005"), ("Apotek Lama Kembar", "0812-3333-0005"), ("Lead Demo", "0812-3333-0005")):
            db.add(Prospect(nama=nama, wilayah=w, tipe="Apotek", sumber="sintetis" if nama == "Lead Demo" else "osm", telepon=tel))
        db.commit()
    r = client.post("/api/prospects/dedupe/pindai", headers=auth).json()
    assert r["calon_baru"] >= 1
    assert client.post("/api/prospects/dedupe/pindai", headers=auth).json()["calon_baru"] == 0
    antrean = client.get("/api/prospects/tinjauan", headers=auth).json()["duplikat"]
    cocok = [x for x in antrean if x["lead"]["wilayah"] == w]
    assert len(cocok) == 1 and cocok[0]["tingkat"] == "pasti", "data demo tidak ikut dicocokkan, dan tidak digabung otomatis"
    assert all(x["lead"]["sumber"] != "sintetis" and x["cocok"]["sumber"] != "sintetis" for x in antrean)


def test_verifikasi_dan_data_kurang_ditandai(client, auth):
    w = _wilayah()
    d = _manual(client, auth, nama="Apotek Kurang", wilayah=w).json()
    assert d["status_verifikasi"] == "perlu_tinjauan"
    assert set(d["alasan_tinjauan"]) >= {"Nomor telepon kosong", "Alamat jalan kosong", "Koordinat kosong"} and d["confidence"] == 0
    assert d["id"] in [x["id"] for x in client.get("/api/prospects/tinjauan", headers=auth).json()["perlu_tinjauan"]]
    assert [i["id"] for i in client.get("/api/prospects", headers=auth, params={"wilayah": w, "verifikasi": "perlu_tinjauan"}).json()["items"]] == [d["id"]]

    assert client.put(f"/api/prospects/{d['id']}/verifikasi", headers=auth, json={"status": "palsu"}).status_code == 400
    v = client.put(f"/api/prospects/{d['id']}/verifikasi", headers=auth, json={"status": "terverifikasi", "catatan": "Sudah dikunjungi"}).json()
    assert v["status_verifikasi"] == "terverifikasi" and v["terakhir_diverifikasi"] and v["confidence"] == 0.2
    assert d["id"] not in [x["id"] for x in client.get("/api/prospects/tinjauan", headers=auth).json()["perlu_tinjauan"]]
    t = client.put(f"/api/prospects/{d['id']}/verifikasi", headers=auth, json={"status": "ditolak"}).json()
    assert t["status_verifikasi"] == "ditolak" and "ditolak" in t["langkah_berikutnya"]
    assert client.post(f"/api/prospects/{d['id']}/kontak-promo", headers=auth).json()["detail"]["kode"] == "DITOLAK_VERIFIKASI"


def test_ubah_nomor_membatalkan_consent_dan_menghitung_skor_ulang(client, auth):
    d = _manual(client, auth, nama="Apotek Ganti Nomor", wilayah=_wilayah(), telepon="0812-3333-0006").json()
    client.put(f"/api/prospects/{d['id']}/consent", headers=auth, json={"status": "GRANTED", "sumber": "Formulir", "cakupan": "promosi_whatsapp", "pada": "2026-10-01T00:00:00Z"})
    r = client.patch(f"/api/prospects/{d['id']}/data", headers=auth, json={"telepon": "0812-3333-0007", "alamat": "Jl. Baru"}).json()
    assert r["consent_status"] == "UNKNOWN" and r["alamat"] == "Jl. Baru" and r["confidence"] > d["confidence"]
    assert client.patch(f"/api/prospects/{d['id']}/data", headers=auth, json={"telepon": "12"}).status_code == 400
    sama = client.get(f"/api/prospects/{d['id']}", headers=auth).json()
    assert sama["riwayat_skor"][0]["pemicu"] == "ubah_data"


def test_filter_daftar(client, auth):
    w = _wilayah()
    a = _manual(client, auth, nama="Apotek Filter Tinggi", wilayah=w, telepon="0812-3333-0008", alamat="Jl. A", lat=-6.99, lng=110.45, jam_buka="Senin").json()
    b = _manual(client, auth, nama="Toko Filter Rendah", wilayah=w, tipe="Toko Obat").json()
    daftar = lambda **f: [i["id"] for i in client.get("/api/prospects", headers=auth, params={"wilayah": w, **f}).json()["items"]]
    assert daftar() == [a["id"], b["id"]], "urut dari skor tertinggi"
    assert daftar(tipe="toko obat") == [b["id"]]
    assert daftar(q="tinggi") == [a["id"]]
    assert daftar(q="100%") == []
    assert daftar(skor_min=50) == [a["id"]] and daftar(skor_maks=10) == [b["id"]]
    assert daftar(sumber="osm") == [] and daftar(sumber="manual") == [a["id"], b["id"]]
    assert daftar(consent_status="GRANTED") == []
    assert client.get("/api/prospects", headers=auth, params={"skor_min": 101}).status_code == 422


# ------------------------------------------------------------------ skor


def test_skor_tanpa_koordinat_tidak_gagal_dan_jujur():
    s = scoring_service.opportunity_score({"name": "Apotek A", "phone": "0812", "opening_hours": None, "has_street": False, "asal": "data"})
    assert s["skor"] == 10 and s["jarak_km"] is None and "Koordinat belum ada" in s["alasan"][0]["keterangan"]
    assert s["alasan"][1]["keterangan"] == "Tersedia", "nomor tidak masuk rincian skor"


def test_bobot_diubah_menaikkan_versi_dan_riwayat_tersimpan(client, auth, admin):
    d = _manual(client, auth, nama="Apotek Bobot", wilayah=_wilayah(), telepon="0812-3333-0009", lat=-6.99, lng=110.45).json()
    awal = client.get("/api/prospects/konfigurasi", headers=admin).json()
    assert awal["sementara"] is True
    for salah in ({"bobot": {"telepon": 50}}, {"bobot": {"palsu": 1}}, {"bobot": {"telepon": "x"}}, {"ambang_confidence": 2}, {"segmen": []}, {"segmen": ["A", "a"]}):
        assert client.put("/api/prospects/konfigurasi", headers=admin, json=salah).status_code == 400, salah
    assert client.get("/api/prospects/konfigurasi", headers=admin).json() == awal, "gagal validasi tidak mengubah apa pun"

    baru = {**awal["bobot"], "geo_maks": 60, "telepon": 20}
    k = client.put("/api/prospects/konfigurasi", headers=admin, json={"bobot": baru}).json()
    assert k["versi"] != awal["versi"] and k["bobot"]["telepon"] == 20
    tetap = client.get(f"/api/prospects/{d['id']}", headers=auth).json()
    assert tetap["skor_versi"] == awal["versi"], "skor lama tetap sampai dihitung ulang"

    h = client.post("/api/prospects/skor/hitung-ulang", headers=admin).json()
    assert h["versi"] == k["versi"] and h["berubah"] >= 1
    sesudah = client.get(f"/api/prospects/{d['id']}", headers=auth).json()
    assert sesudah["skor_versi"] == k["versi"] and [r["pemicu"] for r in sesudah["riwayat_skor"]][:2] == ["hitung_ulang", "manual"]
    assert any(f["faktor"] == "Telepon" and f["maks"] == 20 for f in sesudah["alasan_skor"])
    assert client.post("/api/prospects/skor/hitung-ulang", headers=admin).json()["berubah"] == 0, "tanpa perubahan tidak menambah riwayat"

    assert client.put("/api/prospects/konfigurasi", headers=admin, json={"bobot": awal["bobot"]}).status_code == 200
    client.post("/api/prospects/skor/hitung-ulang", headers=admin)


def test_segmen_bisa_diatur(client, auth, admin):
    awal = client.get("/api/prospects/konfigurasi", headers=admin).json()["segmen"]
    assert _manual(client, auth, nama="Klinik Uji", tipe="Klinik", wilayah=_wilayah()).status_code == 400
    assert client.put("/api/prospects/konfigurasi", headers=admin, json={"segmen": [*awal, "Klinik"]}).status_code == 200
    assert _manual(client, auth, nama="Klinik Uji", tipe="klinik", wilayah=_wilayah()).json()["tipe"] == "Klinik"
    assert client.put("/api/prospects/konfigurasi", headers=admin, json={"segmen": awal}).status_code == 200


def test_nomor_lama_di_rincian_skor_dan_nba_tidak_bocor_ke_staf(client, auth, admin):
    d = _manual(client, admin, nama="Apotek Data Lama", wilayah=_wilayah(), telepon="0812-3333-0010").json()
    with SessionLocal() as db:
        p = db.get(Prospect, d["id"])
        p.alasan_skor = [{"faktor": "Telepon", "poin": 10, "maks": 10, "keterangan": "0812-3333-0010"}]
        p.nba = {"teks": "Hubungi via telepon/WhatsApp 0812-3333-0010", "dasar": ["x"], "produk": []}
        db.commit()
    assert "3333" not in client.get(f"/api/prospects/{d['id']}", headers=auth).text
    assert "0812-3333-0010" in client.get(f"/api/prospects/{d['id']}", headers=admin).text


def test_detail_tidak_ada(client, auth):
    assert client.get("/api/prospects/999999", headers=auth).status_code == 404


def test_csv_melindungi_dari_rumus():
    teks = to_csv([Prospect(nama="=CMD()", tipe="Apotek", alamat="@a", telepon="+62812", sumber="manual", skor=1, skor_geo=0, skor_data=0, status="baru", draf_pesan="-x", consent_status="UNKNOWN", verifikasi="belum")])
    baris = teks.splitlines()[1]
    assert "'=CMD()" in baris and "'@a" in baris and "'+62812" in baris and "'-x" in baris


def test_bukti_dan_riwayat_tidak_kembar_saat_pindai_ulang(client, auth, monkeypatch):
    import json
    from pathlib import Path

    from aage.prospects import lead_service

    fixture = json.loads((Path(__file__).parent / "fixtures" / "overpass_kota_semarang_apotek.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(lead_service, "_post", lambda url, query, timeout_s: fixture)
    tubuh = {"wilayah": _wilayah(), "jenis_toko": "Apotek"}
    pid = client.post("/api/prospek/scout", headers=auth, json=tubuh).json()["items"][0]["id"]

    def jumlah():  # fixture OSM dipakai bersama antar tes, jadi yang dibandingkan adalah pertambahannya
        with SessionLocal() as db:
            return (db.scalar(select(func.count(LeadSkorRiwayat.id)).where(LeadSkorRiwayat.lead_id == pid)),
                    db.scalar(select(func.count(LeadEvidence.id)).where(LeadEvidence.lead_id == pid)))

    awal = jumlah()
    assert min(awal) >= 1
    client.post("/api/prospek/scout", headers=auth, json=tubuh)
    assert jumlah() == awal


# ------------------------------------------------------------------ perbaikan temuan review

_osm_urut = itertools.count(9_000_000)
_CONSENT = {"status": "GRANTED", "sumber": "Formulir", "cakupan": "promosi_whatsapp", "pada": "2026-10-01T00:00:00Z"}


def _pindai(client, auth, monkeypatch, osm_id, wilayah, nama="Apotek Pindai", **tag):
    """Elemen OSM buatan dengan ID sendiri, agar tidak mengganggu baris fixture yang dipakai bersama antar tes."""
    from aage.prospects import lead_service

    elemen = {"type": "node", "id": osm_id, "lat": -6.99, "lon": 110.42, "tags": {"name": nama, **{k.replace("__", ":"): v for k, v in tag.items()}}}
    monkeypatch.setattr(lead_service, "_post", lambda url, query, timeout_s: {"elements": [elemen]})
    r = client.post("/api/prospek/scout", headers=auth, json={"wilayah": wilayah, "jenis_toko": "Apotek"})
    assert r.status_code == 200, r.text
    return r.json()["items"][0]["id"]


def _lead(pid):
    with SessionLocal() as db:
        return db.get(Prospect, pid)


def test_pindai_ulang_tidak_menimpa_data_staf(client, auth, monkeypatch):
    osm, w = next(_osm_urut), _wilayah()
    pid = _pindai(client, auth, monkeypatch, osm, w)
    assert client.patch(f"/api/prospects/{pid}/data", headers=auth, json={"nama": "Apotek Versi Staf", "telepon": "0812-4444-0001", "alamat": "Jl. Staf 1"}).status_code == 200
    assert client.put(f"/api/prospects/{pid}/consent", headers=auth, json=_CONSENT).status_code == 200

    _pindai(client, auth, monkeypatch, osm, _wilayah(), nama="Apotek Versi OSM", phone="0812-4444-0002", addr__street="Jl. OSM", opening_hours="08-20")
    p = _lead(pid)
    assert (p.nama, p.telepon, p.alamat, p.wilayah, p.consent_status) == ("Apotek Versi Staf", "0812-4444-0001", "Jl. Staf 1", w, "GRANTED")
    assert p.jam_buka == "08-20", "kolom yang masih kosong tetap diisi dari OSM"


def test_pindai_ulang_tidak_mengosongkan_dan_nomor_baru_membatalkan_consent(client, auth, monkeypatch):
    osm, w = next(_osm_urut), _wilayah()
    pid = _pindai(client, auth, monkeypatch, osm, w, phone="0812-4444-0003", addr__street="Jl. Lama", website="https://lama.example.com")
    client.put(f"/api/prospects/{pid}/consent", headers=auth, json=_CONSENT)
    awal = _baris_ledger("prospek_diperbarui")

    _pindai(client, auth, monkeypatch, osm, w)  # OSM tidak lagi punya nomor, jalan, dan website
    p = _lead(pid)
    assert (p.telepon, p.alamat, p.alamat_jalan_ada, p.website, p.consent_status) == ("0812-4444-0003", "Jl. Lama", True, "https://lama.example.com", "GRANTED")

    _pindai(client, auth, monkeypatch, osm, w, phone="0812-4444-0004")
    p = _lead(pid)
    assert (p.telepon, p.consent_status, p.consent_sumber, p.consent_pada) == ("0812-4444-0004", "UNKNOWN", None, None)
    assert _baris_ledger("prospek_diperbarui") == awal + 1

    osm2 = next(_osm_urut)
    tanpa_nomor = _pindai(client, auth, monkeypatch, osm2, w, nama="Apotek Tanpa Nomor")
    client.put(f"/api/prospects/{tanpa_nomor}/consent", headers=auth, json=_CONSENT)
    _pindai(client, auth, monkeypatch, osm2, w, nama="Apotek Tanpa Nomor", phone="0812-4444-0005")
    assert _lead(tanpa_nomor).consent_status == "UNKNOWN"


def test_nomor_terisi_saat_gabung_dan_impor_membatalkan_consent(client, auth, admin):
    w = _wilayah()
    a = _manual(client, auth, nama="Apotek Consent Gabung", wilayah=w, alamat="Jl. A").json()
    client.put(f"/api/prospects/{a['id']}/consent", headers=auth, json=_CONSENT)
    b = _manual(client, auth, nama="Apotek Consent Gabung", wilayah=w, alamat="Jl. B", telepon="0812-4444-0006").json()
    with SessionLocal() as db:
        did = db.scalar(select(LeadDuplikat.id).where(LeadDuplikat.lead_id == b["id"], LeadDuplikat.lead_cocok_id == a["id"]))
    r = client.post(f"/api/prospects/duplikat/{did}/putuskan", headers=auth, json={"keputusan": "digabung", "utama_id": a["id"]})
    assert r.status_code == 200, r.text
    p = _lead(a["id"])
    assert p.telepon == "0812-4444-0006" and p.consent_status == "UNKNOWN" and p.consent_pada is None
    assert client.post(f"/api/prospects/{a['id']}/kontak-promo", headers=auth).json()["detail"]["kode"] == "CONSENT_REQUIRED"

    c = _manual(client, auth, nama="Apotek Consent Impor", wilayah=w, alamat="Jl. C").json()
    client.put(f"/api/prospects/{c['id']}/consent", headers=auth, json=_CONSENT)
    token = _unggah(client, admin, f"{JUDUL}\nApotek Consent Impor,Apotek,{w},Jl. C,0812-4444-0007,,,,,X-1\n").json()["token"]
    assert _terapkan(client, admin, token).status_code == 200
    p = _lead(c["id"])
    assert p.telepon == "0812-4444-0007" and p.consent_status == "UNKNOWN"


def test_dua_baris_impor_dengan_referensi_sama_tidak_gagal(client, auth, admin):
    w = _wilayah()
    a = _manual(client, auth, nama="Apotek Referensi", wilayah=w, alamat="Jl. R").json()
    baris = f"Apotek Referensi,Apotek,{w},Jl. R,,,,,,REF-1\n"
    token = _unggah(client, admin, f"{JUDUL}\n{baris}{baris}").json()["token"]
    r = _terapkan(client, admin, token)
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count(LeadEvidence.id)).where(LeadEvidence.lead_id == a["id"], LeadEvidence.source_type == "daftar_mitra")) == 1


def test_nilai_lama_tidak_sah_tidak_menghalangi_ubah_kolom_lain(client, auth):
    d = _manual(client, auth, nama="Apotek Data Lama", wilayah=_wilayah(), lat=-6.99, lng=110.42).json()
    with SessionLocal() as db:
        p = db.get(Prospect, d["id"])
        p.telepon, p.website = "12345", "contoh-lama.example.com"
        db.commit()
    r = client.patch(f"/api/prospects/{d['id']}/data", headers=auth, json={"jam_buka": "08-20"})
    assert r.status_code == 200, r.text
    p = _lead(d["id"])
    assert (p.jam_buka, p.telepon, p.website) == ("08-20", "12345", "contoh-lama.example.com")
    with SessionLocal() as db:
        akhir = db.scalars(select(LedgerEvent).where(LedgerEvent.objek_ref == f"prospect:{d['id']}", LedgerEvent.tipe_event == "prospek_diperbarui").order_by(LedgerEvent.id.desc())).first()
        assert akhir.data["kolom"] == ["jam_buka"]

    assert client.patch(f"/api/prospects/{d['id']}/data", headers=auth, json={"telepon": "0812-4444-0008"}).status_code == 200, "nomor lama bisa diperbaiki"
    r = client.patch(f"/api/prospects/{d['id']}/data", headers=auth, json={"lat": None})
    assert r.status_code == 400 and r.json()["detail"]["kesalahan"][0]["kolom"] == "lat", "lat dan lng tetap dinilai berpasangan"


def test_alamat_jalan_ada_tidak_berubah_bila_alamat_tidak_disentuh(client, auth):
    d = _manual(client, auth, nama="Apotek Bendera Alamat", wilayah=_wilayah(), alamat="Semarang").json()
    with SessionLocal() as db:
        db.get(Prospect, d["id"]).alamat_jalan_ada = False
        db.commit()
    client.patch(f"/api/prospects/{d['id']}/data", headers=auth, json={"jam_buka": "08-20"})
    assert _lead(d["id"]).alamat_jalan_ada is False


def test_lead_digabung_ditolak_saat_diubah_tetapi_consent_tetap_terbuka(client, auth):
    w = _wilayah()
    a = _manual(client, auth, nama="Apotek Arsip", wilayah=w, alamat="Jl. A").json()
    b = _manual(client, auth, nama="Apotek Arsip", wilayah=w, alamat="Jl. B").json()
    with SessionLocal() as db:
        db.get(Prospect, b["id"]).digabung_ke_id = a["id"]
        db.commit()
    for r in (client.patch(f"/api/prospects/{b['id']}/data", headers=auth, json={"jam_buka": "08-20"}),
              client.put(f"/api/prospects/{b['id']}/verifikasi", headers=auth, json={"status": "terverifikasi"})):
        assert r.status_code == 409 and r.json()["detail"]["kode"] == "DIGABUNG" and r.json()["detail"]["lead_id"] == a["id"]
    assert _lead(b["id"]).jam_buka is None
    assert client.put(f"/api/prospects/{b['id']}/consent", headers=auth, json={"status": "OPTED_OUT", "sumber": "Telepon"}).status_code == 200


def test_nomor_dan_nama_sama_beda_wilayah_hanya_mungkin(client, auth, admin):
    nilai = {"nama": "Apotek Cabang", "telepon": "081244440009"}
    a, b = dedupe.kandidat(1, {**nilai, "wilayah": "Kota X"}), dedupe.kandidat(2, {**nilai, "wilayah": "Kota Y"})
    tingkat, alasan = dedupe.bandingkan(a, b)
    assert tingkat == "mungkin" and [x["aturan"] for x in alasan] == ["nomor_nama"]
    assert dedupe.bandingkan(a, dedupe.kandidat(3, {**nilai, "wilayah": "kota x"}))[0] == "pasti"

    w1, w2, w3 = _wilayah(), _wilayah(), _wilayah()
    asal = _manual(client, auth, nama="Apotek Dua Kota", wilayah=w1, telepon="0812-4444-0010").json()
    r = _manual(client, auth, nama="Apotek Dua Kota", wilayah=w2, telepon="0812-4444-0010")
    assert r.status_code == 201 and r.json()["calon_duplikat"][0]["id"] == asal["id"]
    u = _unggah(client, admin, f"{JUDUL}\nApotek Dua Kota,Apotek,{w3},,0812-4444-0010,,,,,\n").json()
    assert u["laporan"]["ringkasan"]["digabung"] == 0 and u["laporan"]["ringkasan"]["perlu_tinjauan"] == 1


def test_selisih_panjang_nama_disaring_sebelum_pencocokan_berat(monkeypatch):
    def jangan(*_a, **_k):
        raise AssertionError("SequenceMatcher tidak boleh dibuat")

    monkeypatch.setattr(dedupe, "SequenceMatcher", jangan)
    a = dedupe.kandidat(1, {"nama": "Apotek Sehat", "wilayah": "Kota X"})
    b = dedupe.kandidat(2, {"nama": "Apotek Sehat Selalu Bersama Keluarga", "wilayah": "Kota X"})
    assert dedupe.bandingkan(a, b) is None


def test_pratinjau_impor_bukan_handler_async():
    import inspect

    from aage import routes

    assert not inspect.iscoroutinefunction(routes.prospects_impor_pratinjau)


@pytest.mark.parametrize("judul,sel", [("hp,telepon", "0812-4444-0011,"), ("telepon,hp", ",0812-4444-0011"), ("hp,telepon", "0812-4444-0011,0812-4444-0012")])
def test_alias_kolom_kembar_tidak_menimpa_nilai(client, admin, judul, sel):
    w = _wilayah()
    u = _unggah(client, admin, f"nama,tipe,wilayah,{judul}\nApotek Alias,Apotek,{w},{sel}\n").json()
    assert any("telepon" in x and "nilai pertama" in x for x in u["laporan"]["peringatan"])
    assert u["laporan"]["contoh"][0]["ada_telepon"] is True
    assert _terapkan(client, admin, u["token"]).status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(Prospect.telepon).where(Prospect.wilayah == w)) == "0812-4444-0011"


def test_sel_csv_terlalu_besar_ditolak_dengan_pesan(client, admin):
    r = _unggah(client, admin, f"{JUDUL}\nApotek Besar,Apotek,Kota A,{'x' * 200_000},,,,,,\n")
    assert r.status_code == 400 and "CSV tidak bisa dibaca" in r.json()["detail"]
