"""Riset pasar prospek (Live AI Search Audit) + Next Best Action.

Live AI Search Audit: berita Google 7 hari terakhir per topik kesehatan di wilayah prospek, lewat Serper
(google.serper.dev, butuh SERPER_API_KEY). Angka yang ditampilkan hanya jumlah artikel yang benar-benar ditemukan
beserta tautannya — tidak ada persentase atau tren karangan. Tanpa API key statusnya "tidak_terhubung".

Next Best Action: dirumuskan deterministik dari sinyal berita + data prospek (skor, jarak, kontak, status) +
katalog (hanya produk dengan klaim resmi) + kebijakan penjualan (tier diskon, gratis ongkir Kota Semarang ≥25 box),
lalu diaudit ClaimGuard sebelum ditampilkan."""

import logging
from concurrent.futures import ThreadPoolExecutor

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import claimguard, clock, ledger
from ..agents.sales import max_discount
from ..config import get_settings
from ..models import ApprovedClaim, Product, Prospect

log = logging.getLogger("aage.prospek.market")
settings = get_settings()

SERPER_NEWS_URL = "https://google.serper.dev/news"
BUNDLE_BOX = 25

# Topik pasar → kueri berita + kata kunci untuk memilih produk berklaim resmi
TOPIK = [
    {"id": "pencernaan", "label": "kesehatan pencernaan", "kueri": "sakit perut OR maag OR diare",
     "kata_klaim": ["pencernaan", "kembung", "diare"]},
    {"id": "daya_tahan", "label": "daya tahan tubuh", "kueri": "flu OR pancaroba OR batuk pilek",
     "kata_klaim": ["daya tahan"]},
    {"id": "batuk", "label": "batuk & tenggorokan", "kueri": "batuk OR ISPA OR polusi udara",
     "kata_klaim": ["batuk", "tenggorokan"]},
    {"id": "stamina", "label": "stamina & kebugaran", "kueri": "cuaca panas OR kelelahan OR stamina",
     "kata_klaim": ["stamina", "energi", "kebugaran"]},
]


def _kota(wilayah: str) -> str:
    w = wilayah.strip()
    for prefix in ("Kota ", "Kabupaten ", "Kab. "):
        if w.startswith(prefix):
            return w[len(prefix):]
    return w


def _serper_news(query: str) -> list[dict]:
    resp = httpx.post(SERPER_NEWS_URL, headers={"X-API-KEY": settings.serper_api_key, "Content-Type": "application/json"},
                      json={"q": query, "gl": "id", "hl": "id", "tbs": "qdr:w", "num": 10}, timeout=12)
    resp.raise_for_status()
    out = []
    for n in resp.json().get("news", []):
        if n.get("link") and n.get("title"):
            out.append({"judul": n["title"], "tautan": n["link"], "cuplikan": n.get("snippet", ""),
                        "sumber": n.get("source", ""), "tanggal": n.get("date", "")})
    return out


def market_audit(wilayah: str) -> dict:
    kota = _kota(wilayah)
    base = {"sumber": "Serper · Google News", "periode": "7 hari terakhir", "wilayah": wilayah, "dipindai": clock.now().isoformat()}
    if not settings.serper_api_key:
        return {**base, "status": "tidak_terhubung", "topik": [], "topik_utama": None,
                "ringkasan": "Isi SERPER_API_KEY di .env (daftar gratis di serper.dev) agar audit mengambil berita Google nyata beserta tautannya."}
    queries = [f"({t['kueri']}) {kota}" for t in TOPIK]
    try:
        with ThreadPoolExecutor(max_workers=len(queries)) as ex:
            hasil = list(ex.map(_serper_news, queries))
    except httpx.HTTPError as exc:
        log.warning("Serper gagal: %s", exc)
        return {**base, "status": "gagal", "topik": [], "topik_utama": None, "ringkasan": f"Pencarian Google gagal: {exc}"}
    topik = [{"id": t["id"], "label": t["label"], "kueri": q, "jumlah_artikel": len(a), "artikel": a}
             for t, q, a in zip(TOPIK, queries, hasil)]
    utama = max(topik, key=lambda x: x["jumlah_artikel"])
    total = sum(t["jumlah_artikel"] for t in topik)
    if total == 0:
        ringkasan = f"Tidak ada berita Google 7 hari terakhir untuk topik kesehatan yang dipantau di {kota}."
        utama_id = None
    else:
        ringkasan = (f"Google News 7 hari terakhir: {total} artikel terkait topik kesehatan di {kota}. Topik paling banyak "
                     f"diberitakan: {utama['label']} ({utama['jumlah_artikel']} artikel).")
        utama_id = utama["id"]
    return {**base, "status": "ok", "topik": topik, "topik_utama": utama_id, "ringkasan": ringkasan}


