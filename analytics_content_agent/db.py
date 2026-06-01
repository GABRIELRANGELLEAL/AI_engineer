"""
PostgreSQL persistence for chat sessions and turns.

This module defines SQLAlchemy 2.0 ORM models and thin helpers used by ``app.py``.
Persistence is **optional**: if the environment variable ``DATABASE_URL`` is unset or
empty, public helpers short-circuit so the API can run without Postgres.

Typical ``DATABASE_URL`` shape::

    postgresql://USER:PASSWORD@HOST:5432/DATABASE

Tables are created idempotently via ``init_db()`` (``CREATE TABLE IF NOT EXISTS`` semantics
through SQLAlchemy metadata).
"""

# Postpone evaluation of type hints (cleaner forward references in ORM annotations).
from __future__ import annotations

# Read DATABASE_URL from the process environment.
import os
# Generate primary keys for ``turns.id`` rows (UUID4 strings).
import uuid
# Store aware timestamps in Python before flush (DB may still use server time in migrations).
from datetime import datetime, timezone
# JSON-serializable dict typing for JSONB-mapped columns and serializer return types.
from typing import Any

# SQLAlchemy core column types and engine factory.
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine
# Postgres-specific binary JSON type (index-friendly vs plain JSON).
from sqlalchemy.dialects.postgresql import JSONB
# Declarative ORM base and typed ``Mapped`` column declarations.
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def database_url() -> str | None:
    """
    Return the JDBC-style Postgres connection URL, or None when persistence is disabled.

    Reads ``DATABASE_URL`` once per call (callers typically memoize behavior via ``enabled()``).

    Returns:
        Non-empty stripped URL string, or None if unset/blank.
    """
    # Strip so accidental spaces in .env do not produce bogus connection attempts.
    u = os.getenv("DATABASE_URL", "").strip()
    # Normalize empty-after-strip to explicit None for boolean checks elsewhere.
    return u or None


def enabled() -> bool:
    """
    Return True when ``DATABASE_URL`` is configured and database writes should run.

    This is the fast guard used by the API layer before scheduling thread-pool DB work.

    Returns:
        True if ``database_url()`` is non-None, else False.
    """
    # Delegates to database_url() so there is a single definition of \"configured\".
    return database_url() is not None


class Base(DeclarativeBase):
    """
    SQLAlchemy declarative base shared by all ORM models in this module.

    Subclasses automatically register tables on ``Base.metadata`` for ``create_all``.
    """


class ChatSessionRow(Base):
    """
    ORM row for table ``chat_sessions``: one row per logical chat opened via POST /session.

    The primary key ``id`` matches the in-memory ``sessions`` dict key in ``app.py``.
    """

    # Explicit SQL table name (snake_case plural).
    __tablename__ = "chat_sessions"

    # UUID string (36 chars with hyphens) from ``uuid.uuid4()`` in the API layer.
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # Full concatenated skill markdown or empty string when no skills were selected.
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Workspace-relative CSV filename bound at session creation (UI contract).
    csv_name: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    # Model id used during skill selection (informational; not necessarily the chat model).
    model_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # Row creation time in UTC (Python-side default at insert time).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),  # TIMESTAMPTZ in PostgreSQL when using native dialect types.
        nullable=False,  # Every session row must have a created timestamp.
        default=lambda: datetime.now(timezone.utc),  # Aware UTC \"now\" at ORM flush time.
    )


class TurnRow(Base):
    """
    ORM row for table ``turns``: one row per persisted chat message / model step.

    ``turn_index`` is unique per ``session_id`` so the API can reconstruct ordering without
    relying solely on ``created_at`` clock skew.
    """

    # Physical table name in Postgres.
    __tablename__ = "turns"
    # Composite uniqueness prevents duplicate sequence numbers within one session.
    __table_args__ = (UniqueConstraint("session_id", "turn_index", name="uq_turns_session_turn_index"),)

    # UUID string primary key for this individual turn row (distinct from session id).
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # Parent session FK: deleting a session cascades and deletes all its turns.
    session_id: Mapped[str] = mapped_column(
        String(36),  # Same width as ``ChatSessionRow.id`` for consistency.
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),  # Orphan turns must not survive session delete.
        index=True,  # Speeds up session-scoped queries (timeline replay, analytics).
    )
    # Monotonic per-session counter allocated by ``app._next_turn_index`` (1,2,3,...).
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # Short string discriminator written by the API (user, assistant, tool_results, ...).
    turn_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    # Raw user-visible text or JSON text for tool_results / error payloads (nullable for pure assistant rows).
    user_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Serialized assistant text blocks (JSON array of dicts, or null when not applicable).
    text_blocks: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    # Serialized assistant tool_use blocks (JSON array of dicts, or null when not applicable).
    tool_blocks: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    # Insert timestamp for auditing and approximate ordering.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


# Lazily created SQLAlchemy Engine (one per process when persistence is enabled).
_engine = None
# Bound session factory configured after engine construction.
_SessionLocal = None


def _ensure_engine() -> None:
    """
    Lazily construct the global Engine and sessionmaker bound to ``DATABASE_URL``.

    Safe to call multiple times: becomes a no-op after the first successful initialization.
    If ``DATABASE_URL`` is missing, leaves globals as None so callers must still gate on ``enabled()``.

    Returns:
        None (mutates module-level ``_engine`` and ``_SessionLocal`` in place).
    """
    # Module-level statement required to assign into outer-scope globals.
    global _engine, _SessionLocal
    # Fast path: already initialized in this interpreter process.
    if _engine is not None:
        return
    # Resolve URL again (may be None if env changed between ``enabled()`` and here).
    url = database_url()
    if not url:
        return
    # pool_pre_ping avoids handing dead connections to callers after idle DB restarts.
    _engine = create_engine(url, pool_pre_ping=True)
    # Classic sessionmaker: explicit commit/rollback in ``with`` blocks; no autoflush surprises.
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)


