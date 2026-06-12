"""Data connection schemas."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from models.data_connection import (
    DataConnectionStatus,
    DataConnectionTipo,
    ProfilingStatus,
)


class DataConnectionCreate(BaseModel):
    nome_amigavel: str = Field(..., min_length=1, max_length=255)
    tipo: DataConnectionTipo
    host: Optional[str] = None
    porta: Optional[int] = None
    database: Optional[str] = None
    usuario: Optional[str] = None
    senha: Optional[str] = None
    connection_string: Optional[str] = None


class DataConnectionUpdate(BaseModel):
    nome_amigavel: Optional[str] = Field(None, min_length=1, max_length=255)
    tipo: Optional[DataConnectionTipo] = None
    host: Optional[str] = None
    porta: Optional[int] = None
    database: Optional[str] = None
    usuario: Optional[str] = None
    senha: Optional[str] = None
    connection_string: Optional[str] = None


class DataConnectionResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    nome_amigavel: str
    tipo: DataConnectionTipo
    host: Optional[str]
    porta: Optional[int]
    database: Optional[str]
    usuario: Optional[str]
    status: DataConnectionStatus
    criado_em: datetime
    atualizado_em: datetime
    ultima_data_profiling: Optional[datetime]
    status_profiling: Optional[ProfilingStatus]

    class Config:
        from_attributes = True


class ConnectionTestError(BaseModel):
    error_code: str
    message: str
