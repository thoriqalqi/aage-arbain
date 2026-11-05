"""Verifikasi knowledge: bot hanya boleh menyajikan fakta yang terverifikasi dan masih berlaku.

Satu baris `verifikasi_fakta` per fakta, karena satu baris produk memuat fakta dengan bukti dan masa berlaku berbeda.
Tutup-gagal: fakta tanpa baris dianggap belum diverifikasi; nilai yang berubah sesudah diverifikasi membatalkan
verifikasinya; kedaluwarsa dihitung saat dibaca. Tidak ada jalur otomatis menuju `terverifikasi`, hanya `ubah_status`.
"""

import hashlib
import json
import re
from collections import Counter
from contextlib import contextmanager
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import clock, ledger, settings_store
from ..models import ApprovedClaim, Chunk, Document, Product, User, VerifikasiFakta
from ..textutil import rupiah

TERVERIFIKASI, SIMULASI, BELUM, KEDALUWARSA = "terverifikasi", "simulasi", "belum_diverifikasi", "kedaluwarsa"
STATUS = (TERVERIFIKASI, SIMULASI, BELUM, KEDALUWARSA)
DEMO, PRODUKSI = settings_store.MODE_DATA[1], settings_store.MODE_DATA[0]
PRODUK, KLAIM, DOKUMEN = "produk", "klaim", "dokumen"
JENIS_PRODUK = {
    "produk": "Identitas dan komposisi", "harga": "Harga dan HET", "moq": "MOQ", "tier_diskon": "Tier diskon",
    "stok": "Stok", "izin_edar": "Izin edar", "halal": "Sertifikat halal", "bko": "Uji BKO", "aturan_pakai": "Aturan pakai",
}
LABEL_KLAIM, LABEL_DOKUMEN = "Klaim resmi", "Dokumen pengetahuan"
_POLA_NOMOR_SIMULASI = re.compile(r"\bSIM\d|-SIM-|simulasi", re.IGNORECASE)
_POLA_JUDUL_SIMULASI = re.compile(r"simulasi|sintetis|data contoh", re.IGNORECASE)
_JENIS_BERNOMOR = {"izin_edar", "halal", "bko"}
_PERINGKAT = {KEDALUWARSA: 0, BELUM: 1, SIMULASI: 2, TERVERIFIKASI: 3}
_KUNCI_SESI = "aage_saringan_fakta"
_MIN_FRAGMEN = 6


class StatusDitolak(ValueError):
    pass


def sidik(nilai: str) -> str:
    return hashlib.sha256(nilai.encode("utf-8")).hexdigest()


def tampak_simulasi(jenis: str, nilai: str) -> bool:
    """Hanya nomor resmi yang diperiksa polanya: kata "simulasi" di komposisi atau harga tidak bermakna apa-apa."""
    return jenis in _JENIS_BERNOMOR and bool(_POLA_NOMOR_SIMULASI.search(nilai))


def judul_simulasi(judul: str) -> bool:
    return bool(_POLA_JUDUL_SIMULASI.search(judul or ""))


def _json(nilai) -> str:
    return json.dumps(nilai, sort_keys=True, ensure_ascii=False) if nilai else ""


def nilai_produk(p: Product, jenis: str) -> str:
    """Nilai yang dijamin oleh verifikasi. String kosong berarti datanya memang tidak ada."""
    t = p.data_teknis or {}
    if jenis == "produk":
        return "|".join(str(x or "") for x in (p.nama, p.kategori, p.kemasan, p.komposisi, p.deskripsi))
    if jenis == "harga":
        return f"{float(p.harga_dasar):.2f}|{p.het_per_botol or ''}|{p.satuan_grosir}" if p.harga_dasar else ""
    if jenis == "moq":
        return str(p.moq) if p.moq else ""
    if jenis == "tier_diskon":
        return "|".join(f"{r.min_qty}:{r.diskon_maks_persen:g}" for r in sorted(p.pricing, key=lambda r: r.min_qty))
    if jenis == "stok":
        return "" if p.stok is None else str(p.stok)
    if jenis == "izin_edar":
        return p.no_izin_edar or ""
    if jenis == "halal":
        return _json(t.get("sertifikasi_halal"))
    if jenis == "bko":
        return _json(t.get("status_bebas_bko"))
    if jenis == "aturan_pakai":
        return str(t.get("aturan_pakai") or "").strip()
    raise KeyError(jenis)


