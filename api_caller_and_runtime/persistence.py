"""
Pluggable persistence backends for conversation history.

Users without Postgres can skip persistence (pass ``persistence=None`` to the
Orchestrator) or implement their own backend (SQLite, JSON file, etc.) by
subclassing ``PersistenceBackend``.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from chat_orchestrator import ChatSession, RunResult
    from response_handler import LoopState

logger = logging.getLogger(__name__)


@runtime_checkable
class PersistenceBackend(Protocol):
    def save(
        self,
        *,
        session: "ChatSession",
        user_prompt: dict[str, Any],
        final_answer: str,
        state: "LoopState",
        task_id: str,
        agent_name: str,
    ) -> None: ...


class SQLAlchemyPersistence:
    """Persists conversations to a ``llm_interactions`` table via SQLAlchemy."""

    def __init__(self, session_factory: Any | None = None):
        self._session_factory = session_factory

    def _get_session_factory(self):
        if self._session_factory is not None:
            return self._session_factory

        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            logger.warning("DATABASE_URL not set — skipping persistence")
            return None

        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        engine = create_engine(database_url, echo=False)
        self._session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        return self._session_factory

    def save(
        self,
        *,
        session: "ChatSession",
        user_prompt: dict[str, Any],
        final_answer: str,
        state: "LoopState",
        task_id: str,
        agent_name: str,
    ) -> None:
        factory = self._get_session_factory()
        if factory is None:
            return

        try:
            from models import LlmInteraction
        except Exception as exc:
            logger.warning("Could not import LlmInteraction — skipping persistence: %s", exc)
            return

        prompt_content = user_prompt.get("content", "")
        prompt_text = (
            prompt_content
            if isinstance(prompt_content, str)
            else json.dumps(prompt_content, ensure_ascii=False)
        )
        model_answer = final_answer or json.dumps(
            state.output_messages, ensure_ascii=False
        )

        db = factory()
        try:
            interaction = LlmInteraction(
                id=str(uuid.uuid4()),
                task_id=task_id,
                agent=agent_name,
                prompt=prompt_text,
                model_answer=model_answer,
                input_tokens=state.total_tokens,
                output_tokens=0,
                raw_response=session.messages,
                created_at=datetime.utcnow(),
            )
            db.add(interaction)
            db.commit()
            logger.info("Conversation persisted (session=%s)", session.session_id)
        except Exception as exc:
            db.rollback()
            logger.warning("Failed to persist conversation: %s", exc)
        finally:
            db.close()
