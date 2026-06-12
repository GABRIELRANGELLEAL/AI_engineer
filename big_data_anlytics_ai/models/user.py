"""User ORM model."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base


class OAuthProvider(str, enum.Enum):
    google = "google"


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(320), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=True)
    nome = Column(String(255), nullable=False)
    criado_em = Column(DateTime, nullable=False, default=datetime.utcnow)
    atualizado_em = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    oauth_provider = Column(Enum(OAuthProvider), nullable=True)
    oauth_id = Column(String(255), nullable=True, index=True)
    idioma_ui_preferido = Column(String(10), nullable=False, default="pt-BR")

    workspace_memberships = relationship(
        "WorkspaceMember", back_populates="user", cascade="all, delete-orphan"
    )
    refresh_tokens = relationship(
        "RefreshToken", back_populates="user", cascade="all, delete-orphan"
    )