def nilai_tampil(p: Product, jenis: str) -> str:
    t = p.data_teknis or {}
    if jenis == "produk":
        return f"{p.kemasan or '-'}; {p.komposisi or '-'}"
    if jenis == "harga":
        return f"{rupiah(p.harga_dasar)}/{p.satuan_grosir}" + (f", HET {rupiah(p.het_per_botol)}" if p.het_per_botol else "")
    if jenis == "moq":
        return f"{p.moq} {p.satuan_grosir}"
    if jenis == "tier_diskon":
        return ", ".join(f"≥{r.min_qty}: {r.diskon_maks_persen:g}%" for r in sorted(p.pricing, key=lambda r: r.min_qty))
    if jenis == "stok":
        return f"{p.stok} {p.satuan_grosir}"
    if jenis == "halal":
        h = t.get("sertifikasi_halal") or {}
        return " · ".join(str(x) for x in (h.get("status"), h.get("nomor_sertifikat"), h.get("lembaga")) if x)
    if jenis == "bko":
        b = t.get("status_bebas_bko") or {}
        return " · ".join(str(x) for x in (b.get("hasil"), b.get("nomor_laporan_uji")) if x)
    return nilai_produk(p, jenis)


class Saringan:
    """Potret status untuk satu jawaban. `boleh_*` mencatat apa yang ditahan dan apakah ada data simulasi yang lolos."""

    def __init__(self, db: Session):
        self.db = db
        self.mode = settings_store.mode_data(db)
        self.hari_ini = clock.now().date()
        self._baris = {(b.objek_tipe, b.objek_id, b.jenis_fakta): b for b in db.scalars(select(VerifikasiFakta))}
        self.memakai_simulasi = False
        self.tertahan: set[str] = set()

    @classmethod
    def dari(cls, db: Session) -> "Saringan":
        return db.info.get(_KUNCI_SESI) or cls(db)

    def baris(self, tipe: str, objek_id: int, jenis: str) -> VerifikasiFakta | None:
        return self._baris.get((tipe, objek_id, jenis))

    def _status(self, tipe: str, objek_id: int, jenis: str, nilai: str | None) -> str:
        b = self.baris(tipe, objek_id, jenis)
        if b is None:
            return BELUM
        if b.berlaku_sampai is not None and b.berlaku_sampai < self.hari_ini:
            return KEDALUWARSA
        if b.status_verifikasi == TERVERIFIKASI:
            if nilai is not None and b.nilai_hash != sidik(nilai):
                return BELUM
            if nilai is not None and tampak_simulasi(jenis, nilai):
                return SIMULASI
        return b.status_verifikasi if b.status_verifikasi in STATUS else BELUM

    def status_produk(self, p: Product, jenis: str) -> str | None:
        """None bila datanya kosong: tidak ada yang perlu ditahan, jawaban "belum ada data" tetap berlaku."""
        nilai = nilai_produk(p, jenis)
        return self._status(PRODUK, p.id, jenis, nilai) if nilai else None

    def status_klaim(self, c: ApprovedClaim) -> str:
        return self._status(KLAIM, c.id, KLAIM, c.teks_klaim)

    def status_dokumen(self, document_id: int) -> str:
        return self._status(DOKUMEN, document_id, DOKUMEN, None)

    def _boleh(self, status: str | None, label: str) -> bool:
        if status is None or status == TERVERIFIKASI:
            return True
        if status == SIMULASI and self.mode == DEMO:
            self.memakai_simulasi = True
            return True
        self.tertahan.add(label)
        return False

    def boleh_produk(self, p: Product, jenis: str) -> bool:
        return self._boleh(self.status_produk(p, jenis), jenis)

    def boleh_klaim(self, c: ApprovedClaim) -> bool:
        return self._boleh(self.status_klaim(c), KLAIM)

    def boleh_dokumen(self, document_id: int) -> bool:
        return self._boleh(self.status_dokumen(document_id), DOKUMEN)

    def boleh_kutip(self, chunk: Chunk) -> bool:
        """Chunk katalog menggabungkan semua fakta satu produk, jadi hanya boleh dikutip bila semuanya lolos."""
        if chunk.document.tipe != "katalog" or chunk.product_id is None:
            return self.boleh_dokumen(chunk.document_id)
        p = self.db.get(Product, chunk.product_id)
        if p is None:
            return False
        hasil = [self.boleh_produk(p, j) for j in ("produk", "izin_edar", "harga", "moq", "halal", "bko")]
        return all(hasil) and all([self.boleh_klaim(c) for c in p.claims])

    def _lolos(self, status: str | None) -> bool:
        return status == TERVERIFIKASI or (status == SIMULASI and self.mode == DEMO)

    def lolos_dokumen(self, document_id: int) -> bool:
        """Untuk memilih kandidat: belum berarti dokumennya disajikan, jadi tidak dicatat sebagai pemakaian."""
        return self._lolos(self.status_dokumen(document_id))

    def potret_nilai(self) -> tuple[set[str], set[str]]:
        """(fragmen yang tidak boleh muncul, fragmen simulasi yang lolos) untuk gerbang teks final. Nilai yang juga dipakai
        fakta lain yang lolos tidak ditahan: dua produk bisa saja berharga sama."""
        tahan, simulasi, aman = set(), set(), set()

        def catat(status: str | None, fragmen: list) -> None:
            bersih = {str(f).strip().lower() for f in fragmen if f and len(str(f).strip()) >= _MIN_FRAGMEN}
            if status is None:
                return
            if not self._lolos(status):
                tahan.update(bersih)
            elif status == SIMULASI:
                simulasi.update(bersih)
            else:
                aman.update(bersih)

        produk = list(self.db.scalars(select(Product).where(Product.aktif.is_(True)).options(selectinload(Product.claims))))
        for p in produk:
            t = p.data_teknis or {}
            halal, bko = t.get("sertifikasi_halal") or {}, t.get("status_bebas_bko") or {}
            catat(self.status_produk(p, "izin_edar"), [p.no_izin_edar])
            catat(self.status_produk(p, "halal"), [halal.get("nomor_sertifikat")])
            catat(self.status_produk(p, "bko"), [bko.get("nomor_laporan_uji")])
            catat(self.status_produk(p, "aturan_pakai"), [t.get("aturan_pakai")])
            harga = [rupiah(p.harga_dasar)] + ([rupiah(p.het_per_botol)] if p.het_per_botol else [])
            catat(self.status_produk(p, "harga"), harga if p.harga_dasar else [])
            for c in p.claims:
                catat(self.status_klaim(c), [c.teks_klaim.rstrip(".")])
        return tahan - aman, simulasi


