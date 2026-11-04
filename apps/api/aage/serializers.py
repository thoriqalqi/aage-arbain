"""Konversi model ORM → JSON untuk dashboard."""

from .claimguard import LABELS
from .clock import aware
from .models import (
    Approval,
    Contact,
    ContentDraft,
    Conversation,
    LedgerEvent,
    Message,
    OrderDraft,
    Product,
    Prospect,
    User,
)
from .security import mask_phone


def ts(dt):
    return aware(dt).isoformat() if dt else None


def user(u: User) -> dict:
    return {"id": u.id, "nama": u.nama, "email": u.email, "role": u.role}


def contact(c: Contact, viewer: User | None) -> dict:
    return {"id": c.id, "channel": c.channel,
            "external_user_id": mask_phone(c.external_user_id, viewer) if viewer else c.external_user_id,
            "wa_number": mask_phone(c.wa_number, viewer) if viewer else c.wa_number,
            "nama_toko": c.nama_toko, "nama_wa": c.nama_wa, "tipe_toko": c.tipe_toko, "alamat": c.alamat,
            "opt_in": c.opt_in, "prospect_id": c.prospect_id}


def message(m: Message) -> dict:
    return {"id": m.id, "arah": m.arah, "pengirim": m.pengirim, "teks": m.teks, "status_kirim": m.status_kirim,
            "verdict": m.verdict, "verdict_label": LABELS.get(m.verdict) if m.verdict else None, "sumber": m.sumber,
            "biaya_rp": m.biaya_rp, "trace_id": m.trace_id, "waktu": ts(m.dibuat_pada)}


def conversation(c: Conversation, viewer: User | None, last: Message | None = None, pending: int = 0,
                 menunggu_sejak=None) -> dict:
    return {"id": c.id, "kanal": c.kanal, "status": c.status, "intent_terakhir": c.intent_terakhir,
            "diperbarui_pada": ts(c.diperbarui_pada), "contact": contact(c.contact, viewer),
            "pesan_terakhir": message(last) if last else None, "approval_menunggu": pending,
            "menunggu_sejak": ts(menunggu_sejak), "ditangani_oleh": c.ditangani_oleh,
            "ditangani_sejak": ts(c.ditangani_sejak), "aktivitas_staf_terakhir": ts(c.aktivitas_staf_terakhir)}


def approval(a: Approval, conv: Conversation | None, viewer: User | None) -> dict:
    return {"id": a.id, "objek_tipe": a.objek_tipe, "objek_id": a.objek_id, "conversation_id": a.conversation_id,
            "alasan": a.alasan, "ringkasan": a.ringkasan, "intent": a.intent, "draf": a.draf, "verdict": a.verdict,
            "verdict_label": LABELS.get(a.verdict) if a.verdict else None, "status": a.status,
            "ditinjau_oleh": a.ditinjau_oleh, "catatan": a.catatan, "trace_id": a.trace_id,
            "dibuat_pada": ts(a.dibuat_pada), "diputus_pada": ts(a.diputus_pada),
            "contact": contact(conv.contact, viewer) if conv else None}


def ledger_event(e: LedgerEvent) -> dict:
    return {"id": e.id, "waktu": ts(e.waktu), "tipe_event": e.tipe_event, "trace_id": e.trace_id,
            "conversation_id": e.conversation_id, "product_id": e.product_id, "objek_ref": e.objek_ref,
            "sumber_ref": e.sumber_ref, "ringkasan": e.ringkasan, "alasan": e.alasan, "verdict": e.verdict,
            "verdict_label": LABELS.get(e.verdict) if e.verdict else None, "aturan_terpicu": e.aturan_terpicu,
            "model": e.model, "token_in": e.token_in, "token_out": e.token_out, "biaya_rp": e.biaya_rp,
            "latensi_ms": e.latensi_ms, "aktor": e.aktor, "outcome": e.outcome, "data": e.data}


