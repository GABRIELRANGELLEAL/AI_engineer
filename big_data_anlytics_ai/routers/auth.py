"""Authentication routes."""

import secrets
import uuid
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from config import get_settings
from database import get_db
from dependencies.auth import get_current_user
from models import OAuthProvider, User
from schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    ResetPasswordRequest,
    SignupRequest,
    TokenResponse,
    UserResponse,
)
from services.auth_service import (
    INVALID_CREDENTIALS,
    get_or_create_oauth_user,
    login_user,
    logout_user,
    refresh_session,
    request_password_reset,
    reset_password,
    signup_user,
)
from services.workspace_service import get_primary_workspace_id

router = APIRouter(prefix="/auth", tags=["auth"])

_oauth_states: dict[str, float] = {}


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.refresh_token_cookie_name,
        value=refresh_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.jwt_refresh_token_expire_hours * 3600,
        path="/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.refresh_token_cookie_name,
        path="/auth",
    )


def _token_response(user: User, access_token: str, db: Session) -> TokenResponse:
    workspace_id = get_primary_workspace_id(db, user.id)
    return TokenResponse(
        access_token=access_token,
        user_id=user.id,
        workspace_id=workspace_id,
    )


@router.post("/signup", response_model=TokenResponse)
def signup(
    body: SignupRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        user, access_token, refresh_raw = signup_user(
            db,
            email=body.email,
            password=body.password,
            nome=body.nome,
            idioma_ui_preferido=body.idioma_ui_preferido,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _set_refresh_cookie(response, refresh_raw)
    return _token_response(user, access_token, db)


@router.post("/login", response_model=TokenResponse)
def login(
    body: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        user, access_token, refresh_raw = login_user(db, body.email, body.password)
    except ValueError as exc:
        if str(exc) == INVALID_CREDENTIALS:
            raise HTTPException(status_code=401, detail=INVALID_CREDENTIALS) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _set_refresh_cookie(response, refresh_raw)
    return _token_response(user, access_token, db)


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    settings = get_settings()
    refresh_token = request.cookies.get(settings.refresh_token_cookie_name)
    if not refresh_token:
        raise HTTPException(status_code=401, detail=INVALID_CREDENTIALS)

    try:
        access_token, new_refresh, user_id = refresh_session(db, refresh_token)
    except ValueError as exc:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    _set_refresh_cookie(response, new_refresh)
    workspace_id = get_primary_workspace_id(db, user_id)
    return TokenResponse(
        access_token=access_token,
        user_id=user_id,
        workspace_id=workspace_id,
    )


@router.post("/logout", response_model=MessageResponse)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    settings = get_settings()
    refresh_token = request.cookies.get(settings.refresh_token_cookie_name)
    if refresh_token:
        logout_user(db, refresh_token)
    _clear_refresh_cookie(response)
    return MessageResponse(message="Logout realizado")


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/forgot-password", response_model=MessageResponse)
def forgot_password(body: ForgotPasswordRequest, db: Session = Depends(get_db)):
    request_password_reset(db, body.email)
    return MessageResponse(
        message="Se o e-mail existir, enviaremos instruções de recuperação"
    )


@router.post("/reset-password", response_model=MessageResponse)
def reset_password_endpoint(body: ResetPasswordRequest, db: Session = Depends(get_db)):
    try:
        reset_password(db, body.token, body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MessageResponse(message="Senha atualizada com sucesso")


@router.get("/google/login")
def google_login():
    settings = get_settings()
    if not settings.google_oauth_client_id or not settings.google_oauth_redirect_uri:
        raise HTTPException(status_code=503, detail="OAuth Google não configurado")

    state = secrets.token_urlsafe(16)
    _oauth_states[state] = 1.0

    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    return RedirectResponse(url)


@router.get("/google/callback")
async def google_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db),
):
    settings = get_settings()
    if error:
        return RedirectResponse(
            f"{settings.frontend_url}/login?error=oauth_denied"
        )
    if not code or not state or state not in _oauth_states:
        raise HTTPException(status_code=400, detail="Estado OAuth inválido")
    _oauth_states.pop(state, None)

    token_url = "https://oauth2.googleapis.com/token"
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            token_url,
            data={
                "code": code,
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "redirect_uri": settings.google_oauth_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Falha ao obter token Google")

        tokens = token_resp.json()
        userinfo_resp = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        if userinfo_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Falha ao obter perfil Google")

    profile = userinfo_resp.json()
    email = profile.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="E-mail não disponível no Google")

    user, access_token, refresh_raw, _ = get_or_create_oauth_user(
        db,
        email=email,
        nome=profile.get("name") or email.split("@")[0],
        oauth_id=profile["id"],
        provider=OAuthProvider.google,
    )

    redirect = RedirectResponse(
        f"{settings.frontend_url}/oauth/callback?access_token={access_token}"
    )
    redirect.set_cookie(
        key=settings.refresh_token_cookie_name,
        value=refresh_raw,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.jwt_refresh_token_expire_hours * 3600,
        path="/auth",
    )
    return redirect
