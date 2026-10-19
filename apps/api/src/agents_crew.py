"""AAGE Multi-Agent Crew — 4 agen CrewAI untuk CV Arba'in.

    b2b_sales_agent    B2B Procurement Specialist        stok, legalitas, nego harga lapis pertama
    lead_miner_agent   Data Scientist & Lead Finder      prospek apotek/minimarket + skor urgensi
    geo_content_agent  GEO & Medical Content Specialist  konten ramah AI search (Perplexity/ChatGPT)
    claim_guard_agent  Compliance Watchdog Hukum Farmasi audit Perban BPOM No. 30/2023

Database produk: config/mock_products.json (50 produk SIMULASI).
Model: AGENT_MODEL (default "anthropic/claude-sonnet-5-5"; claude-3-5-sonnet sudah pensiun 28 Okt 2025).

Mode eksekusi (AGENT_MODE):
    llm       CrewAI + Claude memutuskan, memanggil tool deterministik di bawah.
    simulasi  Tanpa LLM: alur & tool yang sama dijalankan berurutan (untuk demo offline / tanpa API key).
    auto      llm bila ANTHROPIC_API_KEY tersedia, selain itu simulasi (default).

Keputusan kritis TIDAK diserahkan ke LLM: batas diskon dan larangan klaim dihitung oleh tool deterministik,
dan audit ClaimGuard deterministik selalu dijalankan setelah agen — hasil LLM tidak bisa menurunkan BLOCKED.

Human-in-the-loop: `human_in_the_loop=True` (default) menahan deal harga final dan konten sebelum terbit.
Di CLI memakai `Task.human_input` bawaan CrewAI (konfirmasi di terminal); di API, item masuk antrean
approval dashboard dengan status NEED_HUMAN_CONFIRMATION.

Stream log: setiap aktivitas agen dipancarkan sebagai event JSON (lihat `ActivityStream`) yang dikirim
FastAPI ke dashboard Next.js sebagai Server-Sent Events.

CLI:
    python -m src.agents_crew workday --wilayah "Kota Semarang"
    python -m src.agents_crew nego --produk "propolis" --box 50 --diskon 15
    python -m src.agents_crew audit --teks "Madu ini menyembuhkan diabetes 100%"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import queue
import random
import re
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# Jangan kirim telemetri CrewAI ke pihak ketiga (data pembeli & harga bersifat internal).
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aage.claimguard.rules import is_negated  # noqa: E402
from aage.claimguard.service import _product_name_re, _stage1  # noqa: E402  (aturan ClaimGuard yang sama dengan pipeline WA)

PRODUCTS_PATH = Path(os.getenv("AAGE_PRODUCTS_PATH", ROOT / "config" / "mock_products.json"))
REGULASI_PATH = ROOT / "config" / "regulasi_bpom.json"
MODEL = os.getenv("AGENT_MODEL", "anthropic/claude-sonnet-5-5")
GUDANG = {"nama": "Gudang CV Arba'in (contoh) — Semarang", "lat": -6.9932, "lng": 110.4203}

# Status standar yang dikirim ke dashboard
NEED_HUMAN_CONFIRMATION = "NEED_HUMAN_CONFIRMATION"
AUTO_APPROVED = "AUTO_APPROVED"
BLOCKED = "BLOCKED"
REVIEW = "REVIEW"
PASSED = "PASSED"

AGENT_IDS = ("b2b_sales_agent", "lead_miner_agent", "geo_content_agent", "claim_guard_agent")
AGENT_LABEL = {
    "orchestrator": "Orchestrator",
    "b2b_sales_agent": "Sales Agent",
    "lead_miner_agent": "Lead Miner",
    "geo_content_agent": "GEO Marketer",
    "claim_guard_agent": "ClaimGuard Watchdog",
}


# =============================================================================
# Database produk (RAG source)
# =============================================================================


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).strip()


class ProductDB:
    """Akses baca ke config/mock_products.json."""

    def __init__(self, path: Path = PRODUCTS_PATH):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.meta = {k: v for k, v in data.items() if k != "produk"}
        self.products: list[dict] = data["produk"]
        self._by_id = {p["id"]: p for p in self.products}

    def get(self, product_id: str) -> dict | None:
        return self._by_id.get(product_id.strip().upper())

    def find(self, query: str) -> dict | None:
        """Cari produk dari ID, nama, atau kata kunci (pencocokan token sederhana)."""
        q = _norm(query)
        if not q:
            return None
        if (p := self.get(query)) is not None:
            return p
        generic = {"kapsul", "madu", "minyak", "teh", "serbuk", "sirup", "tablet", "botol", "ml", "g", "isi", "plus", "herbal", "anak"}
        q_tokens = set(q.split()) - generic
        best, best_score = None, 0.0
        for p in self.products:
            name_tokens = set(_norm(p["nama_produk"]).split()) - generic
            name_tokens = {t for t in name_tokens if not t.isdigit()}
            kw = set(_norm(p.get("kata_kunci", "")).split())
            score = (len(q_tokens & name_tokens) / max(1, len(name_tokens))) * 2 + len(q_tokens & kw) * 0.2
            if score > best_score:
                best, best_score = p, score
        return best if best_score >= 0.6 else None

    def summary(self, p: dict) -> dict:
        m = p["matriks_harga_b2b"]
        return {
            "id": p["id"], "nama_produk": p["nama_produk"], "kategori": p["kategori"],
            "nomor_izin_edar_bpom": p["nomor_izin_edar_bpom"], "sertifikasi_halal": p["sertifikasi_halal"]["status"],
            "bahan_aktif": p["bahan_aktif"], "klaim_khasiat_resmi_bpom": p["klaim_khasiat_resmi_bpom"],
            "het_per_botol": m["harga_eceran_tertinggi_het"], "harga_b2b_per_botol": m["harga_dasar_b2b_per_botol"],
            "isi_per_box": m["isi_per_box_botol"], "moq_box": m["moq_minimal_box"],
            "status_bebas_bko": p["data_teknis_kefarmasian"]["status_bebas_bko"]["hasil"],
        }


_DB: ProductDB | None = None


def db() -> ProductDB:
    global _DB
    if _DB is None:
        _DB = ProductDB()
    return _DB


def regulasi() -> dict:
    return json.loads(REGULASI_PATH.read_text(encoding="utf-8"))


def rupiah(v: float) -> str:
    return "Rp " + f"{v:,.0f}".replace(",", ".")


# =============================================================================
# Stream log aktivitas agen
# =============================================================================


@dataclass
class AgentEvent:
    agent: str
    message: str
    level: str = "info"  # info | progress | success | warning | alert | hitl | done
    status: str | None = None
    data: dict = field(default_factory=dict)
    ts: str = ""
    clock: str = ""
    seq: int = 0

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, default=str)


class ActivityStream:
    """Antrean event thread-safe. Produsen: crew/simulasi; konsumen: CLI atau endpoint SSE."""

    def __init__(self, start_clock: str = "09:00", on_event: Callable[[AgentEvent], None] | None = None):
        self._q: queue.Queue[AgentEvent | None] = queue.Queue()
        self._seq = 0
        self._lock = threading.Lock()
        h, m = (int(x) for x in start_clock.split(":"))
        self._clock = datetime(2026, 1, 1, h, m)
        self.on_event = on_event
        self.closed = False

    def tick(self, minutes: float = 1) -> None:
        self._clock += timedelta(minutes=minutes)

    def emit(self, agent: str, message: str, level: str = "info", status: str | None = None, **data: Any) -> AgentEvent:
        with self._lock:
            self._seq += 1
            ev = AgentEvent(agent=agent, message=message, level=level, status=status, data=data,
                            ts=datetime.now(timezone.utc).isoformat(), clock=self._clock.strftime("%H:%M"), seq=self._seq)
        if self.on_event:
            try:
                self.on_event(ev)
            except Exception:  # pragma: no cover - callback tidak boleh menghentikan crew
                pass
        self._q.put(ev)
        return ev

    def close(self) -> None:
        self.closed = True
        self._q.put(None)

    def __iter__(self) -> Iterator[AgentEvent]:
        while True:
            ev = self._q.get()
            if ev is None:
                return
            yield ev


_ACTIVE_STREAM: ActivityStream | None = None
_ROLE_TO_ID: dict[str, str] = {}


def _register_event_bus() -> None:
    """Teruskan event internal CrewAI (agent/tool/task) ke stream aktif."""
    try:
        from crewai.events import crewai_event_bus
        from crewai.events.types.agent_events import AgentExecutionCompletedEvent, AgentExecutionStartedEvent
        from crewai.events.types.tool_usage_events import ToolUsageFinishedEvent, ToolUsageStartedEvent
    except ImportError:  # pragma: no cover
        return

    def _agent_id(role: str | None) -> str:
        return _ROLE_TO_ID.get(role or "", "orchestrator")

    @crewai_event_bus.on(AgentExecutionStartedEvent)
    def _on_agent_start(source, event):  # noqa: ARG001
        if _ACTIVE_STREAM:
            _ACTIVE_STREAM.emit(_agent_id(event.agent.role), f"{event.agent.role} mulai mengerjakan tugas", "progress")

    @crewai_event_bus.on(AgentExecutionCompletedEvent)
    def _on_agent_done(source, event):  # noqa: ARG001
        if _ACTIVE_STREAM:
            _ACTIVE_STREAM.emit(_agent_id(event.agent.role), f"{event.agent.role} selesai", "success")

    @crewai_event_bus.on(ToolUsageStartedEvent)
    def _on_tool(source, event):  # noqa: ARG001
        if _ACTIVE_STREAM:
            _ACTIVE_STREAM.emit(_agent_id(event.agent_role), f"Memanggil tool: {event.tool_name}", "progress", tool=event.tool_name)

    @crewai_event_bus.on(ToolUsageFinishedEvent)
    def _on_tool_done(source, event):  # noqa: ARG001
        if _ACTIVE_STREAM:
            _ACTIVE_STREAM.emit(_agent_id(event.agent_role), f"Tool {event.tool_name} selesai", "info", tool=event.tool_name)


# =============================================================================
# Inti deterministik (dipakai tool CrewAI dan mode simulasi)
# =============================================================================


def negotiate_price(product_id: str, qty_box: int, requested_discount_pct: float | None = None,
                    buyer: str = "Pembeli") -> dict:
    """Hitung penawaran dari matriks_harga_b2b. Diskon diminta > batas AI → NEED_HUMAN_CONFIRMATION."""
    p = db().get(product_id) or db().find(product_id)
    if p is None:
        return {"status": NEED_HUMAN_CONFIRMATION, "alasan": f"Produk '{product_id}' tidak ditemukan di database."}
    m = p["matriks_harga_b2b"]
    per_botol, isi = m["harga_dasar_b2b_per_botol"], m["isi_per_box_botol"]
    tier = 0.0
    for t in sorted(m["skema_diskon"], key=lambda x: x["min_box"]):
        if qty_box >= t["min_box"]:
            tier = float(t["diskon_persen"])
    batas = float(m["batas_diskon_maksimal_ai_persen"])
    subtotal = per_botol * isi * qty_box

    def offer(d: float) -> dict:
        harga_botol = per_botol * (1 - d / 100)
        return {"diskon_persen": d, "harga_per_botol": round(harga_botol), "harga_per_box": round(harga_botol * isi),
                "total": round(harga_botol * isi * qty_box), "margin_apotek_vs_het_persen": round((1 - harga_botol / m["harga_eceran_tertinggi_het"]) * 100, 1)}

    base = {"produk": db().summary(p), "qty_box": qty_box, "qty_botol": qty_box * isi, "subtotal": subtotal,
            "diskon_tier_persen": tier, "batas_diskon_maksimal_ai_persen": batas, "diskon_diminta_persen": requested_discount_pct,
            "moq_box": m["moq_minimal_box"], "tempo_pembayaran_hari": m["tempo_pembayaran_hari"]}
    if qty_box < m["moq_minimal_box"]:
        return {**base, "status": NEED_HUMAN_CONFIRMATION, "penawaran": offer(0),
                "alasan": f"Di bawah MOQ {m['moq_minimal_box']} box — perlu keputusan staf."}
    if requested_discount_pct is not None and requested_discount_pct > batas:
        return {**base, "status": NEED_HUMAN_CONFIRMATION, "penawaran": offer(tier),
                "alasan": f"Diskon diminta {requested_discount_pct:g}% melebihi batas AI {batas:g}%. Negosiasi otomatis dihentikan.",
                "laporan_staf": (
                    f"ESKALASI NEGOSIASI — {buyer}\n"
                    f"Produk: {p['nama_produk']} ({p['nomor_izin_edar_bpom']})\n"
                    f"Volume: {qty_box} box × {isi} botol = {qty_box * isi} botol\n"
                    f"Permintaan: diskon {requested_discount_pct:g}% | Tier volume: {tier:g}% | Batas AI: {batas:g}%\n"
                    f"Penawaran terakhir AI: {rupiah(offer(tier)['total'])} (diskon {tier:g}%)\n"
                    f"Jika disetujui {requested_discount_pct:g}%: {rupiah(offer(requested_discount_pct)['total'])} — "
                    f"selisih {rupiah(offer(tier)['total'] - offer(requested_discount_pct)['total'])}\n"
                    "Rekomendasi: tawarkan tempo 14 hari atau bundling sebagai ganti diskon tambahan."
                )}
    applied = tier if requested_discount_pct is None else min(requested_discount_pct, max(tier, 0))
    if requested_discount_pct is not None and requested_discount_pct <= batas and requested_discount_pct > tier:
        # Masih di bawah batas AI tetapi di atas tier volume: AI boleh menawarkan hingga tier, sisanya staf.
        return {**base, "status": NEED_HUMAN_CONFIRMATION, "penawaran": offer(tier),
                "alasan": f"Diskon {requested_discount_pct:g}% di atas tier volume {tier:g}% untuk {qty_box} box — butuh persetujuan staf (deal final).",
                "laporan_staf": f"{buyer} meminta {requested_discount_pct:g}% untuk {qty_box} box {p['nama_produk']}; tier volume {tier:g}%."}
    return {**base, "status": AUTO_APPROVED, "penawaran": offer(applied),
            "alasan": f"Diskon {applied:g}% sesuai koridor tier volume (≤ batas AI {batas:g}%)."}


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    r = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = math.radians(b[0] - a[0]), math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


_CITY = {"kota semarang": (-6.9932, 110.4203), "semarang": (-6.9932, 110.4203), "surakarta": (-7.5695, 110.8290),
         "solo": (-7.5695, 110.8290), "salatiga": (-7.3305, 110.5084), "kudus": (-6.8048, 110.8405),
         "demak": (-6.8909, 110.6396), "kendal": (-6.9196, 110.2033), "ungaran": (-7.1394, 110.4040)}
_NAMES = ["Sehat Sentosa", "Barokah", "Medika Jaya", "Waras", "Prima Farma", "Sumber Sehat", "Mitra Keluarga", "Bunda",
          "Amanah", "Sejahtera", "Harapan", "Tunas Farma", "Rahayu", "Lestari", "Abadi", "Nusantara", "Pelita", "Cahaya",
          "Insan", "Al-Falah", "Mulia", "Makmur", "Asri", "Bakti", "Merdeka", "Pandanaran", "Candi", "Tembalang",
          "Banyumanik", "Gajahmungkur", "Ngaliyan", "Pedurungan", "Kaligawe", "Tlogosari", "Sampangan", "Jatingaleh"]
_CHAINS = ["Kimia Farma", "Apotek K-24", "Century", "Guardian", "Indomaret", "Alfamart"]


def simulate_google_places(wilayah: str, jenis: str = "apotek", n: int = 50) -> dict:
    """Simulator Google Places Text Search (deterministik per wilayah). Mengembalikan prospek + kompetitor jaringan."""
    rng = random.Random(hashlib.md5(f"{wilayah.lower()}|{jenis}".encode()).hexdigest())
    lat0, lng0 = _CITY.get(wilayah.lower().strip(), (GUDANG["lat"], GUDANG["lng"]))
    label = {"apotek": "Apotek", "toko obat": "Toko Obat", "minimarket": "Minimarket"}.get(jenis, "Apotek")
    independen = []
    for i in range(n):
        lat, lng = lat0 + rng.uniform(-0.08, 0.08), lng0 + rng.uniform(-0.08, 0.08)
        has_rating = rng.random() > 0.2
        independen.append({
            "place_id": f"sim_{hashlib.md5(f'{wilayah}{i}'.encode()).hexdigest()[:10]}",
            "nama": f"{label} {_NAMES[i % len(_NAMES)]}{'' if i < len(_NAMES) else ' ' + str(i // len(_NAMES) + 1)}",
            "alamat": f"Jl. {rng.choice(['Pemuda', 'Pandanaran', 'MT Haryono', 'Majapahit', 'Setiabudi', 'Fatmawati', 'Sriwijaya', 'Imam Bonjol'])} No. {rng.randint(1, 200)}, {wilayah}",
            "lat": round(lat, 6), "lng": round(lng, 6), "jenis": jenis, "jaringan": False,
            "rating": round(rng.uniform(3.6, 4.9), 1) if has_rating else None,
            "jumlah_ulasan": rng.randint(5, 420) if has_rating else 0,
            "telepon": f"024-{rng.randint(7000000, 8999999)}" if rng.random() > 0.25 else None,
        })
    kompetitor = [{"nama": f"{rng.choice(_CHAINS)} {rng.choice(_NAMES)}", "lat": lat0 + rng.uniform(-0.08, 0.08),
                   "lng": lng0 + rng.uniform(-0.08, 0.08), "jaringan": True} for _ in range(int(n * 0.6))]
    return {"sumber": "google_places_simulator", "wilayah": wilayah, "jenis": jenis, "prospek": independen, "kompetitor_jaringan": kompetitor}


def score_leads(places: dict, top: int = 10) -> list[dict]:
    """Skor urgensi 0–100: jarak gudang (35), kepadatan kompetitor jaringan radius 1 km (35), rating (15), kontak (15).
    Kompetitor jaringan padat = apotek independen tertekan → lebih urgen didekati dengan harga grosir."""
    out = []
    g = (GUDANG["lat"], GUDANG["lng"])
    for p in places["prospek"]:
        jarak = _haversine_km(g, (p["lat"], p["lng"]))
        kompetitor = sum(1 for k in places["kompetitor_jaringan"] if _haversine_km((p["lat"], p["lng"]), (k["lat"], k["lng"])) <= 1.0)
        s_jarak = max(0.0, 35 * (1 - min(jarak, 25) / 25))
        s_komp = min(35.0, kompetitor * 12.0)
        s_rating = 15 * ((p["rating"] or 3.5) - 3.5) / 1.5 if p["rating"] else 4
        s_kontak = 15 if p["telepon"] else 3
        skor = round(min(100, s_jarak + s_komp + s_rating + s_kontak))
        out.append({**p, "jarak_km": round(jarak, 2), "kompetitor_1km": kompetitor, "skor_urgensi": skor,
                    "alasan": [f"Jarak gudang {jarak:.1f} km (+{s_jarak:.0f})", f"{kompetitor} apotek jaringan dalam 1 km (+{s_komp:.0f})",
                               f"Rating {p['rating'] or '–'} (+{s_rating:.0f})", f"Kontak {'tersedia' if p['telepon'] else 'tidak ada'} (+{s_kontak})"],
                    "klasifikasi": "PRIORITAS TINGGI" if skor >= 70 else "PRIORITAS SEDANG" if skor >= 50 else "PANTAU"})
    out.sort(key=lambda x: x["skor_urgensi"], reverse=True)
    return out[:top]


def build_geo_content(product_id: str, topik: str = "") -> dict:
    """Konten GEO terstruktur (answer-first, fakta bersumber, FAQ, JSON-LD) dari data produk — tanpa keyword stuffing."""
    p = db().get(product_id) or db().find(product_id)
    if p is None:
        return {"error": f"Produk '{product_id}' tidak ditemukan"}
    t = p["data_teknis_kefarmasian"]
    klaim = p["klaim_khasiat_resmi_bpom"]
    m = p["matriks_harga_b2b"]
    md = "\n\n".join([
        f"# {p['nama_produk']}: {topik.strip().capitalize() or 'informasi produk untuk apotek'}",
        f"**Ringkasnya:** {p['nama_produk']} adalah {p['kategori'].lower()} dengan nomor izin edar **{p['nomor_izin_edar_bpom']}** "
        f"({p['sertifikasi_halal']['status'].lower()}). {klaim[0]}",
        "## Komposisi\n\n" + "\n".join(f"- {b}" for b in p["bahan_aktif"]),
        "## Klaim yang disetujui BPOM\n\n" + "\n".join(f"- {k}" for k in klaim),
        f"## Data teknis kefarmasian\n\n- Uji Bahan Kimia Obat: {t['status_bebas_bko']['hasil']} "
        f"({t['status_bebas_bko']['metode']}; parameter: {', '.join(t['status_bebas_bko']['parameter_uji'])}).\n"
        f"- Uji stabilitas: {t['uji_stabilitas']['kondisi']}, {t['uji_stabilitas']['durasi_bulan']} bulan — {t['uji_stabilitas']['hasil']}.\n"
        f"- Efek samping yang mungkin: {'; '.join(t['efek_samping'])}.\n- Penyimpanan: {t['penyimpanan']}",
        f"## Informasi untuk apotek\n\nHarga B2B {rupiah(m['harga_dasar_b2b_per_botol'])}/botol (HET {rupiah(m['harga_eceran_tertinggi_het'])}), "
        f"isi {m['isi_per_box_botol']} botol/box, minimum order {m['moq_minimal_box']} box.",
        "## Catatan\n\nProduk ini bukan obat dan tidak ditujukan untuk mengobati penyakit. Untuk keluhan kesehatan, "
        "konsultasikan dengan dokter atau apoteker.",
    ])
    faq = [
        {"q": f"Apa nomor izin edar {p['nama_produk']}?", "a": f"{p['nomor_izin_edar_bpom']}."},
        {"q": f"Apa kandungan {p['nama_produk']}?", "a": "; ".join(p["bahan_aktif"]) + "."},
        {"q": f"Apa manfaat {p['nama_produk']} menurut klaim yang disetujui?", "a": " ".join(klaim)},
        {"q": f"Apakah {p['nama_produk']} bebas bahan kimia obat?", "a": f"{t['status_bebas_bko']['hasil']} berdasarkan laporan uji {t['status_bebas_bko']['nomor_laporan_uji']}."},
    ]
    json_ld = [
        {"@context": "https://schema.org", "@type": "Product", "name": p["nama_produk"], "sku": p["id"], "category": p["kategori"],
         "brand": {"@type": "Brand", "name": "CV Arba'in"},
         "additionalProperty": [{"@type": "PropertyValue", "name": "Nomor izin edar BPOM", "value": p["nomor_izin_edar_bpom"]},
                                {"@type": "PropertyValue", "name": "Sertifikasi halal", "value": p["sertifikasi_halal"]["status"]}]},
        {"@context": "https://schema.org", "@type": "FAQPage",
         "mainEntity": [{"@type": "Question", "name": f["q"], "acceptedAnswer": {"@type": "Answer", "text": f["a"]}} for f in faq]},
    ]
    return {"product_id": p["id"], "judul": md.splitlines()[0].lstrip("# "), "markdown": md, "faq": faq, "json_ld": json_ld}


_SENT = re.compile(r"[^.!?\n]+[.!?]*")


def audit_compliance(text: str, product_id: str | None = None, sumber: str = "konten") -> dict:
    """ClaimGuard deterministik: larangan JSON produk (R20) + aturan regex R01–R19.
    Kalimat melanggar dipotong; status BLOCKED/REVIEW/PASSED; rujukan pasal Perban BPOM 30/2023 disematkan."""
    reg = regulasi()
    pasal_map, pasal_def = reg["pemetaan_aturan"], reg["pasal"]
    products = [p for p in [db().get(product_id) if product_id else None] if p] or db().products
    larangan = {phrase.lower(): p["id"] for p in products for phrase in p["kata_kunci_larangan_overclaim"]}

    name_re = _product_name_re([p["nama_produk"] for p in db().products])
    pelanggaran, kalimat_bersih, worst = [], [], PASSED
    for m in _SENT.finditer(text):
        s = m.group(0).strip()
        if not s:
            continue
        low = s.lower()
        hits = []
        for phrase, pid in larangan.items():
            idx = low.find(phrase)
            if idx >= 0 and not is_negated(s, idx):
                hits.append({"aturan": "R20", "label": "Frasa larangan overclaim (database produk)", "cocok": phrase,
                             "severity": BLOCKED, "product_id": pid})
        # Nama produk terdaftar bukan klaim → disamarkan; penafian & anjuran konsultasi ditangani _stage1.
        masked = name_re.sub(lambda mm: "x" * len(mm.group(0)), s) if name_re else s
        _, rule_hits, _ = _stage1(masked)
        for h in rule_hits:
            hits.append({"aturan": h.id, "label": h.label, "cocok": h.match,
                         "severity": BLOCKED if h.severity == "blocked" else REVIEW})
        if hits:
            sev = BLOCKED if any(h["severity"] == BLOCKED for h in hits) else REVIEW
            for h in hits:
                h["pasal"] = [{"kode": k, **pasal_def[k]} for k in pasal_map.get(h["aturan"], ["P2A4"])]
            pelanggaran.append({"kalimat": s, "status": sev, "temuan": hits})
            worst = BLOCKED if sev == BLOCKED or worst == BLOCKED else REVIEW
            if sev == REVIEW:
                kalimat_bersih.append(s)  # review: dipertahankan tapi ditandai
        else:
            kalimat_bersih.append(s)

    pasal_unik = []
    for v in pelanggaran:
        for h in v["temuan"]:
            for ps in h["pasal"]:
                if ps["rujukan"] not in {x["rujukan"] for x in pasal_unik}:
                    pasal_unik.append(ps)
    return {
        "status": worst, "sumber": sumber, "product_id": product_id,
        "peraturan": reg["peraturan"]["judul"],
        "pelanggaran": pelanggaran, "pasal_dilanggar": pasal_unik,
        "teks_terpotong": " ".join(kalimat_bersih),
        "notifikasi_dashboard": (f"[BPOM COMPLIANCE ALERT: OVERCLAIM FLAGGED] {len([v for v in pelanggaran if v['status'] == BLOCKED])} kalimat "
                                 f"diblokir dari {sumber}") if worst == BLOCKED else None,
    }


# =============================================================================
# Tool CrewAI (membungkus fungsi deterministik)
# =============================================================================


def _make_tools() -> dict[str, list]:
    from crewai.tools import tool

    @tool("Cari Produk")
    def cari_produk(query: str) -> str:
        """Cari produk CV Arba'in berdasarkan nama/ID/kata kunci. Mengembalikan izin edar, bahan aktif, klaim resmi, dan harga B2B."""
        p = db().find(query)
        return json.dumps(db().summary(p) if p else {"error": "tidak ditemukan"}, ensure_ascii=False)

    @tool("Hitung Penawaran B2B")
    def hitung_penawaran(product_id: str, qty_box: int, diskon_diminta_persen: float = -1) -> str:
        """Hitung harga dari matriks_harga_b2b. Isi diskon_diminta_persen=-1 bila pembeli tidak menyebut diskon.
        Jika status NEED_HUMAN_CONFIRMATION, hentikan negosiasi dan sampaikan bahwa staf akan menindaklanjuti."""
        return json.dumps(negotiate_price(product_id, int(qty_box), None if diskon_diminta_persen < 0 else float(diskon_diminta_persen)), ensure_ascii=False)

    @tool("Google Places Simulator")
    def places(wilayah: str, jenis: str = "apotek") -> str:
        """Cari apotek independen/toko obat/minimarket di wilayah lewat simulator Google Places, lalu hitung skor urgensi."""
        return json.dumps(score_leads(simulate_google_places(wilayah, jenis)), ensure_ascii=False)

    @tool("Data Teknis Produk")
    def data_teknis(product_id: str) -> str:
        """Ambil data lengkap produk (izin edar, halal, BKO, stabilitas, efek samping, klaim resmi) untuk konten GEO."""
        p = db().get(product_id) or db().find(product_id)
        return json.dumps(p or {"error": "tidak ditemukan"}, ensure_ascii=False)

    @tool("Kerangka Konten GEO")
    def kerangka_geo(product_id: str, topik: str) -> str:
        """Bangun kerangka konten GEO terstruktur (markdown + FAQ + JSON-LD) dari data resmi produk."""
        return json.dumps(build_geo_content(product_id, topik), ensure_ascii=False)

    @tool("Audit Kepatuhan BPOM")
    def audit(teks: str, product_id: str = "") -> str:
        """Audit teks terhadap kata_kunci_larangan_overclaim dan aturan klaim (Perban BPOM 30/2023). Mengembalikan status, pasal, dan teks terpotong."""
        return json.dumps(audit_compliance(teks, product_id or None), ensure_ascii=False)

    return {
        "b2b_sales_agent": [cari_produk, hitung_penawaran],
        "lead_miner_agent": [places],
        "geo_content_agent": [data_teknis, kerangka_geo],
        "claim_guard_agent": [audit],
    }


