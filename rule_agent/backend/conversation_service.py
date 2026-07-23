"""
CRUD helpers for the chat workspace (users, projects, conversations, messages).

All functions take an AsyncSession and operate on the ORM models. Route handlers
in `main.py` are thin wrappers over these. Ownership is always enforced by
filtering on user_id so one user can never read or mutate another's data.

Multi-KB (Phase 4): conversations/messages carry a `knowledge_base_id`, not
yet exposed through the HTTP request/response schemas (Phase 5) — every
function here defaults it to `config.settings.active_kb` so current callers
keep working unchanged.
"""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import Conversation, KnowledgeBase, Message, Project, User

_VALID_PERSONAS = {"analyst", "engineer", "pm"}
_HISTORY_LIMIT = 20


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Users ────────────────────────────────────────────────────────────────────


async def get_or_create_user(session: AsyncSession, username: str) -> User:
    username = username.strip()
    user = await session.scalar(select(User).where(User.username == username))
    if user is None:
        user = User(username=username)
        session.add(user)
        await session.flush()
    return user


# ── Projects ─────────────────────────────────────────────────────────────────


async def list_projects(session: AsyncSession, user_id: int) -> list[dict]:
    rows = (await session.execute(
        select(Project).where(Project.user_id == user_id).order_by(Project.created_at.asc())
    )).scalars().all()
    return [_project_dict(p) for p in rows]


async def create_project(session: AsyncSession, user_id: int, name: str, instructions: str | None = None) -> dict:
    project = Project(user_id=user_id, name=name.strip() or "Untitled project", instructions=instructions)
    session.add(project)
    await session.commit()
    return _project_dict(project)


async def get_project(session: AsyncSession, project_id: int, user_id: int) -> Project | None:
    return await session.scalar(
        select(Project).where(Project.id == project_id, Project.user_id == user_id)
    )


async def update_project(
    session: AsyncSession,
    project_id: int,
    user_id: int,
    name: str | None = None,
    instructions: str | None = None,
) -> dict | None:
    project = await get_project(session, project_id, user_id)
    if project is None:
        return None
    if name is not None:
        project.name = name.strip() or project.name
    if instructions is not None:
        project.instructions = instructions
    await session.commit()
    return _project_dict(project)


async def delete_project(session: AsyncSession, project_id: int, user_id: int) -> bool:
    project = await get_project(session, project_id, user_id)
    if project is None:
        return False
    await session.delete(project)
    await session.commit()
    return True


async def project_instructions(session: AsyncSession, project_id: int) -> str | None:
    """Return the standing-instructions string for a project (for chat injection)."""
    instr = await session.scalar(select(Project.instructions).where(Project.id == project_id))
    instr = (instr or "").strip()
    return instr or None


# ── Conversations ────────────────────────────────────────────────────────────


async def list_conversations(
    session: AsyncSession,
    user_id: int,
    project_id: int | None = None,
    persona: str | None = None,
) -> list[dict]:
    stmt = select(Conversation).where(Conversation.user_id == user_id)
    if project_id is not None:
        stmt = stmt.where(Conversation.project_id == project_id)
    if persona is not None:
        stmt = stmt.where(Conversation.persona == persona)
    stmt = stmt.order_by(Conversation.updated_at.desc())
    rows = (await session.execute(stmt)).scalars().all()

    out: list[dict] = []
    for conv in rows:
        preview = await session.scalar(
            select(Message.content)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.id.desc())
            .limit(1)
        )
        d = _conversation_dict(conv)
        d["last_message"] = (preview or "")[:120]
        out.append(d)
    return out


async def create_conversation(
    session: AsyncSession,
    user_id: int,
    persona: str = "analyst",
    project_id: int | None = None,
    title: str | None = None,
    context_rule_id: str | None = None,
    knowledge_base_id: str | None = None,
) -> dict:
    if persona not in _VALID_PERSONAS:
        persona = "analyst"
    conv = Conversation(
        user_id=user_id,
        persona=persona,
        project_id=project_id,
        title=title,
        context_rule_id=context_rule_id,
        knowledge_base_id=knowledge_base_id or settings.active_kb,
    )
    session.add(conv)
    await session.commit()
    return _conversation_dict(conv)


async def get_conversation(session: AsyncSession, conversation_id: int, user_id: int) -> Conversation | None:
    return await session.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id
        )
    )


async def get_conversation_with_messages(
    session: AsyncSession, conversation_id: int, user_id: int
) -> dict | None:
    conv = await get_conversation(session, conversation_id, user_id)
    if conv is None:
        return None
    msgs = (await session.execute(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id.asc())
    )).scalars().all()
    d = _conversation_dict(conv)
    d["messages"] = [_message_dict(m) for m in msgs]
    return d


async def rename_conversation(session: AsyncSession, conversation_id: int, user_id: int, title: str) -> dict | None:
    conv = await get_conversation(session, conversation_id, user_id)
    if conv is None:
        return None
    conv.title = title.strip()[:200] or conv.title
    await session.commit()
    return _conversation_dict(conv)


async def move_conversation(
    session: AsyncSession, conversation_id: int, user_id: int, project_id: int | None
) -> dict | None:
    conv = await get_conversation(session, conversation_id, user_id)
    if conv is None:
        return None
    # Validate target project ownership (None = move out of any project).
    if project_id is not None:
        target = await get_project(session, project_id, user_id)
        if target is None:
            return None
    conv.project_id = project_id
    await session.commit()
    return _conversation_dict(conv)


