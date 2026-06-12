"""
Analytics tracker — persists rule views, chat events, and token usage to SQLite.
All writes are fire-and-forget; failures are silently absorbed so analytics
never disrupts the main request path.
"""

import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite

log = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "data" / "analytics.db"
_INIT_LOCK = asyncio.Lock()
_DB_READY = False

_SCHEMA = """
    CREATE TABLE IF NOT EXISTS rule_views (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_id    TEXT NOT NULL,
        viewed_at  TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_rv_rule ON rule_views(rule_id);
    CREATE INDEX IF NOT EXISTS idx_rv_ts   ON rule_views(viewed_at);

    CREATE TABLE IF NOT EXISTS chat_events (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_id      TEXT,
        intent       TEXT,
        occurred_at  TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_ce_rule ON chat_events(rule_id);
    CREATE INDEX IF NOT EXISTS idx_ce_ts   ON chat_events(occurred_at);

    CREATE TABLE IF NOT EXISTS feedback_events (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        rating       TEXT NOT NULL,
        mode         TEXT,
        rule_id      TEXT,
        occurred_at  TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_fe_ts ON feedback_events(occurred_at);

    CREATE TABLE IF NOT EXISTS token_events (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        prompt_tokens     INTEGER NOT NULL DEFAULT 0,
        completion_tokens INTEGER NOT NULL DEFAULT 0,
        total_tokens      INTEGER NOT NULL DEFAULT 0,
        model             TEXT,
        call_type         TEXT,
        occurred_at       TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_te_ts ON token_events(occurred_at);
"""


async def _ensure_db() -> None:
    global _DB_READY
    if _DB_READY:
        return
    async with _INIT_LOCK:
        if _DB_READY:
            return
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.executescript(_SCHEMA)
            await db.commit()
        _DB_READY = True


