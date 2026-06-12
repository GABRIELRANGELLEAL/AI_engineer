"""Password hashing and strength validation."""

import re

import bcrypt
from zxcvbn import zxcvbn

MIN_PASSWORD_LENGTH = 8
MIN_ZXCVBN_SCORE = 2


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain_password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(
            plain_password.encode(), password_hash.encode()
        )
    except ValueError:
        return False


def validate_password_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError("Senha deve ter no mínimo 8 caracteres")

    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise ValueError("Senha deve conter letras e números")

    result = zxcvbn(password)
    if result["score"] < MIN_ZXCVBN_SCORE:
        feedback = result.get("feedback", {}).get("warning") or result.get(
            "feedback", {}
        ).get("suggestions", ["Senha muito fraca"])
        if isinstance(feedback, list):
            feedback = feedback[0] if feedback else "Senha muito fraca"
        raise ValueError(str(feedback))
