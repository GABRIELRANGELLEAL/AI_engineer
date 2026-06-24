import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.dependencies import (
    get_embedding_provider,
    get_llm_provider,
    get_openai_key,
    get_vector_store,
)
from app.core.embedding import EmbeddingProvider
from app.core.extraction import _detect_language
from app.core.llm import LLMProviderType, LLMError, answer_question
from app.core.retrieval import retrieve_bilingual
from app.core.translation import translate_question
from app.store.vector_store import VectorStore

router = APIRouter()
logger = logging.getLogger(__name__)


class QuestionRequest(BaseModel):
    question: str


class Reference(BaseModel):
    text: str
    document: str
    page: int
    similarity_score: float | None


class QuestionMetadata(BaseModel):
    provider_used: str
    model: str
    retrieval_time_ms: int
    llm_time_ms: int
    total_time_ms: int
    confidence: str
    query_language_used: str | None = None


class QuestionResponse(BaseModel):
    answer: str
    references: list[Reference]
    metadata: QuestionMetadata


@router.post("/question", response_model=QuestionResponse)
async def ask_question(
    body: QuestionRequest,
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
    llm_provider: LLMProviderType = Depends(get_llm_provider),
    vector_store: VectorStore = Depends(get_vector_store),
    openai_key: str | None = Depends(get_openai_key),
):
    stats = vector_store.get_stats()
    if stats["total_chunks"] == 0:
        raise HTTPException(status_code=400, detail="No documents indexed yet. Upload PDFs first.")

    total_start = time.monotonic()

    # Detect question language and translate to the other language for bilingual retrieval
    question_lang = _detect_language(body.question)
    target_lang = "en" if question_lang == "pt" else "pt"

    translated = None
    if openai_key:
        translated = await translate_question(
            question=body.question,
            from_lang=question_lang,
            to_lang=target_lang,
            openai_key=openai_key,
        )

    retrieval_response = await retrieve_bilingual(
        question=body.question,
        embedding_provider=embedding_provider,
        vector_store=vector_store,
        translated_question=translated,
    )

    retrieval_time_ms = int(retrieval_response.metrics.total_time_ms)

    if not retrieval_response.results:
        return QuestionResponse(
            answer="Não encontrei informação suficiente nos documentos disponíveis para responder esta pergunta.",
            references=[],
            metadata=QuestionMetadata(
                provider_used=llm_provider.name,
                model=llm_provider.model,
                retrieval_time_ms=retrieval_time_ms,
                llm_time_ms=0,
                total_time_ms=int((time.monotonic() - total_start) * 1000),
                confidence="low",
                query_language_used=retrieval_response.metrics.query_language_used,
            ),
        )

    from app.core.chunking import Chunk
    chunks_for_llm = [
        Chunk(
            text=r.text,
            filename=r.document,
            page_number=r.page,
            chunk_index=r.chunk_index,
        )
        for r in retrieval_response.results
    ]

    logger.info("action=llm_context | chunks_count=%d", len(chunks_for_llm))
    for i, c in enumerate(chunks_for_llm):
        logger.info(
            "action=llm_context | chunk=%d | file=%s | page=%d | text_preview=%s",
            i, c.filename, c.page_number, c.text[:150],
        )

    try:
        llm_response = await answer_question(
            question=body.question,
            chunks=chunks_for_llm,
            provider=llm_provider,
        )
    except LLMError as e:
        logger.error("action=llm_failed | error=%s", e)
        raise HTTPException(status_code=502, detail=f"LLM provider error: {e}")

    total_time_ms = int((time.monotonic() - total_start) * 1000)

    references = []
    for idx in llm_response.referenced_chunk_indices:
        if 0 <= idx < len(retrieval_response.results):
            r = retrieval_response.results[idx]
            references.append(Reference(
                text=r.text[:500],
                document=r.document,
                page=r.page,
                similarity_score=r.semantic_score,
            ))

    return QuestionResponse(
        answer=llm_response.answer,
        references=references,
        metadata=QuestionMetadata(
            provider_used=llm_response.provider_used,
            model=llm_response.model,
            retrieval_time_ms=retrieval_time_ms,
            llm_time_ms=llm_response.latency_ms,
            total_time_ms=total_time_ms,
            confidence=retrieval_response.metrics.confidence,
            query_language_used=retrieval_response.metrics.query_language_used,
        ),
    )
