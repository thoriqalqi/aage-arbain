"""Deteksi duplikat lead yang deterministik dan bisa dijelaskan.

`pasti`   : ID sumber sama, nomor + nama + wilayah sama, atau nama + wilayah + alamat sama.
`mungkin` : nomor sama dengan nama atau wilayah beda, nama sama di wilayah yang sama (bisa cabang), website sama, atau nama sangat mirip.
Nomor saja tidak pernah dianggap pasti karena satu nomor bisa dipakai beberapa usaha atau cabang. Data demo tidak ikut dicocokkan."""

import re
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from urllib.parse import urlparse

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import clock, ledger
from ..models import Contact, LeadDuplikat, LeadEvidence, Prospect
from . import penilaian
from .mapper import _URUTAN, setel_nomor, wa_number

KATA_UMUM = {"apotek", "apotik", "toko", "obat", "minimarket", "mini", "market", "swalayan", "pt", "cv", "ud", "tb", "tk"}
AMBANG_MIRIP = 0.88
ALAMAT_KOSONG = "Alamat tidak spesifik"


@dataclass
class Kandidat:
    id: int
    nama: str
    inti: str
    wilayah: str
    wa: str | None
    alamat: str
    domain: str | None
    eksternal: str | None


def _huruf_angka(teks: str | None) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (teks or "").lower()).split())


def inti_nama(nama: str) -> str:
    kata = _huruf_angka(nama).split()
    return " ".join(k for k in kata if k not in KATA_UMUM) or " ".join(kata)


def _domain(website: str | None) -> str | None:
    if not website:
        return None
    host = urlparse(website if "//" in website else f"https://{website}").netloc.lower()
    return host.removeprefix("www.") or None


def kandidat(id_: int, data: dict) -> Kandidat:
    alamat = _huruf_angka(data.get("alamat"))
    return Kandidat(id_, data.get("nama") or "", inti_nama(data.get("nama") or ""), _huruf_angka(data.get("wilayah")), wa_number(data.get("telepon")),
                    "" if alamat == "alamat tidak spesifik" else alamat, _domain(data.get("website")), data.get("eksternal_id"))


def dari_prospek(p: Prospect) -> Kandidat:
    return kandidat(p.id, {"nama": p.nama, "wilayah": p.wilayah, "telepon": p.telepon, "alamat": p.alamat, "website": p.website, "eksternal_id": p.eksternal_id})


def bandingkan(a: Kandidat, b: Kandidat) -> tuple[str, list[dict]] | None:
    if a.eksternal and a.eksternal == b.eksternal:
        return "pasti", [{"aturan": "id_sumber", "keterangan": "ID sumber sama"}]
    nama_sama = bool(a.inti) and a.inti == b.inti
    wilayah_sama = bool(a.wilayah) and a.wilayah == b.wilayah
    wa_sama = bool(a.wa) and a.wa == b.wa
    if wa_sama and nama_sama and wilayah_sama:
        return "pasti", [{"aturan": "nomor_nama", "keterangan": "Nomor, nama, dan wilayah sama"}]
    if nama_sama and wilayah_sama and a.alamat and a.alamat == b.alamat:
        return "pasti", [{"aturan": "nama_wilayah_alamat", "keterangan": "Nama, wilayah, dan alamat sama"}]
    alasan = []
    if wa_sama:
        alasan.append({"aturan": "nomor_nama", "keterangan": "Nomor dan nama sama, wilayah berbeda, bisa jadi cabang"} if nama_sama
                      else {"aturan": "nomor", "keterangan": "Nomor sama, nama berbeda"})
    if nama_sama and wilayah_sama:
        alasan.append({"aturan": "nama_wilayah", "keterangan": "Nama sama di wilayah yang sama, bisa jadi cabang berbeda"})
    if wilayah_sama and a.domain and a.domain == b.domain:
        alasan.append({"aturan": "website", "keterangan": "Website sama di wilayah yang sama"})
    if wilayah_sama and not nama_sama and a.inti and b.inti and 2 * min(len(a.inti), len(b.inti)) / (len(a.inti) + len(b.inti)) >= AMBANG_MIRIP:
        mirip = SequenceMatcher(None, a.inti, b.inti)  # pembuatannya mahal, jadi selisih panjang disaring lebih dulu
        if mirip.quick_ratio() >= AMBANG_MIRIP and (rasio := mirip.ratio()) >= AMBANG_MIRIP:
            alasan.append({"aturan": "nama_mirip", "keterangan": f"Nama sangat mirip ({round(rasio * 100)}%) di wilayah yang sama"})
    return ("mungkin", alasan) if alasan else None