def ada_fragmen(fragmen: set[str], teks: str | None) -> list[str]:
    if not teks:
        return []
    rendah = teks.lower()
    # "Rp 36.000" tidak boleh cocok dengan "Rp 36.000.000": angka harus berhenti di situ.
    return [f for f in fragmen if f in rendah and re.search(re.escape(f) + r"(?![\d.,]*\d)", rendah)]


@contextmanager
def sesi(db: Session):
    """Satu potret untuk satu penyusunan draf: hemat query dan mencatat fakta yang dipakai atau ditahan."""
    sar = Saringan(db)
    db.info[_KUNCI_SESI] = sar
    try:
        yield sar
    finally:
        db.info.pop(_KUNCI_SESI, None)


class PencatatImpor:
    """Menulis status dari jalur impor. Tidak pernah membuat `terverifikasi`; verifikasi lama hanya bertahan bila nilainya
    masih sama persis, sehingga pembaruan harga tidak memaksa memeriksa ulang fakta yang tidak berubah."""

    def __init__(self, db: Session, aktor: str):
        self.db, self.aktor = db, aktor
        self._baris = {(b.objek_tipe, b.objek_id, b.jenis_fakta): b for b in db.scalars(select(VerifikasiFakta))}
        self.hitung: Counter = Counter()

    def _simpan(self, kunci: tuple, nilai: str | None, status: str, sumber_bukti: str | None, berlaku: date | None) -> None:
        if status == TERVERIFIKASI:
            raise StatusDitolak("Jalur impor tidak boleh menandai terverifikasi.")
        b = self._baris.get(kunci)
        if b is not None and b.status_verifikasi == TERVERIFIKASI and (nilai is None or b.nilai_hash == sidik(nilai)):
            self.hitung[TERVERIFIKASI] += 1
            return
        if b is None:
            b = VerifikasiFakta(objek_tipe=kunci[0], objek_id=kunci[1], jenis_fakta=kunci[2])
            self.db.add(b)
            self._baris[kunci] = b
        b.status_verifikasi, b.sumber_bukti, b.berlaku_sampai = status, sumber_bukti or None, berlaku
        b.diverifikasi_oleh, b.diverifikasi_pada, b.nilai_hash = None, None, None
        b.diubah_oleh, b.diubah_pada = self.aktor[:120], clock.now()
        self.hitung[status] += 1

    def produk(self, p: Product, status: str, sumber_bukti: str | None = None, berlaku: date | None = None) -> None:
        # Semua jenis ditulis, juga yang masih kosong: stok atau tier yang terisi kemudian tetap punya status asal yang benar.
        for jenis in JENIS_PRODUK:
            nilai = nilai_produk(p, jenis)
            self._simpan((PRODUK, p.id, jenis), nilai, SIMULASI if tampak_simulasi(jenis, nilai) else status, sumber_bukti, berlaku)

    def klaim_baru(self, c: ApprovedClaim, status: str, sumber_bukti: str | None = None, berlaku: date | None = None) -> None:
        self._simpan((KLAIM, c.id, KLAIM), c.teks_klaim, status, sumber_bukti, berlaku)

    def ganti_klaim(self, lama: dict[str, int], baru: list[ApprovedClaim], status: str, sumber_bukti: str | None,
                    berlaku: date | None) -> None:
        """Impor menghapus lalu menulis ulang klaim, jadi id berubah (di SQLite bisa terpakai ulang). Verifikasi mengikuti
        teksnya; klaim yang dibuang ikut hilang statusnya."""
        terbawa = {}
        for teks, cid in lama.items():
            b = self._baris.get((KLAIM, cid, KLAIM))
            if b is not None and b.status_verifikasi == TERVERIFIKASI and b.nilai_hash == sidik(teks):
                terbawa[teks] = (b.diverifikasi_oleh, b.diverifikasi_pada, b.sumber_bukti, b.berlaku_sampai, b.nilai_hash)
        id_baru = {c.id for c in baru}
        for cid in lama.values():
            if cid not in id_baru and (b := self._baris.pop((KLAIM, cid, KLAIM), None)) is not None:
                self.db.delete(b)
        for c in baru:
            self.klaim_baru(c, status, sumber_bukti, berlaku)
            if c.teks_klaim in terbawa:
                b = self._baris[(KLAIM, c.id, KLAIM)]
                b.status_verifikasi = TERVERIFIKASI
                b.diverifikasi_oleh, b.diverifikasi_pada, b.sumber_bukti, b.berlaku_sampai, b.nilai_hash = terbawa[c.teks_klaim]
                c.diverifikasi_oleh = b.diverifikasi_oleh

    def dokumen(self, document_id: int, status: str, sumber_bukti: str | None = None, berlaku: date | None = None) -> None:
        self._simpan((DOKUMEN, document_id, DOKUMEN), None, status, sumber_bukti, berlaku)

    def bawa_dokumen(self, lama_id: int, baru_id: int) -> bool:
        """Versi baru dengan isi sama persis: verifikasi versi lama tetap berlaku."""
        b = self._baris.get((DOKUMEN, lama_id, DOKUMEN))
        if b is None or b.status_verifikasi != TERVERIFIKASI:
            return False
        baru = VerifikasiFakta(objek_tipe=DOKUMEN, objek_id=baru_id, jenis_fakta=DOKUMEN, status_verifikasi=TERVERIFIKASI,
                               diverifikasi_oleh=b.diverifikasi_oleh, diverifikasi_pada=b.diverifikasi_pada, sumber_bukti=b.sumber_bukti,
                               berlaku_sampai=b.berlaku_sampai, diubah_oleh=self.aktor[:120], diubah_pada=clock.now())
        self.db.add(baru)
        self._baris[(DOKUMEN, baru_id, DOKUMEN)] = baru
        return True


