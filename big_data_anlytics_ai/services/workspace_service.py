"""Workspace creation and membership helpers."""

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from models import (
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceMemberPapel,
    WorkspacePlano,
)


def current_billing_period() -> str:
    return datetime.utcnow().strftime("%Y-%m")


def create_default_workspace(db: Session, user: User, nome: str | None = None) -> Workspace:
    workspace = Workspace(
        nome=nome or f"Workspace de {user.nome}",
        plano=WorkspacePlano.starter,
        periodo_referencia=current_billing_period(),
    )
    db.add(workspace)
    db.flush()

    membership = WorkspaceMember(
        user_id=user.id,
        workspace_id=workspace.id,
        papel=WorkspaceMemberPapel.admin,
    )
    db.add(membership)
    db.flush()
    return workspace


def get_user_workspaces(db: Session, user_id: uuid.UUID) -> list[Workspace]:
    return (
        db.query(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .filter(WorkspaceMember.user_id == user_id)
        .all()
    )


def get_primary_workspace_id(db: Session, user_id: uuid.UUID) -> uuid.UUID | None:
    member = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.user_id == user_id)
        .order_by(WorkspaceMember.criado_em.asc())
        .first()
    )
    return member.workspace_id if member else None


def user_is_workspace_member(
    db: Session, user_id: uuid.UUID, workspace_id: uuid.UUID
) -> WorkspaceMember | None:
    return (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.workspace_id == workspace_id,
        )
        .first()
    )


def user_is_workspace_admin(
    db: Session, user_id: uuid.UUID, workspace_id: uuid.UUID
) -> bool:
    member = user_is_workspace_member(db, user_id, workspace_id)
    return member is not None and member.papel == WorkspaceMemberPapel.admin