class Indeks:
    def __init__(self, daftar: list[Kandidat] | None = None):
        self._per_wilayah: dict[str, list[Kandidat]] = defaultdict(list)
        self._per_wa: dict[str, list[Kandidat]] = defaultdict(list)
        self._per_eksternal: dict[str, list[Kandidat]] = defaultdict(list)
        for k in daftar or []:
            self.tambah(k)

    def tambah(self, k: Kandidat) -> None:
        self._per_wilayah[k.wilayah].append(k)
        if k.wa:
            self._per_wa[k.wa].append(k)
        if k.eksternal:
            self._per_eksternal[k.eksternal].append(k)

    def cari(self, k: Kandidat) -> list[dict]:
        """Hasil berurutan tetap: `pasti` lebih dulu, lalu ID terkecil."""
        calon = {c.id: c for c in self._per_wilayah[k.wilayah]}
        calon.update({c.id: c for c in self._per_wa[k.wa]} if k.wa else {})
        calon.update({c.id: c for c in self._per_eksternal[k.eksternal]} if k.eksternal else {})
        hasil = []
        for c in calon.values():
            if c.id != k.id and (cocok := bandingkan(k, c)):
                hasil.append({"id": c.id, "nama": c.nama, "tingkat": cocok[0], "alasan": cocok[1]})
        return sorted(hasil, key=lambda h: (h["tingkat"] != "pasti", h["id"]))


def indeks_aktif(db: Session) -> Indeks:
    return Indeks([dari_prospek(p) for p in db.scalars(select(Prospect).where(Prospect.sumber != "sintetis", Prospect.digabung_ke_id.is_(None)))])


def rekam_calon(db: Session, a: int, b: int, tingkat: str, alasan: list[dict]) -> bool:
    """Satu pasangan satu baris, urutannya tetap. Pasangan yang sudah pernah diputus tidak diangkat lagi."""
    lead_id, cocok_id = max(a, b), min(a, b)
    ada = db.scalar(select(LeadDuplikat).where(LeadDuplikat.lead_id == lead_id, LeadDuplikat.lead_cocok_id == cocok_id))
    if ada is not None:
        return False
    db.add(LeadDuplikat(lead_id=lead_id, lead_cocok_id=cocok_id, tingkat=tingkat, alasan=alasan))
    db.flush()
    return True


def pindai_semua(db: Session, aktor: str) -> dict:
    daftar = [dari_prospek(p) for p in db.scalars(select(Prospect).where(Prospect.sumber != "sintetis", Prospect.digabung_ke_id.is_(None)).order_by(Prospect.id))]
    indeks, baru = Indeks(), 0
    for k in daftar:
        baru += sum(rekam_calon(db, k.id, c["id"], c["tingkat"], c["alasan"]) for c in indeks.cari(k))
        indeks.tambah(k)
    ledger.record(db, "prospek_dedupe_dipindai", aktor=aktor, model=None, outcome="selesai", trace_id=ledger.new_trace_id(),
                  ringkasan=f"{len(daftar)} lead diperiksa, {baru} calon duplikat baru", data={"jumlah": len(daftar), "calon_baru": baru})
    db.commit()
    return {"jumlah": len(daftar), "calon_baru": baru}


def ids_menunggu(db: Session) -> set[int]:
    baris = db.execute(select(LeadDuplikat.lead_id, LeadDuplikat.lead_cocok_id).where(LeadDuplikat.keputusan == "menunggu")).all()
    return {i for pasangan in baris for i in pasangan}


def isi_yang_kosong(utama: Prospect, sumber: dict, kolom: tuple[str, ...]) -> list[str]:
    """"Alamat tidak spesifik" dari OSM berarti alamatnya belum diketahui, jadi diperlakukan sebagai kosong di kedua sisi."""
    terisi = []
    for k in kolom:
        nilai = sumber.get(k)
        if nilai in (None, "") or (k == "alamat" and nilai == ALAMAT_KOSONG):
            continue
        kosong = not utama.alamat_jalan_ada if k == "alamat" else getattr(utama, k) in (None, "")
        if kosong:
            if k == "telepon":
                setel_nomor(utama, nilai)
            else:
                setattr(utama, k, nilai)
            terisi.append(k)
    return terisi


