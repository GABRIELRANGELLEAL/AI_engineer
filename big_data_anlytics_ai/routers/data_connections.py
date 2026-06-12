"""Data connection CRUD routes."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from dependencies.auth import require_workspace_member
from models import DataConnection, DataConnectionStatus
from schemas.data_connection import (
    ConnectionTestError,
    DataConnectionCreate,
    DataConnectionResponse,
    DataConnectionUpdate,
)
from services.connection_tester import test_connection_params, test_stored_connection
from services.encryption import encrypt_value

router = APIRouter(prefix="/workspaces", tags=["data-connections"])


def _to_response(conn: DataConnection) -> DataConnectionResponse:
    return DataConnectionResponse(
        id=conn.id,
        workspace_id=conn.workspace_id,
        nome_amigavel=conn.nome_amigavel,
        tipo=conn.tipo,
        host=conn.host,
        porta=conn.porta,
        database=conn.database,
        usuario=conn.usuario,
        status=conn.status,
        criado_em=conn.criado_em,
        atualizado_em=conn.atualizado_em,
        ultima_data_profiling=conn.ultima_data_profiling,
        status_profiling=conn.status_profiling,
    )


def _apply_credentials(conn: DataConnection, body) -> None:
    if body.senha is not None:
        conn.senha_criptografada = encrypt_value(body.senha) if body.senha else None
    if body.connection_string is not None:
        conn.connection_string_criptografada = (
            encrypt_value(body.connection_string) if body.connection_string else None
        )


@router.get(
    "/{workspace_id}/connections",
    response_model=list[DataConnectionResponse],
)
def list_connections(
    workspace_id: uuid.UUID = Depends(require_workspace_member),
    db: Session = Depends(get_db),
):
    connections = (
        db.query(DataConnection)
        .filter(
            DataConnection.workspace_id == workspace_id,
            DataConnection.deleted_at.is_(None),
        )
        .order_by(DataConnection.criado_em.desc())
        .all()
    )
    return [_to_response(c) for c in connections]


@router.post(
    "/{workspace_id}/connections",
    response_model=DataConnectionResponse,
    responses={400: {"model": ConnectionTestError}},
)
def create_connection(
    body: DataConnectionCreate,
    workspace_id: uuid.UUID = Depends(require_workspace_member),
    db: Session = Depends(get_db),
):
    test_result = test_connection_params(
        tipo=body.tipo,
        host=body.host,
        porta=body.porta,
        database=body.database,
        usuario=body.usuario,
        senha=body.senha,
        connection_string=body.connection_string,
    )
    if not test_result.success:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": test_result.error_code,
                "message": test_result.message,
            },
        )

    conn = DataConnection(
        workspace_id=workspace_id,
        nome_amigavel=body.nome_amigavel,
        tipo=body.tipo,
        host=body.host,
        porta=body.porta,
        database=body.database,
        usuario=body.usuario,
        status=DataConnectionStatus.ativo,
    )
    _apply_credentials(conn, body)
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return _to_response(conn)


@router.get(
    "/{workspace_id}/connections/{connection_id}",
    response_model=DataConnectionResponse,
)
def get_connection(
    connection_id: uuid.UUID,
    workspace_id: uuid.UUID = Depends(require_workspace_member),
    db: Session = Depends(get_db),
):
    conn = _get_connection(db, workspace_id, connection_id)
    return _to_response(conn)


@router.patch(
    "/{workspace_id}/connections/{connection_id}",
    response_model=DataConnectionResponse,
)
def update_connection(
    connection_id: uuid.UUID,
    body: DataConnectionUpdate,
    workspace_id: uuid.UUID = Depends(require_workspace_member),
    db: Session = Depends(get_db),
):
    conn = _get_connection(db, workspace_id, connection_id)

    tipo = body.tipo or conn.tipo
    host = body.host if body.host is not None else conn.host
    porta = body.porta if body.porta is not None else conn.porta
    database = body.database if body.database is not None else conn.database
    usuario = body.usuario if body.usuario is not None else conn.usuario

    senha = body.senha
    conn_str = body.connection_string
    if senha is None and conn.senha_criptografada:
        from services.encryption import decrypt_value

        senha = decrypt_value(conn.senha_criptografada)
    if conn_str is None and conn.connection_string_criptografada:
        from services.encryption import decrypt_value

        conn_str = decrypt_value(conn.connection_string_criptografada)

    test_result = test_connection_params(
        tipo=tipo,
        host=host,
        porta=porta,
        database=database,
        usuario=usuario,
        senha=senha,
        connection_string=conn_str,
    )
    if not test_result.success:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": test_result.error_code,
                "message": test_result.message,
            },
        )

    if body.nome_amigavel is not None:
        conn.nome_amigavel = body.nome_amigavel
    if body.tipo is not None:
        conn.tipo = body.tipo
    if body.host is not None:
        conn.host = body.host
    if body.porta is not None:
        conn.porta = body.porta
    if body.database is not None:
        conn.database = body.database
    if body.usuario is not None:
        conn.usuario = body.usuario

    _apply_credentials(conn, body)
    conn.status = DataConnectionStatus.ativo
    conn.atualizado_em = datetime.utcnow()
    db.commit()
    db.refresh(conn)
    return _to_response(conn)


@router.post(
    "/{workspace_id}/connections/{connection_id}/test",
    response_model=DataConnectionResponse,
)
def retest_connection(
    connection_id: uuid.UUID,
    workspace_id: uuid.UUID = Depends(require_workspace_member),
    db: Session = Depends(get_db),
):
    conn = _get_connection(db, workspace_id, connection_id)
    conn.status = DataConnectionStatus.testando
    db.commit()

    result = test_stored_connection(
        tipo=conn.tipo,
        host=conn.host,
        porta=conn.porta,
        database=conn.database,
        usuario=conn.usuario,
        senha_criptografada=conn.senha_criptografada,
        connection_string_criptografada=conn.connection_string_criptografada,
    )
    conn.status = (
        DataConnectionStatus.ativo if result.success else DataConnectionStatus.erro
    )
    conn.atualizado_em = datetime.utcnow()
    db.commit()
    db.refresh(conn)

    if not result.success:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": result.error_code,
                "message": result.message,
                "connection": _to_response(conn),
            },
        )
    return _to_response(conn)


@router.delete("/{workspace_id}/connections/{connection_id}")
def delete_connection(
    connection_id: uuid.UUID,
    workspace_id: uuid.UUID = Depends(require_workspace_member),
    db: Session = Depends(get_db),
):
    conn = _get_connection(db, workspace_id, connection_id)
    conn.deleted_at = datetime.utcnow()
    conn.status = DataConnectionStatus.erro
    db.commit()
    return {"message": "Conexão removida"}


def _get_connection(
    db: Session, workspace_id: uuid.UUID, connection_id: uuid.UUID
) -> DataConnection:
    conn = (
        db.query(DataConnection)
        .filter(
            DataConnection.id == connection_id,
            DataConnection.workspace_id == workspace_id,
            DataConnection.deleted_at.is_(None),
        )
        .first()
    )
    if not conn:
        raise HTTPException(status_code=404, detail="Conexão não encontrada")
    return conn
