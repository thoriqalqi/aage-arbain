"""Lead masuk: input manual dan impor CSV/Excel (unggah → validasi → pratinjau → konfirmasi).

Lead baru tidak pernah membawa consent dari file: consent selalu dicatat terpisah, dan promosi terblokir sampai itu ada.
Pembuatan draf memakai ClaimGuard seperti pindaian OSM. Tidak ada pesan yang dikirim."""

import csv
import hashlib
import io
import re
import secrets
from collections import Counter
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import claimguard, clock, ledger
from ..models import Contact, LeadImpor, Prospect
from . import dedupe, konfigurasi, normalisasi, penilaian
from .mapper import catat_bukti, opening_message, setel_nomor, wa_number

MAKS_UKURAN = 5 * 1024 * 1024
MAKS_BARIS = 2000
MASA_PRATINJAU = timedelta(hours=24)
SUMBER_IMPOR = {"daftar_mitra": "Daftar dari CV Arba'in atau mitra resmi", "crm": "Data CRM yang sudah ada", "publik": "Info usaha publik yang boleh dipakai"}
LABEL_SUMBER = {**SUMBER_IMPOR, "osm": "OpenStreetMap", "manual": "Input manual", "sintetis": "Data demo"}
KOLOM = ("nama", "tipe", "wilayah", "alamat", "telepon", "website", "lat", "lng", "jam_buka", "referensi")
KOLOM_WAJIB = ("nama", "tipe", "wilayah")
ALIAS = {"nama_toko": "nama", "nama_usaha": "nama", "toko": "nama", "segmen": "tipe", "jenis": "tipe", "jenis_toko": "tipe", "kota": "wilayah", "lokasi": "wilayah",
         "kabupaten_kota": "wilayah", "hp": "telepon", "no_hp": "telepon", "nomor": "telepon", "no_telepon": "telepon", "whatsapp": "telepon", "wa": "telepon",
         "situs": "website", "latitude": "lat", "longitude": "lng", "lon": "lng", "jam": "jam_buka", "jam_operasional": "jam_buka", "id_sumber": "referensi"}
KOLOM_CONSENT = {"consent", "consent_status", "opt_in", "optin", "izin"}
_ISI_KOSONG = ("telepon", "website", "alamat", "lat", "lng", "jam_buka")


class ImporDitolak(ValueError):
    pass


class DataTidakValid(Exception):
    def __init__(self, kesalahan: list[dict]):
        super().__init__("Data lead tidak valid")
        self.kesalahan = kesalahan


class DuplikatPasti(Exception):
    def __init__(self, cocok: dict):
        super().__init__("Lead sudah ada")
        self.cocok = cocok


def _kunci(judul) -> str:
    k = re.sub(r"[^a-z0-9]+", "_", str(judul or "").strip().lower()).strip("_")
    return ALIAS.get(k, k)


def _sel(nilai) -> str:
    if nilai is None:
        return ""
    if isinstance(nilai, float) and nilai.is_integer():
        return str(int(nilai))
    return str(nilai).strip()