def _produk_topik(db: Session, topik: dict, n: int = 2) -> list[tuple[Product, str]]:
    out = []
    rows = db.execute(select(Product, ApprovedClaim).join(ApprovedClaim).where(Product.aktif.is_(True)).order_by(Product.sku))
    for p, c in rows:
        if any(k in c.teks_klaim.lower() for k in topik["kata_klaim"]) and p.id not in {x.id for x, _ in out}:
            out.append((p, c.teks_klaim.rstrip(".")))
        if len(out) >= n:
            break
    return out


def next_best_action(db: Session, p: Prospect, market: dict) -> dict:
    topik_id = market.get("topik_utama") or "daya_tahan"
    topik = next(t for t in TOPIK if t["id"] == topik_id)
    produk = _produk_topik(db, topik)
    dasar = []
    if market.get("topik_utama"):
        jumlah = next(t["jumlah_artikel"] for t in market["topik"] if t["id"] == topik_id)
        sinyal = f"Sinyal pasar: {jumlah} berita Google 7 hari terakhir tentang {topik['label']} di {_kota(p.wilayah)}."
        dasar.append(sinyal)
    else:
        sinyal = "Belum ada sinyal berita; rekomendasi memakai lini produk daya tahan tubuh sebagai pembuka."
        dasar.append(sinyal)

    prioritas = "TINGGI" if p.skor >= 70 else "SEDANG" if p.skor >= 45 else "RENDAH"
    dasar.append(f"Opportunity Score {p.skor}/100 ({p.jarak_km} km dari gudang) → prioritas {prioritas.lower()}.")

    diskon = max(max_discount(db, prod, BUNDLE_BOX)[0] for prod, _ in produk) if produk else 0
    ongkir = "gratis ongkir (kebijakan Kota Semarang ≥25 box)" if p.wilayah.lower() == "kota semarang" else "ongkir sesuai ekspedisi"
    dasar.append(f"Kebijakan penjualan: diskon volume hingga {diskon:g}% mulai {BUNDLE_BOX} box; {ongkir}.")

    if p.telepon:
        kanal = f"Hubungi via telepon/WhatsApp {p.telepon} (pesan pembuka sudah lolos ClaimGuard)."
    else:
        kanal = "Telepon tidak tercantum di OpenStreetMap — jadwalkan kunjungan langsung sales lapangan."
    dasar.append(kanal)

    langkah = {
        "baru": "Lakukan kontak pertama minggu ini",
        "dihubungi": "Tindak lanjuti dengan penawaran tertulis",
        "merespons": "Kirim penawaran bundling dan ajukan draf pesanan",
        "menolak": "Tunda 30 hari, lalu tawarkan ulang dengan lini produk berbeda",
    }[p.status]
    nama_produk = " dan ".join(f"{prod.nama}" for prod, _ in produk) or "produk lini daya tahan tubuh"
    klaim = "; ".join(f"{prod.nama}: {k.lower()}" for prod, k in produk)
    teks = (f"Rekomendasi AAGE (prioritas {prioritas.lower()}): {langkah}. {sinyal} Tawarkan {nama_produk} dalam bundling "
            f"{BUNDLE_BOX} box dengan diskon volume {diskon:g}% dan {ongkir}. {kanal}")
    chk = claimguard.check(db, teks, product_ids=[prod.id for prod, _ in produk] or None, use_llm=False)
    if chk.verdict != claimguard.ALLOWED:
        teks = chk.safe_text
    return {
        "prioritas": prioritas, "langkah": langkah, "topik": topik["label"], "teks": teks,
        "produk": [{"sku": prod.sku, "nama": prod.nama, "izin_edar": prod.no_izin_edar, "klaim_resmi": k} for prod, k in produk],
        "klaim_ringkas": klaim, "penawaran": {"bundling_box": BUNDLE_BOX, "diskon_persen": diskon, "ongkir": ongkir},
        "kanal": kanal, "dasar": dasar, "verdict": chk.verdict, "aturan": chk.rules_triggered,
        "dirumuskan": clock.now().isoformat(), "metode": "deterministik (sinyal berita + data prospek + katalog + kebijakan)",
    }


def research(db: Session, p: Prospect, aktor: str) -> Prospect:
    market = market_audit(p.wilayah)
    p.market_analysis = market
    p.nba = next_best_action(db, p, market)
    ledger.record(db, "prospek_riset", objek_ref=f"prospect:{p.id}", aktor=aktor,
                  ringkasan=f"Riset {p.nama}: {market['status']} · NBA prioritas {p.nba['prioritas'].lower()}",
                  alasan=market["ringkasan"][:400], verdict=p.nba["verdict"],
                  sumber_ref=[{"jenis": "serper", "tautan": a["tautan"]} for t in market["topik"] for a in t["artikel"][:2]],
                  outcome=market["status"], data={"topik_utama": market.get("topik_utama")})
    db.commit()
    return p