def baca_kolom_status(r: dict) -> tuple[dict, list[tuple[str, str]], list[tuple[str, str]]]:
    """Kolom status_verifikasi, sumber_bukti, berlaku_sampai satu baris file: (nilai, error, peringatan)."""
    error, peringatan = [], []
    status = (r.get("status_verifikasi") or "").strip().lower().replace(" ", "_")
    if not status:
        status = BELUM
        peringatan.append(("status_verifikasi", "Status kosong: dianggap belum_diverifikasi, AI tidak mengutip sampai admin memverifikasi."))
    elif status == TERVERIFIKASI:
        status = BELUM
        peringatan.append(("status_verifikasi", "Impor tidak bisa menandai terverifikasi: dianggap belum_diverifikasi, kecuali "
                                                "nilainya sama persis dengan yang sudah diverifikasi admin."))
    elif status not in STATUS:
        error.append(("status_verifikasi", "Isi dengan: simulasi, belum_diverifikasi, atau kedaluwarsa."))
    berlaku = None
    teks = (r.get("berlaku_sampai") or "").strip()
    if teks:
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", teks)
        try:
            berlaku = date(int(m[3]), int(m[2]), int(m[1])) if m else date.fromisoformat(teks[:10])
        except ValueError:
            error.append(("berlaku_sampai", "Tanggal tidak dikenal. Pakai 2027-12-31 atau 31/12/2027."))
        else:
            if berlaku < clock.now().date():
                peringatan.append(("berlaku_sampai", "Tanggal sudah lewat: fakta ini berstatus kedaluwarsa dan tidak dikutip AI."))
    return {"status": status, "sumber_bukti": (r.get("sumber_bukti") or "").strip() or None,
            "berlaku_sampai": berlaku.isoformat() if berlaku else None}, error, peringatan


