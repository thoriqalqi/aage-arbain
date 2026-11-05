"""Audit halaman (M6): meta, heading, schema JSON-LD, statistik tanpa sumber, dan klaim berisiko,
lengkap dengan laporan sebelum/sesudah."""

import ipaddress
import json
import socket
import re
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from .. import claimguard, ledger

_MAKS_ALIH = 5
_MAKS_BYTE = 2_000_000

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


class AlamatDitolak(ValueError):
    pass


def periksa_alamat(url: str) -> None:
    """Audit hanya membuka situs publik, supaya tidak bisa dipakai membaca layanan internal server."""
    u = urlsplit(url)
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        raise AlamatDitolak("Alamat harus berupa URL http atau https yang lengkap, tanpa nama pengguna atau sandi.")
    if u.port not in (None, 80, 443):
        raise AlamatDitolak("Audit hanya membuka situs web di port standar.")
    try:
        alamat = {info[4][0] for info in socket.getaddrinfo(u.hostname, u.port or 443, type=socket.SOCK_STREAM)}
    except socket.gaierror:
        raise AlamatDitolak(f"Situs {u.hostname} tidak ditemukan.") from None
    for a in alamat:
        ip = ipaddress.ip_address(a.split("%")[0])
        if not ip.is_global or ip.is_multicast:
            raise AlamatDitolak("Audit hanya bisa membuka situs publik, bukan alamat internal.")


def _ambil(url: str, *, html_saja: bool = True) -> tuple[str, httpx.Headers, str]:
    with httpx.Client(timeout=15, follow_redirects=False, headers={"User-Agent": "AAGE-audit/0.1"}) as klien:
        for _ in range(_MAKS_ALIH + 1):
            periksa_alamat(url)  # alihan diperiksa ulang: situs publik bisa mengalihkan ke alamat internal
            with klien.stream("GET", url) as resp:
                if resp.is_redirect:
                    url = str(httpx.URL(url).join(resp.headers.get("location", "")))
                    continue
                resp.raise_for_status()
                jenis = resp.headers.get("content-type", "")
                if html_saja and "html" not in jenis.lower():
                    raise AlamatDitolak(f"Alamat ini bukan halaman web (jenis isi: {jenis or 'tidak diketahui'}).")
                isi = b""
                for potongan in resp.iter_bytes():
                    isi += potongan
                    if len(isi) > _MAKS_BYTE:
                        raise AlamatDitolak("Halaman terlalu besar untuk diaudit (lebih dari 2 MB).")
                return isi.decode(resp.encoding or "utf-8", errors="replace"), resp.headers, url
    raise AlamatDitolak("Terlalu banyak alihan alamat.")


def _fetch(url: str) -> str:
    return _ambil(url)[0]


def _robots_txt(url: str) -> bool | None:
    """True bila robots.txt mengizinkan atau tidak ada, False bila melarang, None bila tidak bisa diperiksa."""
    u = urlsplit(url)
    try:
        teks = _ambil(f"{u.scheme}://{u.netloc}/robots.txt", html_saja=False)[0]
    except httpx.HTTPStatusError as exc:
        return True if exc.response.status_code in (404, 410) else None
    except (httpx.HTTPError, AlamatDitolak):
        return None
    parser = RobotFileParser()
    parser.parse(teks.splitlines())
    return parser.can_fetch("Googlebot", url)


def _alamat_sama(a: str, b: str) -> bool:
    ua, ub = urlsplit(a), urlsplit(b)
    return (ua.hostname, ua.path.rstrip("/")) == (ub.hostname, ub.path.rstrip("/"))


def _cek_canonical(soup: BeautifulSoup, alamat: str | None) -> dict:
    tag = soup.find("link", rel=lambda r: r and "canonical" in (r if isinstance(r, list) else r.split()))
    href = (tag.get("href") or "").strip() if tag else ""
    if not href:
        status, detail = "gagal", "Tidak ada link canonical"
    elif not href.startswith(("http://", "https://")):
        status, detail = "gagal", f"Bukan alamat lengkap: {href[:120]}"
    elif alamat and not _alamat_sama(href, alamat):
        status, detail = "gagal", f"Menunjuk ke alamat lain: {href[:120]}"
    else:
        status, detail = "lulus", href[:120]
    return {"id": "canonical", "label": "Canonical", "bobot": 5, "status": status, "detail": detail,
            "saran": "Tambahkan <link rel=\"canonical\"> berisi alamat lengkap halaman ini."}


