"""
Analytics tracker — persists chat events, feedback, and token usage.

Backed by the shared SQLAlchemy database (Postgres in production, SQLite in dev/
tests) via the engines in `db`. All writes are fire-and-forget; failures are
silently absorbed so analytics never disrupts the main request path.

Public API (signatures back-compat — new params are optional/defaulted):
  async track_chat_event / track_feedback / track_token_usage
  sync  track_token_usage_sync
  async get_dashboard_data
  estimate_cost_usd / _cost_rate

Multi-KB (Phase 4): every write accepts an optional `knowledge_base_id`,
defaulting to `config.settings.active_kb`, and persists it on the row. Not
yet threaded from the HTTP layer (Phase 5) — callers that don't pass it get
the active KB.

`track_rule_view` and the RuleView-backed dashboard stats (total/unique/daily
views, top/trending rules) are removed as of Phase 4 — rule-view tracking had
already been dead since the rule card was dropped in Phase 1. The
`rule_views` table itself is left in place (unused) rather than dropped.
"""

import logging
import os
from datetime import datetime, timezone

from sqlalchemy import case, func, select

import db
from config import settings
from models import ChatEvent, FeedbackEvent, TokenEvent

log = logging.getLogger(__name__)


# ── Writes ───────────────────────────────────────────────────────────────────


def track_token_usage_sync(
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    model: str = "",
    call_type: str = "",
    knowledge_base_id: str | None = None,
) -> None:
    """Synchronous token write — safe to call from non-async code."""
    try:
        with db.SyncSessionLocal() as session:
            session.add(
                TokenEvent(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    model=model,
                    call_type=call_type,
                    knowledge_base_id=knowledge_base_id or settings.active_kb,
                    occurred_at=_now(),
                )
            )
            session.commit()
    except Exception as exc:
        log.debug("[analytics] track_token_usage_sync suppressed: %s", exc)


async def track_token_usage(
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    model: str = "",
    call_type: str = "",
    knowledge_base_id: str | None = None,
) -> None:
    """Async token write — safe to call from async code."""
    try:
        async with db.AsyncSessionLocal() as session:
            session.add(
                TokenEvent(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    model=model,
                    call_type=call_type,
                    knowledge_base_id=knowledge_base_id or settings.active_kb,
                    occurred_at=_now(),
                )
            )
            await session.commit()
    except Exception as exc:
        log.debug("[analytics] track_token_usage suppressed: %s", exc)


async def track_chat_event(
    rule_id: str | None,
    intent: str | None,
    user_id: int | None = None,
    knowledge_base_id: str | None = None,
) -> None:
    try:
        async with db.AsyncSessionLocal() as session:
            session.add(
                ChatEvent(
                    rule_id=rule_id.upper() if rule_id else None,
                    intent=intent,
                    user_id=user_id,
                    knowledge_base_id=knowledge_base_id or settings.active_kb,
                    occurred_at=_now(),
                )
            )
            await session.commit()
    except Exception as exc:
        log.debug("[analytics] track_chat_event suppressed: %s", exc)


