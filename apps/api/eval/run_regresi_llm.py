"""Regresi mode LLM yang tahan gangguan: hasil ditulis ke folder baru, baris ERROR saja yang diulang, lalu digabung.

    python -m eval.run_regresi_llm --keluaran hasil_fase4 --emosi 8

- Hasil lama eval/hasil_llm*.jsonl tidak disentuh. Bisa dijalankan ulang: yang sudah dinilai tidak diproses lagi.
- Baris SALAH tidak pernah diulang; hanya baris yang LLM-nya gagal (ERROR) atau belum sempat diproses.
- <folder>/hasil_llm*.jsonl menyimpan semua percobaan termasuk ERROR; *_gabung.jsonl berisi hasil akhir per baris.
- <folder>/laporan.txt: hasil per dataset, statistik kunci fakta, dan error LLM yang tersisa.
"""

import argparse
import collections
import csv
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
JEDA_RONDE_S = (60, 120, 300, 600, 900)  # jeda sebelum mengulang baris ERROR (jaringan/kuota butuh waktu pulih)
KATALOG_UJI = "eval/katalog/katalog_uji_b.xlsx"
TEMP = Path(tempfile.gettempdir())


@dataclass
class Dataset:
    nama: str
    suffix: str = ""
    percobaan: int = 1
    argumen: list[str] = field(default_factory=list)
    percakapan: bool = False

    @property
    def berkas(self) -> str:
        return "hasil_llm_percakapan" if self.percakapan else f"hasil_llm{self.suffix}"

    @property
    def csv(self) -> Path:
        return HERE / f"dataset_{self.nama}.csv"

    def kunci(self) -> list[tuple]:
        rows = list(csv.DictReader(self.csv.open(encoding="utf-8")))
        if self.percakapan:
            return [(r["skenario"], int(r["giliran"])) for r in rows]
        return [(r["id"], k) for r in rows for k in range(self.percobaan)]

    def kunci_baris(self, r: dict) -> tuple:
        return (r["skenario"], r["giliran"]) if self.percakapan else (r["id"], r.get("percobaan", 0))

    def perintah(self, keluaran: str, jeda: float) -> list[str]:
        modul = "eval.run_percakapan" if self.percakapan else "eval.run_eval"
        cmd = [sys.executable, "-m", modul, "--mode", "llm", "--keluaran", keluaran, "--jeda", str(jeda)]
        if not self.percakapan:
            cmd += ["--dataset", self.nama, "--percobaan", str(self.percobaan)]
        return cmd + self.argumen

    def db(self, keluaran: str) -> Path:
        kat = f"_kat-{Path(KATALOG_UJI).stem}" if self.nama == "katalog_uji" else ""
        return TEMP / f"aage-eval-{self.nama}{kat}-{keluaran}-llm.db"


def _baca(folder: Path, d: Dataset) -> list[dict]:
    f = folder / f"{d.berkas}.jsonl"
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()] if f.exists() else []


def gabung(folder: Path, d: Dataset) -> tuple[dict, list[tuple]]:
    """Hasil akhir per kunci: baris DINILAI bila ada, selain itu ERROR terakhir. Kembalikan (hasil, kunci belum ada)."""
    akhir: dict[tuple, dict] = {}
    for r in _baca(folder, d):
        k = d.kunci_baris(r)
        if r.get("status") != "ERROR" or akhir.get(k, {}).get("status", "ERROR") == "ERROR":
            akhir[k] = r
    return akhir, [k for k in d.kunci() if k not in akhir]


def belum_selesai(folder: Path, d: Dataset) -> int:
    akhir, kosong = gabung(folder, d)
    return len(kosong) + sum(r.get("status") == "ERROR" for r in akhir.values())


def jalankan_ronde(folder: Path, daftar: list[Dataset], keluaran: str, jeda: float, ronde: int) -> None:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proses = []
    for d in daftar:
        log = (TEMP / f"aage-regresi-{keluaran}-{d.nama}-r{ronde}.log").open("w", encoding="utf-8")
        proses.append((d, log, subprocess.Popen(d.perintah(keluaran, jeda), cwd=HERE.parent, env=env, stdout=log,
                                                stderr=subprocess.STDOUT)))
    for d, log, p in proses:
        kode = p.wait()
        log.close()
        print(f"  ronde {ronde} · {d.nama}: exit {kode}, sisa {belum_selesai(folder, d)} baris", flush=True)