def baca_file(nama_file: str, isi: bytes) -> tuple[list[str], list[tuple[int, dict]]]:
    if len(isi) > MAKS_UKURAN:
        raise ImporDitolak(f"File terlalu besar, maksimal {MAKS_UKURAN // 1024 // 1024} MB.")
    nama = (nama_file or "").lower()
    if nama.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        try:
            wb = load_workbook(io.BytesIO(isi), read_only=True, data_only=True)
            ws = next((wb[s] for s in wb.sheetnames if s.lower() != "petunjuk"), None)
            rows = list(ws.iter_rows(values_only=True)) if ws is not None else []
        except Exception as exc:  # noqa: BLE001 — file rusak atau bukan xlsx
            raise ImporDitolak(f"File Excel tidak bisa dibaca ({type(exc).__name__}).") from None
    elif nama.endswith(".csv"):
        try:
            teks = isi.decode("utf-8-sig")
        except UnicodeDecodeError:
            teks = isi.decode("latin-1")
        try:
            dialek = csv.Sniffer().sniff(teks[:2048], delimiters=",;\t") if teks.strip() else csv.excel
        except csv.Error:
            dialek = csv.excel
        try:
            rows = list(csv.reader(io.StringIO(teks), dialek))
        except csv.Error:
            raise ImporDitolak("File CSV tidak bisa dibaca: formatnya rusak atau ada sel yang terlalu besar.") from None
    else:
        raise ImporDitolak("Format file harus .xlsx atau .csv.")
    if not rows:
        raise ImporDitolak("File kosong.")
    kunci = [_kunci(h) for h in rows[0]]
    kurang = [k for k in KOLOM_WAJIB if k not in kunci]
    if kurang:
        raise ImporDitolak(f"Kolom wajib tidak ada: {', '.join(kurang)}. Unduh template untuk melihat formatnya.")
    baris = []
    for n, r in enumerate(rows[1:], start=2):  # baris 1 = judul kolom, sama dengan penomoran Excel
        nilai: dict[str, str] = {}
        for k, v in zip(kunci, r):
            if k and not nilai.get(k):  # kolom alias kembar: dipakai nilai pertama yang terisi
                nilai[k] = _sel(v)
        if any(nilai.values()):
            baris.append((n, nilai))
    if not baris:
        raise ImporDitolak("File tidak berisi baris data.")
    if len(baris) > MAKS_BARIS:
        raise ImporDitolak(f"File berisi {len(baris)} baris, maksimal {MAKS_BARIS}.")
    return [k for k in kunci if k], baris


def template_csv() -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(KOLOM)
    w.writerow(["Apotek Contoh Sehat", "Apotek", "Kota Semarang", "Jl. Contoh No. 1", "0812-0000-0000", "", "-6.99", "110.42", "Senin-Sabtu 08-20", "DAFTAR-001"])
    w.writerow(["Toko Obat Contoh", "Toko Obat", "Kota Semarang", "", "", "", "", "", "", "DAFTAR-002"])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def _rencanakan(baris: list[dict], indeks: dedupe.Indeks, buat) -> list[dict]:
    """Keputusan per baris, dipakai pratinjau dan penerapan agar hasilnya sama. `buat` memberi ID lead baru."""
    dari_file: dict[int, int] = {}
    keluar = []
    for r in baris:
        k = dedupe.kandidat(0, {**r["data"], "eksternal_id": None})
        cocok = indeks.cari(k)
        pasti = next((c for c in cocok if c["tingkat"] == "pasti"), None)
        if pasti and pasti["id"] in dari_file:
            keluar.append({**r, "tindakan": "kembar_file", "cocok": pasti, "baris_asal": dari_file[pasti["id"]]})
            continue
        if pasti:
            keluar.append({**r, "tindakan": "gabung", "cocok": pasti, "id": pasti["id"]})
            continue
        k.id = buat(r)
        dari_file[k.id] = r["baris"]
        indeks.tambah(k)
        keluar.append({**r, "tindakan": "tinjau" if cocok else "baru", "calon": cocok, "id": k.id})
    return keluar


def _nomor_ringkas(r: dict) -> dict:
    return {"baris": r["baris"], "nama": r["data"]["nama"], "wilayah": r["data"]["wilayah"]}


def _hapus_pratinjau_lama(db: Session) -> None:
    batas = clock.now() - MASA_PRATINJAU
    for imp in db.scalars(select(LeadImpor).where(LeadImpor.status == "pratinjau")):
        if clock.aware(imp.dibuat_pada) < batas:
            imp.status, imp.baris = "dibatalkan", []


