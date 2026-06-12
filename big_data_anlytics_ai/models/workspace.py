"""Workspace and membership ORM models."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base


class WorkspacePlano(str, enum.Enum):
    starter = "starter"
    pro = "pro"
    enterprise = "enterprise"


class WorkspaceMemberPapel(str, enum.Enum):
    admin = "admin"
    member = "member"


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nome = Column(String(255), nullable=False)
    plano = Column(
        Enum(WorkspacePlano), nullable=False, default=WorkspacePlano.starter
    )
    criado_em = Column(DateTime, nullable=False, default=datetime.utcnow)

    limite_mensagens_mes = Column(Integer, nullable=False, default=1000)
    tokens_consumidos_mes_atual = Column(Integer, nullable=False, default=0)
    periodo_referencia = Column(String(7), nullable=False)  # YYYY-MM

    exibir_pii_liberado = Column(Boolean, nullable=False, default=False)

    members = relationship(
        "WorkspaceMember", back_populates="workspace", cascade="all, delete-orphan"
    )
    data_connections = relationship(
        "DataConnection", back_populates="workspace", cascade="all, delete-orphan"
    )
    invites = relationship(
        "WorkspaceInvite", back_populates="workspace", cascade="all, delete-orphan"
    )


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (
        UniqueConstraint("user_id", "workspace_id", name="uq_workspace_member"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    papel = Column(
        Enum(WorkspaceMemberPapel),
        nullable=False,
        default=WorkspaceMemberPapel.member,
    )
    criado_em = Column(DateTime, nullable=False, default=datetime.utcnow)

    user = relationship("User", back_populates="workspace_memberships")
    workspace = relationship("Workspace", back_populates="members")


class WorkspaceInvite(Base):
    """Invite token for adding members to a workspace."""

    __tablename__ = "workspace_invites"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email = Column(String(320), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    papel = Column(
        Enum(WorkspaceMemberPapel),
        nullable=False,
        default=WorkspaceMemberPapel.member,
    )
    expires_at = Column(DateTime, nullable=False)
    accepted_at = Column(DateTime, nullable=True)
    criado_em = Column(DateTime, nullable=False, default=datetime.utcnow)

    workspace = relationship("Workspace", back_populates="invites")
