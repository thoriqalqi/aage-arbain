"""ClaimGuardEngine — pemeriksaan awal klaim pemasaran produk kesehatan/herbal CV Arba'in.

Alur verify_content(product_id, text_content):
  0. Validasi input (tipe, kosong, panjang, produk dikenal). Tidak ada teks yang dikirim ke LLM sebelum lolos.
  A. Rule-based screening: aturan R01–R19 (aage.claimguard.rules), frasa registry (X01…), larangan produk (R20),
     dan pencocokan klaim manfaat dengan klaim resmi produk (KLAIM_TIDAK_TERDAFTAR).
       - kecocokan aturan berkeyakinan tinggi + rujukan terverifikasi yang berlaku → BLOCKED (LLM tidak dipanggil)
       - kecocokan lain (risiko, konteks/dasar hukum belum cukup) → NEED_REVIEW (LLM tidak dipanggil)
  B. Tanpa kecocokan langsung → analisis konteks LLM (adapter terisolasi, keluaran tervalidasi Pydantic).
       - LLM gagal/tidak dikonfigurasi/keluaran tidak valid → CLAIMGUARD_LLM_FAILURE_STATUS (ERROR default), tidak pernah ALLOWED
       - LLM BLOCKED tanpa rule_id terverifikasi → diturunkan ke NEED_REVIEW (LLM tidak boleh mengarang dasar hukum)
       - kutipan LLM yang tidak ada di teks dibuang

ALLOWED berarti "tidak ditemukan pelanggaran oleh pemeriksaan ini", bukan jaminan kepatuhan hukum."""

from __future__ import annotations

import hashlib
import re
import time
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from aage import claimguard
from aage.claimguard import registry
from aage.claimguard.rules import is_negated
from aage.claimguard.service import _best_claim, _product_name_re
from aage.config import get_settings
from aage.models import ApprovedClaim, Product

from .llm_adapter import ContextReviewer, ReviewerError, ReviewerNotConfigured, ReviewRequest

ENGINE_VERSION = "claimguard-engine/2.0.0"
DISCLAIMER = ("ClaimGuard adalah alat bantu penyaringan awal, bukan pengganti keputusan ahli regulasi atau penasihat hukum. "
              "Hasil ALLOWED berarti tidak ditemukan pelanggaran oleh pemeriksaan ini, bukan jaminan kepatuhan.")
UNVERIFIED_NOTE = "Rujukan regulasi perlu diverifikasi"
HUMAN_REVIEW_NOTE = "Wajib ditinjau manusia sebelum dipublikasikan."
RISKY_LLM_CATEGORIES = {"terapi_penyakit", "absolut", "keamanan", "tanpa_bukti"}

AuditStatus = Literal["BLOCKED", "NEED_REVIEW", "ALLOWED", "ERROR"]


class ClaimGuardInputError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class UnknownProductError(ClaimGuardInputError):
    def __init__(self, product_id: str):
        super().__init__("produk_tidak_dikenal", f"product_id '{product_id}' tidak dikenal atau tidak aktif")


class RuleMatch(BaseModel):
    rule_id: str
    description: str
    severity: str
    confidence: str
    status_aturan: str
    match: str
    sentence: str
    start: int | None
    end: int | None
    decisive: bool
    references: list[dict]


class Evidence(BaseModel):
    kutipan: str
    start: int | None
    end: int | None
    sumber: Literal["aturan", "pencocokan_klaim", "llm"]
    rule_id: str | None
    alasan: str


class ModelInfo(BaseModel):
    provider: str
    model: str
    latency_ms: int | None = None
    input_tokens: int = 0
    output_tokens: int = 0


class OfficialClaim(BaseModel):
    teks: str
    sumber: str
    diverifikasi_oleh: str | None
    data_simulasi: bool


class AuditResult(BaseModel):
    status: AuditStatus
    reason: str
    violation_law: str | None
    regulatory_note: str | None
    matched_rules: list[RuleMatch]
    evidence: list[Evidence]
    references: list[dict]
    recommendation: str | None
    recommendation_note: str | None
    product_id: str
    product_name: str
    product_category: str
    official_claims: list[OfficialClaim]
    audit_id: str | None = None
    engine_version: str = ENGINE_VERSION
    rules_version: str
    stage: Literal["aturan", "llm"]
    model_info: ModelInfo | None = None
    error_code: str | None = None
    input_text_hash: str
    text_length: int
    duration_ms: int
    disclaimer: str = DISCLAIMER


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _norm(s: str) -> str:
    s = s.lower().replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", s).strip()


