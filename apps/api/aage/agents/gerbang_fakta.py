"""Gerbang terakhir sebelum ClaimGuard: teks final (termasuk hasil LLM) tidak boleh memuat nilai fakta yang tidak lolos.

Penyusun jawaban sudah menyaring lebih dulu; gerbang ini menangkap yang lolos dari sana. Label data simulasi dipasang di
sini, sesudah tulis ulang gaya bahasa, supaya kunci fakta dan tulis ulang tidak bisa menghilangkannya."""

from sqlalchemy.orm import Session

from .. import ledger, llm
from ..kb import verifikasi
from . import drafter

LABEL_SIMULASI = "Catatan: data ini contoh/simulasi, bukan data resmi."
TEKS_TERTAHAN = "Mohon maaf, Kak 🙏 Sebagian data yang Kakak tanyakan belum terverifikasi, jadi belum bisa saya sampaikan."
# Pesan empati atau penolakan ini tidak menyajikan data, walau sumbernya dicatat untuk audit.
_TANPA_LABEL = {"keluhan", "fakta_tertahan"}


def _sumber_simulasi(sar: verifikasi.Saringan, d: "drafter.Draft") -> bool:
    return sar.mode == verifikasi.DEMO and any(
        s.get("document_id") and sar.status_dokumen(s["document_id"]) == verifikasi.SIMULASI for s in d.sources)


def _berlabel(teks: str) -> str:
    return teks if LABEL_SIMULASI in teks else f"{teks}\n\n{LABEL_SIMULASI}"


def terapkan(db: Session, d: "drafter.Draft", *, trace_id: str, conversation_id: int) -> "drafter.Draft":
    if not d.text and not d.staff_draft:
        return d
    sar = verifikasi.Saringan.dari(db)
    tahan, simulasi = sar.potret_nilai()
    if d.staff_draft and verifikasi.ada_fragmen(tahan, d.staff_draft):
        d.staff_draft = None
    if d.text and (terlarang := verifikasi.ada_fragmen(tahan, d.text)):
        ledger.record(db, "fakta_tertahan", trace_id=trace_id, conversation_id=conversation_id, aktor="AI", model=llm.OFFLINE_MODEL,
                      objek_ref=f"conversation:{conversation_id}", ringkasan=f"Draf '{d.template}' memuat fakta yang tidak lolos",
                      alasan=f"{len(terlarang)} nilai belum terverifikasi; mode {sar.mode}", outcome="ditahan",
                      data={"template": d.template, "teks_ditolak": d.text})
        akhir = drafter.HOLD_STAF if d.escalate else drafter.TAWAR_STAF
        d.text = f"{TEKS_TERTAHAN} {akhir}"
        d.sources = [drafter._template_source("data belum terverifikasi")]
        d.template, d.teks_template, d.memakai_simulasi = "fakta_tertahan", None, False
        d.konteks = {**d.konteks, "tawar_staf": not d.escalate}
    if d.template in _TANPA_LABEL:
        return d
    pakai = d.memakai_simulasi or _sumber_simulasi(sar, d)
    if d.text and (pakai or verifikasi.ada_fragmen(simulasi, d.text)):
        d.text = _berlabel(d.text)
    if d.staff_draft and (pakai or verifikasi.ada_fragmen(simulasi, d.staff_draft)):
        d.staff_draft = _berlabel(d.staff_draft)
    return d