def _kategori(s: str) -> str:
    """'angka berubah: [...]' → 'angka berubah'; frasa & kata terlarang tetap dengan rinciannya."""
    return s if s.startswith(("frasa kunci", "kata terlarang")) else s.split(":")[0]


def statistik_gaya(folder: Path, daftar: list[Dataset], keluaran: str) -> tuple[dict, collections.Counter, list[str]]:
    per: dict[str, collections.Counter] = {}
    alasan: collections.Counter = collections.Counter()
    contoh: list[str] = []

    def catat(nama: str, data: dict) -> None:
        c = per.setdefault(nama, collections.Counter())
        if data.get("dibatalkan_claimguard"):
            c["dibatalkan ClaimGuard"] += 1
        elif data.get("dipakai"):
            c["diterima"] += 1
        else:
            c["ditolak"] += 1
            alasan.update(_kategori(s) for s in data.get("pelanggaran") or [])
            if data.get("teks_ditolak") and len(contoh) < 6:
                contoh.append(f"{'; '.join(data.get('pelanggaran') or [])[:120]} ← {' '.join(data['teks_ditolak'].split())[:160]}")

    for d in daftar:
        per.setdefault(d.nama, collections.Counter())
        if d.percakapan:  # DB dibuat ulang tiap ronde, jadi catatannya ada di baris hasil
            for r in _baca(folder, d):
                if r.get("gaya"):
                    catat(d.nama, r["gaya"])
        elif d.db(keluaran).exists():
            con = sqlite3.connect(d.db(keluaran))
            for (data,) in con.execute("select data from ledger_events where tipe_event='gaya_bahasa'"):
                catat(d.nama, json.loads(data or "{}"))
            con.close()
    return per, alasan, contoh