def buat_pratinjau(db: Session, nama_file: str, isi: bytes, source_type: str, source_reference: str, aktor: str) -> LeadImpor:
    if source_type not in SUMBER_IMPOR:
        raise ImporDitolak(f"Sumber harus salah satu dari: {', '.join(SUMBER_IMPOR)}")
    source_reference = normalisasi.rapikan(source_reference)
    if len(source_reference) < 3 or len(source_reference) > 300:
        raise ImporDitolak("Isi keterangan sumber: siapa yang memberi daftar ini dan kapan (3-300 karakter).")
    kolom, mentah = baca_file(nama_file, isi)
    segmen = konfigurasi.segmen(db)
    valid, kesalahan = [], []
    for n, nilai in mentah:
        data, salah = normalisasi.validasi(nilai, segmen)
        if salah:
            kesalahan.extend({"baris": n, **s} for s in salah)
        else:
            valid.append({"baris": n, "data": data, "referensi": normalisasi.rapikan(nilai.get("referensi"))[:120] or None})
    urutan = [-(i + 1) for i in range(len(valid))]
    rencana = _rencanakan(valid, dedupe.indeks_aktif(db), lambda r: urutan.pop(0))
    jumlah = Counter(r["tindakan"] for r in rencana)
    peringatan = []
    if KOLOM_CONSENT & set(kolom):
        peringatan.append("Kolom consent di file diabaikan. Consent dicatat terpisah per lead dengan sumber dan waktunya.")
    kembar = sorted(k for k, n in Counter(kolom).items() if n > 1)
    if kembar:
        peringatan.append(f"Beberapa kolom berarti sama: {', '.join(kembar)}. Dipakai nilai pertama yang terisi di tiap baris.")
    asing = sorted(set(kolom) - set(KOLOM) - KOLOM_CONSENT)
    if asing:
        peringatan.append(f"Kolom ini diabaikan: {', '.join(asing)}.")
    sha = hashlib.sha256(isi).hexdigest()
    if db.scalar(select(LeadImpor.id).where(LeadImpor.sha256 == sha, LeadImpor.status == "diterapkan").limit(1)):
        peringatan.append("File yang persis sama sudah pernah diterapkan. Baris yang sama akan digabung, bukan dibuat ulang.")
    laporan = {
        "ringkasan": {"baris": len(mentah), "valid": len(valid), "error": len({e["baris"] for e in kesalahan}), "baru": jumlah["baru"],
                      "digabung": jumlah["gabung"], "perlu_tinjauan": jumlah["tinjau"], "kembar_file": jumlah["kembar_file"]},
        "error": kesalahan, "peringatan": peringatan,
        "digabung": [{**_nomor_ringkas(r), "cocok_dengan": r["cocok"]["nama"], "alasan": [a["keterangan"] for a in r["cocok"]["alasan"]]} for r in rencana if r["tindakan"] == "gabung"][:300],
        "perlu_tinjauan": [{**_nomor_ringkas(r), "cocok_dengan": [c["nama"] for c in r["calon"]][:5], "alasan": sorted({a["keterangan"] for c in r["calon"] for a in c["alasan"]})} for r in rencana if r["tindakan"] == "tinjau"][:300],
        "kembar_file": [{**_nomor_ringkas(r), "sama_dengan_baris": r["baris_asal"]} for r in rencana if r["tindakan"] == "kembar_file"][:300],
        "contoh": [{**_nomor_ringkas(r), "tipe": r["data"]["tipe"], "alamat": r["data"]["alamat"], "ada_telepon": bool(r["data"]["telepon"])} for r in rencana if r["tindakan"] in ("baru", "tinjau")][:20],
    }
    _hapus_pratinjau_lama(db)
    imp = LeadImpor(token=secrets.token_urlsafe(24), nama_file=(nama_file or "")[:300], sha256=sha, source_type=source_type, source_reference=source_reference,
                    baris=valid, laporan=laporan, dibuat_oleh=aktor)
    db.add(imp)
    ledger.record(db, "prospek_impor_pratinjau", aktor=aktor, model=None, outcome="pratinjau", ringkasan=f"{imp.nama_file}: {len(valid)} valid, {laporan['ringkasan']['error']} salah",
                  data={"ringkasan": laporan["ringkasan"], "source_type": source_type, "sha256": sha})
    db.commit()
    return imp


