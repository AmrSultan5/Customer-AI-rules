"""
Analytics unit tests — exercise the SQLite tracker and dashboard aggregation
against a temporary database (no app server, no LLM calls).
"""
import asyncio

import pytest

import analytics

EXPECTED_TOP_LEVEL_KEYS = {
    "overview", "top_rules", "daily_activity", "recent_views",
    "intent_distribution", "trending_rules", "downvoted_rules",
    "tokens_by_call_type", "feedback",
}


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Point the analytics module at an empty temporary database."""
    monkeypatch.setattr(analytics, "DB_PATH", tmp_path / "analytics.db")
    monkeypatch.setattr(analytics, "_DB_READY", False)


def dashboard(total_rules=2):
    return asyncio.run(analytics.get_dashboard_data(total_rules))


# ── Dashboard shape ────────────────────────────────────────────────────────────


def test_empty_dashboard_shape(fresh_db, monkeypatch):
    monkeypatch.delenv("RULE_AGENT_PROMPT_COST_PER_1M", raising=False)
    monkeypatch.delenv("RULE_AGENT_COMPLETION_COST_PER_1M", raising=False)
    data = dashboard()
    assert set(data.keys()) == EXPECTED_TOP_LEVEL_KEYS
    ov = data["overview"]
    assert ov["total_rules"] == 2
    assert ov["total_views"] == 0
    assert ov["estimated_cost_usd"] is None  # cost rates not configured
    assert data["downvoted_rules"] == []
    assert data["tokens_by_call_type"] == []


def test_rule_views_aggregation(fresh_db):
    async def run():
        await analytics.track_rule_view("rule_a")
        await analytics.track_rule_view("rule_a")
        await analytics.track_rule_view("rule_b")
        return await analytics.get_dashboard_data(2)

    data = asyncio.run(run())
    ov = data["overview"]
    assert ov["total_views"] == 3
    assert ov["unique_rules_accessed"] == 2
    assert ov["coverage_pct"] == 100.0
    assert data["top_rules"][0] == {"rule_id": "RULE_A", "views": 2}
    assert len(data["daily_activity"]) == 1
    assert len(data["recent_views"]) == 3
    # Both rules were viewed today → 1 active day each
    assert {r["rule_id"]: r["active_days"] for r in data["trending_rules"]} == {
        "RULE_A": 1, "RULE_B": 1,
    }


# ── Feedback / downvoted rules ────────────────────────────────────────────────


def test_downvoted_rules_aggregation(fresh_db):
    async def run():
        await analytics.track_feedback("down", "analyst", "rule_a")
        await analytics.track_feedback("down", "analyst", "rule_a")
        await analytics.track_feedback("up", "engineer", "rule_a")
        await analytics.track_feedback("up", "analyst", "rule_b")  # up-only → excluded
        await analytics.track_feedback("down", "pm", None)         # no rule → excluded
        return await analytics.get_dashboard_data(2)

    data = asyncio.run(run())
    assert data["downvoted_rules"] == [{"rule_id": "RULE_A", "down": 2, "up": 1}]
    assert data["feedback"]["up"] == 2
    assert data["feedback"]["down"] == 3
    by_mode = {(r["mode"], r["rating"]): r["count"] for r in data["feedback"]["by_mode"]}
    assert by_mode[("analyst", "down")] == 2
    assert by_mode[("engineer", "up")] == 1


# ── Token usage by call type ──────────────────────────────────────────────────


def test_tokens_by_call_type(fresh_db):
    async def run():
        await analytics.track_token_usage(100, 50, 150, "claude-sonnet-4-6", "chat")
        await analytics.track_token_usage(200, 100, 300, "claude-sonnet-4-6", "chat")
        await analytics.track_token_usage(1000, 400, 1400, "claude-sonnet-4-6", "explain_rule")
        await analytics.track_token_usage(10, 5, 15, "claude-sonnet-4-6", "")  # blank → "other"
        return await analytics.get_dashboard_data(2)

    data = asyncio.run(run())
    rows = {r["call_type"]: r for r in data["tokens_by_call_type"]}
    assert rows["chat"] == {
        "call_type": "chat", "calls": 2,
        "prompt_tokens": 300, "completion_tokens": 150, "total_tokens": 450,
    }
    assert rows["explain_rule"]["total_tokens"] == 1400
    assert rows["other"]["calls"] == 1
    # Ordered by total tokens descending
    totals = [r["total_tokens"] for r in data["tokens_by_call_type"]]
    assert totals == sorted(totals, reverse=True)
    assert data["overview"]["total_tokens_used"] == 1865


# ── Cost estimate ─────────────────────────────────────────────────────────────


def test_cost_estimate_disabled_when_unconfigured(monkeypatch):
    monkeypatch.delenv("RULE_AGENT_PROMPT_COST_PER_1M", raising=False)
    monkeypatch.delenv("RULE_AGENT_COMPLETION_COST_PER_1M", raising=False)
    assert analytics.estimate_cost_usd(1_000_000, 1_000_000) is None


def test_cost_estimate_requires_both_rates(monkeypatch):
    monkeypatch.setenv("RULE_AGENT_PROMPT_COST_PER_1M", "2.5")
    monkeypatch.delenv("RULE_AGENT_COMPLETION_COST_PER_1M", raising=False)
    assert analytics.estimate_cost_usd(1_000_000, 1_000_000) is None


def test_cost_estimate_math(monkeypatch):
    monkeypatch.setenv("RULE_AGENT_PROMPT_COST_PER_1M", "2.50")
    monkeypatch.setenv("RULE_AGENT_COMPLETION_COST_PER_1M", "10")
    # 2M prompt → $5.00; 500K completion → $5.00
    assert analytics.estimate_cost_usd(2_000_000, 500_000) == 10.0


@pytest.mark.parametrize("bad", ["abc", "-1", " "])
def test_cost_estimate_rejects_invalid_rate(monkeypatch, bad):
    monkeypatch.setenv("RULE_AGENT_PROMPT_COST_PER_1M", bad)
    monkeypatch.setenv("RULE_AGENT_COMPLETION_COST_PER_1M", "10")
    assert analytics.estimate_cost_usd(1_000_000, 1_000_000) is None


def test_cost_appears_in_overview(fresh_db, monkeypatch):
    monkeypatch.setenv("RULE_AGENT_PROMPT_COST_PER_1M", "1")
    monkeypatch.setenv("RULE_AGENT_COMPLETION_COST_PER_1M", "1")

    async def run():
        await analytics.track_token_usage(500_000, 500_000, 1_000_000, "claude-sonnet-4-6", "chat")
        return await analytics.get_dashboard_data(2)

    data = asyncio.run(run())
    assert data["overview"]["estimated_cost_usd"] == 1.0
