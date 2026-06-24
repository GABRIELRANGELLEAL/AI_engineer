"""
retrieval.py — Hybrid Search with Reciprocal Rank Fusion (RRF)

Combines two retrieval strategies:
  • Semantic search  (cosine similarity via ChromaDB embeddings)
  • Keyword search   (BM25 over raw chunk text)

Final ranking uses weighted RRF:
  score(doc) = β / (k + rank_semantic) + (1 − β) / (k + rank_keyword)

Default weights: β = 0.70 (semantic), 1 − β = 0.30 (keyword).
"""

import math
import re
import time
import logging
from dataclasses import dataclass, field

from app.core.embedding import EmbeddingProvider

logger = logging.getLogger(__name__)

# ── Defaults ─────────────────────────────────────────────────────────────
DEFAULT_TOP_K = 5
DEFAULT_SEARCH_POOL = 50          # candidates each strategy retrieves before fusion
DEFAULT_BETA = 0.70               # semantic weight
RRF_K = 60                        # RRF smoothing constant (standard value from the original paper)
CONFIDENCE_HIGH = 0.80
CONFIDENCE_MEDIUM = 0.60


# ── Data classes ─────────────────────────────────────────────────────────

@dataclass
class RetrievalResult:
    """A single chunk returned by the hybrid retriever."""
    text: str
    document: str
    page: int
    chunk_index: int
    rrf_score: float                        # fused RRF score (primary sort key)
    semantic_score: float | None = None     # cosine similarity (None if absent from semantic results)
    keyword_score: float | None = None      # BM25 score (None if absent from keyword results)
    semantic_rank: int | None = None
    keyword_rank: int | None = None


@dataclass
class RetrievalMetrics:
    embedding_time_ms: float
    semantic_search_time_ms: float
    keyword_search_time_ms: float
    fusion_time_ms: float
    total_time_ms: float
    top_rrf_scores: list[float]
    confidence: str
    semantic_pool_size: int
    keyword_pool_size: int
    query_language_used: str | None = None


@dataclass
class RetrievalResponse:
    results: list[RetrievalResult]
    metrics: RetrievalMetrics


# ── BM25 keyword search ─────────────────────────────────────────────────

_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "to", "of", "in", "for", "on", "with", "at", "by", "from", "as",
    "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all", "each",
    "every", "both", "few", "more", "most", "other", "some", "such", "no",
    "not", "only", "own", "same", "so", "than", "too", "very", "just",
    "and", "but", "or", "nor", "if", "it", "its", "this", "that", "these",
    "those", "i", "me", "my", "we", "our", "you", "your", "he", "him",
    "his", "she", "her", "they", "them", "their", "what", "which", "who",
    # Portuguese common stop words
    "o", "os", "um", "uma", "de", "do", "da", "dos", "das", "em", "no",
    "na", "nos", "nas", "por", "para", "com", "sem", "sob", "sobre",
    "entre", "até", "que", "se", "não", "mais", "mas", "como", "ou",
    "já", "ainda", "também", "foi", "ser", "está", "são", "tem",
    "é", "ao", "aos", "às", "pelo", "pela", "pelos", "pelas",
})

_TOKEN_RE = re.compile(r"[a-zA-Z0-9À-ÿ]+") #help with regex 


def _tokenize(text: str) -> list[str]:
    """Lowercase tokenization with stop-word removal."""
    return [
        w for w in _TOKEN_RE.findall(text.lower()) #transform the text in lower and use regex pattern to extract words
        if w not in _STOP_WORDS and len(w) > 1 # remove useless words
    ]


