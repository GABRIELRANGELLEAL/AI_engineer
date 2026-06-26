import re
import logging
from dataclasses import dataclass
from collections import Counter

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


@dataclass
class PageContent:
    """Cleaned text extracted from a single PDF page.

    Attributes:
        page_number: 1-based page index within the source document.
        text: Cleaned plain text (headers/footers removed, whitespace normalised).
        filename: Original filename of the source PDF.
    """

    page_number: int
    text: str
    filename: str


@dataclass
class ExtractionResult:
    """Outcome of processing a single PDF file.

    Attributes:
        pages: Ordered list of per-page content objects.
        filename: Original filename of the source PDF.
        total_pages: Total number of pages in the document.
        has_extractable_text: False when the PDF contains only scanned images.
        warning: Human-readable message set when extraction was partial or failed.
        detected_language: ISO-639-1 code inferred from document text ("pt" or "en").
    """

    pages: list[PageContent]
    filename: str
    total_pages: int
    has_extractable_text: bool
    warning: str | None = None
    detected_language: str = "en"


_PT_WORDS = frozenset({
    "de", "do", "da", "dos", "das", "em", "no", "na", "nos", "nas",
    "um", "uma", "uns", "umas", "para", "com", "por", "que", "não",
    "mais", "mas", "como", "quando", "também", "está", "são", "foi",
    "ser", "ter", "ele", "ela", "eles", "elas", "isso", "este", "essa",
    "esse", "aqui", "muito", "pode", "deve", "sobre", "entre", "após",
    "sendo", "assim", "onde", "qual", "quais", "pelo", "pela",
})

_EN_WORDS = frozenset({
    "the", "and", "for", "are", "but", "not", "you", "all", "can",
    "her", "was", "one", "our", "out", "had", "has", "have", "with",
    "this", "that", "from", "they", "will", "been", "which", "when",
    "there", "their", "what", "your", "said", "each", "about", "into",
    "than", "then", "these", "some", "would", "could", "should", "may",
    "also", "its", "only", "over", "such", "use", "how", "both",
})


def _detect_language(text: str) -> str:
    """Heuristic language detection based on word frequency and diacritics.

    Samples up to 500 words from the text, counts matches against PT and EN
    stop-word sets, and applies a diacritic boost for characters exclusive to
    Portuguese (ã, õ, ç, etc.).  No external dependency required.

    Returns:
        "pt" if Portuguese signals dominate, "en" otherwise.
    """
    words = re.findall(r"[a-zA-ZÀ-ÿ]+", text.lower())
    if not words:
        return "en"

    sample = words[:500]
    pt_count = sum(1 for w in sample if w in _PT_WORDS)
    en_count = sum(1 for w in sample if w in _EN_WORDS)

    diacritics = len(re.findall(r"[ãõçáéíóúâêôàü]", text[:2000]))
    pt_count += diacritics * 2

    return "pt" if pt_count > en_count else "en"


def _detect_repeated_lines(raw_pages: list[tuple[int, str]], threshold: float = 0.6) -> set[str]:
    """Return lines that appear on more than ``threshold`` fraction of pages.

    Lines that repeat across most pages are almost certainly headers or footers.
    The heuristic is intentionally skipped for very short documents (< 3 pages)
    where repetition is expected and legitimate.

    Args:
        raw_pages: List of ``(1-based page number, raw text)`` tuples.
        threshold: Fraction of pages a line must appear on to be flagged.
            Defaults to 0.6 (appears on at least 60 % of pages).

    Returns:
        Set of stripped line strings to exclude during cleaning.
    """
    if len(raw_pages) < 3:
        return set()

    line_counts: Counter[str] = Counter()
    for _, text in raw_pages:
        # Only consider short lines (headers/footers are rarely long paragraphs)
        lines = {ln.strip() for ln in text.splitlines() if 3 < len(ln.strip()) < 120}
        line_counts.update(lines)

    min_occurrences = max(2, int(len(raw_pages) * threshold))
    return {line for line, count in line_counts.items() if count >= min_occurrences}


def _clean_text(text: str, remove_lines: set[str]) -> str:
    """Strip repeated header/footer lines and normalise whitespace.

    Args:
        text: Raw page text as returned by PyMuPDF.
        remove_lines: Stripped line strings that should be dropped (headers/footers).

    Returns:
        Cleaned text, or an empty string if nothing remains after filtering.
    """
    lines = text.splitlines()
    filtered = [ln for ln in lines if ln.strip() not in remove_lines]
    joined = "\n".join(filtered)

    # Normalize whitespace: collapse runs of spaces/tabs, keep single newlines
    joined = re.sub(r"[ \t]+", " ", joined)
    # Collapse 3+ consecutive newlines into two (preserve paragraph breaks)
    joined = re.sub(r"\n{3,}", "\n\n", joined)

    return joined.strip()


def extract_pdf(file_bytes: bytes, filename: str) -> ExtractionResult:
    """Extract and clean text from a PDF supplied as raw bytes.

    Reads every page with PyMuPDF, detects repeated headers/footers across
    pages, strips them, and normalises whitespace.  If the PDF contains no
    selectable text (scanned images only), returns an empty result with a
    human-readable warning instead of raising.

    Args:
        file_bytes: Raw PDF content — typically the bytes read from an upload.
        filename: Original filename; stored in every returned ``PageContent``
            and used in log messages.

    Returns:
        An ``ExtractionResult`` with ``has_extractable_text=False`` and a
        ``warning`` message for scanned PDFs, or a fully populated result
        otherwise.
    """
    with fitz.open(stream=file_bytes, filetype="pdf") as doc:
        total_pages = len(doc)

        raw_pages: list[tuple[int, str]] = []
        for page in doc:
            text = page.get_text("text")
            raw_pages.append((page.number + 1, text))

    total_text = "".join(t for _, t in raw_pages)
    if not total_text.strip():
        logger.warning("action=extract | file=%s | no_extractable_text=true", filename)
        return ExtractionResult(
            pages=[],
            filename=filename,
            total_pages=total_pages,
            has_extractable_text=False,
            warning=(
                f"'{filename}' appears to be a scanned PDF with no extractable text. "
                "OCR is required to process this document."
            ),
        )

    headers_footers = _detect_repeated_lines(raw_pages)

    pages: list[PageContent] = []
    for page_number, text in raw_pages:
        cleaned = _clean_text(text, headers_footers)
        if cleaned:
            pages.append(PageContent(page_number=page_number, text=cleaned, filename=filename))

    detected_language = _detect_language(total_text)

    logger.info(
        "action=extract | file=%s | pages=%d | extracted_pages=%d | language=%s",
        filename,
        total_pages,
        len(pages),
        detected_language,
    )

    return ExtractionResult(
        pages=pages,
        filename=filename,
        total_pages=total_pages,
        has_extractable_text=True,
        detected_language=detected_language,
    )