def _cek_robots(soup: BeautifulSoup, headers: httpx.Headers | None, alamat: str | None) -> dict:
    larangan = []
    for meta in soup.find_all("meta", attrs={"name": re.compile(r"^(robots|googlebot)$", re.IGNORECASE)}):
        if re.search(r"noindex|none", meta.get("content") or "", re.IGNORECASE):
            larangan.append("meta robots melarang pengindeksan")
    if headers is not None and re.search(r"noindex|none", headers.get("x-robots-tag", ""), re.IGNORECASE):
        larangan.append("header X-Robots-Tag melarang pengindeksan")
    robots = _robots_txt(alamat) if alamat else None
    if robots is False:
        larangan.append("robots.txt melarang Googlebot membuka halaman ini")
    catatan = "robots.txt mengizinkan" if robots else "robots.txt tidak diperiksa"
    return {"id": "robots", "label": "Boleh diindeks mesin pencari", "bobot": 5, "status": "gagal" if larangan else "lulus",
            "detail": "; ".join(larangan) if larangan else f"Tidak ada larangan di halaman; {catatan}",
            "saran": "Hapus noindex atau aturan Disallow bila halaman ini memang ingin muncul di pencarian."}


def _skor(checks: list[dict]) -> int:
    total = sum(c["bobot"] for c in checks)
    return round(100 * sum(c["bobot"] for c in checks if c["status"] == "lulus") / total) if total else 100


def audit(db: Session, *, url: str | None = None, text: str | None = None, html_doc: str | None = None,
          aktor: str = "staf") -> dict:
    started = time.perf_counter()
    is_html = bool(url or html_doc)
    headers, alamat = None, None
    if url:
        html_doc, headers, alamat = _ambil(url)
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
        checks.append(_cek_canonical(soup, alamat))
        checks.append(_cek_robots(soup, headers, alamat))
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
        checks.append({"id": "schema", "label": "Schema JSON-LD (Product/FAQPage/Organization)", "bobot": 10,
                       "status": "lulus" if {"Product", "FAQPage"} <= set(jsonld_types) else "gagal",
                       "detail": ", ".join(jsonld_types) or "Tidak ada JSON-LD",
                       "saran": "Tambahkan JSON-LD Product, FAQPage, dan Organization dari Studio Konten."})
        faq_present = "FAQPage" in jsonld_types or "pertanyaan" in body_text.lower()
        checks.append({"id": "faq", "label": "Blok FAQ untuk AI search", "bobot": 5,
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

    before = _skor(checks)
    rewrites = [{"sebelum": s.text, "sesudah": s.suggestion, "verdict": s.verdict,
                 "aturan": [f"{h.id} {h.label}" for h in s.rules]} for s in risky]
    after_text = check.safe_text
    after_check = claimguard.check(db, after_text, use_llm=False) if after_text else None
    # Skor dihitung dari pemeriksaan yang sama. Mengganti kalimat hanya memperbaiki pemeriksaan teks; struktur halaman tetap.
    sisa_berisiko = [s for s in after_check.sentences if s.verdict != claimguard.ALLOWED] if after_check else []
    sisa_statistik = any(h.id == "R17" for s in (after_check.sentences if after_check else []) for h in s.rules)
    teks_lulus = {"klaim": not sisa_berisiko, "statistik": not sisa_statistik}
    cek_sesudah = [{**c, "status": "lulus" if teks_lulus[c["id"]] else "gagal"} if c["id"] in teks_lulus else c for c in checks]
    struktur_gagal = [c for c in cek_sesudah if c["id"] not in teks_lulus and c["status"] == "gagal"]
    cek_potensi = [{**c, "status": "lulus"} if c in struktur_gagal else c for c in cek_sesudah]
    after = _skor(cek_sesudah)
    report = {
        "sumber": url or ("html" if html_doc else "teks"),
        "skor_sebelum": before,
        "skor_sesudah": after,
        "skor_potensi": _skor(cek_potensi),
        "perlu_perbaikan_struktur": [c["label"] for c in struktur_gagal],
        "kalimat_perlu_ditinjau": len(sisa_berisiko),
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
                  ringkasan=f"Audit {report['sumber'][:80]}: skor {before} → {after}, potensi {report['skor_potensi']}",
                  verdict=check.verdict, aturan_terpicu=check.rules_triggered, outcome=f"{len(risky)} kalimat berisiko",
                  model=check.model, data=report["ringkasan"])
    db.commit()
    return report
