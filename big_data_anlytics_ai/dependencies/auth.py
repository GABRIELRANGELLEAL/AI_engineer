"""FastAPI auth dependencies."""

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from database import get_db
from models import User, WorkspaceMemberPapel
from services.tokens import decode_access_token
from services.workspace_service import user_is_workspace_admin, user_is_workspace_member

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    db: Session = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Não autenticado",
        )
    try:
        payload = decode_access_token(credentials.credentials)
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Token inválido")
        user_id = uuid.UUID(payload["sub"])
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Token inválido") from exc

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="Usuário não encontrado")
    return user


def get_active_workspace_id(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
) -> uuid.UUID | None:
    if not credentials:
        return None
    try:
        payload = decode_access_token(credentials.credentials)
        ws = payload.get("workspace_id")
        return uuid.UUID(ws) if ws else None
    except Exception:
        return None


def require_workspace_member(
    workspace_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> uuid.UUID:
    if not user_is_workspace_member(db, user.id, workspace_id):
        raise HTTPException(status_code=403, detail="Acesso negado ao workspace")
    return workspace_id


def require_workspace_admin(
    workspace_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> uuid.UUID:
    if not user_is_workspace_admin(db, user.id, workspace_id):
        raise HTTPException(status_code=403, detail="Permissão de admin necessária")
    return workspace_id
