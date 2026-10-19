"""ClaimGuard (M3): tiga tahap — aturan deterministik → pencocokan approved_claims → LLM-judge.

Dipakai oleh Sales Assistant (sebelum kirim), Content Studio (sebelum ekspor), Prospect Mapper
(draf pesan pembuka), approval staf (teks hasil edit), dan Playground."""

import json
import re
import time
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import llm
from ..models import ApprovedClaim, Product
from ..textutil import content_tokens, cosine, stem
from .rules import HEALTH_OBJ_RE, RULES, is_benefit_claim, is_negated, stat_without_source

ALLOWED, REVIEW, BLOCKED = "allowed", "review", "blocked"
LABELS = {ALLOWED: "Diizinkan", REVIEW: "Perlu review", BLOCKED: "Diblokir"}
_RANK = {ALLOWED: 0, REVIEW: 1, BLOCKED: 2}

ADVISORY_RE = re.compile(
    r"\b(konsultasi\w*|tanyakan|hubungi|periksakan)\b.{0,40}\b(dokter|apoteker|tenaga kesehatan|tenaga medis)\b",
    re.IGNORECASE,
)
MATCH_THRESHOLD = 0.5
_REGULASI_PATH = Path(__file__).resolve().parents[2] / "config" / "regulasi_bpom.json"