def buat_lead(db: Session, data: dict, *, source_type: str, reference: str, aktor: str, pemicu: str, trace: str | None = None, metadata: dict | None = None) -> Prospect:
    wa = wa_number(data.get("telepon"))
    p = Prospect(nama=data["nama"], tipe=data["tipe"], wilayah=data["wilayah"], alamat=data.get("alamat") or "", telepon=data.get("telepon"), website=data.get("website"),
                 lat=data.get("lat"), lng=data.get("lng"), jam_buka=data.get("jam_buka"), alamat_jalan_ada=bool(data.get("alamat")), sumber=source_type,
                 status="baru", dikumpulkan_pada=clock.now(), sudah_pelanggan=bool(wa and db.scalar(select(Contact.id).where(Contact.wa_number == wa).limit(1))))
    pesan = opening_message(p.nama, p.wilayah, p.tipe)
    cek = claimguard.check(db, pesan, use_llm=False)
    p.draf_pesan, p.draf_verdict = (pesan if cek.verdict == claimguard.ALLOWED else cek.safe_text), cek.verdict
    db.add(p)
    db.flush()
    penilaian.nilai_ulang(db, p, pemicu)
    catat_bukti(db, p.id, source_type, reference, metadata)
    ledger.record(db, "prospek_dibuat", trace_id=trace, objek_ref=f"prospect:{p.id}", aktor=aktor, model=None, ringkasan=f"{p.nama} · skor {p.skor}", outcome="baru",
                  alasan="; ".join(f"{r['faktor']} +{r['poin']}" for r in p.alasan_skor), verdict=p.draf_verdict,
                  sumber_ref=[{"jenis": source_type, "referensi": reference[:200]}], data={"wilayah": p.wilayah, "tipe": p.tipe, "skor": p.skor})
    return p


def terapkan(db: Session, token: str, aktor: str, *, lewati_error: bool = False) -> LeadImpor:
    """Satu transaksi: gagal di tengah berarti tidak ada lead yang masuk. Mengulang permintaan yang sama mengembalikan hasil lama."""
    imp = db.scalar(select(LeadImpor).where(LeadImpor.token == token).with_for_update())
    if imp is None:
        raise LookupError("Pratinjau tidak ditemukan")
    if imp.status == "diterapkan":
        return imp
    if imp.status != "pratinjau":
        raise ImporDitolak("Pratinjau ini sudah dibatalkan. Unggah ulang filenya.")
    if clock.aware(imp.dibuat_pada) < clock.now() - MASA_PRATINJAU:
        raise ImporDitolak("Pratinjau kedaluwarsa setelah 24 jam. Unggah ulang filenya.")
    jumlah_error = imp.laporan["ringkasan"]["error"]
    if jumlah_error and not lewati_error:
        raise ImporDitolak(f"Ada {jumlah_error} baris salah. Perbaiki filenya, atau konfirmasi untuk melewati baris tersebut.")
    trace = ledger.new_trace_id()
    konteks = {"impor": imp.token[:8], "file": imp.nama_file}

    def referensi(r: dict) -> str:
        return f"{imp.source_reference} | {r.get('referensi') or 'baris ' + str(r['baris'])}"

    def buat(r: dict) -> int:
        p = buat_lead(db, r["data"], source_type=imp.source_type, reference=referensi(r), aktor=aktor, pemicu="impor", trace=trace, metadata={**konteks, "baris": r["baris"]})
        return p.id

    rencana = _rencanakan(imp.baris, dedupe.indeks_aktif(db), buat)
    for r in rencana:
        if r["tindakan"] == "gabung":
            lama = db.get(Prospect, r["id"])
            ada_consent = lama.consent_status == "GRANTED"
            kolom = dedupe.isi_yang_kosong(lama, r["data"], _ISI_KOSONG)
            if "alamat" in kolom:
                lama.alamat_jalan_ada = True
            if kolom:
                penilaian.nilai_ulang(db, lama, "impor")
            catat_bukti(db, lama.id, imp.source_type, referensi(r), {**konteks, "baris": r["baris"], "alasan_cocok": r["cocok"]["alasan"]})
            ledger.record(db, "prospek_diperbarui", trace_id=trace, objek_ref=f"prospect:{lama.id}", aktor=aktor, model=None, ringkasan=f"{lama.nama}: bukti baru dari impor",
                          alasan="; ".join(a["keterangan"] for a in r["cocok"]["alasan"]), data={"kolom_terisi": kolom, "baris": r["baris"], "consent_dibatalkan": ada_consent and lama.consent_status != "GRANTED"})
        elif r["tindakan"] == "tinjau":
            for c in r["calon"]:
                dedupe.rekam_calon(db, r["id"], c["id"], c["tingkat"], c["alasan"])
    jumlah = Counter(r["tindakan"] for r in rencana)
    imp.hasil = {"baru": jumlah["baru"], "digabung": jumlah["gabung"], "perlu_tinjauan": jumlah["tinjau"], "kembar_file": jumlah["kembar_file"], "dilewati_salah": jumlah_error}
    imp.status, imp.baris, imp.diterapkan_pada = "diterapkan", [], clock.now()
    ledger.record(db, "prospek_diimpor", trace_id=trace, aktor=aktor, model=None, outcome="diterapkan", ringkasan=f"{imp.nama_file}: {imp.hasil['baru'] + imp.hasil['perlu_tinjauan']} lead baru, {imp.hasil['digabung']} digabung",
                  sumber_ref=[{"jenis": imp.source_type, "referensi": imp.source_reference[:200], "sha256": imp.sha256}], data=imp.hasil)
    db.commit()
    return imp


