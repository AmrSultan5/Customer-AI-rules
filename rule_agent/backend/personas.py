"""
Single source of truth for chat personas and which ones are admin-enabled.

Three chat personas exist: analyst, engineer (Data Engineer), pm (Project
Manager). Only `analyst` is enabled by default; an admin flips the others on
via PUT /admin/personas. The enabled set is stored as a single AppSetting row
(key=SETTING_KEY, value={"ids": [...]}) so it survives restarts without a
dedicated table. `analyst` can never be disabled — it is always force-included.
"""
from typing import Iterable, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from models import AppSetting

PersonaId = Literal["analyst", "engineer", "pm"]

PERSONAS = [
    {
        "id": "analyst",
        "label": "Analyst",
        "description": "Answers questions about existing Customer data-quality rules.",
    },
    {
        "id": "engineer",
        "label": "Data Engineer",
        "description": "Helps implement or change rules and data pipelines.",
    },
    {
        "id": "pm",
        "label": "Project Manager",
        "description": "Sizes and scopes rule and pipeline change requests.",
    },
]
PERSONA_IDS = frozenset(p["id"] for p in PERSONAS)
ALWAYS_ON: PersonaId = "analyst"
DEFAULT_ENABLED: list[str] = ["analyst"]
SETTING_KEY = "enabled_personas"


def _ordered(ids: Iterable[str]) -> list[str]:
    """Return `ids` in PERSONAS declaration order (deterministic)."""
    idset = set(ids)
    return [p["id"] for p in PERSONAS if p["id"] in idset]


async def get_enabled_personas(session: AsyncSession) -> list[str]:
    """Read the enabled-persona set, defaulting safely on any bad/missing data.

    Row absent, value not a dict, "ids" missing/not-a-list, or an empty/fully
    invalid list all fall back to DEFAULT_ENABLED. Stored ids are always
    filtered down to PERSONA_IDS, and ALWAYS_ON is always present in the
    result regardless of what was stored.
    """
    row = await session.get(AppSetting, SETTING_KEY)
    ids: list[str] = []
    if row is not None and isinstance(row.value, dict):
        raw = row.value.get("ids")
        if isinstance(raw, list):
            ids = [i for i in raw if isinstance(i, str) and i in PERSONA_IDS]
    if not ids:
        ids = list(DEFAULT_ENABLED)
    return _ordered(set(ids) | {ALWAYS_ON})


async def set_enabled_personas(session: AsyncSession, ids: Iterable[str]) -> list[str]:
    """Filter to known persona ids, force-include ALWAYS_ON, persist, and return."""
    normalized = _ordered((set(ids) & PERSONA_IDS) | {ALWAYS_ON})
    row = await session.get(AppSetting, SETTING_KEY)
    if row is None:
        row = AppSetting(key=SETTING_KEY, value={"ids": normalized})
        session.add(row)
    else:
        row.value = {"ids": normalized}
    await session.commit()
    return normalized