def init_db() -> None:
    """
    Create all ORM-mapped tables in the target database if they do not already exist.

    No-op when ``DATABASE_URL`` is unset. Must run before concurrent inserts in production
    (``app`` lifespan calls this once at startup).

    Raises:
        Various SQLAlchemy/DBAPI errors if the URL is invalid or the server is unreachable.
    """
    # Respect optional persistence: skip silently when not configured.
    if not enabled():
        return
    # Construct engine/sessionmaker if this is the first DB touch of the process.
    _ensure_engine()
    # Static analysis hint: after _ensure_engine with enabled(), engine must exist.
    assert _engine is not None
    # DDL for every subclass of ``Base`` registered at import time (chat_sessions, turns).
    Base.metadata.create_all(bind=_engine)


def insert_chat_session(
    session_id: str,
    *,
    system_prompt: str,
    csv_name: str,
    model_name: str | None,
) -> None:
    """
    Insert or update one ``chat_sessions`` row keyed by ``session_id``.

    Uses ``Session.merge`` so a duplicate insert by id upserts ORM state instead of always failing.

    Args:
        session_id: Primary key string (UUID).
        system_prompt: Snapshot of the system prompt at session creation.
        csv_name: Bound CSV basename under workspace.
        model_name: Optional model label used during skill selection.

    Returns:
        None.
    """
    # Guard: callers should skip, but double-check to avoid engine creation with no URL.
    if not enabled():
        return
    # Ensure globals exist before opening a SQLAlchemy session.
    _ensure_engine()
    # Session factory must be ready if engine exists and enabled() was True.
    assert _SessionLocal is not None
    # Build a transient ORM instance representing the desired row state.
    row = ChatSessionRow(
        id=session_id,
        system_prompt=system_prompt or "",  # Normalize None-ish values to empty string NOT NULL column.
        csv_name=csv_name or "",
        model_name=model_name,
    )
    # Context-managed session: commit persists; rollback on exception inside context.
    with _SessionLocal() as db:
        db.merge(row)  # INSERT ... ON CONFLICT style behavior depending on dialect/driver.
        db.commit()  # Flush pending INSERT/UPDATE to the database.


def insert_turn(
    session_id: str,
    *,
    turn_index: int,
    turn_kind: str,
    user_prompt: str | None = None,
    text_blocks: list[dict[str, Any]] | None = None,
    tool_blocks: list[dict[str, Any]] | None = None,
) -> str:
    """
    Insert one ``turns`` row and return its generated primary key ``id``.

    Args:
        session_id: FK to ``chat_sessions.id`` (must exist or insert fails per FK rules).
        turn_index: Monotonic per-session sequence number (must respect unique constraint).
        turn_kind: Short label describing who produced the row (see ``app.py`` callers).
        user_prompt: Optional text/JSON-text column payload.
        text_blocks: Optional assistant text block list serialized to JSONB.
        tool_blocks: Optional assistant tool_use list serialized to JSONB.

    Returns:
        New UUID string primary key for the inserted row, or empty string when DB disabled.
    """
    # No database configured: API still wants a return value for uniform call sites.
    if not enabled():
        return ""
    # Prepare engine/sessionmaker if needed.
    _ensure_engine()
    assert _SessionLocal is not None
    # Fresh UUID for this turn row (distinct from session_id and from other turns).
    tid = str(uuid.uuid4())
    # ORM instance fully populated before add/commit.
    row = TurnRow(
        id=tid,
        session_id=session_id,
        turn_index=turn_index,
        turn_kind=turn_kind,
        user_prompt=user_prompt,
        text_blocks=text_blocks,
        tool_blocks=tool_blocks,
    )
    with _SessionLocal() as db:
        db.add(row)  # Pure INSERT path (duplicates on unique turn_index should error).
        db.commit()
    # Return PK so future features (attachments, links) can reference the exact row.
    return tid


def serialize_text_blocks(text_blocks) -> list[dict[str, Any]]:
    """
    Convert Anthropic SDK text block objects into JSON-serializable dicts for JSONB storage.

    Args:
        text_blocks: Iterable of SDK objects exposing ``.text`` (fallback: ``str(obj)``).

    Returns:
        List of dicts shaped like ``{\"text\": \"...\"}`` suitable for ``TurnRow.text_blocks``.
    """
    # Output accumulator (typed for static analysis).
    out: list[dict[str, Any]] = []
    # Preserve iteration order as returned by the API client.
    for b in text_blocks:
        # Prefer the official attribute when present (Anthropic content blocks).
        t = getattr(b, "text", None)
        if t is not None:
            out.append({"text": t})
        else:
            # Defensive fallback if a different object type slips through tests/mocks.
            out.append({"text": str(b)})
    return out


def serialize_tool_blocks(tool_blocks) -> list[dict[str, Any]]:
    """
    Convert Anthropic SDK tool_use block objects into JSON-serializable dicts.

    Args:
        tool_blocks: Iterable of objects with ``id``, ``name``, and ``input`` attributes.

    Returns:
        List of dicts with keys id/name/input (values possibly None if mocked poorly).
    """
    # List comprehension keeps structure compact and order-stable.
    return [
        {
            "id": getattr(b, "id", None),  # Tool use correlation id for tool_result pairing.
            "name": getattr(b, "name", None),  # Registered tool name string (bash, view, ...).
            "input": getattr(b, "input", None),  # JSON-decoded dict of arguments from the model.
        }
        for b in tool_blocks
    ]
