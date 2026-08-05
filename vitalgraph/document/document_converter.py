"""
Document → Markdown conversion for upload ingest.

Uploaded documents segment far better as Markdown: the segmenter's
``detect_is_markdown`` picks ``markdown_heading_split`` when it sees two or more
heading lines, and falls back to a paragraph heuristic otherwise. Converting on
ingest is therefore what turns a PDF or a Word file into something the
heading-based splitter can use.

Library choices are constrained by licence. This project ships under Apache-2.0,
so the AGPL (``pymupdf``) and GPL (``html2text``) options are deliberately
excluded. What is used here:

- HTML  → ``markdownify``  (MIT)
- DOCX  → ``mammoth`` → HTML → ``markdownify``  (BSD-2 + MIT)
- PDF   → ``pdfplumber``  (MIT)
- MD/TXT → passthrough (already text)

**Failure policy: loud, not silent.** ``strip_html`` in the segmentation
processor historically swallowed a missing ``bs4`` and quietly produced worse
output, which meant nobody noticed the downgrade for a long time (see
issues/018). Conversion here raises ``ConversionError`` instead — the caller
decides whether to store the raw bytes, tell the user, or fail the upload.
"""

import io
import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


class ConversionError(Exception):
    """Raised when a document cannot be converted to Markdown."""


# Formats we can convert or pass through. Anything else is rejected up front
# rather than being stored as mojibake.
EXT_HTML = {".html", ".htm", ".xhtml"}
EXT_DOCX = {".docx"}
EXT_PDF = {".pdf"}
EXT_MARKDOWN = {".md", ".markdown"}
EXT_PLAIN = {".txt", ".csv", ".json", ".log", ".text"}

SUPPORTED_EXTENSIONS = EXT_HTML | EXT_DOCX | EXT_PDF | EXT_MARKDOWN | EXT_PLAIN

# Formats that arrive as bytes we must parse rather than decode.
BINARY_EXTENSIONS = EXT_DOCX | EXT_PDF

_MARKDOWN_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)

# Collapse the runs of blank lines that converters tend to emit.
_EXCESS_BLANK_LINES_RE = re.compile(r"\n{3,}")


@dataclass
class ConversionResult:
    """Outcome of converting one uploaded document."""

    markdown: str
    """Converted (or passed-through) Markdown text."""

    source_format: str
    """Normalised extension the conversion was performed for, e.g. ``.pdf``."""

    converted: bool
    """False when the input was already text and was passed through unchanged."""

    original_html: Optional[str] = None
    """Original HTML, when the source was HTML — preserved for hasKGDocumentHTMLContent."""

    heading_count: int = 0
    """Number of Markdown heading lines in the result. Two or more means the
    segmenter will choose the heading-based split."""


def normalise_extension(filename: str) -> str:
    """Lowercase extension including the dot, or '' when there is none."""
    if "." not in filename:
        return ""
    return "." + filename.rsplit(".", 1)[1].lower()


def is_supported(filename: str) -> bool:
    return normalise_extension(filename) in SUPPORTED_EXTENSIONS


def _tidy(markdown: str) -> str:
    """Normalise line endings and collapse excess blank lines."""
    text = markdown.replace("\r\n", "\n").replace("\r", "\n")
    text = _EXCESS_BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


def _decode_text(data: bytes) -> str:
    """Decode text input, falling back to latin-1 so we never lose the body."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        logger.warning("Upload was not valid UTF-8; decoding as latin-1")
        return data.decode("latin-1", errors="replace")


def html_to_markdown(html: str) -> str:
    """Convert an HTML string to Markdown, preserving heading structure."""
    try:
        from markdownify import markdownify
    except ImportError as e:  # pragma: no cover - dependency is declared
        raise ConversionError(
            "markdownify is required for HTML conversion but is not installed"
        ) from e

    # ATX headings ('# Foo') are what detect_is_markdown looks for; the
    # underline style would not be recognised.
    return _tidy(markdownify(html, heading_style="ATX"))


def docx_to_markdown(data: bytes) -> str:
    """Convert DOCX bytes to Markdown via mammoth's semantic HTML."""
    try:
        import mammoth
    except ImportError as e:  # pragma: no cover - dependency is declared
        raise ConversionError(
            "mammoth is required for DOCX conversion but is not installed"
        ) from e

    try:
        # mammoth maps Word heading STYLES to <h1>..<h6>, which is why DOCX
        # survives the trip with real headings rather than bold paragraphs.
        result = mammoth.convert_to_html(io.BytesIO(data))
    except Exception as e:
        raise ConversionError(f"DOCX conversion failed: {e}") from e

    for message in result.messages:
        logger.debug("mammoth: %s", message)

    return html_to_markdown(result.value)


def pdf_to_markdown(data: bytes) -> str:
    """
    Extract PDF text as Markdown.

    pdfplumber gives text and layout, not semantics — a PDF carries no heading
    markup, so headings cannot be recovered reliably. Pages are emitted with a
    ``## Page N`` heading so the result still has structure the heading splitter
    can use, and so segment boundaries line up with pages.
    """
    try:
        import pdfplumber
    except ImportError as e:  # pragma: no cover - dependency is declared
        raise ConversionError(
            "pdfplumber is required for PDF conversion but is not installed"
        ) from e

    parts = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                text = (page.extract_text() or "").strip()
                if text:
                    parts.append(f"## Page {page_number}\n\n{text}")
    except ConversionError:
        raise
    except Exception as e:
        raise ConversionError(f"PDF conversion failed: {e}") from e

    if not parts:
        # A scanned PDF has no text layer. Say so plainly rather than storing an
        # empty document that later looks like a segmentation bug.
        raise ConversionError(
            "PDF contains no extractable text (it may be a scanned image; OCR is not supported)"
        )

    return _tidy("\n\n".join(parts))


def convert_to_markdown(data: bytes, filename: str) -> ConversionResult:
    """
    Convert an uploaded document to Markdown.

    Args:
        data: Raw uploaded bytes.
        filename: Original filename — the extension selects the converter.

    Returns:
        ConversionResult with the Markdown and what was done to produce it.

    Raises:
        ConversionError: unsupported extension, or the converter failed.
    """
    ext = normalise_extension(filename)

    if ext not in SUPPORTED_EXTENSIONS:
        raise ConversionError(
            f"Unsupported file type '{ext or filename}'. Supported: "
            + ", ".join(sorted(SUPPORTED_EXTENSIONS))
        )

    if ext in EXT_HTML:
        html = _decode_text(data)
        markdown = html_to_markdown(html)
        return ConversionResult(
            markdown=markdown,
            source_format=ext,
            converted=True,
            original_html=html,
            heading_count=len(_MARKDOWN_HEADING_RE.findall(markdown)),
        )

    if ext in EXT_DOCX:
        markdown = docx_to_markdown(data)
        return ConversionResult(
            markdown=markdown,
            source_format=ext,
            converted=True,
            heading_count=len(_MARKDOWN_HEADING_RE.findall(markdown)),
        )

    if ext in EXT_PDF:
        markdown = pdf_to_markdown(data)
        return ConversionResult(
            markdown=markdown,
            source_format=ext,
            converted=True,
            heading_count=len(_MARKDOWN_HEADING_RE.findall(markdown)),
        )

    # .md / .txt and friends: already text, so store as-is. Converting plain
    # text would only invent structure that is not there.
    text = _tidy(_decode_text(data))
    return ConversionResult(
        markdown=text,
        source_format=ext,
        converted=False,
        heading_count=len(_MARKDOWN_HEADING_RE.findall(text)),
    )
