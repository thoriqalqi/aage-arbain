"""Eval kategori ClaimGuard, jalur deterministik tanpa LLM.

Dataset eval/datasets/klaim_kategori.csv memuat parafrase yang sengaja belum tentu tertangkap aturan. Angkanya ukuran,
bukan gerbang lolos, dan dataset ditulis tim, jadi ini bukan uji buta. Jangan menyetel aturan hanya demi angka ini.

    python -m eval.run_klaim --keluaran hasil_kerja
"""

import argparse
import csv
import json
from pathlib import Path

from eval.metrik_klaim import biner, macro_f1, per_kategori

HERE = Path(__file__).resolve().parent
DATASET = HERE / "datasets" / "klaim_kategori.csv"
AMAN = {"SUPPORTED_CLAIM", "SAFE_PRODUCT_DESCRIPTION"}
TANPA_DASAR = "UNSUPPORTED_CLAIM"
_RANK_KEPUTUSAN = {"PASS": 0, "NEEDS_REVIEW": 1, "BLOCK": 2}


def baca_dataset(path: Path = DATASET) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def prediksi_kategori(sentences: list[dict]) -> str:
    """Satu baris bisa terpecah jadi beberapa kalimat: pakai kalimat dengan keputusan terberat, lalu risiko tertinggi."""
    from aage.claimguard import registry

    terberat = max(sentences, key=lambda s: (_RANK_KEPUTUSAN[s["keputusan"]], registry.peringkat_risiko(s["risiko"])))
    return terberat["kategori"]


def nilai(baris: list[dict]) -> dict:
    """Hitung metrik dari baris {kalimat, kategori, keputusan, prediksi_kategori, prediksi_keputusan}."""
    kategori = per_kategori([(b["kategori"], b["prediksi_kategori"]) for b in baris])
    emas_aman = [b for b in baris if b["kategori"] in AMAN]
    emas_risiko = [b for b in baris if b["kategori"] not in AMAN]
    tp = sum(b["prediksi_keputusan"] != "PASS" for b in emas_risiko)
    fp = sum(b["prediksi_keputusan"] != "PASS" for b in emas_aman)
    tanpa_dasar = [b for b in baris if b["kategori"] == TANPA_DASAR]
    confusion: dict[str, dict[str, int]] = {}
    for b in baris:
        kolom = confusion.setdefault(b["keputusan"], {})
        kolom[b["prediksi_keputusan"]] = kolom.get(b["prediksi_keputusan"], 0) + 1
    return {
        "n": len(baris),
        "per_kategori": kategori,
        "macro_f1": macro_f1(kategori),
        "akurasi_kategori": round(100 * sum(b["kategori"] == b["prediksi_kategori"] for b in baris) / len(baris), 1) if baris else 0.0,
        "akurasi_keputusan": round(100 * sum(b["keputusan"] == b["prediksi_keputusan"] for b in baris) / len(baris), 1) if baris else 0.0,
        **biner(tp, fp, len(emas_risiko) - tp, len(emas_aman) - fp),
        "unsupported_claim_recall": round(100 * sum(b["prediksi_keputusan"] != "PASS" for b in tanpa_dasar) / len(tanpa_dasar), 1) if tanpa_dasar else 0.0,
        "confusion_keputusan": confusion,
        "lolos_berisiko": [b["kalimat"] for b in emas_risiko if b["prediksi_keputusan"] == "PASS"],
        "blok_lolos": sum(b["keputusan"] == "BLOCK" and b["prediksi_keputusan"] == "PASS" for b in baris),
        "aman_tertahan": [b["kalimat"] for b in emas_aman if b["prediksi_keputusan"] != "PASS"],
    }


def jalankan(db) -> list[dict]:
    from aage import claimguard

    baris = []
    for r in baca_dataset():
        hasil = claimguard.check(db, r["kalimat"], use_llm=False).to_dict()
        baris.append({**r, "prediksi_kategori": prediksi_kategori(hasil["sentences"]), "prediksi_keputusan": hasil["keputusan"],
                      "aturan": hasil["rules_triggered"], "versi_aturan": hasil["rules_version"]})
    return baris


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--keluaran", required=True, help="folder di eval/ untuk hasil; jangan di-commit")
    args = p.parse_args()

    from eval import run_eval

    run_eval._prepare_env("template", "klaim")
    from aage import settings_store
    from aage.db import SessionLocal, init_db
    from aage.seed import seed_base

    init_db(drop=True)
    with SessionLocal() as db:
        seed_base(db)
        settings_store.pasang_mode_data(db, "demo", "eval")  # dataset bergantung pada katalog simulasi
        baris = jalankan(db)
    ringkas = nilai(baris)
    folder = HERE / args.keluaran
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "hasil_klaim.json").write_text(json.dumps({"ringkasan": ringkas, "baris": baris}, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Versi aturan {baris[0]['versi_aturan']}, {ringkas['n']} kalimat, tanpa LLM. Ukuran, bukan uji buta.")
    for k, v in ringkas["per_kategori"].items():
        print(f"  {k:26} n={v['n']:3} P={v['precision']:5} R={v['recall']:5} F1={v['f1']:5}")
    print(f"macro F1 {ringkas['macro_f1']}, akurasi kategori {ringkas['akurasi_kategori']}, akurasi keputusan {ringkas['akurasi_keputusan']}")
    print(f"false positive {ringkas['false_positive_rate']}, false negative {ringkas['false_negative_rate']}, "
          f"unsupported recall {ringkas['unsupported_claim_recall']}, BLOCK lolos jadi PASS {ringkas['blok_lolos']}")
    print("confusion keputusan (emas -> prediksi):", json.dumps(ringkas["confusion_keputusan"]))


if __name__ == "__main__":
    main()
