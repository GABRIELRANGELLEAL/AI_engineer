import logging

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)


class ValidateKeysRequest(BaseModel):
    openai_key: str | None = None
    anthropic_key: str | None = None


class KeyStatus(BaseModel):
    valid: bool
    message: str


class ValidateKeysResponse(BaseModel):
    openai: KeyStatus | None = None
    anthropic: KeyStatus | None = None


async def _validate_openai(key: str) -> KeyStatus:
    try:
        from openai import AsyncOpenAI, AuthenticationError
        client = AsyncOpenAI(api_key=key, timeout=10.0)
        await client.models.list()
        return KeyStatus(valid=True, message="Conectado com sucesso")
    except AuthenticationError:
        return KeyStatus(valid=False, message="API key inválida ou sem permissão")
    except Exception as e:
        return KeyStatus(valid=False, message=f"Erro de conexão: {e}")


async def _validate_anthropic(key: str) -> KeyStatus:
    try:
        from anthropic import AsyncAnthropic, AuthenticationError
        client = AsyncAnthropic(api_key=key, timeout=10.0)
        await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1,
            messages=[{"role": "user", "content": "hi"}],
        )
        return KeyStatus(valid=True, message="Conectado com sucesso")
    except AuthenticationError:
        return KeyStatus(valid=False, message="API key inválida ou sem permissão")
    except Exception as e:
        return KeyStatus(valid=False, message=f"Erro de conexão: {e}")


@router.post("/validate-keys", response_model=ValidateKeysResponse)
async def validate_keys(body: ValidateKeysRequest):
    if not body.openai_key and not body.anthropic_key:
        return ValidateKeysResponse(
            openai=KeyStatus(valid=False, message="Não fornecida"),
            anthropic=KeyStatus(valid=False, message="Não fornecida"),
        )

    response = ValidateKeysResponse()

    if body.openai_key:
        response.openai = await _validate_openai(body.openai_key)
        logger.info("action=validate_key provider=openai valid=%s", response.openai.valid)

    if body.anthropic_key:
        response.anthropic = await _validate_anthropic(body.anthropic_key)
        logger.info("action=validate_key provider=anthropic valid=%s", response.anthropic.valid)

    return response