class _BM25Index:
    """Minimal in-memory BM25 index.

    Built from scratch (no external dependency) so the project stays lean.
    Uses the BM25-Okapi variant with standard parameters k1=1.5, b=0.75.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1 # controla saturação do TF
        self.b = b # controla normalização por tamanho do documento
        self._doc_tokens: list[list[str]] = [] # tokens de cada chunk
        self._doc_lens: list[int] = [] # quantidade de tokens por chunk
        self._avgdl: float = 0.0 # média de tokens entre todos os chunks
        self._df: dict[str, int] = {}   # em quantos chunks cada palavra aparece
        self._n: int = 0 # total de chunks

    def index(self, texts: list[str]) -> None:
        """Build the index from a list of raw texts."""
        self._doc_tokens = [_tokenize(t) for t in texts] # pega apenas palavras importantes da cada chunk
        self._doc_lens = [len(toks) for toks in self._doc_tokens] 
        self._n = len(texts)
        self._avgdl = sum(self._doc_lens) / max(self._n, 1)

        self._df = {}
        for toks in self._doc_tokens:
            seen = set(toks) # remove duplicatas DENTRO do mesmo chunk
            for term in seen:
                self._df[term] = self._df.get(term, 0) + 1

    def search(self, query: str, top_k: int = 50) -> list[tuple[int, float]]:
        """Return (doc_index, bm25_score) pairs sorted descending by score."""
        query_tokens = _tokenize(query)
        if not query_tokens or self._n == 0:
            return []

        scores: list[float] = [0.0] * self._n

        for term in query_tokens:
            df = self._df.get(term, 0)
            if df == 0:
                continue
            idf = math.log((self._n - df + 0.5) / (df + 0.5) + 1.0)

            for idx, doc_toks in enumerate(self._doc_tokens):
                tf = doc_toks.count(term)
                if tf == 0:
                    continue
                dl = self._doc_lens[idx]
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (1 - self.b + self.b * dl / self._avgdl)
                scores[idx] += idf * numerator / denominator

        ranked = [(i, s) for i, s in enumerate(scores) if s > 0]
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked[:top_k]


# ── RRF fusion ───────────────────────────────────────────────────────────

def _fuse_rrf(
    semantic_ranking: list[tuple[str, float]],
    keyword_ranking: list[tuple[str, float]],
    beta: float = DEFAULT_BETA,
    k: int = RRF_K,
) -> dict[str, dict]:
    """Reciprocal Rank Fusion across two ranked lists.

    Args:
        semantic_ranking: [(chunk_id, cosine_score), ...] in descending order.
        keyword_ranking:  [(chunk_id, bm25_score), ...]   in descending order.
        beta: weight for semantic component (1 − beta goes to keyword).
        k: smoothing constant (typically 60).

    Returns:
        dict keyed by chunk_id with rrf_score, ranks, and raw scores.
    """
    fused: dict[str, dict] = {}

    for rank, (cid, score) in enumerate(semantic_ranking, start=1):
        fused.setdefault(cid, {
            "rrf_score": 0.0,
            "semantic_score": None,
            "keyword_score": None,
            "semantic_rank": None,
            "keyword_rank": None,
        })
        fused[cid]["rrf_score"] += beta / (k + rank)
        fused[cid]["semantic_score"] = score
        fused[cid]["semantic_rank"] = rank

    for rank, (cid, score) in enumerate(keyword_ranking, start=1):
        fused.setdefault(cid, {
            "rrf_score": 0.0,
            "semantic_score": None,
            "keyword_score": None,
            "semantic_rank": None,
            "keyword_rank": None,
        })
        fused[cid]["rrf_score"] += (1 - beta) / (k + rank)
        fused[cid]["keyword_score"] = score
        fused[cid]["keyword_rank"] = rank

    return fused


# ── Confidence classification ────────────────────────────────────────────

def _classify_confidence(top_semantic_score: float | None) -> str:
    """Uses the best cosine similarity to classify confidence.

    RRF scores are not on a 0–1 scale so they are poor confidence
    indicators.  The raw cosine similarity from the top semantic
    hit gives a meaningful signal.
    """
    if top_semantic_score is None:
        return "low"
    if top_semantic_score > CONFIDENCE_HIGH:
        return "high"
    if top_semantic_score >= CONFIDENCE_MEDIUM:
        return "medium"
    return "low"


# ── Metadata filter ──────────────────────────────────────────────────────

def _apply_metadata_filter(
    results: list[RetrievalResult],
    filter_filenames: list[str] | None = None,
) -> list[RetrievalResult]:
    """Optional post-fusion metadata filter (as shown in the diagram).

    Supports filtering by document name for now; easily extensible
    to page ranges, date filters, etc.
    """
    if not filter_filenames:
        return results
    allowed = set(filter_filenames)
    return [r for r in results if r.document in allowed]


# ── Main public API ──────────────────────────────────────────────────────

async def retrieve(
    question: str,
    embedding_provider: EmbeddingProvider,
    vector_store,                          # VectorStore instance (duck-typed)
    top_k: int = DEFAULT_TOP_K,
    search_pool: int = DEFAULT_SEARCH_POOL,
    beta: float = DEFAULT_BETA,
    filter_filenames: list[str] | None = None,
) -> RetrievalResponse:
    """Hybrid retrieval pipeline.

    Flow (mirrors the diagram):
      1. Generate query embedding
      2. Semantic search   → pool of candidates (search_pool size)
      3. Keyword search    → pool of candidates (search_pool size)
      4. Metadata filter   → remove unwanted documents from each pool
      5. RRF fusion        → merge both pools into a single ranking
      6. Return top_k      → final results with scores and metrics

    Args:
        question:           User's natural-language question.
        embedding_provider: Must be the same provider used at indexing time.
        vector_store:       ChromaDB wrapper exposing search() and get_all_chunks().
        top_k:              Number of final results to return.
        search_pool:        How many candidates each strategy retrieves before fusion.
        beta:               Semantic weight in RRF (default 0.70).
        filter_filenames:   Optional list of filenames to restrict results to.

    Returns:
        RetrievalResponse with ranked results and timing metrics.
    """
    total_start = time.perf_counter()

    # ── 1. Query embedding ───────────────────────────────────────────
    embed_start = time.perf_counter()
    query_embedding = (await embedding_provider.embed([question]))[0]
    embedding_time_ms = (time.perf_counter() - embed_start) * 1000

    # ── 2. Semantic search (ChromaDB cosine similarity) ──────────────
    sem_start = time.perf_counter()
    semantic_raw = vector_store.search(
        query_embedding=query_embedding,
        top_k=search_pool,
    )
    semantic_time_ms = (time.perf_counter() - sem_start) * 1000

    # Build a chunk_id → metadata lookup from the semantic results
    chunk_meta: dict[str, dict] = {}
    semantic_ranking: list[tuple[str, float]] = []

    for hit in semantic_raw:
        cid = f"{hit.metadata['filename']}::{hit.metadata['chunk_index']}"
        chunk_meta[cid] = {
            "text": hit.text,
            "document": hit.metadata["filename"],
            "page": hit.metadata["page_number"],
            "chunk_index": hit.metadata["chunk_index"],
        }
        semantic_ranking.append((cid, hit.score))

    # ── 3. Keyword search (BM25) ────────────────────────────────────
    kw_start = time.perf_counter()

    all_chunks = vector_store.get_all_chunks()
    bm25 = _BM25Index()
    bm25.index([c["text"] for c in all_chunks])

    bm25_hits = bm25.search(question, top_k=search_pool)

    keyword_ranking: list[tuple[str, float]] = []
    for doc_idx, bm25_score in bm25_hits:
        c = all_chunks[doc_idx]
        cid = f"{c['filename']}::{c['chunk_index']}"
        chunk_meta.setdefault(cid, {
            "text": c["text"],
            "document": c["filename"],
            "page": c["page_number"],
            "chunk_index": c["chunk_index"],
        })
        keyword_ranking.append((cid, bm25_score))

    keyword_time_ms = (time.perf_counter() - kw_start) * 1000

    # ── 4. RRF fusion ────────────────────────────────────────────────
    fusion_start = time.perf_counter()
    fused = _fuse_rrf(semantic_ranking, keyword_ranking, beta=beta)

    # Build result objects sorted by rrf_score descending
    results: list[RetrievalResult] = []
    for cid, scores in fused.items():
        meta = chunk_meta[cid]
        results.append(RetrievalResult(
            text=meta["text"],
            document=meta["document"],
            page=meta["page"],
            chunk_index=meta["chunk_index"],
            rrf_score=scores["rrf_score"],
            semantic_score=scores["semantic_score"],
            keyword_score=scores["keyword_score"],
            semantic_rank=scores["semantic_rank"],
            keyword_rank=scores["keyword_rank"],
        ))

    results.sort(key=lambda r: r.rrf_score, reverse=True)

    # ── 5. Metadata filter ───────────────────────────────────────────
    results = _apply_metadata_filter(results, filter_filenames)

    # ── 6. Trim to top_k ────────────────────────────────────────────
    results = results[:top_k]

    fusion_time_ms = (time.perf_counter() - fusion_start) * 1000
    total_time_ms = (time.perf_counter() - total_start) * 1000

    # ── Metrics ──────────────────────────────────────────────────────
    top_semantic = semantic_ranking[0][1] if semantic_ranking else None
    confidence = _classify_confidence(top_semantic)

    metrics = RetrievalMetrics(
        embedding_time_ms=round(embedding_time_ms, 1),
        semantic_search_time_ms=round(semantic_time_ms, 1),
        keyword_search_time_ms=round(keyword_time_ms, 1),
        fusion_time_ms=round(fusion_time_ms, 1),
        total_time_ms=round(total_time_ms, 1),
        top_rrf_scores=[round(r.rrf_score, 6) for r in results],
        confidence=confidence,
        semantic_pool_size=len(semantic_ranking),
        keyword_pool_size=len(keyword_ranking),
    )

    # ── Structured logging ───────────────────────────────────────────
    logger.info(
        "action=retrieve | question=%r | strategy=hybrid_rrf | beta=%.2f | "
        "top_k=%d | semantic_pool=%d | keyword_pool=%d | "
        "top_rrf=%.6f | top_cosine=%s | confidence=%s | "
        "embed_ms=%.1f | sem_ms=%.1f | kw_ms=%.1f | fusion_ms=%.1f | total_ms=%.1f",
        question[:80],
        beta,
        top_k,
        len(semantic_ranking),
        len(keyword_ranking),
        results[0].rrf_score if results else 0.0,
        f"{top_semantic:.4f}" if top_semantic is not None else "N/A",
        confidence,
        embedding_time_ms,
        semantic_time_ms,
        keyword_time_ms,
        fusion_time_ms,
        total_time_ms,
    )

    return RetrievalResponse(results=results, metrics=metrics)


async def retrieve_bilingual(
    question: str,
    embedding_provider: EmbeddingProvider,
    vector_store,
    translated_question: str | None = None,
    top_k: int = DEFAULT_TOP_K,
    search_pool: int = DEFAULT_SEARCH_POOL,
    beta: float = DEFAULT_BETA,
    filter_filenames: list[str] | None = None,
) -> RetrievalResponse:
    """Hybrid retrieval over both the original and translated question.

    Runs retrieve() for the original question and, if a translation is
    available, for the translated question too.  Results are merged by
    chunk ID keeping the highest RRF score, then re-sorted and trimmed
    to top_k.  Metrics are taken from the primary (original) retrieval.
    """
    primary = await retrieve(
        question=question,
        embedding_provider=embedding_provider,
        vector_store=vector_store,
        top_k=top_k,
        search_pool=search_pool,
        beta=beta,
        filter_filenames=filter_filenames,
    )

    if not translated_question:
        primary.metrics.query_language_used = "original"
        return primary

    secondary = await retrieve(
        question=translated_question,
        embedding_provider=embedding_provider,
        vector_store=vector_store,
        top_k=top_k,
        search_pool=search_pool,
        beta=beta,
        filter_filenames=filter_filenames,
    )

    # Merge by chunk ID, keeping the best RRF score from either retrieval
    merged: dict[str, RetrievalResult] = {}
    for r in primary.results:
        cid = f"{r.document}::{r.chunk_index}"
        merged[cid] = r

    for r in secondary.results:
        cid = f"{r.document}::{r.chunk_index}"
        if cid not in merged or r.rrf_score > merged[cid].rrf_score:
            merged[cid] = r

    final_results = sorted(merged.values(), key=lambda r: r.rrf_score, reverse=True)[:top_k]

    primary.metrics.query_language_used = "bilingual"
    primary.metrics.top_rrf_scores = [round(r.rrf_score, 6) for r in final_results]
    primary.metrics.total_time_ms = round(
        primary.metrics.total_time_ms + secondary.metrics.total_time_ms, 1
    )

    return RetrievalResponse(results=final_results, metrics=primary.metrics)