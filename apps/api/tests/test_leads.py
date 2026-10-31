"""Leads → pelanggan: skor jaringan nasional, nomor WhatsApp, tautan prospek ↔ percakapan, funnel, tindak lanjut."""

import json
from pathlib import Path

import pytest

from aage.agents.graph import handle_inbound
from aage.db import SessionLocal
from aage.models import Prospect
from aage.prospects import lead_service
from aage.prospects.mapper import wa_number
from aage.prospects.scoring_service import national_chain, opportunity_score


@pytest.mark.parametrize("phone,expected", [
    ("+62 812-3456-7890", "6281234567890"), ("0812 3456 7890", "6281234567890"), ("024 8311234", "62248311234"),
    ("081234567890;024 1234", "6281234567890"), ("123", None), (None, None),
])
def test_wa_number_normalization(phone, expected):
    assert wa_number(phone) == expected


def test_national_chain_penalty_is_transparent():
    assert national_chain("Apotek K-24 MT Haryono Semarang") == "K-24"
    assert national_chain("Apotek Sehat", "Kimia Farma") == "Kimia Farma"
    assert national_chain("Apotek Sumber Waras") is None
    base = {"latitude": -6.99, "longitude": 110.38, "phone": "024", "opening_hours": "Mo-Su", "has_street": True}
    biasa = opportunity_score({**base, "name": "Apotek Sumber Waras"})
    rantai = opportunity_score({**base, "name": "Kimia Farma Pandanaran"})
    assert rantai["skor"] == biasa["skor"] - 25 and rantai["jaringan"] == "Kimia Farma"
    assert any(r["faktor"] == "Jaringan nasional" and r["poin"] == -25 for r in rantai["alasan"])


def test_prospect_to_customer_funnel(client, auth, monkeypatch):
    fixture = json.loads((Path(__file__).parent / "fixtures" / "overpass_kota_semarang_apotek.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(lead_service, "_post", lambda url, query, timeout_s: fixture)
    data = client.post("/api/prospek/scout", headers=auth, json={"wilayah": "Kota Semarang", "jenis_toko": "Apotek"}).json()
    assert any(it["jaringan"] for it in data["items"])

    target = next(it for it in data["items"] if not it["jaringan"])
    with SessionLocal() as db:
        db.get(Prospect, target["id"]).telepon = "0812-7777-0001"
        db.commit()

    # Staf mencatat rencana tindak lanjut (sudah lewat → dihitung jatuh tempo)
    r = client.patch(f"/api/prospects/{target['id']}", headers=auth,
                     json={"status": "dihubungi", "catatan": "Pemilik minta katalog", "pic": "Sari",
                           "tindak_lanjut_pada": "2026-01-01T09:00:00+07:00"})
    assert r.status_code == 200 and r.json()["catatan"] == "Pemilik minta katalog" and r.json()["wa"] == "6281277770001"

    # Prospek membalas lewat WhatsApp → tertaut & naik ke "merespons"
    with SessionLocal() as db:
        res = handle_inbound(db, external_user_id="6281277770001", text="pesan 10 box propolis tetes, alamat: Jl. Uji 1 Semarang",
                             channel="whatsapp", telepon="6281277770001")
        assert res.approval_id
        approval_id = res.approval_id
    lst = client.get(f"/api/prospects?wilayah=Kota Semarang&tipe={target['tipe']}", headers=auth).json()
    item = next(it for it in lst["items"] if it["id"] == target["id"])
    assert item["status"] == "merespons" and item["conversation_id"] == res.conversation_id
    assert lst["funnel"]["merespons"] >= 1 and lst["funnel"]["tindak_lanjut_jatuh_tempo"] >= 1

    # Draf pesanan dikonfirmasi staf → prospek menjadi pelanggan
    assert client.post(f"/api/approvals/{approval_id}/decide", headers=auth, json={"aksi": "setujui"}).status_code == 200
    lst = client.get(f"/api/prospects?wilayah=Kota Semarang&tipe={target['tipe']}", headers=auth).json()
    item = next(it for it in lst["items"] if it["id"] == target["id"])
    assert item["status"] == "pelanggan" and item["sudah_pelanggan"]
    assert lst["funnel"]["pelanggan"] >= 1
