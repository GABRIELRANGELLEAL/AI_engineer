"""
SQLAlchemy ORM models shared across the API and agent modules.
"""

from datetime import datetime

from sqlalchemy import Column, String, Text, Integer, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Task(Base):
    """Task table: stores user tasks and their current state."""
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, index=True)
    prompt = Column(Text, nullable=False)
    status = Column(String, nullable=False)
    data_source_type = Column(String, nullable=False)
    data_source_meta = Column(Text, nullable=False)
    result = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LlmInteraction(Base):
    """LLM interactions table: audit log of all agent calls."""
    __tablename__ = "llm_interactions"

    id = Column(String, primary_key=True, index=True)
    task_id = Column(String, nullable=False, index=True)
    agent = Column(String, nullable=False)
    prompt = Column(Text, nullable=False)
    model_answer = Column(Text, nullable=False)
    input_tokens = Column(Integer, nullable=False)
    output_tokens = Column(Integer, nullable=False)
    raw_response = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
