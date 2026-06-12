"""
Application configuration loaded from environment variables.
"""

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


def _get_database_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL not set in environment")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


class Settings:
    database_url: str = _get_database_url()

    jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
    jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    jwt_access_token_expire_minutes: int = int(
        os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    )
    jwt_refresh_token_expire_hours: int = int(
        os.getenv("JWT_REFRESH_TOKEN_EXPIRE_HOURS", "8")
    )

    fernet_key: str = os.getenv("FERNET_KEY", "")

    google_oauth_client_id: str = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
    google_oauth_client_secret: str = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
    google_oauth_redirect_uri: str = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "")

    frontend_url: str = os.getenv("FRONTEND_URL", "http://localhost:3000")
    api_base_url: str = os.getenv("API_BASE_URL", "http://localhost:8000")

    password_reset_token_expire_minutes: int = int(
        os.getenv("PASSWORD_RESET_TOKEN_EXPIRE_MINUTES", "60")
    )

    refresh_token_cookie_name: str = os.getenv(
        "REFRESH_TOKEN_COOKIE_NAME", "refresh_token"
    )
    cookie_secure: bool = os.getenv("COOKIE_SECURE", "false").lower() == "true"
    cookie_samesite: str = os.getenv("COOKIE_SAMESITE", "lax")

    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    email_from: str = os.getenv("EMAIL_FROM", "noreply@localhost")
    email_mock: bool = os.getenv("EMAIL_MOCK", "true").lower() == "true"

    db_connection_test_timeout_seconds: int = int(
        os.getenv("DB_CONNECTION_TEST_TIMEOUT_SECONDS", "10")
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
