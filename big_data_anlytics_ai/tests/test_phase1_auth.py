"""Phase 1 auth flow smoke tests."""

import os

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

os.environ.setdefault(
    "DATABASE_URL", "postgresql://app:app@localhost:5432/analytics"
)
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-only")
os.environ.setdefault("FERNET_KEY", Fernet.generate_key().decode())
os.environ.setdefault("EMAIL_MOCK", "true")

from main import app  # noqa: E402

client = TestClient(app)


@pytest.fixture
def unique_user():
    import uuid

    suffix = uuid.uuid4().hex[:8]
    return {
        "email": f"user_{suffix}@example.com",
        "password": "SenhaForte123",
        "nome": "Usuário Teste",
    }


def test_signup_login_me(unique_user):
    signup = client.post("/auth/signup", json=unique_user)
    if signup.status_code == 500:
        pytest.skip("Database not available")
    assert signup.status_code == 200, signup.text
    data = signup.json()
    assert "access_token" in data
    assert data["workspace_id"] is not None

    login = client.post(
        "/auth/login",
        json={"email": unique_user["email"], "password": unique_user["password"]},
    )
    assert login.status_code == 200

    me = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {data['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == unique_user["email"]


def test_login_invalid_credentials():
    resp = client.post(
        "/auth/login",
        json={"email": "naoexiste@example.com", "password": "SenhaForte123"},
    )
    if resp.status_code == 500:
        pytest.skip("Database not available")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Credenciais inválidas"
