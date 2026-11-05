"""Registry rujukan regulasi & kebijakan aturan ClaimGuard (config/claimguard_registry.json).

Satu sumber untuk semua pemakai ClaimGuard: pipeline WA (service.check → pasal), agen CrewAI, dan
ClaimGuardEngine (Compliance Check). Hanya rujukan berstatus VERIFIED yang boleh disajikan sebagai dasar hukum;
selain itu UI wajib menampilkan "Rujukan regulasi perlu diverifikasi"."""

import json
import re
from functools import lru_cache
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "claimguard_registry.json"
VERIFIED = "VERIFIED"
DECISIVE_RULE_STATUS = "DITINJAU"


@lru_cache
def load() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def rules_version() -> str:
    return load()["rules_version"]


def klasifikasi(rule_id: str) -> tuple[str, str]:
    """(kategori, risiko) aturan. Aturan yang belum diklasifikasi selalu perlu dinilai manusia."""
    r = load()["rules"].get(rule_id) or {}
    return r.get("kategori", "UNCERTAIN_CLAIM"), r.get("risiko", "MEDIUM")


def peringkat_risiko(risiko: str) -> int:
    return load()["tingkat_risiko"].index(risiko)


def celah_bukti(kategori: str) -> str:
    return load()["kategori_klaim"][kategori]["celah_bukti"]


def reference(ref_id: str) -> dict | None:
    reg = load()
    ref = reg["references"].get(ref_id)
    if ref is None:
        return None
    law = reg["regulations"][ref["regulation"]]
    return {
        "ref_id": ref_id,
        "regulation_id": ref["regulation"],
        "regulation_title": law["regulation_title"],
        "singkat": law["singkat"],
        "article_reference": ref["article_reference"],
        "ringkasan": ref["ringkasan"],
        "jurisdiction": law["jurisdiction"],
        "official_source_url": law["official_source_url"],
        "official_pdf_url": law.get("official_pdf_url"),
        "applies_to": law["applies_to"],
        "verification_status": law["verification_status"],
        "last_verified_at": law["last_verified_at"],
        "rules_version": reg["rules_version"],
    }


def rule(rule_id: str) -> dict:
    r = load()["rules"].get(rule_id)
    if r is None:  # aturan yang belum didaftarkan tidak pernah boleh memutus BLOCKED
        return {"rule_id": rule_id, "description": rule_id, "severity": "review", "confidence": "sedang",
                "status_aturan": "TIDAK_TERDAFTAR", "references": []}
    return {"rule_id": rule_id, **r}


def references_for(rule_id: str, kategori: str | None = None) -> list[dict]:
    """Rujukan aturan + apakah berlaku untuk kategori produk (mis. Perban 30/2023 hanya Obat Bahan Alam)."""
    out = []
    for ref_id in rule(rule_id)["references"]:
        ref = reference(ref_id)
        if ref is not None:
            ref["berlaku_untuk_produk"] = kategori is None or kategori in ref["applies_to"]
            out.append(ref)
    return out


def usable_references(rule_id: str, kategori: str | None) -> list[dict]:
    """Rujukan yang boleh disajikan sebagai dasar hukum: terverifikasi DAN berlaku untuk kategori produk."""
    return [r for r in references_for(rule_id, kategori) if r["verification_status"] == VERIFIED and r["berlaku_untuk_produk"]]


def is_decisive(rule_id: str, kategori: str | None) -> bool:
    """BLOCKED tanpa LLM hanya bila aturan berkeyakinan tinggi, sudah ditinjau, dan punya rujukan terverifikasi
    yang berlaku untuk kategori produk. Selain itu kecocokan → NEED_REVIEW."""
    r = rule(rule_id)
    return (r["severity"] == "blocked" and r["confidence"] == "tinggi" and r["status_aturan"] == DECISIVE_RULE_STATUS
            and bool(usable_references(rule_id, kategori)))


@lru_cache
def phrase_rules() -> list[tuple[str, re.Pattern]]:
    """Aturan frasa tambahan dari registry (X01, X02, …) — dapat diperbarui tanpa mengubah kode."""
    out = []
    for rule_id, r in load()["rules"].items():
        phrases = r.get("frasa") or []
        if phrases:
            alt = "|".join(r"\s+".join(map(re.escape, p.split())) for p in sorted(phrases, key=len, reverse=True))
            out.append((rule_id, re.compile(rf"(?<!\w)(?:{alt})(?!\w)", re.IGNORECASE)))
    return out


def format_law(refs: list[dict]) -> str | None:
    """'Perban BPOM 34/2022 (…) — Lampiran I bagian I angka 7; Pasal 3 ayat (2) · Perban BPOM 30/2023 (…) — …'"""
    by_law: dict[str, list[str]] = {}
    for r in refs:
        arts = by_law.setdefault(r["singkat"], [])
        if r["article_reference"] not in arts:
            arts.append(r["article_reference"])
    return " · ".join(f"{law} — {'; '.join(arts)}" for law, arts in by_law.items()) or None


def legacy_view() -> dict:
    """Bentuk lama {peraturan, pasal, pemetaan_aturan} untuk service.check dan agen CrewAI."""
    reg = load()
    pasal = {}
    for ref_id in reg["references"]:
        ref = reference(ref_id)
        status = "" if ref["verification_status"] == VERIFIED else " [PERLU VERIFIKASI]"
        pasal[ref_id] = {"rujukan": f"{ref['singkat']} {ref['article_reference']}{status}", "ringkasan": ref["ringkasan"],
                         "sumber": ref["official_source_url"], "status_verifikasi": ref["verification_status"]}
    laws = reg["regulations"].values()
    return {
        "peraturan": {"judul": " & ".join(law["singkat"] for law in laws),
                      "sumber": [law["official_source_url"] for law in laws], "rules_version": reg["rules_version"]},
        "pasal": pasal,
        "pemetaan_aturan": {rid: r["references"] for rid, r in reg["rules"].items()},
    }