def status_awal_produk(sumber_data: str | None) -> str:
    return SIMULASI if (sumber_data or "") in ("simulasi", "sintetis") else BELUM


def status_awal_dokumen(judul: str) -> str:
    return SIMULASI if judul_simulasi(judul) else BELUM


def terlemah(daftar: list[str | None]) -> str | None:
    ada = [s for s in daftar if s]
    return min(ada, key=lambda s: _PERINGKAT[s]) if ada else None


def _objek(db: Session, tipe: str, objek_id: int, jenis: str) -> tuple[str | None, str, int | None, str]:
    """(nilai, label, product_id, nama objek) atau StatusDitolak bila objeknya tidak dikenal."""
    if tipe == PRODUK:
        p = db.get(Product, objek_id)
        if p is None or jenis not in JENIS_PRODUK:
            raise StatusDitolak("Fakta produk tidak ditemukan.")
        return nilai_produk(p, jenis), JENIS_PRODUK[jenis], p.id, f"{p.sku} {p.nama}"
    if tipe == KLAIM:
        c = db.get(ApprovedClaim, objek_id)
        if c is None or jenis != KLAIM:
            raise StatusDitolak("Klaim tidak ditemukan.")
        return c.teks_klaim, LABEL_KLAIM, c.product_id, f"#{c.id}"
    if tipe == DOKUMEN:
        d = db.get(Document, objek_id)
        if d is None or jenis != DOKUMEN:
            raise StatusDitolak("Dokumen tidak ditemukan.")
        return None, LABEL_DOKUMEN, None, f"{d.judul} v{d.versi}"
    raise StatusDitolak("Jenis objek tidak dikenal.")


