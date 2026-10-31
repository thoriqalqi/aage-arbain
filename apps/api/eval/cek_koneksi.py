"""SATU panggilan verifikasi lewat llm.complete (Gemini REST langsung). Tidak mencetak API key.

    python -m eval.cek_koneksi            # format router: JSON, max 80 token, temperature 0, LLM_MODEL
    python -m eval.cek_koneksi --juri     # format juri ClaimGuard: JSON, max 300 token, LLM_JUDGE_MODEL

Respons mentah (teks + finishReason) ditangkap dari dalam skrip ini saja; kode aplikasi tidak diubah.
"""

import os
import sys
import tempfile
from pathlib import Path

os.environ.update({
    "DATABASE_URL": f"sqlite:///{(Path(tempfile.gettempdir()) / 'aage-cek-koneksi.db').as_posix()}",
    "LLM_FALLBACK_MODELS": "", "WATI_API_KEY": "", "WA_ACCESS_TOKEN": "", "FONNTE_TOKEN": "",
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aage import llm  # noqa: E402
from aage.agents.router import INTENTS  # noqa: E402
from aage.claimguard.service import JUDGE_PROMPT  # noqa: E402
from aage.config import get_settings  # noqa: E402
from aage.db import init_db  # noqa: E402

JURI = "--juri" in sys.argv
s = get_settings()
init_db()

captured: dict = {}
_orig = llm._post


def _spy(url, body, timeout, headers=None):
    captured["model"] = body.get("model") or url.rsplit("/models/", 1)[-1].split(":")[0]
    captured["generationConfig"] = body.get("generationConfig") or {k: body[k] for k in ("max_tokens", "temperature", "response_format") if k in body}
    resp = _orig(url, body, timeout, headers)
    captured["http"] = resp.status_code
    try:
        captured["raw"] = resp.json()
    except ValueError:
        captured["raw"] = resp.text[:300]
    return resp


llm._post = _spy

if JURI:
    sentence = "Mengandung antioksidan tinggi yang baik untuk tubuh."
    claims = "- Membantu memelihara stamina dan kebugaran tubuh.\n- Sumber energi untuk aktivitas sehari-hari."
    res = llm.complete([{"role": "user", "content": JUDGE_PROMPT.format(claims=claims, sentence=sentence)}],
                       judge=True, json_mode=True, max_tokens=300, temperature=0)
    ok = res is not None and isinstance(res.data, dict) and res.data.get("verdict") in ("allowed", "review", "blocked")
else:
    t = "kak brp lama pengiriman ke solo?"
    res = llm.complete([{"role": "user", "content": (
        "Klasifikasikan pesan pembeli B2B produk herbal ke salah satu intent: "
        + ", ".join(INTENTS) + f'. Pesan: "{t}". Jawab JSON {{"intent": "...", "alasan": "..."}}')}],
        json_mode=True, max_tokens=80, temperature=0)
    ok = res is not None and isinstance(res.data, dict) and res.data.get("intent") in INTENTS

raw = captured.get("raw") if isinstance(captured.get("raw"), dict) else {}
cand = (raw.get("candidates") or [{}])[0]
if raw.get("choices"):
    _ch = raw["choices"][0]
    cand = {"finishReason": _ch.get("finish_reason"), "content": {"parts": [{"text": (_ch.get("message") or {}).get("content") or ""}]}}
    raw["usageMetadata"] = raw.get("usage")
teks = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []) if not p.get("thought"))
print(f"format={'juri (300 token)' if JURI else 'router (80 token)'} · model={captured.get('model')} · "
      f"HTTP {captured.get('http')} · generationConfig={captured.get('generationConfig')}")
print(f"HASIL: {'LULUS' if ok else 'GAGAL'}")
print(f"finish_reason: {cand.get('finishReason')} · usage: {raw.get('usageMetadata')}")
print(f"teks mentah: {teks[:200]!r}")
if res is not None:
    print(f"hasil parse: {res.data} · {res.latensi_ms} ms")
else:
    print(f"last_error: {llm.last_error()}")