def laporan(folder: Path, daftar: list[Dataset], keluaran: str, ronde: int) -> bool:
    baris: list[str] = [f"Regresi LLM · keluaran {keluaran} · {ronde} ronde", ""]
    semua_lolos, total_err, total_kosong = True, 0, 0
    meter: collections.Counter = collections.Counter()
    for d in daftar:
        akhir, kosong = gabung(folder, d)
        semua = _baca(folder, d)
        (folder / f"{d.berkas}_gabung.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in akhir.values()), encoding="utf-8")
        err = [r for r in akhir.values() if r.get("status") == "ERROR"]
        salah = [r for r in akhir.values() if r.get("status") != "ERROR" and not r.get("benar")]
        pulih = sum(r.get("status") == "ERROR" for r in semua) - len(err)
        total_err += len(err)
        total_kosong += len(kosong)
        semua_lolos &= not (err or salah or kosong)
        benar = sum(bool(r.get("benar")) for r in akhir.values() if r.get("status") != "ERROR")
        info = f"{d.nama:12s} {benar}/{len(d.kunci())} lolos · salah {len(salah)} · ERROR tersisa {len(err)} · belum diproses {len(kosong)} · pulih setelah diulang {pulih}"
        if d.percobaan > 1:
            per_id: dict[str, list[dict]] = collections.defaultdict(list)
            for r in akhir.values():
                per_id[r["id"]].append(r)
            lolos_id = sum(len(v) == d.percobaan and all(x.get("benar") for x in v) for v in per_id.values())
            tak_stabil = {i: v for i, v in per_id.items() if len({(x.get("intent"), x.get("keputusan"), x.get("generator"), bool(x.get("benar"))) for x in v}) > 1}
            info += f"\n{'':12s} {d.percobaan} kali: {lolos_id}/{len(per_id)} pesan lolos semua · konsisten {len(per_id) - len(tak_stabil)}/{len(per_id)}"
            for i, v in tak_stabil.items():
                info += f"\n{'':12s} ≈ tidak konsisten {i} {v[0]['pesan'][:50]!r}: " + ", ".join(sorted({f'{x.get("intent")}/{x.get("keputusan")}/{x.get("generator")}/{"lolos" if x.get("benar") else "SALAH"}' for x in v}))
        baris.append(info)
        for r in salah:
            nama = f"{r['skenario']}#{r['giliran']}" if d.percakapan else f"{r['id']}#{r.get('percobaan', 0)}"
            alasan = r.get("gagal") if d.percakapan else r.get("alasan")
            baris.append(f"   ✗ {nama} [{r.get('intent')}→{r.get('keputusan')}] {r['pesan'][:60]!r} | {str(alasan)[:140]} | {' '.join(r['jawaban'].split())[:200]!r}")
        for r in err:
            pesan = ((r.get("llm") or {}).get("error") or [{}])[-1].get("pesan") or r.get("error_alur")
            baris.append(f"   ! ERROR {r.get('id') or r.get('skenario')}: {r['pesan'][:60]!r} | {str(pesan)[:140]}")
        f = folder / f"{d.berkas}_ringkas.jsonl"
        for x in (f.read_text(encoding="utf-8").splitlines() if f.exists() else []):
            meter.update(json.loads(x).get("llm") or {})

    per, alasan, contoh = statistik_gaya(folder, daftar, keluaran)
    jumlah = collections.Counter()
    for c in per.values():
        jumlah.update(c)
    baris += ["", "Kunci fakta (gaya bahasa LLM):",
              f"  diterima {jumlah['diterima']} (lalu dibatalkan ClaimGuard {jumlah['dibatalkan ClaimGuard']}) · ditolak {jumlah['ditolak']}"]
    for nama, c in per.items():
        baris.append(f"  {nama:12s} diterima {c['diterima']} · dibatalkan ClaimGuard {c['dibatalkan ClaimGuard']} · ditolak {c['ditolak']}")
    baris.append("  Alasan penolakan: " + (json.dumps(dict(alasan.most_common()), ensure_ascii=False) if alasan else "-"))
    baris += [f"  Contoh ditolak: {x}" for x in contoh]
    baris += ["", f"Panggilan LLM (ronde yang selesai): {dict(meter)}",
              f"Error LLM tersisa: {total_err} baris ERROR, {total_kosong} baris belum diproses",
              f"KESIMPULAN: {'SEMUA LOLOS 100%' if semua_lolos else 'BELUM 100%'}"]
    teks = "\n".join(baris)
    (folder / "laporan.txt").write_text(teks + "\n", encoding="utf-8")
    print(teks, flush=True)
    return semua_lolos


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--keluaran", required=True, help="nama folder baru di eval/")
    p.add_argument("--emosi", type=int, default=8, help="berapa kali dataset emosi dijalankan (konsistensi)")
    p.add_argument("--jeda", type=float, default=4.0)
    args = p.parse_args()
    folder = HERE / args.keluaran
    folder.mkdir(exist_ok=True)
    daftar = [Dataset("realistis"), Dataset("holdout", "_holdout"), Dataset("adversarial", "_adversarial"),
              Dataset("lapangan", "_lapangan"), Dataset("emosi", "_emosi", percobaan=args.emosi),
              Dataset("katalog_uji", "_katalog_uji_kat-katalog_uji_b", argumen=["--katalog", KATALOG_UJI]),
              Dataset("percakapan", percakapan=True)]
    ronde = 0
    for ronde in range(1, len(JEDA_RONDE_S) + 2):
        todo = [d for d in daftar if belum_selesai(folder, d)]
        if not todo:
            ronde -= 1
            break
        if ronde > 1:
            jeda = JEDA_RONDE_S[ronde - 2]
            print(f"Masih ada baris error/belum diproses di {[d.nama for d in todo]}; menunggu {jeda} dtk", flush=True)
            time.sleep(jeda)
        print(f"Ronde {ronde}: {[(d.nama, belum_selesai(folder, d)) for d in todo]}", flush=True)
        jalankan_ronde(folder, todo, args.keluaran, args.jeda, ronde)
    sys.exit(0 if laporan(folder, daftar, args.keluaran, ronde) else 1)


if __name__ == "__main__":
    main()
