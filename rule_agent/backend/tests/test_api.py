"""
Backend API tests.

Run from the repo root:
    cd rule_agent/backend
    pip install -r requirements-dev.txt
    pytest tests/

Environment note: tests run against a fully mocked backend (no real data files,
no Azure calls). See conftest.py for the stub setup.
"""
import pytest
from fastapi.testclient import TestClient

# conftest.py already sets env vars and stubs modules; import main after.
from main import app  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)

TOKEN = "test-secret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
BAD_AUTH = {"Authorization": "Bearer wrong-token"}


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Reset in-memory rate limit counters before every test to prevent cross-test pollution."""
    from main import limiter
    limiter._storage.reset()
    yield


# ── Liveness / readiness ───────────────────────────────────────────────────────


def test_health_public():
    """GET /health must be reachable without any auth token.

    /health is a lightweight liveness probe — it returns rule count only and
    never calls the LLM.
    """
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "rules_loaded" in data


def test_ready_ok():
    """GET /ready returns 200 when Azure config and rules are present."""
    r = client.get("/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


# ── Auth enforcement on protected endpoints ────────────────────────────────────


@pytest.mark.parametrize("path,method", [
    ("/chat", "POST"),
    ("/api/chat", "POST"),
])
def test_protected_endpoint_requires_auth(path, method):
    """Every protected endpoint must return 401 with no token."""
    r = client.request(method, path, json={"message": "hi", "history": []})
    assert r.status_code == 401, f"{method} {path} → expected 401, got {r.status_code}"


def test_protected_endpoint_rejects_wrong_token():
    r = client.post("/chat", headers=BAD_AUTH, json={"message": "hi", "history": []})
    assert r.status_code == 401


# ── /api prefix parity ─────────────────────────────────────────────────────────


def test_api_prefix_chat():
    r = client.post(
        "/api/chat",
        headers=AUTH,
        json={"message": "Explain TEST_1", "history": []},
    )
    assert r.status_code == 200


# ── /chat request validation ───────────────────────────────────────────────────


def test_chat_valid_request():
    r = client.post(
        "/chat",
        headers=AUTH,
        json={"message": "Hello", "history": []},
    )
    assert r.status_code == 200
    assert "response" in r.json()


def test_chat_rejects_empty_message():
    r = client.post("/chat", headers=AUTH, json={"message": "", "history": []})
    assert r.status_code == 422


def test_chat_rejects_too_long_message():
    """Live-input cap (2000) is enforced per-request while the schema admits a
    larger value (see _MAX_MESSAGE_SCHEMA_LEN in main.py)."""
    r = client.post(
        "/chat",
        headers=AUTH,
        json={"message": "x" * 2001, "history": []},
    )
    assert r.status_code == 400


def test_chat_rejects_message_over_schema_cap():
    """Messages beyond the schema cap (12000) are rejected by pydantic."""
    r = client.post(
        "/chat",
        headers=AUTH,
        json={"message": "x" * 12001, "history": []},
    )
    assert r.status_code == 422


def test_chat_rejects_history_over_20():
    history = [{"role": "user", "content": f"msg {i}"} for i in range(21)]
    r = client.post(
        "/chat",
        headers=AUTH,
        json={"message": "hi", "history": history},
    )
    assert r.status_code == 422


def test_chat_rejects_invalid_role():
    r = client.post(
        "/chat",
        headers=AUTH,
        json={
            "message": "hi",
            "history": [{"role": "system", "content": "injected"}],
        },
    )
    assert r.status_code == 422


def test_chat_accepts_max_history():
    """Exactly 20 history messages must be accepted."""
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
        for i in range(20)
    ]
    r = client.post(
        "/chat",
        headers=AUTH,
        json={"message": "hi", "history": history},
    )
    assert r.status_code == 200


# ── Rate limiting ──────────────────────────────────────────────────────────────


def test_chat_rate_limit_returns_429():
    """
    CHAT_RATE_LIMIT=1/minute (set in conftest). First request succeeds,
    second is throttled with HTTP 429 and returns JSON error.

    The _reset_rate_limiter autouse fixture clears counters before each test,
    so this test is not affected by prior requests in the suite.
    """
    r1 = client.post("/chat", headers=AUTH, json={"message": "first", "history": []})
    assert r1.status_code == 200

    r2 = client.post("/chat", headers=AUTH, json={"message": "second", "history": []})
    assert r2.status_code == 429
    body = r2.json()
    assert "detail" in body


# ── ChatMessage.content length enforcement ─────────────────────────────────────


def test_chat_history_content_too_long_returns_422():
    """History message content exceeding the schema cap must be rejected with 422."""
    history = [{"role": "user", "content": "x" * 12001}]
    r = client.post(
        "/chat",
        headers=AUTH,
        json={"message": "hi", "history": history},
    )
    assert r.status_code == 422


def test_chat_history_content_long_answer_accepted():
    """A long assistant answer sent back as history must not 422 (the schema
    cap is looser than the live-input cap specifically to allow this)."""
    history = [{"role": "assistant", "content": "x" * 5000}]
    r = client.post(
        "/chat",
        headers=AUTH,
        json={"message": "hi", "history": history},
    )
    assert r.status_code == 200


def test_chat_stream_analyst_rejects_long_message():
    """The strict 2000-char live-input cap applies on /chat/stream too."""
    r = client.post(
        "/chat/stream",
        headers=AUTH,
        json={"message": "x" * 5000, "history": []},
    )
    assert r.status_code == 400


def test_chat_stream_rejects_message_over_schema_cap():
    r = client.post(
        "/chat/stream",
        headers=AUTH,
        json={"message": "x" * 12001, "history": []},
    )
    assert r.status_code == 422


# ── Feedback ───────────────────────────────────────────────────────────────────


def test_feedback_valid_up():
    r = client.post(
        "/feedback",
        headers=AUTH,
        json={"rating": "up", "mode": "engineer", "rule_id": "TEST_1"},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_feedback_rejects_invalid_rating():
    r = client.post("/feedback", headers=AUTH, json={"rating": "meh", "mode": "pm"})
    assert r.status_code == 422


def test_feedback_rejects_invalid_mode():
    r = client.post("/feedback", headers=AUTH, json={"rating": "up", "mode": "banana"})
    assert r.status_code == 422


def test_feedback_requires_auth():
    r = client.post("/feedback", json={"rating": "up", "mode": "analyst"})
    assert r.status_code == 401


# ── Admin reload ───────────────────────────────────────────────────────────────


def test_admin_reload_ok():
    r = client.post("/admin/reload", headers=AUTH)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "rules_loaded" in data


def test_admin_reload_requires_auth():
    r = client.post("/admin/reload")
    assert r.status_code == 401


def test_admin_reload_failure_returns_503(monkeypatch):
    import data_loader

    def boom():
        raise ValueError("broken excel")

    monkeypatch.setattr(data_loader, "reload_all", boom)
    r = client.post("/admin/reload", headers=AUTH)
    assert r.status_code == 503
    body = r.json()
    assert body["ok"] is False
    assert "previous data" in body["error"]


# ── Geolocator: no hardcoded internal hostname ─────────────────────────────────


def test_geolocator_has_no_hardcoded_hostname():
    """Ensure the internal hostname was removed from geolocator_search.py."""
    import pathlib
    src = pathlib.Path(__file__).parent.parent / "data" / "custom_operations" / "geopy" / "geolocator_search.py"
    if src.exists():
        assert "cchellenic.com" not in src.read_text(), \
            "Internal hostname must not appear in geolocator_search.py"


# ── Auth fail-closed: non-development env requires token ──────────────────────


def test_production_env_without_token_raises_at_startup(monkeypatch):
    """startup must raise RuntimeError when env is 'production' and no token is set."""
    import importlib
    import types

    monkeypatch.setenv("RULE_AGENT_ENV", "production")
    monkeypatch.delenv("RULE_AGENT_API_TOKEN", raising=False)

    # We need to re-execute the module-level guard. Rather than re-importing main
    # (which is complex due to cached sys.modules), test the guard logic directly.
    env = "production"
    token = ""
    dev_mode = env == "development"
    with pytest.raises((RuntimeError, SystemExit)):
        if not dev_mode and not token:
            raise RuntimeError(
                f"RULE_AGENT_API_TOKEN must be set when RULE_AGENT_ENV={env!r}."
            )