# =============================================================================
# Definisi 4 agen (prompt sistem kaku)
# =============================================================================

AGENT_SPECS: dict[str, dict[str, str]] = {
    "b2b_sales_agent": {
        "role": "B2B Procurement Specialist",
        "goal": "Melayani purchasing apotek/minimarket via WhatsApp untuk tanya stok, legalitas, dan nego harga lapis pertama.",
        "backstory": (
            "Anda spesialis pengadaan B2B CV Arba'in yang berbicara dengan bahasa profesional farmasi: margin, HET, tempo, "
            "konsinyasi, MOQ, dan izin edar. ATURAN KAKU: (1) Setiap angka harga WAJIB berasal dari tool 'Hitung Penawaran B2B' "
            "yang membaca 'matriks_harga_b2b' — dilarang mengarang harga atau diskon. (2) Jika apotek menawar diskon melebihi "
            "'batas_diskon_maksimal_ai_persen', Anda WAJIB berhenti bernegosiasi otomatis, menetapkan status eskalasi "
            "NEED_HUMAN_CONFIRMATION, dan menyusun draf laporan untuk staf (produk, volume, permintaan, tier, batas, selisih). "
            "(3) Hanya sampaikan klaim khasiat yang ada di 'klaim_khasiat_resmi_bpom'. (4) Jangan pernah menjanjikan kesembuhan."
        ),
    },
    "lead_miner_agent": {
        "role": "Data Scientist & Lead Finder",
        "goal": "Menganalisis wilayah dan mencari koordinat apotek independen/minimarket baru secara otonom lewat Google Places API simulator.",
        "backstory": (
            "Anda data scientist yang mengklasifikasikan prospek baru dan menghitung skor urgensi pendekatan berdasarkan jarak ke "
            "gudang dan kepadatan apotek kompetitor jaringan. ATURAN KAKU: gunakan tool 'Google Places Simulator'; jangan "
            "menambah prospek yang tidak ada di hasil tool; jelaskan alasan skor per prospek; Anda TIDAK mengirim pesan ke prospek."
        ),
    },
    "geo_content_agent": {
        "role": "GEO & Medical Content Specialist",
        "goal": "Membuat konten pemasaran produk kesehatan yang ramah mesin pencari AI (Perplexity/ChatGPT) tanpa keyword stuffing.",
        "backstory": (
            "Anda penulis konten medis untuk Generative Engine Optimization. ATURAN KAKU: tulis konten terstruktur (jawaban "
            "langsung di paragraf pertama, heading, daftar fakta, FAQ, JSON-LD) yang memuat nomor izin edar BPOM dan data ilmiah "
            "kefarmasian dari file produk (bahan aktif, uji BKO, uji stabilitas, efek samping) agar dipercaya LLM crawler. Klaim "
            "manfaat HANYA dari 'klaim_khasiat_resmi_bpom'. Dilarang superlatif, statistik tanpa sumber, dan pengulangan kata kunci."
        ),
    },
    "claim_guard_agent": {
        "role": "Compliance Watchdog Hukum Farmasi",
        "goal": "Mengaudit setiap teks keluaran dari sales agent dan geo agent agar patuh Peraturan BPOM No 30 Tahun 2023.",
        "backstory": (
            "Anda auditor kepatuhan yang sangat kaku. ATURAN KAKU: jalankan tool 'Audit Kepatuhan BPOM' atas SETIAP teks. Jika teks "
            "mengandung kata kunci dari array 'kata_kunci_larangan_overclaim' di json produk atau melanggar aturan klaim, Anda "
            "WAJIB memotong teks, mengubah status menjadi BLOCKED, menyematkan nomor pasal yang dilanggar dari hasil tool, dan "
            "melempar notifikasi ke dashboard. Anda tidak boleh melonggarkan keputusan BLOCKED dari tool."
        ),
    },
}


