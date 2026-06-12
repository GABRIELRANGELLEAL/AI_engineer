"""Workspace schemas."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from models.workspace import WorkspaceMemberPapel, WorkspacePlano


class WorkspaceResponse(BaseModel):
    id: UUID
    nome: str
    plano: WorkspacePlano
    criado_em: datetime
    limite_mensagens_mes: int
    tokens_consumidos_mes_atual: int
    periodo_referencia: str
    exibir_pii_liberado: bool

    class Config:
        from_attributes = True


class WorkspaceMemberResponse(BaseModel):
    user_id: UUID
    email: EmailStr
    nome: str
    papel: WorkspaceMemberPapel
    criado_em: datetime


class InviteMemberRequest(BaseModel):
    email: EmailStr
    papel: WorkspaceMemberPapel = WorkspaceMemberPapel.member


class InviteMemberResponse(BaseModel):
    invite_token: str
    invite_url: str
    expires_at: datetime


class AcceptInviteRequest(BaseModel):
    token: str


class UpdateWorkspaceRequest(BaseModel):
    nome: Optional[str] = Field(None, min_length=1, max_length=255)
    exibir_pii_liberado: Optional[bool] = None