def _locate(haystack: str, needle: str, offset: int = 0) -> tuple[int | None, int | None]:
    idx = haystack.lower().find(needle.lower())
    return (offset + idx, offset + idx + len(needle)) if idx >= 0 else (None, None)


class ClaimGuardEngine:
    def __init__(self, db: Session, reviewer: ContextReviewer | None = None, *, max_text_length: int | None = None,
                 llm_failure_status: str | None = None):
        settings = get_settings()
        self.db = db
        self.reviewer = reviewer
        self.max_text_length = max_text_length or settings.claimguard_max_text_length
        failure = (llm_failure_status or settings.claimguard_llm_failure_status).upper()
        self.llm_failure_status: AuditStatus = "NEED_REVIEW" if failure == "NEED_REVIEW" else "ERROR"

    # ------------------------------------------------------------------ validasi

    def _validate(self, product_id: object, text_content: object) -> tuple[Product, str]:
        if not isinstance(product_id, str) or not isinstance(text_content, str):
            raise ClaimGuardInputError("tipe_data_tidak_valid", "product_id dan teks harus berupa string")
        pid = product_id.strip()
        if not pid:
            raise ClaimGuardInputError("product_id_kosong", "product_id wajib diisi")
        if not text_content.strip():
            raise ClaimGuardInputError("teks_kosong", "Teks pemasaran wajib diisi")
        if len(text_content) > self.max_text_length:
            raise ClaimGuardInputError("teks_terlalu_panjang",
                                       f"Teks {len(text_content)} karakter melebihi batas {self.max_text_length} karakter")
        product = self.db.scalar(select(Product).where(Product.sku == pid, Product.aktif.is_(True)))
        if product is None:
            raise UnknownProductError(pid)
        return product, text_content

    # ------------------------------------------------------------------ Tahap A

    def _stage_a(self, product: Product, text: str) -> tuple[claimguard.CheckResult, list[RuleMatch], dict[int, list[RuleMatch]]]:
        chk = claimguard.check(self.db, text, product_ids=[product.id], use_llm=False)
        name_re = _product_name_re([p.nama for p in self.db.scalars(select(Product))])
        kategori = product.kategori
        matches: list[RuleMatch] = []
        per_sentence: dict[int, list[RuleMatch]] = {}

        def add(rule_id: str, found: str, s: claimguard.service.SentenceResult, i: int) -> None:
            if any(m.rule_id == rule_id for m in per_sentence.get(i, [])):
                return
            r = registry.rule(rule_id)
            start, end = _locate(s.text, found, s.start)
            m = RuleMatch(rule_id=rule_id, description=r["description"], severity=r["severity"], confidence=r["confidence"],
                          status_aturan=r["status_aturan"], match=found, sentence=s.text, start=start, end=end,
                          decisive=registry.is_decisive(rule_id, kategori),
                          references=registry.references_for(rule_id, kategori))
            matches.append(m)
            per_sentence.setdefault(i, []).append(m)

        for i, s in enumerate(chk.sentences):
            for h in s.rules:
                add(h.id, h.match, s, i)
            masked = name_re.sub(lambda mm: "x" * len(mm.group(0)), s.text) if name_re else s.text
            for rule_id, pattern in registry.phrase_rules():
                m = pattern.search(masked)
                if m and not is_negated(masked, m.start()):
                    add(rule_id, s.text[m.start():m.end()], s, i)
            if s.stage == "pencocokan":
                add("KLAIM_TIDAK_TERDAFTAR", s.text, s, i)
        return chk, matches, per_sentence

    def _is_clean(self, product: Product, text: str) -> bool:
        chk, matches, _ = self._stage_a(product, text)
        return not matches and chk.verdict == claimguard.ALLOWED

    # ------------------------------------------------------------------ rekomendasi

    def _claims(self, product: Product) -> list[ApprovedClaim]:
        return list(self.db.scalars(select(ApprovedClaim).where(ApprovedClaim.product_id == product.id).order_by(ApprovedClaim.id)))

    def _recommend(self, product: Product, chk: claimguard.CheckResult, flagged: set[int]) -> tuple[str | None, str]:
        if not flagged:
            return None, f"Tidak ada kalimat spesifik yang dapat diperbaiki otomatis — tinjau secara manual. {HUMAN_REVIEW_NOTE}"
        claims = self._claims(product)
        if not claims:
            return None, ("Produk belum memiliki klaim resmi di katalog — tulis ulang secara manual; "
                          f"ClaimGuard tidak membuat klaim pengganti. {HUMAN_REVIEW_NOTE}")
        flagged_text = " ".join(chk.sentences[i].text for i in sorted(flagged))
        claim, _ = _best_claim(flagged_text, claims, strict=False)
        claim = claim or claims[0]
        teks = claim.teks_klaim.strip().rstrip(".")
        claim_sentence = f"{product.nama} {teks[0].lower()}{teks[1:]}."
        keep = [s.text for i, s in enumerate(chk.sentences) if i not in flagged]
        if _norm(claim_sentence) not in _norm(" ".join(keep)):
            keep.append(claim_sentence)
        candidate = " ".join(keep)
        if not self._is_clean(product, candidate):
            return None, f"Rekomendasi otomatis masih memicu aturan ClaimGuard — tulis ulang secara manual. {HUMAN_REVIEW_NOTE}"
        simulasi = product.sumber_data == "simulasi"
        sumber = f"{claim.sumber_dokumen}{' — data simulasi, cocokkan dengan dokumen izin edar' if simulasi else ''}"
        return candidate, (f"Rekomendasi menghapus {len(flagged)} kalimat bermasalah dan hanya memakai klaim katalog produk "
                           f"({sumber}); tidak ada manfaat baru yang ditambahkan. {HUMAN_REVIEW_NOTE}")

    # ------------------------------------------------------------------ utama

    def verify_content(self, product_id: str, text_content: str) -> AuditResult:
        started = time.perf_counter()
        product, text = self._validate(product_id, text_content)
        kategori = product.kategori
        claims = self._claims(product)
        base = {
            "product_id": product.sku, "product_name": product.nama, "product_category": kategori,
            "official_claims": [OfficialClaim(teks=c.teks_klaim, sumber=c.sumber_dokumen, diverifikasi_oleh=c.diverifikasi_oleh,
                                              data_simulasi=product.sumber_data == "simulasi") for c in claims],
            "rules_version": registry.rules_version(), "input_text_hash": text_hash(text), "text_length": len(text),
        }

        def done(**kw) -> AuditResult:
            return AuditResult(**base, **kw, duration_ms=int((time.perf_counter() - started) * 1000))

        chk, matches, per_sentence = self._stage_a(product, text)
        if matches:
            decisive = [m for m in matches if m.decisive]
            relevant = decisive or matches
            refs = _unique_refs(r for m in relevant for r in registry.usable_references(m.rule_id, kategori))
            evidence = [Evidence(kutipan=m.match, start=m.start, end=m.end, rule_id=m.rule_id,
                                 sumber="pencocokan_klaim" if m.rule_id == "KLAIM_TIDAK_TERDAFTAR" else "aturan",
                                 alasan=m.description) for m in matches]
            rec, rec_note = self._recommend(product, chk, set(per_sentence))
            unverified = [m.rule_id for m in relevant if not registry.usable_references(m.rule_id, kategori)]
            note = None
            if not refs:
                note = UNVERIFIED_NOTE
            elif unverified:
                note = f"{UNVERIFIED_NOTE} untuk aturan {', '.join(sorted(set(unverified)))} (tanpa rujukan terverifikasi yang berlaku)."
            if decisive:
                status: AuditStatus = "BLOCKED"
                reason = (f"Ditemukan {len(decisive)} kecocokan aturan berisiko tinggi yang terverifikasi: "
                          + "; ".join(f"{m.rule_id} {m.description} (“{m.match[:80]}”)" for m in decisive[:4]))
            else:
                status = "NEED_REVIEW"
                reason = (f"Ditemukan {len(matches)} indikasi risiko yang memerlukan peninjauan manusia: "
                          + "; ".join(f"{m.rule_id} {m.description} (“{m.match[:80]}”)" for m in matches[:4]))
            return done(status=status, reason=reason, violation_law=registry.format_law(refs), regulatory_note=note,
                        matched_rules=matches, evidence=evidence, references=refs, recommendation=rec,
                        recommendation_note=rec_note, stage="aturan")

        # ------------------------------------------------------------------ Tahap B: konteks LLM
        verified_rules = []
        for rule_id in registry.load()["rules"]:
            usable = registry.usable_references(rule_id, kategori)
            if usable:
                verified_rules.append({"rule_id": rule_id, "description": registry.rule(rule_id)["description"],
                                       "rujukan": registry.format_law(usable)})
        req = ReviewRequest(text=text, product_name=product.nama, product_category=kategori,
                            official_claims=[c.teks_klaim for c in claims], rules=verified_rules)
        try:
            if self.reviewer is None:
                raise ReviewerNotConfigured("adapter LLM tidak tersedia")
            outcome = self.reviewer.review(req)
        except ReviewerError as exc:
            info = ModelInfo(provider=self.reviewer.provider, model=self.reviewer.model) if self.reviewer else None
            label = "perlu peninjauan manusia" if self.llm_failure_status == "NEED_REVIEW" else "status kepatuhan belum dapat dipastikan"
            return done(status=self.llm_failure_status, error_code=exc.code, stage="llm", model_info=info,
                        reason=(f"Tahap aturan tidak menemukan kecocokan, tetapi analisis konteks (LLM) tidak dapat diselesaikan: "
                                f"{exc}. Audit belum lengkap — {label}."),
                        violation_law=None, regulatory_note=None, matched_rules=[], evidence=[], references=[],
                        recommendation=None, recommendation_note=None)

        review = outcome.review
        info = ModelInfo(provider=outcome.provider, model=outcome.model, latency_ms=outcome.latency_ms,
                         input_tokens=outcome.input_tokens, output_tokens=outcome.output_tokens)
        norm_text = _norm(text)
        valid = [f for f in review.findings if _norm(f.quote) and _norm(f.quote) in norm_text]
        dropped = len(review.findings) - len(valid)
        evidence = []
        for f in valid:
            start, end = _locate(text, f.quote)
            evidence.append(Evidence(kutipan=f.quote, start=start, end=end, sumber="llm", rule_id=f.rule_id,
                                     alasan=f"[{f.category}] {f.explanation}"))
        cited = [f for f in valid if f.rule_id and registry.is_decisive(f.rule_id, kategori)]
        notes = [f"{dropped} kutipan LLM tidak ditemukan di teks dan diabaikan."] if dropped else []

        if review.status == "ALLOWED" and not any(f.category in RISKY_LLM_CATEGORIES for f in valid):
            status = "ALLOWED"
            reason = ("Tidak ditemukan pelanggaran oleh pemeriksaan ini (aturan + analisis konteks LLM). "
                      f"{review.summary} Ini bukan jaminan kepatuhan hukum.")
        elif review.status == "BLOCKED" and cited:
            status = "BLOCKED"
            reason = f"Analisis konteks menemukan risiko tinggi pada aturan terverifikasi {', '.join(sorted({f.rule_id for f in cited}))}: {review.summary}"
        else:
            status = "NEED_REVIEW"
            if review.status == "ALLOWED":
                notes.append("LLM menyatakan ALLOWED tetapi melaporkan temuan berisiko — diperlakukan sebagai NEED_REVIEW.")
            elif review.status == "BLOCKED":
                notes.append("LLM menilai risiko tinggi tanpa merujuk aturan terverifikasi — diturunkan ke NEED_REVIEW.")
            if not valid:
                notes.append("Tidak ada kutipan valid yang mendukung penilaian LLM.")
            reason = f"Analisis konteks memerlukan peninjauan manusia: {review.summary}"

        rule_ids = [f.rule_id for f in (cited if status == "BLOCKED" else valid) if f.rule_id]
        refs = _unique_refs(r for rid in rule_ids for r in registry.usable_references(rid, kategori))
        matched = [RuleMatch(rule_id=f.rule_id, description=registry.rule(f.rule_id)["description"], severity="blocked",
                             confidence="tinggi", status_aturan=registry.rule(f.rule_id)["status_aturan"], match=f.quote,
                             sentence=f.quote, start=_locate(text, f.quote)[0], end=_locate(text, f.quote)[1], decisive=True,
                             references=registry.references_for(f.rule_id, kategori)) for f in cited] if status == "BLOCKED" else []
        rec = rec_note = None
        if status != "ALLOWED":
            if review.rewrite and review.rewrite.strip() and self._is_clean(product, review.rewrite.strip()):
                rec = review.rewrite.strip()
                rec_note = ("Rekomendasi dari LLM, sudah diperiksa ulang tahap aturan (tidak memicu aturan dan klaimnya cocok "
                            f"dengan klaim katalog). {HUMAN_REVIEW_NOTE}")
            else:
                flagged = {i for i, s in enumerate(chk.sentences) if any(_norm(f.quote) in _norm(s.text) or _norm(s.text) in _norm(f.quote) for f in valid)}
                rec, rec_note = self._recommend(product, chk, flagged)
        note = " ".join(notes) or None
        if status != "ALLOWED" and not refs:
            note = f"{UNVERIFIED_NOTE}. {note or ''}".strip()
        return done(status=status, reason=reason, violation_law=registry.format_law(refs), regulatory_note=note,
                    matched_rules=matched, evidence=evidence, references=refs, recommendation=rec,
                    recommendation_note=rec_note, stage="llm", model_info=info)


def _unique_refs(refs) -> list[dict]:
    out, seen = [], set()
    for r in refs:
        if r["ref_id"] not in seen:
            seen.add(r["ref_id"])
            out.append(r)
    return out
