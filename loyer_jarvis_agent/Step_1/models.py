from datetime import datetime, date
from enum import Enum
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, Date,
    ForeignKey, Enum as SQLEnum, JSON, ARRAY
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector

Base = declarative_base()


class FilingStatusEnum(str, Enum):
    NEW = "new"
    ANALYZED = "analyzed"
    CONFIRMED = "confirmed"
    DISCARDED = "discarded"


class DeadlineTypeEnum(str, Enum):
    REQUEST = "request"
    FOLLOW_UP = "follow_up"
    REVIEW = "review"
    FILING = "filing"


class ExampleTypeEnum(str, Enum):
    ANALYSIS = "analysis"
    DOCUMENT = "document"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, unique=True)
    google_calendar_token = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    cases = relationship("Case", back_populates="lawyer")


class Case(Base):
    __tablename__ = "cases"

    id = Column(Integer, primary_key=True)
    case_number = Column(String(255), nullable=False, unique=True)
    court = Column(String(255), nullable=False)
    lawyer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    lawyer = relationship("User", back_populates="cases")
    filings = relationship("Filing", back_populates="case")


class Filing(Base):
    __tablename__ = "filings"

    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    raw_content = Column(Text, nullable=False)
    filing_date = Column(DateTime, nullable=False)
    status = Column(SQLEnum(FilingStatusEnum), default=FilingStatusEnum.NEW, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    case = relationship("Case", back_populates="filings")
    analyses = relationship("Analysis", back_populates="filing")


class Analysis(Base):
    __tablename__ = "analyses"

    id = Column(Integer, primary_key=True)
    filing_id = Column(Integer, ForeignKey("filings.id"), nullable=False)
    action_required = Column(Boolean, nullable=False)
    justification = Column(Text, nullable=False)
    rag_examples_used = Column(JSON, nullable=True)
    lawyer_confirmed = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    filing = relationship("Filing", back_populates="analyses")
    tasks = relationship("Task", back_populates="analysis")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id"), nullable=False)
    description = Column(Text, nullable=False)
    deadline_type = Column(SQLEnum(DeadlineTypeEnum), nullable=False)
    due_date = Column(Date, nullable=False)
    google_calendar_event_id = Column(String(255), nullable=True)
    lawyer_confirmed = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    analysis = relationship("Analysis", back_populates="tasks")
    drafts = relationship("Draft", back_populates="task")


class Draft(Base):
    __tablename__ = "drafts"

    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    content = Column(Text, nullable=False)
    version = Column(Integer, nullable=False)
    chosen = Column(Boolean, default=False, nullable=False)
    edited_by_lawyer = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    task = relationship("Task", back_populates="drafts")


class ExampleBank(Base):
    __tablename__ = "example_bank"

    id = Column(Integer, primary_key=True)
    type = Column(SQLEnum(ExampleTypeEnum), nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1536), nullable=False)
    metadata = Column(JSON, nullable=True)
    source_draft_id = Column(Integer, ForeignKey("drafts.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    source_draft = relationship("Draft")
