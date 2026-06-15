"""
Tests for the chat workspace: users, projects, conversations, message
persistence, project-instruction injection, and gpt-4o-mini auto-titling
(OpenAI mocked so no network calls).
"""
import asyncio
import json as _json

import pytest
from fastapi.testclient import TestClient

import conversation_service as cs
import db
import openai_client
from main import app

client = TestClient(app, raise_server_exceptions=False)

TOKEN = "test-secret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _hdr(username: str) -> dict:
    return {**AUTH, "X-User": username}


@pytest.fixture(autouse=True)
def _clean_db_and_limiter():
    """Fresh schema and reset rate-limit counters before each test."""
    asyncio.run(db.reset_db())
    from main import limiter
    limiter._storage.reset()
    yield


# ── Users / projects ─────────────────────────────────────────────────────────


def test_login_creates_user():
    r = client.post("/users/login", headers=AUTH, json={"username": "alice"})
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "alice"
    assert isinstance(body["user_id"], int)


def test_project_crud():
    r = client.post("/projects", headers=_hdr("alice"), json={"name": "DCC work"})
    assert r.status_code == 200
    pid = r.json()["id"]

    # update name + instructions
    r = client.patch(
        f"/projects/{pid}", headers=_hdr("alice"),
        json={"name": "DCC", "instructions": "Scope answers to the DCC module."},
    )
    assert r.status_code == 200
    assert r.json()["instructions"] == "Scope answers to the DCC module."

    # list
    r = client.get("/projects", headers=_hdr("alice"))
    assert r.status_code == 200
    assert len(r.json()) == 1

    # delete
    r = client.delete(f"/projects/{pid}", headers=_hdr("alice"))
    assert r.status_code == 200
    assert client.get("/projects", headers=_hdr("alice")).json() == []


def test_missing_x_user_header_rejected():
    r = client.get("/projects", headers=AUTH)
    assert r.status_code == 400


# ── Conversations ────────────────────────────────────────────────────────────


def test_conversation_crud_and_persona():
    # one conversation per persona, all under a project
    pid = client.post("/projects", headers=_hdr("alice"), json={"name": "P"}).json()["id"]
    ids = {}
    for persona in ("analyst", "engineer", "pm"):
        r = client.post(
            "/conversations", headers=_hdr("alice"),
            json={"persona": persona, "project_id": pid},
        )
        assert r.status_code == 200
        assert r.json()["persona"] == persona
        ids[persona] = r.json()["id"]

    # list scoped to project + persona
    r = client.get("/conversations", headers=_hdr("alice"), params={"project_id": pid, "persona": "pm"})
    assert [c["id"] for c in r.json()] == [ids["pm"]]

    # rename + move out of project
    r = client.patch(
        f"/conversations/{ids['analyst']}", headers=_hdr("alice"),
        json={"title": "Renamed", "project_id": None},
    )
    assert r.status_code == 200
    assert r.json()["title"] == "Renamed"
    assert r.json()["project_id"] is None

    # delete
    r = client.delete(f"/conversations/{ids['engineer']}", headers=_hdr("alice"))
    assert r.status_code == 200
    r = client.get(f"/conversations/{ids['engineer']}", headers=_hdr("alice"))
    assert r.status_code == 404


def test_user_isolation():
    pid = client.post("/projects", headers=_hdr("alice"), json={"name": "secret"}).json()["id"]
    client.post("/conversations", headers=_hdr("alice"), json={"persona": "analyst", "project_id": pid})
    # bob sees nothing
    assert client.get("/projects", headers=_hdr("bob")).json() == []
    assert client.get("/conversations", headers=_hdr("bob")).json() == []
    # bob cannot read alice's conversation
    assert client.get(f"/conversations/{pid}", headers=_hdr("bob")).status_code == 404


# ── Service-level: messages & history ─────────────────────────────────────────


def test_append_and_recent_history_ordering_and_cap():
    async def run():
        async with db.AsyncSessionLocal() as s:
            user = await cs.get_or_create_user(s, "carol")
            await s.commit()
            conv = await cs.create_conversation(s, user.id, persona="analyst")
            cid = conv["id"]
            for i in range(25):
                await cs.append_message(s, cid, "user", f"m{i}")
            hist = await cs.recent_history(s, cid, limit=20)
            first = await cs.first_user_message(s, cid)
            return hist, first

    hist, first = asyncio.run(run())
    assert len(hist) == 20           # capped
    assert hist[0]["content"] == "m5"   # oldest of the last 20, in chronological order
    assert hist[-1]["content"] == "m24"
    assert first == "m0"


# ── /chat/stream persistence + instruction injection + auto-title ─────────────


def test_chat_stream_persists_and_titles_and_injects_instructions(monkeypatch):
    captured = {}

    async def fake_stream(message, context_rule_id=None, history=None, mode="analyst",
                          allow_general=False, extra_context=None):
        captured["extra_context"] = extra_context
        captured["mode"] = mode
        captured["history"] = history
        yield f"data: {_json.dumps({'type': 'chunk', 'text': 'Hello '})}\n\n"
        yield f"data: {_json.dumps({'type': 'chunk', 'text': 'world'})}\n\n"
        yield f"data: {_json.dumps({'type': 'done', 'rule_id': 'TEST_1', 'suggested_followups': ['a']})}\n\n"

    async def fake_title(user_msg, assistant_msg=""):
        return "Mocked Title"

    import main as main_module
    monkeypatch.setattr(main_module, "stream_message", fake_stream)
    monkeypatch.setattr(openai_client, "generate_title_async", fake_title)

    # project with instructions + an engineer conversation in it
    pid = client.post(
        "/projects", headers=_hdr("dave"),
        json={"name": "P", "instructions": "Always mention DCC."},
    ).json()["id"]
    cid = client.post(
        "/conversations", headers=_hdr("dave"),
        json={"persona": "engineer", "project_id": pid},
    ).json()["id"]

    r = client.post(
        "/chat/stream", headers=_hdr("dave"),
        json={"message": "do the thing", "conversation_id": cid},
    )
    assert r.status_code == 200
    assert "world" in r.text

    # persona came from the conversation, instructions were injected
    assert captured["mode"] == "engineer"
    assert captured["extra_context"] == "Always mention DCC."

    # both turns persisted, assistant text accumulated, title generated
    detail = client.get(f"/conversations/{cid}", headers=_hdr("dave")).json()
    msgs = detail["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == "do the thing"
    assert msgs[1]["content"] == "Hello world"
    assert msgs[1]["rule_id"] == "TEST_1"
    assert detail["title"] == "Mocked Title"


def test_chat_stream_unknown_conversation_404(monkeypatch):
    async def fake_stream(*a, **k):
        yield f"data: {_json.dumps({'type': 'done', 'rule_id': None, 'suggested_followups': []})}\n\n"
        return

    import main as main_module
    monkeypatch.setattr(main_module, "stream_message", fake_stream)
    r = client.post(
        "/chat/stream", headers=_hdr("erin"),
        json={"message": "hi", "conversation_id": 99999},
    )
    assert r.status_code == 404