def has_llm_credentials() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


def resolve_mode(mode: str | None = None) -> str:
    mode = (mode or os.getenv("AGENT_MODE", "auto")).lower()
    if mode == "auto":
        return "llm" if has_llm_credentials() else "simulasi"
    return mode


class AAGECrew:
    """Crew terintegrasi 4 agen. Satu instance per eksekusi (stream log terikat ke instance)."""

    def __init__(self, *, human_in_the_loop: bool = True, mode: str | None = None, stream: ActivityStream | None = None,
                 interactive: bool = False, speed: float = 1.0,
                 on_hitl: Callable[[dict], None] | None = None):
        self.human_in_the_loop = human_in_the_loop
        self.mode = resolve_mode(mode)
        self.stream = stream or ActivityStream()
        self.interactive = interactive  # True = CLI: pakai Task.human_input CrewAI (konfirmasi di terminal)
        self.speed = speed
        self.on_hitl = on_hitl
        self.hitl_items: list[dict] = []
        self._agents: dict[str, Any] | None = None

    # ---------------------------------------------------------------- util
    def _pause(self, seconds: float) -> None:
        if self.speed > 0:
            time.sleep(seconds / self.speed)

    def _hitl(self, item: dict) -> None:
        item = {"status": NEED_HUMAN_CONFIRMATION, **item}
        self.hitl_items.append(item)
        self.stream.emit("orchestrator", f"Human-in-the-loop: {item['judul']}", "hitl", NEED_HUMAN_CONFIRMATION, item=item)
        if self.on_hitl:
            self.on_hitl(item)

    # ---------------------------------------------------------------- CrewAI
    def agents(self) -> dict[str, Any]:
        if self._agents is None:
            from crewai import LLM, Agent

            _register_event_bus_once()
            llm = LLM(model=MODEL)  # provider Anthropic native (SDK resmi); tanpa temperature (ditolak model 5.x)
            tools = _make_tools()
            self._agents = {}
            for aid, spec in AGENT_SPECS.items():
                _ROLE_TO_ID[spec["role"]] = aid
                self._agents[aid] = Agent(role=spec["role"], goal=spec["goal"], backstory=spec["backstory"], tools=tools[aid],
                                          llm=llm, allow_delegation=False, max_iter=6, verbose=False)
        return self._agents

    def _task(self, agent_id: str, description: str, expected: str, *, human: bool = False, context: list | None = None):
        from crewai import Task

        return Task(description=description, expected_output=expected, agent=self.agents()[agent_id], context=context or [],
                    human_input=bool(human and self.human_in_the_loop and self.interactive))

    def _kickoff(self, tasks: list) -> Any:
        from crewai import Crew, Process

        global _ACTIVE_STREAM
        crew = Crew(agents=list(self.agents().values()), tasks=tasks, process=Process.sequential, verbose=False)
        _ACTIVE_STREAM = self.stream
        try:
            return crew.kickoff()
        finally:
            _ACTIVE_STREAM = None

    # ---------------------------------------------------------------- alur (workflow)
    def negotiate(self, pesan: str, product_id: str, qty_box: int, diskon: float | None, buyer: str) -> dict:
        """Sales agent → (deal final butuh manusia) → ClaimGuard atas draf balasan."""
        s = self.stream
        s.emit("b2b_sales_agent", f"Pesan WA dari {buyer}: “{pesan}”", "progress")
        hasil = negotiate_price(product_id, qty_box, diskon, buyer)
        p = hasil.get("produk", {})
        if self.mode == "llm":
            t_sales = self._task(
                "b2b_sales_agent",
                f"Pesan WhatsApp dari {buyer}: \"{pesan}\". Produk: {product_id}, {qty_box} box, diskon diminta: "
                f"{diskon if diskon is not None else 'tidak disebut'}. Gunakan tool, lalu tulis balasan WhatsApp profesional "
                f"(maks 90 kata). Bila status NEED_HUMAN_CONFIRMATION, katakan staf akan menindaklanjuti dan sertakan draf laporan staf.",
                "Balasan WhatsApp + status (AUTO_APPROVED/NEED_HUMAN_CONFIRMATION) + draf laporan staf bila eskalasi.",
                human=hasil["status"] == AUTO_APPROVED,  # deal harga final dikonfirmasi manusia
            )
            t_guard = self._task("claim_guard_agent", "Audit balasan sales agent sebelum dikirim.",
                                 "Status kepatuhan, pasal, dan teks terpotong.", context=[t_sales])
            out = self._kickoff([t_sales, t_guard])
            balasan = str(t_sales.output.raw if t_sales.output else out)
        else:
            self._pause(0.6)
            s.emit("b2b_sales_agent", f"Membaca matriks_harga_b2b {p.get('nama_produk', product_id)} — tier {hasil.get('diskon_tier_persen', 0):g}%, "
                   f"batas AI {hasil.get('batas_diskon_maksimal_ai_persen', 0):g}%", "info", produk=product_id)
            off = hasil.get("penawaran", {})
            if hasil["status"] == AUTO_APPROVED:
                balasan = (f"Baik, Bapak/Ibu. Untuk {qty_box} box {p['nama_produk']} ({p['nomor_izin_edar_bpom']}), harga "
                           f"{rupiah(off['harga_per_botol'])}/botol (diskon {off['diskon_persen']:g}%), total {rupiah(off['total'])}. "
                           f"Margin apotek terhadap HET sekitar {off['margin_apotek_vs_het_persen']:g}%. Tempo 14 hari dapat diajukan untuk pelanggan tetap.")
            else:
                balasan = (f"Terima kasih atas penawarannya. Untuk {qty_box} box {p.get('nama_produk', product_id)}, diskon yang dapat saya berikan "
                           f"saat ini {off.get('diskon_persen', 0):g}% ({rupiah(off.get('total', 0))}). Permintaan diskon "
                           f"{(diskon or 0):g}% saya teruskan ke staf penjualan untuk keputusan final.")
        self._pause(0.5)
        level = "success" if hasil["status"] == AUTO_APPROVED else "warning"
        s.emit("b2b_sales_agent", f"Status negosiasi: {hasil['status']} — {hasil.get('alasan', '')}", level, hasil["status"], negosiasi=hasil)
        audit = self.guard(balasan, product_id, "b2b_sales_agent")
        if hasil["status"] == NEED_HUMAN_CONFIRMATION:
            self._hitl({"jenis": "negosiasi", "judul": f"Eskalasi diskon {buyer}", "laporan": hasil.get("laporan_staf"), "negosiasi": hasil,
                        "draf_balasan": audit["teks_terpotong"]})
        elif self.human_in_the_loop:
            self._hitl({"jenis": "deal_final", "judul": f"Konfirmasi invoice {buyer}", "negosiasi": hasil, "draf_balasan": audit["teks_terpotong"]})
        return {"balasan": balasan, "negosiasi": hasil, "audit": audit}

    def mine_leads(self, wilayah: str, jenis: str = "apotek") -> list[dict]:
        s = self.stream
        s.emit("lead_miner_agent", f"Menyisir {jenis} independen di {wilayah} lewat Google Places simulator…", "progress")
        places = simulate_google_places(wilayah, jenis)
        self._pause(0.8)
        s.emit("lead_miner_agent", f"{len(places['prospek'])} titik ditemukan, {len(places['kompetitor_jaringan'])} kompetitor jaringan dipetakan", "info")
        leads = score_leads(places)
        if self.mode == "llm":
            t = self._task("lead_miner_agent", f"Analisis wilayah {wilayah} untuk {jenis}. Gunakan tool, lalu ringkas 5 prospek teratas beserta alasan skor.",
                           "Daftar 5 prospek teratas dengan skor urgensi dan alasan.")
            self._kickoff([t])
        for ld in leads[:5]:
            self._pause(0.25)
            s.emit("lead_miner_agent", f"{ld['nama']} — skor {ld['skor_urgensi']} ({ld['klasifikasi']}), {ld['jarak_km']} km, "
                   f"{ld['kompetitor_1km']} kompetitor ≤1 km", "info", lead=ld)
        s.emit("lead_miner_agent", f"Klasifikasi selesai: {sum(1 for x in leads if x['skor_urgensi'] >= 70)} prospek prioritas tinggi", "success")
        return leads

    def write_content(self, product_id: str, topik: str) -> dict:
        s = self.stream
        s.emit("geo_content_agent", f"Menyusun konten GEO untuk {product_id}: “{topik}”", "progress")
        draft = build_geo_content(product_id, topik)
        if self.mode == "llm":
            t = self._task("geo_content_agent",
                           f"Tulis artikel GEO (±300 kata) untuk produk {product_id} dengan topik \"{topik}\". Gunakan tool data teknis "
                           "dan kerangka GEO. Sertakan nomor izin edar dan data BKO/stabilitas; jangan keyword stuffing.",
                           "Artikel markdown + FAQ.", human=True)
            self._kickoff([t])
            draft["markdown"] = str(t.output.raw) if t.output else draft["markdown"]
        self._pause(0.9)
        s.emit("geo_content_agent", f"Draf “{draft['judul']}” selesai: {len(draft['faq'])} FAQ, JSON-LD Product+FAQPage", "success")
        audit = self.guard(draft["markdown"] + "\n" + " ".join(f["a"] for f in draft["faq"]), product_id, "geo_content_agent")
        if self.human_in_the_loop:
            self._hitl({"jenis": "konten", "judul": f"Review konten: {draft['judul']}", "konten": draft, "audit_status": audit["status"]})
        return {"draft": draft, "audit": audit}

    def guard(self, teks: str, product_id: str | None, sumber: str) -> dict:
        s = self.stream
        s.emit("claim_guard_agent", f"Menyaring keluaran {AGENT_LABEL.get(sumber, sumber)} terhadap Perban BPOM 30/2023…", "progress")
        self._pause(0.5)
        audit = audit_compliance(teks, product_id, sumber)
        if audit["status"] == BLOCKED:
            pasal = ", ".join(p["rujukan"] for p in audit["pasal_dilanggar"][:3])
            s.emit("claim_guard_agent", f"BLOCKED — {len(audit['pelanggaran'])} kalimat melanggar ({pasal}). Teks dipotong.", "alert", BLOCKED, audit=audit)
        elif audit["status"] == REVIEW:
            s.emit("claim_guard_agent", "REVIEW — ada kalimat perlu ditinjau staf", "warning", REVIEW, audit=audit)
        else:
            s.emit("claim_guard_agent", "Kepatuhan BPOM: lolos (0 pelanggaran)", "success", PASSED, audit=audit)
        return audit

    def workday(self, wilayah: str = "Kota Semarang") -> dict:
        """Simulasi satu hari kerja kantor AI: lead mining → negosiasi WA → konten GEO → audit promo lama → antrean HITL."""
        s = self.stream
        s.emit("orchestrator", f"Workday dimulai — 4 agen online · model {MODEL} · mode {self.mode}"
               + (" (tanpa API key: tool deterministik, tanpa LLM)" if self.mode == "simulasi" else ""), "info")
        hasil: dict[str, Any] = {}
        s.tick(0)
        hasil["leads"] = self.mine_leads(wilayah)
        s.tick(2)
        hasil["nego"] = [
            self.negotiate("Pak, propolis tetes 50 box bisa diskon 8%? tempo 14 hari ya", "ARB-006", 50, 8, "Apotek Sehat Sentosa"),
        ]
        s.tick(2)
        hasil["nego"].append(self.negotiate("Madu Stamina Plus 30 box, minta diskon 15% kalau bisa", "ARB-002", 30, 15, "Toko Obat Barokah"))
        s.tick(3)
        hasil["konten"] = self.write_content("ARB-002", "madu untuk stamina pelanggan apotek")
        s.tick(2)
        s.emit("claim_guard_agent", "Memeriksa draf promosi lama dari tim marketing (situs mitra)…", "progress")
        hasil["promo_lama"] = self.guard(DRAF_PROMO_MELANGGAR, "ARB-002", "draf promosi marketing")
        s.tick(1)
        s.emit("orchestrator", f"Workday selesai — {len(hasil['leads'])} prospek, {len(hasil['nego'])} negosiasi, "
               f"{len(self.hitl_items)} item menunggu persetujuan manusia", "done", data_ringkas={"hitl": len(self.hitl_items)})
        return hasil


