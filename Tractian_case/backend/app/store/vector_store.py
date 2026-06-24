import logging
from dataclasses import dataclass
from pathlib import Path

import chromadb
from chromadb.config import Settings

from app.core.chunking import Chunk

logger = logging.getLogger(__name__)

DEFAULT_PERSIST_DIR = "/app/data/chromadb"
DEFAULT_COLLECTION = "documents"


@dataclass
class SearchResult:
    text: str
    metadata: dict   # keys: filename, page_number, chunk_index
    score: float


class VectorStore:

    def __init__(
        self,
        persist_directory: str = DEFAULT_PERSIST_DIR,
        collection_name: str = DEFAULT_COLLECTION,
        embedding_model: str = "text-embedding-3-small",
    ):
        Path(persist_directory).mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(
            path=persist_directory,
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={
                "hnsw:space": "cosine",
                "embedding_model": embedding_model,
            },
        )
        self._embedding_model = embedding_model
        self._validate_embedding_model(embedding_model)

    def _validate_embedding_model(self, requested: str) -> None:
        metadata = self.collection.metadata or {}
        stored = metadata.get("embedding_model")
        if not stored:
            logger.info("action=collection_init embedding_model=%s (new collection)", requested)
            return
        if stored != requested:
            raise ValueError(
                f"Collection was indexed with '{stored}' but current provider uses "
                f"'{requested}'. Call reset() to destroy the collection and reindex, "
                f"or reinstantiate VectorStore with embedding_model='{stored}'."
            )

    def reset(self) -> None:
        """Delete and recreate the collection. Destroys all indexed data."""
        name = self.collection.name
        self.client.delete_collection(name)
        self.collection = self.client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine", "embedding_model": self._embedding_model},
        )
        logger.info("action=reset_collection collection=%s", name)

    def add_documents(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        if not chunks:
            return
        if len(chunks) != len(embeddings):
            raise ValueError(
                f"chunks ({len(chunks)}) and embeddings ({len(embeddings)}) must have the same length"
            )

        ids = [f"{c.filename}::{c.chunk_index}" for c in chunks]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate chunk IDs detected within the batch. Check chunk_index uniqueness.")
        documents = [c.text for c in chunks]
        metadatas = [
            {
                "filename": c.filename,
                "page_number": c.page_number,
                "chunk_index": c.chunk_index,
            }
            for c in chunks
        ]

        self.collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        logger.info(
            "action=add_documents chunks=%d collection=%s",
            len(chunks),
            self.collection.name,
        )

    def search(self, query_embedding: list[float], top_k: int = 5) -> list[SearchResult]:
        count = self.collection.count()
        if count == 0:
            return []

        # n_results cannot exceed the number of items in the collection
        n = min(top_k, count)
        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n,
            include=["documents", "metadatas", "distances"],
        )

        docs = result["documents"][0]
        metas = result["metadatas"][0]
        dists = result["distances"][0]

        results = []
        for text, meta, dist in zip(docs, metas, dists):
            similarity = max(0.0, min(1.0, 1.0 - dist))
            results.append(
                SearchResult(
                    text=text,
                    metadata={
                        "filename": meta["filename"],
                        "page_number": meta["page_number"],
                        "chunk_index": meta["chunk_index"],
                    },
                    score=round(similarity, 4),
                )
            )
        return results

    def get_all_chunks(self) -> list[dict]:
        """Return all stored chunks as plain dicts for BM25 indexing."""
        data = self.collection.get(include=["documents", "metadatas"])
        return [
            {
                "text": doc,
                "filename": meta["filename"],
                "page_number": meta["page_number"],
                "chunk_index": meta["chunk_index"],
            }
            for doc, meta in zip(data["documents"], data["metadatas"])
        ]

    def list_documents(self) -> list[str]:
        return self.get_stats()["documents"]

    def get_stats(self) -> dict:
        data = self.collection.get(include=["metadatas"])
        metas = data["metadatas"]
        per_doc: dict[str, int] = {}
        for m in metas:
            per_doc[m["filename"]] = per_doc.get(m["filename"], 0) + 1
        return {
            "documents_indexed": len(per_doc),
            "total_chunks": len(metas),
            "chunks_per_document": per_doc,
            "documents": sorted(per_doc.keys()),
        }

    def delete_document(self, filename: str) -> None:
        self.collection.delete(where={"filename": filename})
        logger.info("action=delete_document filename=%s", filename)
