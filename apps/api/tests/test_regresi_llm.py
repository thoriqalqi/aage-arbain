"""Alat regresi LLM: hasil digabung per baris, ERROR diulang, baris SALAH tidak disembunyikan."""

import json

from eval.run_regresi_llm import Dataset, belum_selesai, gabung


def _tulis(folder, nama, rows):
    (folder / f"{nama}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_merge_prefers_scored_row_and_counts_what_remains(tmp_path):
    d = Dataset("holdout", "_holdout")
    kunci = d.kunci()
    a, b, c = kunci[0][0], kunci[1][0], kunci[2][0]
    _tulis(tmp_path, d.berkas, [
        {"id": a, "percobaan": 0, "status": "ERROR"},
        {"id": a, "percobaan": 0, "status": "DINILAI", "benar": True},  # pulih setelah diulang
        {"id": b, "percobaan": 0, "status": "DINILAI", "benar": False},  # SALAH tetap SALAH, tidak diulang
        {"id": c, "percobaan": 0, "status": "ERROR"},
    ])
    akhir, kosong = gabung(tmp_path, d)
    assert akhir[(a, 0)]["benar"] is True and akhir[(b, 0)]["benar"] is False and akhir[(c, 0)]["status"] == "ERROR"
    assert len(kosong) == len(kunci) - 3
    assert belum_selesai(tmp_path, d) == len(kunci) - 3 + 1


def test_scored_row_is_not_replaced_by_later_error(tmp_path):
    d = Dataset("holdout", "_holdout")
    a = d.kunci()[0][0]
    _tulis(tmp_path, d.berkas, [{"id": a, "percobaan": 0, "status": "DINILAI", "benar": True},
                                {"id": a, "percobaan": 0, "status": "ERROR"}])
    assert gabung(tmp_path, d)[0][(a, 0)]["status"] == "DINILAI"


def test_each_attempt_of_a_repeated_dataset_is_expected(tmp_path):
    d = Dataset("emosi", "_emosi", percobaan=8)
    baris = len(d.kunci()) // 8
    assert baris == 50 and belum_selesai(tmp_path, d) == 400