def gabung(db: Session, utama: Prospect, duplikat: Prospect, aktor: str, alasan: list[dict]) -> None:
    """Baris duplikat tetap ada dan menunjuk ke lead utama, jadi riwayatnya tidak hilang. Opt-out selalu ikut; consent tidak."""
    kolom = ("telepon", "website", "alamat", "lat", "lng", "jam_buka", "catatan", "pic", "tindak_lanjut_pada")
    sumber = {k: getattr(duplikat, k) for k in kolom}
    if not duplikat.alamat_jalan_ada:
        sumber["alamat"] = None
    ada_consent = utama.consent_status == "GRANTED"
    terisi = isi_yang_kosong(utama, sumber, kolom)
    consent_batal = ada_consent and utama.consent_status != "GRANTED"
    if "alamat" in terisi:
        utama.alamat_jalan_ada = True
    if duplikat.consent_status == "OPTED_OUT" and utama.consent_status != "OPTED_OUT":
        utama.consent_status, utama.consent_sumber = "OPTED_OUT", duplikat.consent_sumber or f"Digabung dari lead {duplikat.id}"
        utama.consent_cakupan, utama.consent_pada = None, duplikat.consent_pada or clock.now()
    if _URUTAN.get(duplikat.status, -1) > _URUTAN.get(utama.status, -1) or (duplikat.status == "menolak" and utama.status != "pelanggan"):
        utama.status = duplikat.status
    utama.sudah_pelanggan = utama.sudah_pelanggan or duplikat.sudah_pelanggan
    duplikat.digabung_ke_id = utama.id
    ada = {(b.source_type, b.source_reference) for b in db.scalars(select(LeadEvidence).where(LeadEvidence.lead_id == utama.id))}
    for b in db.scalars(select(LeadEvidence).where(LeadEvidence.lead_id == duplikat.id)):
        if (b.source_type, b.source_reference) not in ada:
            b.lead_id = utama.id
    for c in db.scalars(select(Contact).where(Contact.prospect_id == duplikat.id)):
        c.prospect_id = utama.id
    for d in db.scalars(select(LeadDuplikat).where(LeadDuplikat.keputusan == "menunggu", or_(LeadDuplikat.lead_id == duplikat.id, LeadDuplikat.lead_cocok_id == duplikat.id))):
        d.keputusan, d.diputuskan_oleh, d.diputuskan_pada = "gugur", aktor, clock.now()
    penilaian.nilai_ulang(db, utama, "gabung")
    ledger.record(db, "prospek_digabung", objek_ref=f"prospect:{utama.id}", aktor=aktor, model=None, outcome="digabung",
                  ringkasan=f"{duplikat.nama} (lead {duplikat.id}) digabung ke {utama.nama}",
                  alasan="; ".join(a["keterangan"] for a in alasan), data={"utama": utama.id, "duplikat": duplikat.id, "kolom_terisi": terisi, "alasan": alasan, "consent_dibatalkan": consent_batal})


def putuskan(db: Session, duplikat_id: int, keputusan: str, utama_id: int | None, aktor: str) -> LeadDuplikat:
    d = db.get(LeadDuplikat, duplikat_id)
    if d is None:
        raise LookupError("Calon duplikat tidak ditemukan")
    if d.keputusan != "menunggu":
        raise ValueError("Calon duplikat ini sudah diputus")
    if keputusan not in ("digabung", "bukan_duplikat"):
        raise ValueError("Keputusan harus digabung atau bukan_duplikat")
    if keputusan == "digabung":
        if utama_id not in (d.lead_id, d.lead_cocok_id):
            raise ValueError("Lead utama harus salah satu dari pasangan ini")
        utama = db.get(Prospect, utama_id)
        kedua = db.get(Prospect, d.lead_cocok_id if utama_id == d.lead_id else d.lead_id)
        gabung(db, utama, kedua, aktor, d.alasan)
    d.keputusan, d.diputuskan_oleh, d.diputuskan_pada = keputusan, aktor, clock.now()
    ledger.record(db, "prospek_duplikat_diputus", objek_ref=f"prospect:{d.lead_id}", aktor=aktor, model=None, outcome=keputusan,
                  ringkasan=f"Calon duplikat lead {d.lead_id} dan {d.lead_cocok_id}: {keputusan}",
                  alasan="; ".join(a["keterangan"] for a in d.alasan), data={"lead_id": d.lead_id, "lead_cocok_id": d.lead_cocok_id, "utama": utama_id})
    db.commit()
    return d