def batal(db: Session, token: str) -> LeadImpor:
    imp = db.scalar(select(LeadImpor).where(LeadImpor.token == token))
    if imp is None:
        raise LookupError("Pratinjau tidak ditemukan")
    if imp.status == "pratinjau":
        imp.status, imp.baris = "dibatalkan", []
        db.commit()
    return imp


def buat_manual(db: Session, data: dict, *, reference: str | None, aktor: str) -> tuple[Prospect, list[dict]]:
    """`pasti` duplikat ditolak; `mungkin` tetap dibuat dan masuk antrean tinjauan."""
    bersih, salah = normalisasi.validasi(data, konfigurasi.segmen(db))
    if salah:
        raise DataTidakValid(salah)
    cocok = dedupe.indeks_aktif(db).cari(dedupe.kandidat(0, bersih))
    pasti = next((c for c in cocok if c["tingkat"] == "pasti"), None)
    if pasti:
        raise DuplikatPasti(pasti)
    p = buat_lead(db, bersih, source_type="manual", reference=normalisasi.rapikan(reference) or f"Dicatat {aktor}", aktor=aktor, pemicu="manual")
    for c in cocok:
        dedupe.rekam_calon(db, p.id, c["id"], c["tingkat"], c["alasan"])
    db.commit()
    return p, cocok


def ubah_data(db: Session, p: Prospect, data: dict, aktor: str) -> tuple[Prospect, list[str]]:
    """Melengkapi data lead. Nomor yang berubah membatalkan consent, karena consent melekat pada nomor lama."""
    gabungan = {"nama": p.nama, "tipe": p.tipe, "wilayah": p.wilayah, "alamat": p.alamat, "telepon": p.telepon, "website": p.website, "lat": p.lat, "lng": p.lng, "jam_buka": p.jam_buka, **data}
    segmen = konfigurasi.segmen(db)
    bersih, salah = normalisasi.validasi(gabungan, segmen if p.tipe.lower() in {s.lower() for s in segmen} else [*segmen, p.tipe])
    # Nilai lama yang tidak memenuhi aturan sekarang tidak boleh menghalangi perubahan kolom lain. Lat dan lng selalu dinilai berpasangan.
    dinilai = set(data) | ({"lat", "lng"} if {"lat", "lng"} & set(data) else set())
    salah = [s for s in salah if s["kolom"] in dinilai]
    if salah:
        raise DataTidakValid(salah)
    berubah = [k for k, v in bersih.items() if k in data and (getattr(p, k) or None) != (v or None)]
    if not berubah:
        return p, []
    consent_batal = False
    for k in berubah:
        if k == "telepon":
            consent_batal = setel_nomor(p, bersih[k])
        else:
            setattr(p, k, bersih[k] if bersih[k] is not None else ("" if k == "alamat" else None))
    if "alamat" in berubah:
        p.alamat_jalan_ada = bool(p.alamat) and p.alamat != dedupe.ALAMAT_KOSONG
    penilaian.nilai_ulang(db, p, "ubah_data")
    catat_bukti(db, p.id, "manual", f"Diubah {aktor}", {"kolom": berubah})
    ledger.record(db, "prospek_diperbarui", objek_ref=f"prospect:{p.id}", aktor=aktor, model=None, ringkasan=f"{p.nama}: {', '.join(berubah)} diperbarui",
                  data={"kolom": berubah, "consent_dibatalkan": consent_batal})
    indeks = dedupe.indeks_aktif(db)
    for c in indeks.cari(dedupe.dari_prospek(p)):
        dedupe.rekam_calon(db, p.id, c["id"], c["tingkat"], c["alasan"])
    db.commit()
    return p, berubah
