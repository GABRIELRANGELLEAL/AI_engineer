"""Auth request/response schemas."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    nome: str = Field(..., min_length=1, max_length=255)
    idioma_ui_preferido: str = "pt-BR"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: UUID
    workspace_id: Optional[UUID] = None


class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    nome: str
    idioma_ui_preferido: str
    criado_em: datetime

    class Config:
        from_attributes = True


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8)


class MessageResponse(BaseModel):
    message: str
