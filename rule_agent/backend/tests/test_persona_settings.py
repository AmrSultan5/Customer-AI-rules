"""
Tests for admin-controlled persona switches: GET /personas, GET/PUT
/admin/personas, and enforcement (conversation creation, listing, and detail
lookup all respect the enabled set — hidden, never deleted).
"""
import asyncio

import pytest
from fastapi.testclient import TestClient

import db
from main import app

client = TestClient(app, raise_server_exceptions=False)

TOKEN = "test-secret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _hdr(username: str) -> dict:
    return {**AUTH, "X-User": username}


def _enable(personas: list[str]) -> dict:
    r = client.put("/admin/personas", headers=AUTH, json={"enabled": personas})
    assert r.status_code == 200
    return r.json()


def _enabled_map(payload: dict) -> dict:
    return {p["id"]: p["enabled"] for p in payload["personas"]}


@pytest.fixture(autouse=True)
def _clean_db_and_limiter():
    """Fresh schema and reset rate-limit counters before each test."""
    asyncio.run(db.reset_db())
    from main import limiter
    limiter._storage.reset()
    yield


# ── GET /personas ────────────────────────────────────────────────────────────


def test_get_personas_default_only_analyst_enabled():
    r = client.get("/personas", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    ids = {p["id"] for p in body["personas"]}
    assert ids == {"analyst", "engineer", "pm"}
    enabled = _enabled_map(body)
    assert enabled["analyst"] is True
    assert enabled["engineer"] is False
    assert enabled["pm"] is False


# ── PUT /admin/personas ──────────────────────────────────────────────────────


def test_admin_put_personas_persists():
    _enable(["analyst", "engineer"])

    r = client.get("/personas", headers=AUTH)
    enabled = _enabled_map(r.json())
    assert enabled["analyst"] is True
    assert enabled["engineer"] is True
    assert enabled["pm"] is False


def test_admin_cannot_disable_analyst():
    put_body = _enable(["engineer"])
    assert _enabled_map(put_body)["analyst"] is True

    r = client.get("/personas", headers=AUTH)
    assert _enabled_map(r.json())["analyst"] is True


# ── Enforcement: POST /conversations ─────────────────────────────────────────


def test_create_conversation_rejected_when_persona_disabled_then_allowed():
    # pm disabled by default
    r = client.post(
        "/conversations", headers=_hdr("alice"), json={"persona": "pm"},
    )
    assert r.status_code == 403
    assert r.json()["detail"] == {"error": "That assistant mode is not currently available."}

    _enable(["analyst", "pm"])
    r = client.post(
        "/conversations", headers=_hdr("alice"), json={"persona": "pm"},
    )
    assert r.status_code == 200
    assert r.json()["persona"] == "pm"


# ── Disabled persona hides (not deletes) existing conversations ─────────────


def test_disabled_persona_conversation_hidden_not_deleted():
    _enable(["analyst", "engineer", "pm"])
    created = client.post(
        "/conversations", headers=_hdr("bob"),
        json={"persona": "engineer", "title": "Pipeline change"},
    ).json()
    cid = created["id"]

    # sanity: visible while enabled
    r = client.get("/conversations", headers=_hdr("bob"))
    assert cid in [c["id"] for c in r.json()]
    assert client.get(f"/conversations/{cid}", headers=_hdr("bob")).status_code == 200

    # disable engineer
    _enable(["analyst"])

    r = client.get("/conversations", headers=_hdr("bob"))
    assert cid not in [c["id"] for c in r.json()]
    r = client.get(f"/conversations/{cid}", headers=_hdr("bob"))
    assert r.status_code == 404

    # re-enable: reappears with data intact
    _enable(["analyst", "engineer"])
    r = client.get("/conversations", headers=_hdr("bob"))
    assert cid in [c["id"] for c in r.json()]
    r = client.get(f"/conversations/{cid}", headers=_hdr("bob"))
    assert r.status_code == 200
    detail = r.json()
    assert detail["id"] == cid
    assert detail["persona"] == "engineer"
    assert detail["title"] == "Pipeline change"


# ── Admin auth ────────────────────────────────────────────────────────────────


def test_admin_personas_requires_admin_token():
    # missing token
    assert client.get("/admin/personas").status_code == 401
    assert client.put("/admin/personas", json={"enabled": ["analyst"]}).status_code == 401

    # wrong token
    wrong = {"Authorization": "Bearer wrong-token"}
    assert client.get("/admin/personas", headers=wrong).status_code == 401
    assert client.put("/admin/personas", headers=wrong, json={"enabled": ["analyst"]}).status_code == 401
