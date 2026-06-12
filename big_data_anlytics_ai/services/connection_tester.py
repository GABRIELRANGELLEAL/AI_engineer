"""Test database connections before persisting credentials."""

import socket
from dataclasses import dataclass
from typing import Optional

import psycopg2

from config import get_settings
from models.data_connection import DataConnectionTipo
from services.encryption import decrypt_value


@dataclass
class ConnectionTestResult:
    success: bool
    error_code: Optional[str] = None
    message: Optional[str] = None


def _timeout() -> int:
    return get_settings().db_connection_test_timeout_seconds


def test_postgres(host: str, porta: int, database: str, usuario: str, senha: str) -> ConnectionTestResult:
    try:
        conn = psycopg2.connect(
            host=host,
            port=porta,
            dbname=database,
            user=usuario,
            password=senha,
            connect_timeout=_timeout(),
        )
        conn.close()
        return ConnectionTestResult(success=True)
    except psycopg2.OperationalError as exc:
        msg = str(exc).lower()
        if "timeout" in msg or "timed out" in msg:
            return ConnectionTestResult(
                success=False, error_code="timeout", message="Tempo esgotado ao conectar"
            )
        if "password authentication failed" in msg or "authentication failed" in msg:
            return ConnectionTestResult(
                success=False,
                error_code="auth_failure",
                message="Falha de autenticação",
            )
        if "could not translate host name" in msg or "name or service not known" in msg:
            return ConnectionTestResult(
                success=False,
                error_code="host_not_found",
                message="Host não encontrado",
            )
        return ConnectionTestResult(
            success=False, error_code="connection_error", message=str(exc)
        )
    except socket.gaierror:
        return ConnectionTestResult(
            success=False, error_code="host_not_found", message="Host não encontrado"
        )


def test_sqlserver(
    host: str, porta: int, database: str, usuario: str, senha: str
) -> ConnectionTestResult:
    try:
        import pymssql
    except ImportError:
        return ConnectionTestResult(
            success=False,
            error_code="driver_missing",
            message="Driver pymssql não instalado",
        )

    try:
        conn = pymssql.connect(
            server=host,
            port=porta,
            user=usuario,
            password=senha,
            database=database,
            login_timeout=_timeout(),
            timeout=_timeout(),
        )
        conn.close()
        return ConnectionTestResult(success=True)
    except pymssql.OperationalError as exc:
        msg = str(exc).lower()
        if "timeout" in msg or "timed out" in msg:
            return ConnectionTestResult(
                success=False, error_code="timeout", message="Tempo esgotado ao conectar"
            )
        if "login failed" in msg or "authentication" in msg:
            return ConnectionTestResult(
                success=False,
                error_code="auth_failure",
                message="Falha de autenticação",
            )
        if "getaddrinfo failed" in msg or "unknown host" in msg:
            return ConnectionTestResult(
                success=False, error_code="host_not_found", message="Host não encontrado"
            )
        return ConnectionTestResult(
            success=False, error_code="connection_error", message=str(exc)
        )
    except socket.gaierror:
        return ConnectionTestResult(
            success=False, error_code="host_not_found", message="Host não encontrado"
        )


def test_connection_params(
    tipo: DataConnectionTipo,
    host: Optional[str],
    porta: Optional[int],
    database: Optional[str],
    usuario: Optional[str],
    senha: Optional[str],
    connection_string: Optional[str] = None,
) -> ConnectionTestResult:
    if connection_string:
        if tipo == DataConnectionTipo.postgres:
            try:
                conn = psycopg2.connect(connection_string, connect_timeout=_timeout())
                conn.close()
                return ConnectionTestResult(success=True)
            except psycopg2.OperationalError as exc:
                msg = str(exc).lower()
                if "timeout" in msg:
                    return ConnectionTestResult(
                        success=False,
                        error_code="timeout",
                        message="Tempo esgotado ao conectar",
                    )
                if "authentication" in msg:
                    return ConnectionTestResult(
                        success=False,
                        error_code="auth_failure",
                        message="Falha de autenticação",
                    )
                return ConnectionTestResult(
                    success=False, error_code="connection_error", message=str(exc)
                )
        return ConnectionTestResult(
            success=False,
            error_code="unsupported",
            message="Connection string alternativa suportada apenas para postgres",
        )

    if not all([host, porta, database, usuario, senha]):
        return ConnectionTestResult(
            success=False,
            error_code="invalid_params",
            message="Parâmetros de conexão incompletos",
        )

    if tipo == DataConnectionTipo.postgres:
        return test_postgres(host, porta, database, usuario, senha)
    return test_sqlserver(host, porta, database, usuario, senha)


def test_stored_connection(
    tipo: DataConnectionTipo,
    host: Optional[str],
    porta: Optional[int],
    database: Optional[str],
    usuario: Optional[str],
    senha_criptografada: Optional[str],
    connection_string_criptografada: Optional[str],
) -> ConnectionTestResult:
    senha = decrypt_value(senha_criptografada) if senha_criptografada else None
    conn_str = (
        decrypt_value(connection_string_criptografada)
        if connection_string_criptografada
        else None
    )
    return test_connection_params(
        tipo=tipo,
        host=host,
        porta=porta,
        database=database,
        usuario=usuario,
        senha=senha,
        connection_string=conn_str,
    )