@lru_cache
def regulasi() -> dict:
    """Rujukan pasal Perban BPOM 30/2023 per aturan (config/regulasi_bpom.json)."""
    try:
        return json.loads(_REGULASI_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:  # pragma: no cover
        return {"pasal": {}, "pemetaan_aturan": {}, "peraturan": {"judul": ""}}


def pasal_for(rule_id: str) -> list[dict]:
    reg = regulasi()
    return [{"kode": k, **reg["pasal"][k]} for k in reg["pemetaan_aturan"].get(rule_id, []) if k in reg["pasal"]]


def worst(*verdicts: str) -> str:
    return max(verdicts, key=lambda v: _RANK[v]) if verdicts else ALLOWED


@dataclass
class RuleHit:
    id: str
    label: str
    severity: str
    match: str
    alasan: str
    pasal: list[dict] = field(default_factory=list)


@dataclass
class SentenceResult:
    text: str
    start: int
    end: int
    verdict: str
    rules: list[RuleHit] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    matched_claim: dict | None = None
    suggestion: str | None = None
    stage: str = "aturan"


@dataclass
class CheckResult:
    verdict: str
    label: str
    sentences: list[SentenceResult]
    rules_triggered: list[str]
    summary: dict
    pasal_dilanggar: list[dict]
    safe_text: str
    model: str
    token_in: int = 0
    token_out: int = 0
    biaya_rp: float = 0.0
    duration_ms: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @property
    def reasons(self) -> list[str]:
        out: list[str] = []
        for s in self.sentences:
            out.extend(s.reasons)
        return list(dict.fromkeys(out))


_SENT_RE = re.compile(r"[^.!?\n]+[.!?]*", re.MULTILINE)


def _sentences(text: str) -> list[tuple[str, int, int]]:
    out = []
    for m in _SENT_RE.finditer(text):
        raw = m.group(0)
        stripped = raw.strip()
        if len(stripped) < 2:
            continue
        lead = len(raw) - len(raw.lstrip())
        start = m.start() + lead
        out.append((stripped, start, start + len(stripped)))
    return out


def _stage1(sentence: str) -> tuple[str, list[RuleHit], list[str]]:
    hits: list[RuleHit] = []
    reasons: list[str] = []
    advisory = bool(ADVISORY_RE.search(sentence))
    for rule in RULES:
        for m in rule.pattern.finditer(sentence):
            if rule.negatable and is_negated(sentence, m.start()):
                reasons.append(f"'{m.group(0)}' berada dalam kalimat negasi/penafian — tidak dihitung sebagai klaim.")
                continue
            if advisory and rule.id in {"R04", "R05"}:
                reasons.append("Nama penyakit muncul dalam anjuran konsultasi ke tenaga kesehatan.")
                continue
            hits.append(RuleHit(rule.id, rule.label, rule.severity, m.group(0), rule.alasan))
            break
    stat = stat_without_source(sentence)
    if stat:
        hits.append(RuleHit("R17", "Statistik tanpa sumber", REVIEW, stat.group(0),
                            "Angka/statistik kesehatan harus disertai sumber yang dapat diverifikasi."))
    # R05 (penyebutan penyakit) tidak perlu dilaporkan lagi bila R04 sudah memblokir.
    if any(h.id == "R04" for h in hits):
        hits = [h for h in hits if h.id != "R05"]
    # Bila klaim 100% spesifik (R07) terpicu, R14 umum berlebihan.
    if any(h.id == "R07" for h in hits):
        hits = [h for h in hits if h.id != "R14"]
    verdict = worst(*[h.severity for h in hits]) if hits else ALLOWED
    reasons.extend(f"{h.id} {h.label}: \"{h.match}\" — {h.alasan}" for h in hits)
    return verdict, hits, reasons


def _token_overlap(a: str, b: str) -> float:
    ta = {stem(t) for t in content_tokens(a)}
    tb = {stem(t) for t in content_tokens(b)}
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(tb)


def _load_claims(db: Session, product_ids: list[int] | None) -> list[ApprovedClaim]:
    q = select(ApprovedClaim).join(Product).where(Product.aktif.is_(True))
    if product_ids:
        q = q.where(ApprovedClaim.product_id.in_(product_ids))
    return list(db.scalars(q))


_OBJ_ALIAS = {"badan": "tubuh", "sehat": "kesehatan", "imunitas": "daya tahan", "imun": "daya tahan", "gizi": "nutrisi",
              "bugar": "kebugaran", "liver": "hati", "perut": "pencernaan", "lambung": "pencernaan"}
_INCREASE_RE = re.compile(r"\b(meningkatkan|menambah|memperkuat|menguatkan|melipatgandakan|memaksimalkan)\b", re.IGNORECASE)


def _objects(text: str) -> set[str]:
    return {_OBJ_ALIAS.get(m.lower(), m.lower()) for m in HEALTH_OBJ_RE.findall(text)}


def _compatible(sentence: str, claim_text: str) -> bool:
    """Klaim hanya cocok bila objek manfaatnya tercakup klaim disetujui dan tidak lebih kuat
    (mis. 'meningkatkan' ≠ 'memelihara')."""
    if not _objects(sentence) <= _objects(claim_text):
        return False
    if _INCREASE_RE.search(sentence) and not _INCREASE_RE.search(claim_text):
        return False
    return True


def _best_claim(sentence: str, claims: list[ApprovedClaim], strict: bool = True) -> tuple[ApprovedClaim | None, float]:
    best, best_score = None, 0.0
    vec = llm.embed(sentence) if claims else None
    for c in claims:
        if strict and not _compatible(sentence, c.teks_klaim):
            continue
        score = 0.5 * cosine(vec, c.embedding) + 0.5 * _token_overlap(sentence, c.teks_klaim)
        if score > best_score:
            best, best_score = c, score
    return best, best_score


def _suggest(sentence: SentenceResult, claims: list[ApprovedClaim], product_names: dict[int, str],
             product_scoped: bool) -> str:
    # Dengan konteks produk: pakai klaim disetujui produk itu yang paling mirip.
    # Tanpa konteks: hanya bila ada klaim yang benar-benar relevan, selain itu kalimat aman umum.
    claim, score = _best_claim(sentence.text, claims, strict=not product_scoped)
    if claim is not None and (product_scoped or score >= 0.35):
        nama = product_names.get(claim.product_id, "Produk ini")
        teks = claim.teks_klaim.rstrip(".")
        teks = teks[0].lower() + teks[1:] if teks else teks
        return f"{nama} {teks}. Untuk keluhan penyakit, konsultasikan dengan dokter atau apoteker."
    return ("Produk ini membantu memelihara kesehatan tubuh sebagai bagian dari pola hidup sehat. "
            "Untuk keluhan penyakit, konsultasikan dengan dokter atau apoteker.")


def _product_name_re(names: list[str]) -> re.Pattern | None:
    variants = set()
    for n in names:
        if not n:
            continue
        variants.add(n)
        core = re.sub(r"\s+\d+(?:\s*\w+)?$", "", n).strip()  # "Jahe Merah Instan 20 sachet" → "Jahe Merah Instan"
        if len(core.split()) >= 2:
            variants.add(core)
    names = list(variants)
    if not names:
        return None
    return re.compile("|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)), re.IGNORECASE)


JUDGE_PROMPT ="""Anda adalah pemeriksa kepatuhan klaim produk herbal/suplemen di Indonesia (aturan BPOM).
Nilai SATU kalimat berikut. Klaim terapi (menyembuhkan/mengobati/mencegah penyakit), jaminan hasil,
dan klaim yang tidak ada di daftar klaim disetujui TIDAK boleh diizinkan.

Daftar klaim disetujui untuk produk terkait:
{claims}

Kalimat: "{sentence}"

Jawab HANYA JSON: {{"claims": ["klaim yang terkandung"], "verdict": "allowed|review|blocked", "reasons": ["alasan singkat bahasa Indonesia"]}}"""


def check(
    db: Session,
    text: str,
    *,
    product_ids: list[int] | None = None,
    use_llm: bool = True,
) -> CheckResult:
    started = time.perf_counter()
    claims = _load_claims(db, product_ids)
    product_scoped = bool(product_ids and claims)
    if product_ids and not claims:
        claims = _load_claims(db, None)
    product_names = {p.id: p.nama for p in db.scalars(select(Product))}
    results: list[SentenceResult] = []
    model = llm.OFFLINE_MODEL
    tok_in = tok_out = 0
    cost = 0.0

    name_re = _product_name_re(list(product_names.values()))
    scope = db.scalars(select(Product).where(Product.id.in_(product_ids))) if product_ids else db.scalars(select(Product))
    larangan = sorted({ph.lower() for p in scope for ph in (p.larangan or [])}, key=len, reverse=True)
    for sent, start, end in _sentences(text):
        # Nama produk terdaftar (mis. "Jahe Merah Instan") bukan klaim → disamarkan sebelum pemeriksaan.
        masked = name_re.sub(lambda m: "x" * len(m.group(0)), sent) if name_re else sent
        verdict, hits, reasons = _stage1(masked)
        # R20: frasa larangan overclaim milik produk (kata_kunci_larangan_overclaim di config/mock_products.json)
        low = sent.lower()
        for phrase in larangan:
            idx = low.find(phrase)
            if idx >= 0 and not is_negated(sent, idx):
                hits.append(RuleHit("R20", "Frasa larangan overclaim produk", BLOCKED, phrase,
                                    "Frasa ini tercantum di daftar larangan overclaim produk."))
                reasons.append(f"R20 Frasa larangan overclaim produk: \"{phrase}\"")
                verdict = BLOCKED
                break
        for h in hits:
            h.pasal = pasal_for(h.id)
        sr = SentenceResult(sent, start, end, verdict, hits, reasons)

        # Tahap 2: kalimat manfaat harus cocok dengan approved_claims.
        if verdict != BLOCKED and is_benefit_claim(masked):
            claim, score = _best_claim(sent, claims)
            if claim is not None and score >= MATCH_THRESHOLD:
                sr.matched_claim = {"id": claim.id, "teks": claim.teks_klaim, "product_id": claim.product_id,
                                    "skor": round(score, 3), "sumber": claim.sumber_dokumen}
                sr.reasons.append(f"Cocok dengan klaim disetujui #{claim.id} (skor {score:.2f}).")
            else:
                sr.verdict = worst(sr.verdict, REVIEW)
                sr.stage = "pencocokan"
                sr.reasons.append("Klaim manfaat tidak ditemukan di daftar klaim disetujui.")

        # Tahap 3: LLM-judge hanya untuk kasus ambigu; tidak pernah menurunkan "diblokir".
        if sr.verdict == REVIEW and use_llm:
            related = [c.teks_klaim for c in claims[:12]]
            res = llm.complete(
                [{"role": "user", "content": JUDGE_PROMPT.format(claims="\n".join(f"- {c}" for c in related) or "-", sentence=sent)}],
                judge=True, json_mode=True, max_tokens=300, temperature=0,
            )
            if res is not None and isinstance(res.data, dict):
                model, tok_in, tok_out, cost = res.model, tok_in + res.token_in, tok_out + res.token_out, cost + res.biaya_rp
                jv = str(res.data.get("verdict", "")).lower()
                hard_review = any(h.severity == REVIEW and h.id in {"R05", "R17"} for h in hits)
                if jv in _RANK and not (jv == ALLOWED and hard_review):
                    sr.verdict = jv
                    sr.stage = "llm-judge"
                sr.reasons.extend(f"LLM-judge: {r}" for r in res.data.get("reasons", [])[:3])

        if sr.verdict != ALLOWED:
            sr.suggestion = _suggest(sr, claims, product_names, product_scoped)
        results.append(sr)

    overall = worst(*[s.verdict for s in results]) if results else ALLOWED
    rules_triggered = sorted({h.id for s in results for h in s.rules})
    safe_parts = []
    for s in results:
        if s.verdict == ALLOWED:
            safe_parts.append(s.text)
        elif s.suggestion and s.suggestion not in safe_parts:
            safe_parts.append(s.suggestion)
    summary = {v: sum(1 for s in results if s.verdict == v) for v in (ALLOWED, REVIEW, BLOCKED)}
    pasal_dilanggar: list[dict] = []
    for s in results:
        if s.verdict == ALLOWED:
            continue
        refs = [ps for h in s.rules for ps in h.pasal] or (pasal_for("KLAIM_TIDAK_TERDAFTAR") if s.stage == "pencocokan" else [])
        for ps in refs:
            if ps["kode"] not in {x["kode"] for x in pasal_dilanggar}:
                pasal_dilanggar.append(ps)
    return CheckResult(
        verdict=overall,
        label=LABELS[overall],
        sentences=results,
        rules_triggered=rules_triggered,
        summary=summary,
        pasal_dilanggar=pasal_dilanggar,
        safe_text=" ".join(safe_parts),
        model=model,
        token_in=tok_in,
        token_out=tok_out,
        biaya_rp=round(cost, 2),
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
