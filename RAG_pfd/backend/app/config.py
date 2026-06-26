from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    chunk_size: int = 512
    chunk_overlap: int = 50
    top_k: int = 5
    llm_model_openai: str = "gpt-4o-mini"
    llm_model_anthropic: str = "claude-sonnet-4-6"
    embedding_model: str = "text-embedding-3-small"
    chroma_persist_dir: str = "./data/chromadb"
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
