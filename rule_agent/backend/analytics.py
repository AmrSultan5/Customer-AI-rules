"""
Analytics tracker — persists rule views, chat events, feedback, and token usage.

Backed by the shared SQLAlchemy database (Postgres in production, SQLite in dev/
tests) via the engines in `db`. All writes are fire-and-forget; failures are
silently absorbed so analytics never disrupts the main request path.

Public API (signatures unchanged from the previous SQLite implementation):
  async track_rule_view / track_chat_event / track_feedback / track_token_usage
  sync  track_token_usage_sync
  async get_dashboard_data
  estimate_cost_usd / _cost_rate
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select

import db
from models import ChatEvent, FeedbackEvent, RuleView, TokenEvent

log = logging.getLogger(__name__)


# ── Writes ───────────────────────────────────────────────────────────────────


async def track_rule_view(rule_id: str) -> None:
    try:
        async with db.AsyncSessionLocal() as session:
            session.add(RuleView(rule_id=rule_id.upper(), viewed_at=_now()))
            await session.commit()
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
        with db.SyncSessionLocal() as session:
            session.add(
                TokenEvent(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    model=model,
                    call_type=call_type,
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
                    occurred_at=_now(),
                )
            )
            await session.commit()
    except Exception as exc:
        log.debug("[analytics] track_token_usage suppressed: %s", exc)


async def track_chat_event(
    rule_id: str | None, intent: str | None, user_id: int | None = None
) -> None:
    try:
        async with db.AsyncSessionLocal() as session:
            session.add(
                ChatEvent(
                    rule_id=rule_id.upper() if rule_id else None,
                    intent=intent,
                    user_id=user_id,
                    occurred_at=_now(),
                )
            )
            await session.commit()
    except Exception as exc:
        log.debug("[analytics] track_chat_event suppressed: %s", exc)


async def track_feedback(
    rating: str, mode: str | None, rule_id: str | None, user_id: int | None = None
) -> None:
    try:
        async with db.AsyncSessionLocal() as session:
            session.add(
                FeedbackEvent(
                    rating=rating,
                    mode=mode,
                    rule_id=rule_id.upper() if rule_id else None,
                    user_id=user_id,
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
    try:
        now = _now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = now - timedelta(days=7)
        thirty_ago = now - timedelta(days=30)
        day_expr = func.date(RuleView.viewed_at)

        async with db.AsyncSessionLocal() as session:

            async def scalar(stmt) -> int:
                val = await session.scalar(stmt)
                return int(val or 0)

            total_views = await scalar(select(func.count()).select_from(RuleView))
            views_today = await scalar(
                select(func.count()).select_from(RuleView).where(RuleView.viewed_at >= today_start)
            )
            views_week = await scalar(
                select(func.count()).select_from(RuleView).where(RuleView.viewed_at >= week_ago)
            )
            unique_accessed = await scalar(
                select(func.count(func.distinct(RuleView.rule_id)))
            )
            chat_with_rule = await scalar(
                select(func.count()).select_from(ChatEvent).where(ChatEvent.rule_id.isnot(None))
            )

            total_tokens_used = await scalar(select(func.coalesce(func.sum(TokenEvent.total_tokens), 0)))
            total_prompt_tokens = await scalar(select(func.coalesce(func.sum(TokenEvent.prompt_tokens), 0)))
            total_completion_tokens = await scalar(select(func.coalesce(func.sum(TokenEvent.completion_tokens), 0)))

            # Top 15 most viewed rules
            top_rows = (await session.execute(
                select(RuleView.rule_id, func.count().label("views"))
                .group_by(RuleView.rule_id)
                .order_by(func.count().desc())
                .limit(15)
            )).all()

            # Daily activity — last 30 days
            daily_rows = (await session.execute(
                select(day_expr.label("day"), func.count().label("views"))
                .where(RuleView.viewed_at >= thirty_ago)
                .group_by(day_expr)
                .order_by(day_expr.asc())
            )).all()

            # Recent 10 views
            recent_rows = (await session.execute(
                select(RuleView.rule_id, RuleView.viewed_at)
                .order_by(RuleView.viewed_at.desc())
                .limit(10)
            )).all()

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

            # Top rules by unique-day engagement (breadth over last 30d)
            active_days_expr = func.count(func.distinct(day_expr))
            trending_rows = (await session.execute(
                select(RuleView.rule_id, active_days_expr.label("active_days"))
                .where(RuleView.viewed_at >= thirty_ago)
                .group_by(RuleView.rule_id)
                .order_by(active_days_expr.desc())
                .limit(5)
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
            "top_rules":          [{"rule_id": r.rule_id, "views": int(r.views)} for r in top_rows],
            "daily_activity":     [{"date": str(r.day), "views": int(r.views)} for r in daily_rows],
            "recent_views":       [
                {"rule_id": r.rule_id, "viewed_at": _iso(r.viewed_at)} for r in recent_rows
            ],
            "intent_distribution":[{"intent": r.intent, "count": int(r.cnt)} for r in intent_rows],
            "trending_rules":     [{"rule_id": r.rule_id, "active_days": int(r.active_days)} for r in trending_rows],
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


def _iso(val) -> str:
    """Render a datetime (or already-string) timestamp as an ISO string."""
    return val.isoformat() if hasattr(val, "isoformat") else str(val)