async def delete_conversation(session: AsyncSession, conversation_id: int, user_id: int) -> bool:
    conv = await get_conversation(session, conversation_id, user_id)
    if conv is None:
        return False
    await session.delete(conv)
    await session.commit()
    return True


async def needs_title(session: AsyncSession, conversation_id: int) -> bool:
    """True if the conversation has no title yet (gate the title LLM call)."""
    title = await session.scalar(select(Conversation.title).where(Conversation.id == conversation_id))
    return not (title or "").strip()


async def set_title_if_empty(session: AsyncSession, conversation_id: int, title: str) -> None:
    conv = await session.get(Conversation, conversation_id)
    if conv is not None and not (conv.title or "").strip():
        conv.title = title.strip()[:200]
        await session.commit()


async def touch_conversation(session: AsyncSession, conversation_id: int) -> None:
    conv = await session.get(Conversation, conversation_id)
    if conv is not None:
        conv.updated_at = _utcnow()
        await session.commit()


# ── Messages ─────────────────────────────────────────────────────────────────


async def append_message(
    session: AsyncSession,
    conversation_id: int,
    role: str,
    content: str,
    rule_id: str | None = None,
    followups: list | None = None,
    knowledge_base_id: str | None = None,
) -> dict:
    # A message inherits its conversation's KB unless the caller overrides it
    # explicitly; falls back to the configured active KB if the conversation
    # cannot be found (should not normally happen — conversation_id is a FK).
    if knowledge_base_id is None:
        conv = await session.get(Conversation, conversation_id)
        knowledge_base_id = conv.knowledge_base_id if conv is not None else settings.active_kb
    msg = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        rule_id=rule_id,
        suggested_followups=followups,
        knowledge_base_id=knowledge_base_id,
    )
    session.add(msg)
    await session.commit()
    return _message_dict(msg)


async def recent_history(session: AsyncSession, conversation_id: int, limit: int = _HISTORY_LIMIT) -> list[dict]:
    """Return the last `limit` messages as [{'role','content'}] for the agent."""
    rows = (await session.execute(
        select(Message.role, Message.content)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(limit)
    )).all()
    return [{"role": r.role, "content": r.content} for r in reversed(rows)]


async def first_user_message(session: AsyncSession, conversation_id: int) -> str | None:
    return await session.scalar(
        select(Message.content)
        .where(Message.conversation_id == conversation_id, Message.role == "user")
        .order_by(Message.id.asc())
        .limit(1)
    )


async def message_count(session: AsyncSession, conversation_id: int) -> int:
    return int(await session.scalar(
        select(func.count()).select_from(Message).where(Message.conversation_id == conversation_id)
    ) or 0)


# ── Knowledge bases ──────────────────────────────────────────────────────────


async def get_kb_prompt(session: AsyncSession, kb_id: str) -> str | None:
    """Return kb_id's stored *reviewed* system-prompt fragment, if any.

    This is the `enhanced_prompt` a user saved via Settings (draft → AI-enhance
    → review/edit → save, Phase 6) — the text `prompts.build_system_prompt`
    injects into the assembled analyst system prompt. None if the KB has no
    row yet or no prompt has been saved.
    """
    return await session.scalar(
        select(KnowledgeBase.enhanced_prompt).where(KnowledgeBase.id == kb_id)
    )


async def save_kb_prompt(
    session: AsyncSession,
    kb_id: str,
    custom_prompt: str | None,
    enhanced_prompt: str | None,
    name: str | None = None,
) -> KnowledgeBase:
    """Upsert kb_id's custom/enhanced system-prompt fields (Settings → Save,
    Phase 6). Creates the KnowledgeBase row if it doesn't exist yet — startup
    seeding (db.seed_knowledge_bases) normally creates one row per registered
    descriptor first, but tests and other callers that reset the schema
    without running the app lifespan won't have it. `name` is only used when
    creating a new row (falls back to kb_id); an existing row's name is left
    untouched.

    No cache to clear: chat handlers call get_kb_prompt() fresh on every
    request and inject the result via prompts.build_system_prompt (Phase 5),
    and explanation_engine.explain_rule's lru_cache is keyed on the assembled
    system_prompt string — so a changed prompt takes effect on the very next
    call with no invalidation step needed.
    """
    row = await session.get(KnowledgeBase, kb_id)
    if row is None:
        row = KnowledgeBase(id=kb_id, name=name or kb_id)
        session.add(row)
    row.custom_prompt = custom_prompt
    row.enhanced_prompt = enhanced_prompt
    row.prompt_updated_at = _utcnow()
    await session.commit()
    return row


# ── Serializers ──────────────────────────────────────────────────────────────


def _project_dict(p: Project) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "instructions": p.instructions,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _conversation_dict(c: Conversation) -> dict:
    return {
        "id": c.id,
        "project_id": c.project_id,
        "persona": c.persona,
        "title": c.title,
        "context_rule_id": c.context_rule_id,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _message_dict(m: Message) -> dict:
    return {
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "rule_id": m.rule_id,
        "suggested_followups": m.suggested_followups or [],
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }
