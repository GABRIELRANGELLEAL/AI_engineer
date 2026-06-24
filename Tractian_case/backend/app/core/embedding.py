import asyncio
import logging

from openai import AsyncOpenAI, RateLimitError, APITimeoutError, APIConnectionError

from app.core.chunking import Chunk

logger = logging.getLogger(__name__)

BATCH_SIZE = 100
MAX_TOKENS_PER_INPUT = 8000  # OpenAI hard limit is 8191; leave headroom

_RETRYABLE = (RateLimitError, APITimeoutError, APIConnectionError)

_MODEL_DIMENSIONS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


def _safe_truncate(text: str) -> str:
    words = text.split()
    limit = int(MAX_TOKENS_PER_INPUT / 1.3)
    if len(words) <= limit:
        return text
    logger.warning("action=embed_truncate original_words=%d limit_words=%d", len(words), limit)
    return " ".join(words[:limit])


class OpenAIEmbeddingProvider:

    def __init__(self, api_key: str, model: str = "text-embedding-3-small"):
        self.client = AsyncOpenAI(api_key=api_key, timeout=30.0)
        self.model = model

    @property
    def dimensions(self) -> int:
        return _MODEL_DIMENSIONS.get(self.model, 1536)

    async def _create_with_retry(self, texts: list[str]):
        for attempt in range(3):
            try:
                return await self.client.embeddings.create(model=self.model, input=texts)
            except _RETRYABLE as exc:
                if attempt == 2:
                    raise
                wait = 2 ** attempt
                logger.warning(
                    "action=embed_retry attempt=%d wait=%ds error=%s", attempt + 1, wait, exc
                )
                await asyncio.sleep(wait)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        stripped = [_safe_truncate(t.strip()) for t in texts]
        non_empty = [(i, t) for i, t in enumerate(stripped) if t]

        if not non_empty:
            return [[0.0] * self.dimensions for _ in texts]

        indices, clean_texts = zip(*non_empty)
        response = await self._create_with_retry(list(clean_texts))

        result_map = {idx: item.embedding for idx, item in zip(indices, response.data)}
        zero = [0.0] * self.dimensions
        return [result_map.get(i, zero) for i in range(len(texts))]


# class LocalEmbeddingProvider:
#
#     def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
#         self._model_name = model_name
#         self._model = None
#
#     def _get_model(self):
#         if self._model is None:
#             from sentence_transformers import SentenceTransformer
#             self._model = SentenceTransformer(self._model_name)
#         return self._model
#
#     @property
#     def dimensions(self) -> int:
#         return 384
#
#     async def embed(self, texts: list[str]) -> list[list[float]]:
#         embeddings = await asyncio.to_thread(
#             lambda: self._get_model().encode(texts, convert_to_numpy=True)
#         )
#         return embeddings.tolist()


EmbeddingProvider = OpenAIEmbeddingProvider


def get_embedding_provider(openai_key: str) -> EmbeddingProvider:
    return OpenAIEmbeddingProvider(api_key=openai_key)


async def embed_chunks_in_batches(
    chunks: list[Chunk],
    provider: OpenAIEmbeddingProvider,
    #| LocalEmbeddingProvider,
    batch_size: int = BATCH_SIZE,
) -> list[list[float]]:
    texts = [chunk.text for chunk in chunks]
    all_embeddings: list[list[float]] = []
    total_batches = -(-len(texts) // batch_size)

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        batch_embeddings = await provider.embed(batch)
        all_embeddings.extend(batch_embeddings)
        logger.info(
            "action=embed_batch batch=%d/%d chunks=%d",
            i // batch_size + 1,
            total_batches,
            len(batch),
        )

    return all_embeddings
