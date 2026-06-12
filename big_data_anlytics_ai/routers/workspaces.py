"""Workspace management routes."""

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from config import get_settings
from database import get_db
from dependencies.auth import get_current_user, require_workspace_admin, require_workspace_member
from models import User, Workspace, WorkspaceInvite, WorkspaceMember
from schemas.auth import MessageResponse
from schemas.workspace import (
    AcceptInviteRequest,
    InviteMemberRequest,
    InviteMemberResponse,
    UpdateWorkspaceRequest,
    WorkspaceMemberResponse,
    WorkspaceResponse,
)
from services.auth_service import accept_workspace_invite
from services.tokens import generate_opaque_token, hash_token
from services.workspace_service import get_user_workspaces

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

INVITE_EXPIRE_DAYS = 7


@router.get("", response_model=list[WorkspaceResponse])
def list_workspaces(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_user_workspaces(db, user.id)


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
def get_workspace(
    workspace_id: uuid.UUID = Depends(require_workspace_member),
    db: Session = Depends(get_db),
):
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace não encontrado")
    return workspace


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
def update_workspace(
    body: UpdateWorkspaceRequest,
    workspace_id: uuid.UUID = Depends(require_workspace_admin),
    db: Session = Depends(get_db),
):
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace não encontrado")

    if body.nome is not None:
        workspace.nome = body.nome
    if body.exibir_pii_liberado is not None:
        workspace.exibir_pii_liberado = body.exibir_pii_liberado

    db.commit()
    db.refresh(workspace)
    return workspace


@router.get("/{workspace_id}/members", response_model=list[WorkspaceMemberResponse])
def list_members(
    workspace_id: uuid.UUID = Depends(require_workspace_member),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(WorkspaceMember, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .filter(WorkspaceMember.workspace_id == workspace_id)
        .order_by(WorkspaceMember.criado_em.asc())
        .all()
    )
    return [
        WorkspaceMemberResponse(
            user_id=member.user_id,
            email=user.email,
            nome=user.nome,
            papel=member.papel,
            criado_em=member.criado_em,
        )
        for member, user in rows
    ]


@router.post("/{workspace_id}/invites", response_model=InviteMemberResponse)
def invite_member(
    body: InviteMemberRequest,
    workspace_id: uuid.UUID = Depends(require_workspace_admin),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    raw = generate_opaque_token()
    expires_at = datetime.utcnow() + timedelta(days=INVITE_EXPIRE_DAYS)

    invite = WorkspaceInvite(
        workspace_id=workspace_id,
        email=body.email.lower(),
        token_hash=hash_token(raw),
        papel=body.papel,
        expires_at=expires_at,
    )
    db.add(invite)
    db.commit()

    invite_url = f"{settings.frontend_url}/accept-invite?token={raw}"
    return InviteMemberResponse(
        invite_token=raw,
        invite_url=invite_url,
        expires_at=expires_at,
    )


@router.post("/{workspace_id}/members", response_model=MessageResponse)
def add_member_by_email(
    body: InviteMemberRequest,
    workspace_id: uuid.UUID = Depends(require_workspace_admin),
    db: Session = Depends(get_db),
):
    """Add an existing user to the workspace by e-mail (MVP direct add)."""
    from models import User

    user = db.query(User).filter(User.email == body.email.lower()).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail="Usuário não encontrado. Use convite por link.",
        )

    existing = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.workspace_id == workspace_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Usuário já é membro")

    member = WorkspaceMember(
        user_id=user.id,
        workspace_id=workspace_id,
        papel=body.papel,
    )
    db.add(member)
    db.commit()
    return MessageResponse(message="Membro adicionado com sucesso")


@router.post("/invites/accept", response_model=MessageResponse)
def accept_invite(
    body: AcceptInviteRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        accept_workspace_invite(db, user, body.token)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MessageResponse(message="Convite aceito com sucesso")