def _ensure_db_sync() -> None:
    """Synchronous schema bootstrap used by sync callers (e.g. explanation_engine)."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(_SCHEMA)
        conn.commit()


async def track_rule_view(rule_id: str) -> None:
    try:
        await _ensure_db()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO rule_views (rule_id, viewed_at) VALUES (?, ?)",
                (rule_id.upper(), datetime.now(timezone.utc).isoformat()),
            )
            await db.commit()
    except Exception as exc:
        log.debug("[analytics] track_rule_view suppressed: %s", exc)


def track_token_usage_sync(
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    model: str = "",
    call_type: str = "",
) -> None:
    """Synchronous token write — safe to call from non-async code."""
    try:
        _ensure_db_sync()
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO token_events (prompt_tokens, completion_tokens, total_tokens, model, call_type, occurred_at) VALUES (?, ?, ?, ?, ?, ?)",
                (prompt_tokens, completion_tokens, total_tokens, model, call_type, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
    except Exception as exc:
        log.debug("[analytics] track_token_usage_sync suppressed: %s", exc)


async def track_token_usage(
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    model: str = "",
    call_type: str = "",
) -> None:
    """Async token write — safe to call from async code."""
    try:
        await _ensure_db()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO token_events (prompt_tokens, completion_tokens, total_tokens, model, call_type, occurred_at) VALUES (?, ?, ?, ?, ?, ?)",
                (prompt_tokens, completion_tokens, total_tokens, model, call_type, datetime.now(timezone.utc).isoformat()),
            )
            await db.commit()
    except Exception as exc:
        log.debug("[analytics] track_token_usage suppressed: %s", exc)


async def track_chat_event(rule_id: str | None, intent: str | None) -> None:
    try:
        await _ensure_db()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO chat_events (rule_id, intent, occurred_at) VALUES (?, ?, ?)",
                (
                    rule_id.upper() if rule_id else None,
                    intent,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            await db.commit()
    except Exception as exc:
        log.debug("[analytics] track_chat_event suppressed: %s", exc)


async def track_feedback(rating: str, mode: str | None, rule_id: str | None) -> None:
    try:
        await _ensure_db()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO feedback_events (rating, mode, rule_id, occurred_at) VALUES (?, ?, ?, ?)",
                (
                    rating,
                    mode,
                    rule_id.upper() if rule_id else None,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            await db.commit()
    except Exception as exc:
        log.debug("[analytics] track_feedback suppressed: %s", exc)


def _cost_rate(env_var: str) -> float | None:
    """Read a USD-per-1M-tokens rate from the environment; None if unset/invalid."""
    raw = os.environ.get(env_var, "").strip()
    if not raw:
        return None
    try:
        rate = float(raw)
        return rate if rate >= 0 else None
    except ValueError:
        log.warning("[analytics] %s is not a number: %r — cost estimate disabled", env_var, raw)
        return None


def estimate_cost_usd(prompt_tokens: int, completion_tokens: int) -> float | None:
    """Estimate LLM spend from configured per-1M-token rates.

    Rates are deployment-specific (Azure OpenAI pricing varies by region/model),
    so they are supplied via RULE_AGENT_PROMPT_COST_PER_1M and
    RULE_AGENT_COMPLETION_COST_PER_1M rather than hardcoded. Returns None when
    either rate is unconfigured, which hides the cost figure in the dashboard.
    """
    prompt_rate = _cost_rate("RULE_AGENT_PROMPT_COST_PER_1M")
    completion_rate = _cost_rate("RULE_AGENT_COMPLETION_COST_PER_1M")
    if prompt_rate is None or completion_rate is None:
        return None
    cost = (prompt_tokens / 1_000_000) * prompt_rate + (completion_tokens / 1_000_000) * completion_rate
    return round(cost, 4)


async def get_dashboard_data(total_rules: int) -> dict:
    try:
        await _ensure_db()
        now = datetime.now(timezone.utc)
        today_str      = now.date().isoformat()
        week_ago_str   = (now - timedelta(days=7)).isoformat()
        thirty_ago_str = (now - timedelta(days=30)).isoformat()

        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row

            async def scalar(sql, params=()):
                async with db.execute(sql, params) as cur:
                    row = await cur.fetchone()
                    return row[0] if row else 0

            async def rows(sql, params=()):
                async with db.execute(sql, params) as cur:
                    return await cur.fetchall()

            total_views      = await scalar("SELECT COUNT(*) FROM rule_views")
            views_today      = await scalar(
                "SELECT COUNT(*) FROM rule_views WHERE viewed_at >= ?", (today_str,)
            )
            views_week       = await scalar(
                "SELECT COUNT(*) FROM rule_views WHERE viewed_at >= ?", (week_ago_str,)
            )
            unique_accessed  = await scalar(
                "SELECT COUNT(DISTINCT rule_id) FROM rule_views"
            )
            chat_with_rule   = await scalar(
                "SELECT COUNT(*) FROM chat_events WHERE rule_id IS NOT NULL"
            )

            # Token usage totals
            total_tokens_used      = await scalar("SELECT COALESCE(SUM(total_tokens), 0)      FROM token_events")
            total_prompt_tokens    = await scalar("SELECT COALESCE(SUM(prompt_tokens), 0)     FROM token_events")
            total_completion_tokens= await scalar("SELECT COALESCE(SUM(completion_tokens), 0) FROM token_events")

            # Top 15 most viewed rules
            top_raw = await rows("""
                SELECT rule_id, COUNT(*) AS views
                FROM rule_views
                GROUP BY rule_id
                ORDER BY views DESC
                LIMIT 15
            """)

            # Daily activity — last 30 days
            daily_raw = await rows("""
                SELECT DATE(viewed_at) AS day, COUNT(*) AS views
                FROM rule_views
                WHERE viewed_at >= ?
                GROUP BY day
                ORDER BY day ASC
            """, (thirty_ago_str,))

            # Recent 10 views
            recent_raw = await rows("""
                SELECT rule_id, viewed_at
                FROM rule_views
                ORDER BY viewed_at DESC
                LIMIT 10
            """)

            # Intent distribution
            intent_raw = await rows("""
                SELECT intent, COUNT(*) AS cnt
                FROM chat_events
                WHERE intent IS NOT NULL
                GROUP BY intent
                ORDER BY cnt DESC
                LIMIT 10
            """)

            # Answer feedback (thumbs up/down on persona/analyst replies)
            feedback_up   = await scalar("SELECT COUNT(*) FROM feedback_events WHERE rating = 'up'")
            feedback_down = await scalar("SELECT COUNT(*) FROM feedback_events WHERE rating = 'down'")
            feedback_mode_raw = await rows("""
                SELECT mode, rating, COUNT(*) AS cnt
                FROM feedback_events
                WHERE mode IS NOT NULL
                GROUP BY mode, rating
            """)

            # Top rules by unique-day engagement (breadth over last 30d)
            trending_raw = await rows("""
                SELECT rule_id, COUNT(DISTINCT DATE(viewed_at)) AS active_days
                FROM rule_views
                WHERE viewed_at >= ?
                GROUP BY rule_id
                ORDER BY active_days DESC
                LIMIT 5
            """, (thirty_ago_str,))

            # Rules generating the most negative answer feedback
            downvoted_raw = await rows("""
                SELECT rule_id,
                       SUM(CASE WHEN rating = 'down' THEN 1 ELSE 0 END) AS down,
                       SUM(CASE WHEN rating = 'up'   THEN 1 ELSE 0 END) AS up
                FROM feedback_events
                WHERE rule_id IS NOT NULL
                GROUP BY rule_id
                HAVING down > 0
                ORDER BY down DESC, up ASC
                LIMIT 10
            """)

            # Token usage split by call type (explain_rule / chat / stream)
            tokens_by_type_raw = await rows("""
                SELECT COALESCE(NULLIF(call_type, ''), 'other') AS call_type,
                       COUNT(*)                          AS calls,
                       COALESCE(SUM(prompt_tokens), 0)     AS prompt_tokens,
                       COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                       COALESCE(SUM(total_tokens), 0)      AS total_tokens
                FROM token_events
                GROUP BY 1
                ORDER BY total_tokens DESC
            """)

        coverage_pct = round(unique_accessed / total_rules * 100, 1) if total_rules > 0 else 0

        return {
            "overview": {
                "total_rules":           total_rules,
                "total_views":           total_views,
                "unique_rules_accessed": unique_accessed,
                "coverage_pct":          coverage_pct,
                "views_today":           views_today,
                "views_this_week":       views_week,
                "chat_queries_with_rule":  chat_with_rule,
                "total_tokens_used":       total_tokens_used,
                "total_prompt_tokens":     total_prompt_tokens,
                "total_completion_tokens": total_completion_tokens,
                "estimated_cost_usd":      estimate_cost_usd(total_prompt_tokens, total_completion_tokens),
            },
            "top_rules":          [{"rule_id": r["rule_id"], "views": r["views"]} for r in top_raw],
            "daily_activity":     [{"date": r["day"],    "views": r["views"]} for r in daily_raw],
            "recent_views":       [{"rule_id": r["rule_id"], "viewed_at": r["viewed_at"]} for r in recent_raw],
            "intent_distribution":[{"intent": r["intent"],  "count": r["cnt"]} for r in intent_raw],
            "trending_rules":     [{"rule_id": r["rule_id"], "active_days": r["active_days"]} for r in trending_raw],
            "downvoted_rules":    [{"rule_id": r["rule_id"], "down": r["down"], "up": r["up"]} for r in downvoted_raw],
            "tokens_by_call_type": [
                {
                    "call_type":         r["call_type"],
                    "calls":             r["calls"],
                    "prompt_tokens":     r["prompt_tokens"],
                    "completion_tokens": r["completion_tokens"],
                    "total_tokens":      r["total_tokens"],
                }
                for r in tokens_by_type_raw
            ],
            "feedback": {
                "up":      feedback_up,
                "down":    feedback_down,
                "by_mode": [
                    {"mode": r["mode"], "rating": r["rating"], "count": r["cnt"]}
                    for r in feedback_mode_raw
                ],
            },
        }

    except Exception as exc:
        log.warning("[analytics] get_dashboard_data failed: %s", exc)
        return {
            "overview": {
                "total_rules": total_rules,
                "total_views": 0, "unique_rules_accessed": 0, "coverage_pct": 0,
                "views_today": 0, "views_this_week": 0, "chat_queries_with_rule": 0,
                "total_tokens_used": 0, "total_prompt_tokens": 0, "total_completion_tokens": 0,
                "estimated_cost_usd": None,
            },
            "top_rules": [], "daily_activity": [], "recent_views": [],
            "intent_distribution": [], "trending_rules": [],
            "downvoted_rules": [], "tokens_by_call_type": [],
            "feedback": {"up": 0, "down": 0, "by_mode": []},
        }
