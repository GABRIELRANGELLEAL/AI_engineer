import logging
import time

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.api.dependencies import get_embedding_provider, get_vector_store
from app.core.chunking import chunk_pages
from app.core.embedding import EmbeddingProvider, embed_chunks_in_batches
from app.core.extraction import extract_pdf
from app.store.vector_store import VectorStore

router = APIRouter()
logger = logging.getLogger(__name__)


class DocumentDetail(BaseModel):
    filename: str
    pages: int
    chunks: int
    processing_time_ms: int
    detected_language: str


class UploadResponse(BaseModel):
    message: str
    documents_indexed: int
    total_chunks: int
    details: list[DocumentDetail]


@router.post("/documents", response_model=UploadResponse)
async def upload_documents(
    files: list[UploadFile] = File(...),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
    vector_store: VectorStore = Depends(get_vector_store),
):
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    details: list[DocumentDetail] = []
    total_chunks = 0

    for file in files:
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail=f"File '{file.filename}' is not a PDF")

        start = time.monotonic()

        pdf_bytes = await file.read()
        extraction_result = extract_pdf(pdf_bytes, file.filename)

        if extraction_result.warning:
            logger.warning("action=extract file=%s warning=%s", file.filename, extraction_result.warning)

        chunks = chunk_pages(extraction_result.pages)

        if not chunks:
            details.append(DocumentDetail(
                filename=file.filename,
                pages=len(extraction_result.pages),
                chunks=0,
                processing_time_ms=int((time.monotonic() - start) * 1000),
                detected_language=extraction_result.detected_language,
            ))
            continue

        embeddings = await embed_chunks_in_batches(chunks, embedding_provider)
        vector_store.add_documents(chunks, embeddings)

        elapsed = int((time.monotonic() - start) * 1000)
        total_chunks += len(chunks)

        details.append(DocumentDetail(
            filename=file.filename,
            pages=len(extraction_result.pages),
            chunks=len(chunks),
            processing_time_ms=elapsed,
            detected_language=extraction_result.detected_language,
        ))

        logger.info(
            "action=index_document file=%s pages=%d chunks=%d time_ms=%d",
            file.filename, len(extraction_result.pages), len(chunks), elapsed,
        )

    return UploadResponse(
        message="Documents processed successfully",
        documents_indexed=len(details),
        total_chunks=total_chunks,
        details=details,
    )