def product(p: Product, with_details: bool = True) -> dict:
    d = {"id": p.id, "sku": p.sku, "nama": p.nama, "kategori": p.kategori, "komposisi": p.komposisi,
         "kemasan": p.kemasan, "satuan_grosir": p.satuan_grosir, "no_izin_edar": p.no_izin_edar,
         "harga_dasar": p.harga_dasar, "moq": p.moq, "sumber_data": p.sumber_data, "aktif": p.aktif,
         "stok": p.stok, "deskripsi": p.deskripsi or "",
         "halal": ((p.data_teknis or {}).get("sertifikasi_halal") or {}).get("status"),
         "bko": ((p.data_teknis or {}).get("status_bebas_bko") or {}).get("hasil")}
    if with_details:
        d["klaim"] = [{"id": c.id, "teks": c.teks_klaim, "sumber": c.sumber_dokumen, "diverifikasi_oleh": c.diverifikasi_oleh}
                      for c in p.claims]
        d["tier"] = [{"min_qty": r.min_qty, "diskon_maks_persen": r.diskon_maks_persen} for r in p.pricing]
    return d


def order(o: OrderDraft) -> dict:
    return {"id": o.id, "item": o.item, "nama_toko": o.nama_toko, "alamat": o.alamat, "total": o.total,
            "status": o.status, "dibuat_pada": ts(o.dibuat_pada)}


def content(d: ContentDraft, full: bool = True) -> dict:
    out = {"id": d.id, "product_id": d.product_id, "tipe": d.tipe, "topik": d.topik, "target": d.target,
           "judul": d.judul, "claim_verdict": d.claim_verdict, "verdict_label": LABELS.get(d.claim_verdict),
           "status": d.status, "dibuat_pada": ts(d.dibuat_pada)}
    if full:
        out.update({"isi": d.isi, "faq": d.faq, "meta": d.meta, "json_ld": d.json_ld, "claim_report": d.claim_report})
    return out


def prospect(p: Prospect, viewer: User, conversation_id: int | None = None) -> dict:
    from .prospects.mapper import wa_number

    wa = wa_number(p.telepon)
    return {"id": p.id, "nama": p.nama, "wa": wa if viewer.role == "admin" else None, "ada_wa": wa is not None, "conversation_id": conversation_id,
            "catatan": p.catatan, "tindak_lanjut_pada": ts(p.tindak_lanjut_pada), "pic": p.pic, "jaringan": p.jaringan, "alamat": p.alamat, "wilayah": p.wilayah, "lat": p.lat, "lng": p.lng,
            "tipe": p.tipe, "telepon": mask_phone(p.telepon, viewer), "website": p.website, "rating": p.rating,
            "jumlah_ulasan": p.jumlah_ulasan, "jarak_km": p.jarak_km, "sudah_pelanggan": p.sudah_pelanggan,
            "skor": p.skor, "alasan_skor": p.alasan_skor, "draf_pesan": p.draf_pesan, "draf_verdict": p.draf_verdict,
            "status": p.status, "sumber": p.sumber, "osm_id": p.eksternal_id, "jam_buka": p.jam_buka,
            "alamat_jalan_ada": p.alamat_jalan_ada, "skor_geo": p.skor_geo, "skor_data": p.skor_data,
            "terakhir_dipindai": ts(p.terakhir_dipindai), "market_analysis": p.market_analysis, "nba": p.nba,
            "dikumpulkan_pada": ts(p.dikumpulkan_pada), "diperbarui_pada": ts(p.diperbarui_pada), "confidence": p.confidence, "skor_versi": p.skor_versi,
            "verifikasi": p.verifikasi, "terakhir_diverifikasi": ts(p.terakhir_diverifikasi), "digabung_ke_id": p.digabung_ke_id,
            "consent_status": p.consent_status, "consent_sumber": p.consent_sumber, "consent_cakupan": p.consent_cakupan, "consent_pada": ts(p.consent_pada)}
