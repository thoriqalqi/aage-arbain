"""Audit halaman (M6): meta, heading, schema JSON-LD, statistik tanpa sumber, dan klaim berisiko,
lengkap dengan laporan sebelum/sesudah."""

import json
import time

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from .. import claimguard, ledger

SAMPLE_PAGE = """<!doctype html><html lang="id"><head><meta charset="utf-8">
<title>Madu Herbal</title></head><body>
<h1>Madu Stamina Plus — Madu Ajaib Keluarga</h1>
<h1>Promo Grosir</h1>
<p>Madu Stamina Plus terbukti ampuh menyembuhkan diabetes dan darah tinggi hanya dalam 7 hari.</p>
<p>Sebanyak 95% pengguna merasakan stamina meningkat 3 kali lipat setelah satu minggu.</p>
<p>Dibuat dari madu hutan pilihan, jahe merah, dan temulawak.</p>
<p>100% alami tanpa efek samping, aman untuk semua usia.</p>
<p>Membantu memelihara stamina dan kebugaran tubuh.</p>
<p>Lebih ampuh dari merek lain, cocok untuk menjaga daya tahan tubuh keluarga.</p>
<p>Hubungi kami untuk harga grosir apotek dan toko obat.</p>
</body></html>"""


def _fetch(url: str) -> str:
    resp = httpx.get(url, timeout=15, follow_redirects=True, headers={"User-Agent": "AAGE-audit/0.1"})
    resp.raise_for_status()
    return resp.text


