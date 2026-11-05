"""Metrik klasifikasi klaim. Fungsi murni tanpa database, dipakai eval/run.py dan eval/run_klaim.py."""


def _pct(a: int, b: int) -> float:
    return round(100 * a / b, 1) if b else 0.0


def _f1(tp: int, fp: int, fn: int) -> float:
    return round(100 * 2 * tp / (2 * tp + fp + fn), 1) if tp else 0.0


def biner(tp: int, fp: int, fn: int, tn: int) -> dict:
    """Positif berarti kalimat berisiko. Rate positif palsu dan negatif palsu dalam persen."""
    return {"f1": _f1(tp, fp, fn), "false_positive_rate": _pct(fp, fp + tn), "false_negative_rate": _pct(fn, fn + tp)}


def per_kategori(pasangan: list[tuple[str, str]]) -> dict[str, dict]:
    """Precision, recall, dan F1 per kategori dari pasangan (emas, prediksi)."""
    hasil = {}
    for k in sorted({g for g, _ in pasangan} | {p for _, p in pasangan}):
        tp = sum(g == k and p == k for g, p in pasangan)
        fp = sum(g != k and p == k for g, p in pasangan)
        fn = sum(g == k and p != k for g, p in pasangan)
        hasil[k] = {"n": tp + fn, "precision": _pct(tp, tp + fp), "recall": _pct(tp, tp + fn), "f1": _f1(tp, fp, fn)}
    return hasil


def macro_f1(kategori: dict[str, dict]) -> float:
    """Rata-rata F1 kategori yang punya contoh emas."""
    nilai = [v["f1"] for v in kategori.values() if v["n"]]
    return round(sum(nilai) / len(nilai), 1) if nilai else 0.0
