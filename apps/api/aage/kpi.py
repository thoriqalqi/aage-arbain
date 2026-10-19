"""KPI & funnel (M5) — semua angka dihitung dari tabel ledger_events, bukan hard-code."""

from collections import Counter, defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import clock
from .models import LedgerEvent

FUNNEL = ["Prospek", "Dihubungi", "Merespons", "Minta penawaran", "Draf pesanan"]
QUOTE_INTENTS = {"harga_moq", "negosiasi"}


def _events(db: Session, start: datetime, end: datetime) -> list[LedgerEvent]:
    return list(db.scalars(select(LedgerEvent).where(LedgerEvent.waktu >= start, LedgerEvent.waktu < end)))


_aware = clock.aware


def _summary(events: list[LedgerEvent]) -> dict:
    inbound = [e for e in events if e.tipe_event == "pesan_masuk"]
    convs = {e.conversation_id for e in inbound}
    decisions = Counter(e.outcome for e in events if e.tipe_event == "kebijakan")
    total_dec = sum(decisions.values())
    auto_out = [e for e in events if e.tipe_event == "pesan_keluar" and e.aktor == "AI" and e.latensi_ms is not None]
    staff_out = [e for e in events if e.tipe_event == "pesan_keluar" and e.aktor.startswith("staf") and e.latensi_ms is not None]
    blocked = sum(1 for e in events if e.tipe_event in {"claimguard", "claimguard_inbound"} and e.verdict == "blocked")
    review = sum(1 for e in events if e.tipe_event == "claimguard" and e.verdict == "review")
    cost = sum(e.biaya_rp or 0 for e in events)
    conv_cost = sum(e.biaya_rp or 0 for e in events if e.conversation_id is not None)
    lat_sorted = sorted(e.latensi_ms for e in auto_out)
    p95 = lat_sorted[min(len(lat_sorted) - 1, int(0.95 * len(lat_sorted)))] if lat_sorted else None
    return {
        "chat": len(convs),
        "pesan_masuk": len(inbound),
        "otomatis_persen": round(100 * decisions.get("kirim", 0) / total_dec, 1) if total_dec else 0.0,
        "eskalasi_persen": round(100 * (decisions.get("eskalasi", 0) + decisions.get("tahan", 0)) / total_dec, 1) if total_dec else 0.0,
        "keputusan": dict(decisions),
        "klaim_diblokir": blocked,
        "klaim_ditahan": decisions.get("tahan", 0) + review,
        "respons_ai_rata_ms": round(sum(lat_sorted) / len(lat_sorted)) if lat_sorted else None,
        "respons_ai_p95_ms": p95,
        "respons_staf_rata_menit": round(sum(e.latensi_ms for e in staff_out) / len(staff_out) / 60000, 1) if staff_out else None,
        "biaya_total_rp": round(cost, 2),
        "biaya_per_percakapan_rp": round(conv_cost / len(convs), 2) if convs else 0.0,
    }


def funnel(events_all: list[LedgerEvent]) -> list[dict]:
    created = {e.objek_ref for e in events_all if e.tipe_event == "prospek_dibuat"}
    reached: dict[str, set] = defaultdict(set)
    for e in events_all:
        if e.tipe_event == "prospek_status":
            reached[e.outcome or ""].add(e.objek_ref)
    contacted = reached["dihubungi"] | reached["merespons"] | reached["menolak"]
    responded = reached["merespons"]
    quote_convs = {e.conversation_id for e in events_all
                   if e.tipe_event == "intent" and (e.data or {}).get("intent") in QUOTE_INTENTS}
    orders = {e.objek_ref for e in events_all if e.tipe_event == "draf_pesanan"}
    values = [len(created), len(contacted), len(responded), len(quote_convs), len(orders)]
    out = []
    for i, (label, v) in enumerate(zip(FUNNEL, values)):
        prev = values[i - 1] if i else None
        out.append({"tahap": label, "nilai": v,
                    "konversi_persen": round(100 * v / prev, 1) if prev else None})
    return out


def compute(db: Session, start: datetime | None = None, end: datetime | None = None) -> dict:
    end = end or clock.now()
    start = start or end - timedelta(days=14)
    span = end - start
    events = _events(db, start, end)
    prev = _events(db, start - span, start)
    all_events = list(db.scalars(select(LedgerEvent)))

    cur, before = _summary(events), _summary(prev)
    delta = {k: (round(cur[k] - before[k], 1) if isinstance(cur[k], (int, float)) and isinstance(before[k], (int, float)) else None)
             for k in ("chat", "otomatis_persen", "klaim_diblokir", "biaya_per_percakapan_rp")}

    # Seri harian (volume chat, otomatis vs eskalasi) + sparkline 7 hari per KPI
    days = max(1, span.days)
    series = []
    for i in range(days):
        d0 = (start + timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        d1 = d0 + timedelta(days=1)
        evs = [e for e in events if d0 <= _aware(e.waktu) < d1]
        s = _summary(evs)
        series.append({"tanggal": d0.date().isoformat(), "chat": s["chat"], "pesan": s["pesan_masuk"],
                       "otomatis": s["keputusan"].get("kirim", 0),
                       "eskalasi": s["keputusan"].get("eskalasi", 0) + s["keputusan"].get("tahan", 0),
                       "diblokir": s["klaim_diblokir"], "biaya_per_percakapan_rp": s["biaya_per_percakapan_rp"],
                       "otomatis_persen": s["otomatis_persen"]})

    month_start = end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    biaya_bulan = sum(e.biaya_rp or 0 for e in all_events if _aware(e.waktu) >= month_start)
    return {
        "periode": {"dari": start.isoformat(), "sampai": end.isoformat()},
        "ringkasan": cur,
        "delta": delta,
        "harian": series,
        "funnel": funnel(all_events),
        "biaya_bulan_ini_rp": round(biaya_bulan, 2),
        "sumber": "ledger_events",
    }