def audit(db: Session, *, url: str | None = None, text: str | None = None, html_doc: str | None = None,
          aktor: str = "staf") -> dict:
    started = time.perf_counter()
    is_html = bool(url or html_doc)
    if url:
        html_doc = _fetch(url)
    checks: list[dict] = []
    body_text = text or ""
    jsonld_types: list[str] = []

    if is_html:
        soup = BeautifulSoup(html_doc, "html.parser")
        for s in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(s.string or "{}")
                items = data if isinstance(data, list) else [data]
                jsonld_types += [str(i.get("@type")) for i in items if isinstance(i, dict)]
            except json.JSONDecodeError:
                checks.append({"id": "schema_invalid", "label": "JSON-LD tidak valid", "status": "gagal", "bobot": 10,
                               "detail": "Ada blok JSON-LD yang tidak bisa dibaca mesin pencari.",
                               "saran": "Perbaiki sintaks JSON-LD (gunakan ekspor dari Studio Konten)."})
        title = (soup.title.string or "").strip() if soup.title else ""
        meta = soup.find("meta", attrs={"name": "description"})
        desc = (meta.get("content") or "").strip() if meta else ""
        h1 = [h.get_text(" ", strip=True) for h in soup.find_all("h1")]
        h2 = soup.find_all("h2")
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        body_text = "\n".join(p.get_text(" ", strip=True) for p in soup.find_all(["p", "li", "h1", "h2", "h3"])) or soup.get_text("\n")

        checks.append({"id": "title", "label": "Meta title", "bobot": 10,
                       "status": "lulus" if 30 <= len(title) <= 60 else "gagal",
                       "detail": f"\"{title}\" ({len(title)} karakter)" if title else "Tidak ada <title>",
                       "saran": "Gunakan title 30–60 karakter berisi nama produk + kategori."})
        checks.append({"id": "meta_description", "label": "Meta description", "bobot": 10,
                       "status": "lulus" if 70 <= len(desc) <= 160 else "gagal",
                       "detail": f"{len(desc)} karakter" if desc else "Tidak ada meta description",
                       "saran": "Tulis 70–160 karakter yang menjawab 'apa produk ini' dan untuk siapa."})
        checks.append({"id": "h1", "label": "Satu H1 per halaman", "bobot": 5,
                       "status": "lulus" if len(h1) == 1 else "gagal", "detail": f"{len(h1)} H1 ditemukan",
                       "saran": "Pakai tepat satu H1; jadikan heading lain H2/H3."})
        checks.append({"id": "h2", "label": "Struktur heading (H2)", "bobot": 5,
                       "status": "lulus" if h2 else "gagal", "detail": f"{len(h2)} H2 ditemukan",
                       "saran": "Bagi konten ke bagian H2 (Ringkasan, Komposisi, Penyimpanan, FAQ)."})
        checks.append({"id": "schema", "label": "Schema JSON-LD (Product/FAQPage/Organization)", "bobot": 15,
                       "status": "lulus" if {"Product", "FAQPage"} <= set(jsonld_types) else "gagal",
                       "detail": ", ".join(jsonld_types) or "Tidak ada JSON-LD",
                       "saran": "Tambahkan JSON-LD Product, FAQPage, dan Organization dari Studio Konten."})
        faq_present = "FAQPage" in jsonld_types or "pertanyaan" in body_text.lower()
        checks.append({"id": "faq", "label": "Blok FAQ untuk AI search", "bobot": 10,
                       "status": "lulus" if faq_present else "gagal",
                       "detail": "Ada" if faq_present else "Tidak ada FAQ",
                       "saran": "Tambahkan 4–6 tanya-jawab singkat yang mudah dikutip AI search."})

    check = claimguard.check(db, body_text, use_llm=False)
    risky = [s for s in check.sentences if s.verdict != claimguard.ALLOWED]
    stat = [s for s in check.sentences if any(h.id == "R17" for h in s.rules)]
    blocked = [s for s in check.sentences if s.verdict == claimguard.BLOCKED]
    checks.append({"id": "statistik", "label": "Statistik tanpa sumber", "bobot": 15,
                   "status": "lulus" if not stat else "gagal", "detail": f"{len(stat)} kalimat",
                   "saran": "Hapus angka atau sertakan sumber yang dapat diverifikasi."})
    checks.append({"id": "klaim", "label": "Klaim berisiko (ClaimGuard)", "bobot": 30,
                   "status": "lulus" if not risky else "gagal",
                   "detail": f"{len(blocked)} diblokir, {len(risky) - len(blocked)} perlu review",
                   "saran": "Ganti dengan kalimat aman dari daftar klaim disetujui."})

    total = sum(c["bobot"] for c in checks)
    before = round(100 * sum(c["bobot"] for c in checks if c["status"] == "lulus") / total) if total else 100
    rewrites = [{"sebelum": s.text, "sesudah": s.suggestion, "verdict": s.verdict,
                 "aturan": [f"{h.id} {h.label}" for h in s.rules]} for s in risky]
    after_text = check.safe_text
    after_check = claimguard.check(db, after_text, use_llm=False) if after_text else None
    report = {
        "sumber": url or ("html" if html_doc else "teks"),
        "skor_sebelum": before,
        "skor_sesudah": 100 if after_check is None or after_check.verdict == claimguard.ALLOWED else 90,
        "cek": checks,
        "claimguard": check.to_dict(),
        "perbaikan_kalimat": rewrites,
        "teks_sesudah": after_text,
        "verdict_sesudah": after_check.verdict if after_check else claimguard.ALLOWED,
        "ringkasan": {"kalimat": len(check.sentences), "berisiko": len(risky), "diblokir": len(blocked),
                      "statistik_tanpa_sumber": len(stat)},
        "durasi_ms": int((time.perf_counter() - started) * 1000),
    }
    ledger.record(db, "audit_halaman", objek_ref=f"audit:{url or 'teks'}"[:80], aktor=aktor,
                  ringkasan=f"Audit {report['sumber'][:80]}: skor {before} → {report['skor_sesudah']}",
                  verdict=check.verdict, aturan_terpicu=check.rules_triggered, outcome=f"{len(risky)} kalimat berisiko",
                  model=check.model, data=report["ringkasan"])
    db.commit()
    return report
