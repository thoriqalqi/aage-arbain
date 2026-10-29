"""Studio Konten: format baru, validasi topik, edit + ClaimGuard ulang, antrean Approval, aturan dua orang, arsip."""

import pytest

from aage.models import LedgerEvent


@pytest.fixture
def admin(client):
    tok = client.post("/api/auth/login", json={"email": "admin@aage.local", "password": "admin123"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _gen(client, h, tipe="artikel", topik="stamina saat musim hujan"):
    r = client.post("/api/content/generate", headers=h, json={"product_id": 1, "topik": topik, "target": "apotek", "tipe": tipe})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("tipe", ["caption_ig", "broadcast_wa", "marketplace", "brosur"])
def test_new_formats_are_checked_and_not_web(client, auth, tipe):
    d = _gen(client, auth, tipe)
    assert d["tipe"] == tipe and d["claim_verdict"] != "blocked"
    assert d["json_ld"] == [] and d["faq"] == []


def test_broadcast_has_opt_out_and_brochure_has_tiers(client, auth):
    assert "Balas STOP" in _gen(client, auth, "broadcast_wa")["isi"]
    assert "Diskon volume" in _gen(client, auth, "brosur")["isi"]


@pytest.mark.parametrize("topik", ["", "Fw", "  ", "12345"])
def test_topic_is_required(client, auth, topik):
    r = client.post("/api/content/generate", headers=auth, json={"product_id": 1, "topik": topik, "tipe": "artikel"})
    assert r.status_code == 400 and "Topik" in r.json()["detail"]


def test_edit_rechecks_and_is_logged(client, auth, db):
    d = _gen(client, auth)
    r = client.patch(f"/api/content/{d['id']}", headers=auth, json={"isi": d["isi"] + "\n\nMadu ini menyembuhkan diabetes."})
    assert r.status_code == 200 and r.json()["claim_verdict"] == "blocked"
    assert db.query(LedgerEvent).filter_by(tipe_event="konten_diedit", objek_ref=f"content:{d['id']}").count() == 1
    assert client.post(f"/api/content/{d['id']}/submit", headers=auth).status_code == 422  # diblokir tidak bisa diajukan


def test_live_recheck_endpoint(client, auth):
    r = client.post("/api/content/recheck", headers=auth, json={"teks": "Produk ini menyembuhkan kanker.", "product_id": 1})
    assert r.status_code == 200 and r.json()["verdict"] == "blocked" and r.json()["sentences"]


def test_submit_goes_to_approval_queue_with_two_person_rule(client, auth, admin):
    d = _gen(client, auth, "caption_ig")
    sub = client.post(f"/api/content/{d['id']}/submit", headers=auth).json()
    assert sub["status"] == "menunggu_approval"
    queue = client.get("/api/approvals?status=menunggu", headers=admin).json()["items"]
    ap = next(a for a in queue if a["objek_tipe"] == "konten" and a["objek_id"] == d["id"])
    # Pengaju tidak boleh menyetujui sendiri, dan konten tidak bisa diedit selama menunggu.
    assert client.post(f"/api/approvals/{ap['id']}/decide", headers=auth, json={"aksi": "setujui"}).status_code == 422
    assert client.patch(f"/api/content/{d['id']}", headers=auth, json={"judul": "x"}).status_code == 409
    assert client.post(f"/api/approvals/{ap['id']}/decide", headers=admin, json={"aksi": "setujui"}).status_code == 200
    assert client.get(f"/api/content/{d['id']}", headers=auth).json()["status"] == "disetujui"
    exp = client.get(f"/api/content/{d['id']}/export", headers=auth).json()
    assert exp["format"] == "teks" and "CV Arba'in" in exp["teks"]


def test_reject_returns_to_creator(client, auth, admin):
    d = _gen(client, auth, "marketplace")
    ap_id = client.post(f"/api/content/{d['id']}/submit", headers=auth).json()["approval_id"]
    assert client.post(f"/api/approvals/{ap_id}/decide", headers=admin, json={"aksi": "tolak"}).status_code == 200
    assert client.get(f"/api/content/{d['id']}", headers=auth).json()["status"] == "ditolak"
    assert client.patch(f"/api/content/{d['id']}", headers=auth, json={"judul": "Judul baru"}).json()["status"] == "draf"


def test_archive_hides_from_list(client, auth):
    d = _gen(client, auth)
    client.post(f"/api/content/{d['id']}/arsip", headers=auth)
    ids = [x["id"] for x in client.get("/api/content", headers=auth).json()["items"]]
    assert d["id"] not in ids
    assert d["id"] in [x["id"] for x in client.get("/api/content?arsip=true", headers=auth).json()["items"]]
