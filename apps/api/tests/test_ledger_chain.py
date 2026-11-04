"""Rantai hash Ledger: setiap event tersegel, dan perubahan diam-diam di database terdeteksi."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from aage import ledger, ledger_chain
from aage.agents.graph import handle_inbound
from aage.db import IS_POSTGRES
from aage.models import LedgerImmutableError


def test_new_events_are_sealed_and_chain_is_intact(db):
    handle_inbound(db, external_user_id="t-rantai", text="ada produk untuk stamina?", channel="webchat")
    db.commit()
    r = ledger_chain.verify(db)
    assert r["utuh"] and r["belum_disegel"] == 0 and r["diperiksa"] == r["jumlah_event"] > 0
    assert len(r["hash_terakhir"]) == 64


def test_each_hash_links_to_previous(db):
    a = ledger.record(db, "pesan_masuk", ringkasan="satu", aktor="pembeli")
    b = ledger.record(db, "pesan_masuk", ringkasan="dua", aktor="pembeli")
    ha, hb = (db.query(ledger_chain.LedgerHash).filter_by(event_id=e.id).one() for e in (a, b))
    assert hb.prev_hash == ha.hash and hb.hash == ledger_chain.digest(ha.hash, b)
    db.rollback()


def test_tampering_is_detected(db):
    ev = ledger.record(db, "pesan_keluar", ringkasan="Harga Rp 100.000", aktor="AI")
    db.commit()
    if IS_POSTGRES:  # lapis pertama: trigger menolak; penyerang harus punya hak mematikannya dulu
        with pytest.raises(DBAPIError, match="append-only"), db.begin_nested():
            db.execute(text("UPDATE ledger_events SET ringkasan = 'Harga Rp 1' WHERE id = :i"), {"i": ev.id})
        db.execute(text("ALTER TABLE ledger_events DISABLE TRIGGER ledger_no_update"))
    # Penyerang mengubah baris langsung lewat SQL (melewati penjaga ORM).
    db.execute(text("UPDATE ledger_events SET ringkasan = 'Harga Rp 1' WHERE id = :i"), {"i": ev.id})
    db.expire_all()
    r = ledger_chain.verify(db)
    assert not r["utuh"] and r["masalah"][0]["event_id"] == ev.id
    db.rollback()
    assert ledger_chain.verify(db)["utuh"]


def test_hashes_are_append_only(db):
    ev = ledger.record(db, "pesan_masuk", ringkasan="x", aktor="pembeli")
    h = db.query(ledger_chain.LedgerHash).filter_by(event_id=ev.id).one()
    h.hash = "0" * 64
    with pytest.raises(LedgerImmutableError):
        db.flush()
    db.rollback()


def test_verify_endpoint_and_hash_in_list(client, auth):
    r = client.get("/api/ledger/verify", headers=auth).json()
    assert r["utuh"] is True
    items = client.get("/api/ledger?limit=3", headers=auth).json()["items"]
    assert all(len(i["hash"]) == 64 for i in items)