async def track_feedback(
    rating: str,
    mode: str | None,
    rule_id: str | None,
    user_id: int | None = None,
    knowledge_base_id: str | None = None,
) -> None:
    try:
        async with db.AsyncSessionLocal() as session:
            session.add(
                FeedbackEvent(
                    rating=rating,
                    mode=mode,
                    rule_id=rule_id.upper() if rule_id else None,
                    user_id=user_id,
                    knowledge_base_id=knowledge_base_id or settings.active_kb,
                    occurred_at=_now(),
                )
            )
            await session.commit()
    except Exception as exc:
        log.debug("[analytics] track_feedback suppressed: %s", exc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Cost estimate (unchanged behavior) ───────────────────────────────────────


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

    Rates are deployment-specific, so they are supplied via
    RULE_AGENT_PROMPT_COST_PER_1M and RULE_AGENT_COMPLETION_COST_PER_1M rather
    than hardcoded. Returns None when either rate is unconfigured, which hides
    the cost figure in the dashboard.
    """
    prompt_rate = _cost_rate("RULE_AGENT_PROMPT_COST_PER_1M")
    completion_rate = _cost_rate("RULE_AGENT_COMPLETION_COST_PER_1M")
    if prompt_rate is None or completion_rate is None:
        return None
    cost = (prompt_tokens / 1_000_000) * prompt_rate + (completion_tokens / 1_000_000) * completion_rate
    return round(cost, 4)


# ── Dashboard aggregation ────────────────────────────────────────────────────


async def get_dashboard_data(total_rules: int) -> dict:
    """Aggregate ChatEvent/FeedbackEvent/TokenEvent stats.

    The RuleView-backed stats (total/unique/daily views, top/trending rules,
    recent views, coverage_pct) were dropped in Phase 4 along with the
    RuleView model — rule-view tracking died with the rule card in Phase 1.
    No route currently calls this (the admin dashboard route was removed in
    Phase 1 too); kept for its aggregation logic and test coverage.
    """
    try:
        async with db.AsyncSessionLocal() as session:

            async def scalar(stmt) -> int:
                val = await session.scalar(stmt)
                return int(val or 0)

            chat_with_rule = await scalar(
                select(func.count()).select_from(ChatEvent).where(ChatEvent.rule_id.isnot(None))
            )

            total_tokens_used = await scalar(select(func.coalesce(func.sum(TokenEvent.total_tokens), 0)))
            total_prompt_tokens = await scalar(select(func.coalesce(func.sum(TokenEvent.prompt_tokens), 0)))
            total_completion_tokens = await scalar(select(func.coalesce(func.sum(TokenEvent.completion_tokens), 0)))

            # Intent distribution
            intent_rows = (await session.execute(
                select(ChatEvent.intent, func.count().label("cnt"))
                .where(ChatEvent.intent.isnot(None))
                .group_by(ChatEvent.intent)
                .order_by(func.count().desc())
                .limit(10)
            )).all()

            # Answer feedback (thumbs up/down)
            feedback_up = await scalar(
                select(func.count()).select_from(FeedbackEvent).where(FeedbackEvent.rating == "up")
            )
            feedback_down = await scalar(
                select(func.count()).select_from(FeedbackEvent).where(FeedbackEvent.rating == "down")
            )
            feedback_mode_rows = (await session.execute(
                select(FeedbackEvent.mode, FeedbackEvent.rating, func.count().label("cnt"))
                .where(FeedbackEvent.mode.isnot(None))
                .group_by(FeedbackEvent.mode, FeedbackEvent.rating)
            )).all()

            # Rules generating the most negative feedback
            down_sum = func.sum(case((FeedbackEvent.rating == "down", 1), else_=0))
            up_sum = func.sum(case((FeedbackEvent.rating == "up", 1), else_=0))
            downvoted_rows = (await session.execute(
                select(FeedbackEvent.rule_id, down_sum.label("down"), up_sum.label("up"))
                .where(FeedbackEvent.rule_id.isnot(None))
                .group_by(FeedbackEvent.rule_id)
                .having(down_sum > 0)
                .order_by(down_sum.desc(), up_sum.asc())
                .limit(10)
            )).all()

            # Token usage split by call type
            call_type_expr = func.coalesce(func.nullif(TokenEvent.call_type, ""), "other")
            total_tokens_sum = func.coalesce(func.sum(TokenEvent.total_tokens), 0)
            tokens_by_type_rows = (await session.execute(
                select(
                    call_type_expr.label("call_type"),
                    func.count().label("calls"),
                    func.coalesce(func.sum(TokenEvent.prompt_tokens), 0).label("prompt_tokens"),
                    func.coalesce(func.sum(TokenEvent.completion_tokens), 0).label("completion_tokens"),
                    total_tokens_sum.label("total_tokens"),
                )
                .group_by(call_type_expr)
                .order_by(total_tokens_sum.desc())
            )).all()

        return {
            "overview": {
                "total_rules":             total_rules,
                "chat_queries_with_rule":  chat_with_rule,
                "total_tokens_used":       total_tokens_used,
                "total_prompt_tokens":     total_prompt_tokens,
                "total_completion_tokens": total_completion_tokens,
                "estimated_cost_usd":      estimate_cost_usd(total_prompt_tokens, total_completion_tokens),
            },
            "intent_distribution":[{"intent": r.intent, "count": int(r.cnt)} for r in intent_rows],
            "downvoted_rules":    [
                {"rule_id": r.rule_id, "down": int(r.down or 0), "up": int(r.up or 0)} for r in downvoted_rows
            ],
            "tokens_by_call_type": [
                {
                    "call_type":         r.call_type,
                    "calls":             int(r.calls),
                    "prompt_tokens":     int(r.prompt_tokens),
                    "completion_tokens": int(r.completion_tokens),
                    "total_tokens":      int(r.total_tokens),
                }
                for r in tokens_by_type_rows
            ],
            "feedback": {
                "up":      feedback_up,
                "down":    feedback_down,
                "by_mode": [
                    {"mode": r.mode, "rating": r.rating, "count": int(r.cnt)}
                    for r in feedback_mode_rows
                ],
            },
        }

    except Exception as exc:
        log.warning("[analytics] get_dashboard_data failed: %s", exc)
        return {
            "overview": {
                "total_rules": total_rules,
                "chat_queries_with_rule": 0,
                "total_tokens_used": 0, "total_prompt_tokens": 0, "total_completion_tokens": 0,
                "estimated_cost_usd": None,
            },
            "intent_distribution": [],
            "downvoted_rules": [], "tokens_by_call_type": [],
            "feedback": {"up": 0, "down": 0, "by_mode": []},
        }
