import logging
from dataclasses import dataclass

from app.core.extraction import PageContent

logger = logging.getLogger(__name__)

CHUNK_SIZE = 512     # approximate tokens per chunk
CHUNK_OVERLAP = 50   # approximate tokens of overlap between consecutive chunks
MIN_CHUNK_TOKENS = 50  # segments smaller than this are merged with the next


@dataclass
class Chunk:
    text: str
    filename: str
    page_number: int
    chunk_index: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _approx_tokens(text: str) -> int:
    """Approximate token count using the 3.5-chars-per-token heuristic. (4 for english works well)"""
    return max(1, len(text) // 3.5) # 


def _split_text(text: str, chunk_size: int) -> list[str]:
    """Recursively split text into pieces ≤ chunk_size tokens.

    Separator hierarchy (spec §chunking.py):
      1. paragraph breaks (\\n\\n)
      2. line breaks (\\n)
      3. sentence boundaries ('. ')
      4. word boundaries (' ')
      5. raw characters (last resort)
    """
    if _approx_tokens(text) <= chunk_size:
        return [text]

    for sep in ("\n\n", "\n", ". ", " "):
        parts = [p.strip() for p in text.split(sep) if p.strip()]
        if len(parts) > 1:
            result: list[str] = []
            for part in parts:
                result.extend(_split_text(part, chunk_size))
            return result

    # Character-level fallback
    char_limit = chunk_size * 4
    return [text[i : i + char_limit] for i in range(0, len(text), char_limit)]


def _merge_small_segments(segments: list[str], min_tokens: int) -> list[str]:
    """Merge any segment smaller than *min_tokens* into the following segment."""
    if not segments:
        return []

    merged: list[str] = []
    buffer = segments[0]

    for seg in segments[1:]:
        if _approx_tokens(buffer) < min_tokens:
            buffer = buffer + " " + seg
        else:
            merged.append(buffer)
            buffer = seg

    merged.append(buffer)
    return merged


def _build_chunks_with_overlap(
    segments: list[str], chunk_size: int, chunk_overlap: int
) -> list[str]:
    """Accumulate *segments* into chunks of ≤ *chunk_size* tokens.

    When a chunk is emitted, the tail segments that fit within *chunk_overlap*
    tokens are carried over as the beginning of the next chunk.
    """
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for seg in segments:
        seg_tokens = _approx_tokens(seg)

        if current_tokens + seg_tokens > chunk_size and current:
            chunks.append("\n\n".join(current))

            # Build overlap window from the tail of the emitted chunk
            overlap: list[str] = []
            overlap_tokens = 0
            for s in reversed(current):
                t = _approx_tokens(s)
                if overlap_tokens + t <= chunk_overlap:
                    overlap.insert(0, s)
                    overlap_tokens += t
                else:
                    break

            current = overlap
            current_tokens = overlap_tokens

        current.append(seg)
        current_tokens += seg_tokens

    if current:
        chunks.append("\n\n".join(current))

    return chunks


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def chunk_pages(
    pages: list[PageContent],
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
    min_chunk_tokens: int = MIN_CHUNK_TOKENS,
) -> list[Chunk]:
    """Convert a list of PageContent objects into a flat list of Chunk objects.

    Each page is processed independently so that every chunk retains the
    correct page_number. A monotonically increasing chunk_index
    is assigned across the entire document.

    Args:
        pages: Ordered per-page content from :func:`extraction.extract_pdf`.
        chunk_size: Target maximum size of each chunk in approximate tokens.
        chunk_overlap: Number of tokens to repeat at the start of the next chunk.
        min_chunk_tokens: Segments below this size are merged with the next one.

    Returns:
        Flat list of chunks ready for embedding and indexing.
    """
    all_chunks: list[Chunk] = []
    chunk_index = 0
    filename = pages[0].filename if pages else "unknown"

    for page in pages:
        if not page.text.strip():
            continue

        segments = _split_text(page.text, chunk_size)
        segments = _merge_small_segments(segments, min_chunk_tokens)
        page_chunk_texts = _build_chunks_with_overlap(segments, chunk_size, chunk_overlap)

        for text in page_chunk_texts:
            all_chunks.append(
                Chunk(
                    text=text,
                    filename=page.filename,
                    page_number=page.page_number,
                    chunk_index=chunk_index,
                )
            )
            chunk_index += 1

    logger.info(
        "action=chunk | file=%s | chunks=%d",
        filename,
        len(all_chunks),
    )

    return all_chunks
