from fastapi import Header, Depends, HTTPException

from app.config import Settings, get_settings
from app.core.embedding import (
    OpenAIEmbeddingProvider,
    EmbeddingProvider,
)
from app.core.llm import (
    OpenAILLMProvider,
    AnthropicLLMProvider,
    FallbackLLMProvider,
    LLMProviderType,
)
from app.store.vector_store import VectorStore

_vector_store: VectorStore | None = None


def get_vector_store(
    settings: Settings = Depends(get_settings),
) -> VectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore(
            persist_directory=settings.chroma_persist_dir,
            embedding_model=settings.embedding_model,
        )
    return _vector_store


def get_openai_key(
    x_openai_key: str | None = Header(default=None),
) -> str | None:
    return x_openai_key


def get_anthropic_key(
    x_anthropic_key: str | None = Header(default=None),
) -> str | None:
    return x_anthropic_key


def get_embedding_provider(
    openai_key: str | None = Depends(get_openai_key),
) -> EmbeddingProvider:
    if not openai_key:
        raise HTTPException(status_code=401, detail="OpenAI key is required for embeddings. Send X-OpenAI-Key header.")
    return OpenAIEmbeddingProvider(api_key=openai_key)


def get_llm_provider(
    openai_key: str | None = Depends(get_openai_key),
    anthropic_key: str | None = Depends(get_anthropic_key),
    settings: Settings = Depends(get_settings),
) -> LLMProviderType:
    if openai_key and anthropic_key:
        return FallbackLLMProvider(
            primary=OpenAILLMProvider(api_key=openai_key, model=settings.llm_model_openai),
            fallback=AnthropicLLMProvider(api_key=anthropic_key, model=settings.llm_model_anthropic),
        )
    if openai_key:
        return OpenAILLMProvider(api_key=openai_key, model=settings.llm_model_openai)
    if anthropic_key:
        return AnthropicLLMProvider(api_key=anthropic_key, model=settings.llm_model_anthropic)
    raise HTTPException(status_code=401, detail="No API key provided. Send X-OpenAI-Key or X-Anthropic-Key header.")