DRAF_PROMO_MELANGGAR = (
    "Madu Stamina Plus terbukti ampuh menyembuhkan diabetes dan darah tinggi hanya dalam 7 hari. "
    "Sebanyak 95% pengguna merasakan stamina 3 kali lipat dalam sehari. "
    "100% alami tanpa efek samping, jadi obat kuat pria paling mujarab. "
    "Membantu memelihara stamina dan kebugaran tubuh."
)

_BUS_REGISTERED = False


def _register_event_bus_once() -> None:
    global _BUS_REGISTERED
    if not _BUS_REGISTERED:
        _register_event_bus()
        _BUS_REGISTERED = True


def run_in_thread(fn: Callable[[AAGECrew], Any], crew: AAGECrew) -> threading.Thread:
    """Jalankan alur di thread terpisah; stream ditutup saat selesai (dipakai endpoint SSE)."""

    def _target():
        try:
            fn(crew)
        except Exception as exc:  # pragma: no cover - dilaporkan ke dashboard
            crew.stream.emit("orchestrator", f"Error: {exc}", "alert")
        finally:
            crew.stream.close()

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    return t


# =============================================================================
# CLI
# =============================================================================


def _print_stream(crew: AAGECrew) -> None:
    colors = {"alert": "\033[91m", "warning": "\033[93m", "success": "\033[92m", "hitl": "\033[95m", "done": "\033[96m"}
    for ev in crew.stream:
        c = colors.get(ev.level, "")
        print(f"{c}[{ev.clock}] {AGENT_LABEL.get(ev.agent, ev.agent):<20} {ev.message}\033[0m", flush=True)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="AAGE Multi-Agent Crew")
    ap.add_argument("perintah", choices=["workday", "nego", "audit", "leads", "konten"])
    ap.add_argument("--wilayah", default="Kota Semarang")
    ap.add_argument("--produk", default="ARB-002")
    ap.add_argument("--box", type=int, default=50)
    ap.add_argument("--diskon", type=float, default=None)
    ap.add_argument("--teks", default=DRAF_PROMO_MELANGGAR)
    ap.add_argument("--topik", default="informasi produk untuk apotek")
    ap.add_argument("--mode", default=None, choices=["auto", "llm", "simulasi"])
    ap.add_argument("--tanpa-hitl", action="store_true", help="matikan human-in-the-loop")
    ap.add_argument("--json", action="store_true", help="cetak event sebagai JSON lines (untuk pipe ke API)")
    args = ap.parse_args(argv)

    crew = AAGECrew(human_in_the_loop=not args.tanpa_hitl, mode=args.mode, interactive=True, speed=4.0)
    flows = {
        "workday": lambda c: c.workday(args.wilayah),
        "nego": lambda c: c.negotiate(f"{args.box} box, diskon {args.diskon}%", args.produk, args.box, args.diskon, "Pembeli CLI"),
        "audit": lambda c: c.guard(args.teks, args.produk, "CLI"),
        "leads": lambda c: c.mine_leads(args.wilayah),
        "konten": lambda c: c.write_content(args.produk, args.topik),
    }
    run_in_thread(flows[args.perintah], crew)
    if args.json:
        for ev in crew.stream:
            print(ev.to_json(), flush=True)
    else:
        _print_stream(crew)


if __name__ == "__main__":
    main()