def ubah_status(db: Session, *, objek_tipe: str, objek_id: int, jenis_fakta: str, status: str, sumber_bukti: str | None,
                berlaku_sampai: date | None, user: User) -> VerifikasiFakta:
    """Satu-satunya jalur menuju `terverifikasi`. Nama verifikator diambil dari akun yang login. Pemanggil yang commit."""
    if status not in STATUS:
        raise StatusDitolak("Status tidak dikenal.")
    nilai, label, product_id, nama = _objek(db, objek_tipe, objek_id, jenis_fakta)
    if nilai == "":
        raise StatusDitolak("Datanya kosong, jadi tidak ada yang bisa diberi status.")
    bukti = (sumber_bukti or "").strip()
    hari_ini = clock.now().date()
    if status == TERVERIFIKASI:
        if len(bukti) < 3:
            raise StatusDitolak("Sumber bukti wajib diisi untuk menandai terverifikasi.")
        if nilai is not None and tampak_simulasi(jenis_fakta, nilai):
            raise StatusDitolak("Nilai ini masih berpola data simulasi. Ganti dengan data resmi dulu.")
        if berlaku_sampai is not None and berlaku_sampai < hari_ini:
            raise StatusDitolak("Tanggal berlaku sudah lewat. Fakta ini berstatus kedaluwarsa.")
    b = db.scalar(select(VerifikasiFakta).where(VerifikasiFakta.objek_tipe == objek_tipe, VerifikasiFakta.objek_id == objek_id,
                                                VerifikasiFakta.jenis_fakta == jenis_fakta))
    sebelum = b.status_verifikasi if b is not None else BELUM
    if b is None:
        b = VerifikasiFakta(objek_tipe=objek_tipe, objek_id=objek_id, jenis_fakta=jenis_fakta)
        db.add(b)
    sekarang = clock.now()
    b.status_verifikasi, b.sumber_bukti, b.berlaku_sampai = status, bukti or None, berlaku_sampai
    b.diubah_oleh, b.diubah_pada = f"staf:{user.nama}"[:120], sekarang
    if status == TERVERIFIKASI:
        b.diverifikasi_oleh, b.diverifikasi_pada = user.nama, sekarang
        b.nilai_hash = sidik(nilai) if nilai is not None else None
    else:
        b.diverifikasi_oleh, b.diverifikasi_pada, b.nilai_hash = None, None, None
    if objek_tipe == KLAIM:
        db.get(ApprovedClaim, objek_id).diverifikasi_oleh = user.nama if status == TERVERIFIKASI else None
    ledger.record(db, "fakta_status_diubah", aktor=f"staf:{user.nama}", objek_ref=f"{objek_tipe}:{objek_id}:{jenis_fakta}"[:80],
                  product_id=product_id, model=None, outcome=status, alasan=bukti[:500],
                  ringkasan=f"{label} {nama}: {sebelum} → {status}"[:280],
                  data={"sebelum": sebelum, "sesudah": status, "sumber_bukti": bukti or None,
                        "berlaku_sampai": berlaku_sampai.isoformat() if berlaku_sampai else None})
    return b


def _item(sar: Saringan, tipe: str, objek_id: int, jenis: str, label: str, nilai: str, status: str, **lain) -> dict:
    b = sar.baris(tipe, objek_id, jenis)
    return {"objek_tipe": tipe, "objek_id": objek_id, "jenis_fakta": jenis, "label": label, "nilai": nilai[:300], "status": status,
            "nilai_berubah": b is not None and b.status_verifikasi == TERVERIFIKASI and status == BELUM,
            "diverifikasi_oleh": b.diverifikasi_oleh if b else None,
            "diverifikasi_pada": b.diverifikasi_pada.isoformat() if b and b.diverifikasi_pada else None,
            "sumber_bukti": b.sumber_bukti if b else None,
            "berlaku_sampai": b.berlaku_sampai.isoformat() if b and b.berlaku_sampai else None, **lain}


def daftar(db: Session, status: list[str] | None = None) -> dict:
    """Semua fakta dari produk dan dokumen aktif untuk halaman Katalog."""
    sar = Saringan(db)
    items = []
    produk = db.scalars(select(Product).where(Product.aktif.is_(True)).order_by(Product.sku)
                        .options(selectinload(Product.claims), selectinload(Product.pricing)))
    for p in produk:
        induk = {"produk": {"id": p.id, "sku": p.sku, "nama": p.nama}}
        for jenis, label in JENIS_PRODUK.items():
            st = sar.status_produk(p, jenis)
            if st is not None:
                items.append(_item(sar, PRODUK, p.id, jenis, label, nilai_tampil(p, jenis), st, **induk))
        for c in p.claims:
            items.append(_item(sar, KLAIM, c.id, KLAIM, LABEL_KLAIM, c.teks_klaim, sar.status_klaim(c), **induk))
    for d in db.scalars(select(Document).where(Document.aktif.is_(True)).order_by(Document.id)):
        items.append(_item(sar, DOKUMEN, d.id, DOKUMEN, LABEL_DOKUMEN, f"{d.judul} v{d.versi}", sar.status_dokumen(d.id), produk=None))
    jumlah = Counter(i["status"] for i in items)
    if status:
        items = [i for i in items if i["status"] in status]
    return {"mode_data": sar.mode, "ringkasan": {s: jumlah.get(s, 0) for s in STATUS}, "items": items}
