"""Authentication business logic."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from config import get_settings
from models import (
    OAuthProvider,
    PasswordResetToken,
    RefreshToken,
    User,
    WorkspaceInvite,
    WorkspaceMember,
    WorkspaceMemberPapel,
)
from services.email_service import send_email
from services.password import hash_password, validate_password_strength, verify_password
from services.tokens import (
    create_access_token,
    generate_opaque_token,
    hash_token,
    refresh_token_expires_at,
)
from services.workspace_service import create_default_workspace, get_primary_workspace_id


INVALID_CREDENTIALS = "Credenciais inválidas"


def signup_user(
    db: Session,
    email: str,
    password: str,
    nome: str,
    idioma_ui_preferido: str = "pt-BR",
) -> tuple[User, str, str]:
    validate_password_strength(password)

    existing = db.query(User).filter(User.email == email.lower()).first()
    if existing:
        raise ValueError("E-mail já cadastrado")

    user = User(
        email=email.lower(),
        password_hash=hash_password(password),
        nome=nome,
        idioma_ui_preferido=idioma_ui_preferido,
    )
    db.add(user)
    db.flush()

    workspace = create_default_workspace(db, user)
    db.flush()

    access_token = create_access_token(user.id, workspace.id)
    refresh_raw, _ = _create_refresh_token(db, user.id)
    db.commit()
    db.refresh(user)
    return user, access_token, refresh_raw


def login_user(db: Session, email: str, password: str) -> tuple[User, str, str]:
    user = db.query(User).filter(User.email == email.lower()).first()
    if not user or not verify_password(password, user.password_hash):
        raise ValueError(INVALID_CREDENTIALS)

    workspace_id = get_primary_workspace_id(db, user.id)
    access_token = create_access_token(user.id, workspace_id)
    refresh_raw, _ = _create_refresh_token(db, user.id)
    user.atualizado_em = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user, access_token, refresh_raw


def _create_refresh_token(db: Session, user_id: uuid.UUID) -> tuple[str, RefreshToken]:
    raw = generate_opaque_token()
    record = RefreshToken(
        user_id=user_id,
        token_hash=hash_token(raw),
        expires_at=refresh_token_expires_at(),
        last_activity_at=datetime.utcnow(),
    )
    db.add(record)
    return raw, record


def refresh_session(db: Session, refresh_token: str) -> tuple[str, str, uuid.UUID]:
    token_hash = hash_token(refresh_token)
    record = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == token_hash)
        .first()
    )
    if not record or record.revoked_at or record.expires_at < datetime.utcnow():
        raise ValueError(INVALID_CREDENTIALS)

    settings = get_settings()
    inactivity_limit = datetime.utcnow() - timedelta(
        hours=settings.jwt_refresh_token_expire_hours
    )
    if record.last_activity_at < inactivity_limit:
        record.revoked_at = datetime.utcnow()
        db.commit()
        raise ValueError("Sessão expirada por inatividade")

    record.last_activity_at = datetime.utcnow()
    workspace_id = get_primary_workspace_id(db, record.user_id)
    access_token = create_access_token(record.user_id, workspace_id)

    new_raw, new_record = _create_refresh_token(db, record.user_id)
    record.revoked_at = datetime.utcnow()
    db.commit()
    return access_token, new_raw, record.user_id


def logout_user(db: Session, refresh_token: str) -> None:
    token_hash = hash_token(refresh_token)
    record = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == token_hash)
        .first()
    )
    if record and not record.revoked_at:
        record.revoked_at = datetime.utcnow()
        db.commit()


def get_or_create_oauth_user(
    db: Session,
    email: str,
    nome: str,
    oauth_id: str,
    provider: OAuthProvider = OAuthProvider.google,
) -> tuple[User, str, str, bool]:
    user = db.query(User).filter(User.oauth_id == oauth_id).first()
    created = False

    if not user:
        user = db.query(User).filter(User.email == email.lower()).first()
        if user:
            user.oauth_provider = provider
            user.oauth_id = oauth_id
            if not user.nome:
                user.nome = nome
        else:
            user = User(
                email=email.lower(),
                nome=nome,
                oauth_provider=provider,
                oauth_id=oauth_id,
                password_hash=None,
            )
            db.add(user)
            db.flush()
            create_default_workspace(db, user)
            created = True

    workspace_id = get_primary_workspace_id(db, user.id)
    access_token = create_access_token(user.id, workspace_id)
    refresh_raw, _ = _create_refresh_token(db, user.id)
    user.atualizado_em = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user, access_token, refresh_raw, created


def request_password_reset(db: Session, email: str) -> None:
    user = db.query(User).filter(User.email == email.lower()).first()
    if not user:
        return

    raw = generate_opaque_token()
    record = PasswordResetToken(
        user_id=user.id,
        token_hash=hash_token(raw),
        expires_at=datetime.utcnow()
        + timedelta(minutes=get_settings().password_reset_token_expire_minutes),
    )
    db.add(record)
    db.commit()

    reset_url = f"{get_settings().frontend_url}/reset-password?token={raw}"
    send_email(
        to=user.email,
        subject="Redefinição de senha",
        body=f"Use o link abaixo para redefinir sua senha (válido por tempo limitado):\n\n{reset_url}",
    )


def reset_password(db: Session, token: str, new_password: str) -> None:
    validate_password_strength(new_password)
    token_hash = hash_token(token)
    record = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == token_hash)
        .first()
    )
    if (
        not record
        or record.used_at
        or record.expires_at < datetime.utcnow()
    ):
        raise ValueError("Token inválido ou expirado")

    user = db.query(User).filter(User.id == record.user_id).first()
    if not user:
        raise ValueError("Token inválido ou expirado")

    user.password_hash = hash_password(new_password)
    user.atualizado_em = datetime.utcnow()
    record.used_at = datetime.utcnow()
    db.commit()


def accept_workspace_invite(
    db: Session, user: User, invite_token: str
) -> WorkspaceMember:
    token_hash = hash_token(invite_token)
    invite = (
        db.query(WorkspaceInvite)
        .filter(WorkspaceInvite.token_hash == token_hash)
        .first()
    )
    if (
        not invite
        or invite.accepted_at
        or invite.expires_at < datetime.utcnow()
    ):
        raise ValueError("Convite inválido ou expirado")

    if invite.email.lower() != user.email.lower():
        raise ValueError("Convite destinado a outro e-mail")

    existing = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.workspace_id == invite.workspace_id,
        )
        .first()
    )
    if existing:
        invite.accepted_at = datetime.utcnow()
        db.commit()
        return existing

    member = WorkspaceMember(
        user_id=user.id,
        workspace_id=invite.workspace_id,
        papel=invite.papel,
    )
    db.add(member)
    invite.accepted_at = datetime.utcnow()
    db.commit()
    db.refresh(member)
    return member
