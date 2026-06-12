"""Data connection ORM model."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base


class DataConnectionTipo(str, enum.Enum):
    postgres = "postgres"
    sqlserver = "sqlserver"


class DataConnectionStatus(str, enum.Enum):
    ativo = "ativo"
    erro = "erro"
    testando = "testando"


class ProfilingStatus(str, enum.Enum):
    pendente = "pendente"
    em_andamento = "em_andamento"
    concluido = "concluido"
    falhou = "falhou"


class DataConnection(Base):
    __tablename__ = "data_connections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    nome_amigavel = Column(String(255), nullable=False)
    tipo = Column(Enum(DataConnectionTipo), nullable=False)
    host = Column(String(255), nullable=True)
    porta = Column(Integer, nullable=True)
    database = Column(String(255), nullable=True)
    usuario = Column(String(255), nullable=True)
    senha_criptografada = Column(Text, nullable=True)
    connection_string_criptografada = Column(Text, nullable=True)
    status = Column(
        Enum(DataConnectionStatus),
        nullable=False,
        default=DataConnectionStatus.testando,
    )
    criado_em = Column(DateTime, nullable=False, default=datetime.utcnow)
    atualizado_em = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    ultima_data_profiling = Column(DateTime, nullable=True)
    status_profiling = Column(
        Enum(ProfilingStatus), nullable=True, default=ProfilingStatus.pendente
    )

    deleted_at = Column(DateTime, nullable=True)

    workspace = relationship("Workspace", back_populates="data_connections")
