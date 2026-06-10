"""
Document segmentation engine.

Splits document text into segments using either markdown heading-based
splitting or plain recursive character splitting. Auto-detects markdown
content when no method is explicitly specified.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Union

from vitalgraph.document.segment_config import MarkdownSegmentConfig, PlainSplitConfig

logger = logging.getLogger(__name__)

# Regex to detect markdown headings (used for auto-detection)
_MARKDOWN_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)


@dataclass
class SegmentResult:
    """A single segment produced by the segmentation engine."""

    content: str
    segment_index: int  # 1-based ordinal
    start_char_offset: int
    end_char_offset: int
    token_length: int
    segment_type_uri: str
    heading: Optional[str] = None  # heading text if from markdown split


def detect_is_markdown(text: str) -> bool:
    """Auto-detect whether text contains markdown headings."""
    matches = _MARKDOWN_HEADING_RE.findall(text)
    return len(matches) >= 2


class DocumentSegmenter:
    """
    Splits document text into segments using configured strategy.

    Supports:
    - Markdown heading-based splitting (primary + secondary recursive split)
    - Plain recursive character splitting (for non-markdown content)
    - Auto-detection of markdown content

    Token counting uses a provided tokenizer function that should match
    the vector provider's tokenizer.
    """

    def __init__(self, tokenizer: Optional[Callable[[str], int]] = None):
        """
        Args:
            tokenizer: Function that returns token count for a given text.
                       If None, uses a simple whitespace-based approximation.
        """
        self._tokenizer = tokenizer or self._default_tokenizer

    @staticmethod
    def _default_tokenizer(text: str) -> int:
        """Simple whitespace token count approximation."""
        return len(text.split())

    def segment(
        self,
        text: str,
        config: Optional[Union[MarkdownSegmentConfig, PlainSplitConfig]] = None,
    ) -> List[SegmentResult]:
        """
        Segment text into chunks.

        If config is None, auto-detects markdown and uses appropriate defaults.

        Args:
            text: The document text to segment.
            config: Segmentation configuration. If None, auto-detects method.

        Returns:
            List of SegmentResult objects (1-indexed).
        """
        if not text or not text.strip():
            return []

        if config is None:
            if detect_is_markdown(text):
                config = MarkdownSegmentConfig()
            else:
                config = PlainSplitConfig()

        if isinstance(config, MarkdownSegmentConfig):
            return self._segment_markdown(text, config)
        else:
            return self._segment_plain(text, config)

    # -------------------------------------------------------------------------
    # Markdown splitting
    # -------------------------------------------------------------------------

    def _segment_markdown(
        self, text: str, config: MarkdownSegmentConfig
    ) -> List[SegmentResult]:
        """Split by markdown headings, then recursively split oversized sections."""
        sections = self._split_by_headings(text, config.heading_levels, config.preserve_heading)

        results: List[SegmentResult] = []
        segment_index = 1

        for section in sections:
            section_text = section["content"]
            section_heading = section.get("heading")
            token_count = self._tokenizer(section_text)

            if token_count <= config.max_segment_tokens:
                if token_count >= config.min_segment_tokens:
                    results.append(SegmentResult(
                        content=section_text,
                        segment_index=segment_index,
                        start_char_offset=section["start"],
                        end_char_offset=section["end"],
                        token_length=token_count,
                        segment_type_uri=config.segment_type_uri,
                        heading=section_heading,
                    ))
                    segment_index += 1
                else:
                    # Too small — merge with previous if possible
                    if results:
                        prev = results[-1]
                        merged_content = prev.content + "\n\n" + section_text
                        results[-1] = SegmentResult(
                            content=merged_content,
                            segment_index=prev.segment_index,
                            start_char_offset=prev.start_char_offset,
                            end_char_offset=section["end"],
                            token_length=self._tokenizer(merged_content),
                            segment_type_uri=prev.segment_type_uri,
                            heading=prev.heading,
                        )
                    else:
                        # First section is too small, keep it anyway
                        results.append(SegmentResult(
                            content=section_text,
                            segment_index=segment_index,
                            start_char_offset=section["start"],
                            end_char_offset=section["end"],
                            token_length=token_count,
                            segment_type_uri=config.segment_type_uri,
                            heading=section_heading,
                        ))
                        segment_index += 1
            else:
                # Oversized section — recursive split
                sub_chunks = self._recursive_split(
                    section_text,
                    config.max_segment_tokens,
                    config.overlap_tokens,
                )
                for chunk in sub_chunks:
                    chunk_tokens = self._tokenizer(chunk)
                    if chunk_tokens >= config.min_segment_tokens:
                        # Calculate approximate char offset within section
                        chunk_start = section["start"] + section_text.find(chunk)
                        results.append(SegmentResult(
                            content=chunk,
                            segment_index=segment_index,
                            start_char_offset=chunk_start,
                            end_char_offset=chunk_start + len(chunk),
                            token_length=chunk_tokens,
                            segment_type_uri="urn:segtype:paragraph",
                            heading=section_heading,
                        ))
                        segment_index += 1

        # Re-index to ensure contiguous 1-based indexing
        for i, result in enumerate(results):
            result.segment_index = i + 1

        return results

    def _split_by_headings(
        self, text: str, levels: List[int], preserve_heading: bool
    ) -> List[dict]:
        """
        Split markdown text at heading boundaries.

        Returns list of {"heading": str|None, "content": str, "start": int, "end": int}.
        """
        # Build pattern for the configured heading levels
        max_level = max(levels) if levels else 3
        pattern = re.compile(
            r"^(#{1," + str(max_level) + r"})\s+(.+)$", re.MULTILINE
        )

        sections = []
        last_end = 0
        last_heading = None

        for match in pattern.finditer(text):
            heading_level = len(match.group(1))
            if heading_level not in levels:
                continue

            heading_text = match.group(2).strip()
            heading_start = match.start()

            # Capture content before this heading as previous section
            if heading_start > last_end or sections:
                content_before = text[last_end:heading_start].strip()
                if content_before or not sections:
                    if sections:
                        # Update the last section's content
                        sections[-1]["content"] = content_before
                        sections[-1]["end"] = heading_start
                    elif content_before:
                        # Content before first heading (preamble)
                        sections.append({
                            "heading": None,
                            "content": content_before,
                            "start": 0,
                            "end": heading_start,
                        })

            # Start new section
            if preserve_heading:
                section_start = match.start()
            else:
                section_start = match.end() + 1 if match.end() < len(text) else match.end()

            sections.append({
                "heading": heading_text,
                "content": "",  # will be filled on next iteration or at end
                "start": section_start,
                "end": len(text),  # default, updated later
            })

            last_end = match.end() + 1 if match.end() < len(text) else match.end()
            last_heading = heading_text

        # Fill in the last section's content
        if sections:
            last_section = sections[-1]
            if not last_section["content"]:
                content = text[last_section["start"]:].strip()
                last_section["content"] = content
                last_section["end"] = len(text)
        else:
            # No headings found — return entire text as one section
            sections.append({
                "heading": None,
                "content": text.strip(),
                "start": 0,
                "end": len(text),
            })

        # Rebuild section content from start/end offsets for accuracy
        for i, section in enumerate(sections):
            end = sections[i + 1]["start"] if i + 1 < len(sections) else len(text)
            section["content"] = text[section["start"]:end].strip()
            section["end"] = end

        return sections

    # -------------------------------------------------------------------------
    # Plain recursive splitting
    # -------------------------------------------------------------------------

    def _segment_plain(
        self, text: str, config: PlainSplitConfig
    ) -> List[SegmentResult]:
        """Split text using recursive character splitting."""
        chunks = self._recursive_split(
            text, config.max_segment_tokens, config.overlap_tokens
        )

        results: List[SegmentResult] = []
        char_offset = 0

        for i, chunk in enumerate(chunks):
            token_count = self._tokenizer(chunk)
            if token_count < config.min_segment_tokens and results:
                # Merge with previous
                prev = results[-1]
                merged = prev.content + "\n\n" + chunk
                results[-1] = SegmentResult(
                    content=merged,
                    segment_index=prev.segment_index,
                    start_char_offset=prev.start_char_offset,
                    end_char_offset=char_offset + len(chunk),
                    token_length=self._tokenizer(merged),
                    segment_type_uri=config.segment_type_uri,
                )
            else:
                results.append(SegmentResult(
                    content=chunk,
                    segment_index=i + 1,
                    start_char_offset=char_offset,
                    end_char_offset=char_offset + len(chunk),
                    token_length=token_count,
                    segment_type_uri=config.segment_type_uri,
                ))
            # Track position (approximate due to overlap)
            chunk_pos = text.find(chunk, char_offset)
            if chunk_pos >= 0:
                char_offset = chunk_pos + len(chunk)
            else:
                char_offset += len(chunk)

        # Re-index
        for i, result in enumerate(results):
            result.segment_index = i + 1

        return results

    # -------------------------------------------------------------------------
    # Recursive character splitter (shared utility)
    # -------------------------------------------------------------------------

    def _recursive_split(
        self, text: str, max_tokens: int, overlap_tokens: int = 0
    ) -> List[str]:
        """
        Recursively split text at natural boundaries until all chunks
        fit within max_tokens.

        Split hierarchy: paragraphs → newlines → sentences → spaces.
        """
        separators = ["\n\n", "\n", ". ", " "]
        return self._split_recursive(text, separators, max_tokens, overlap_tokens)

    def _split_recursive(
        self, text: str, separators: List[str], max_tokens: int, overlap_tokens: int
    ) -> List[str]:
        """Recursive implementation of character text splitting."""
        if not text.strip():
            return []

        # If text fits, return as-is
        if self._tokenizer(text) <= max_tokens:
            return [text.strip()] if text.strip() else []

        # Find best separator
        separator = separators[0] if separators else " "
        remaining_separators = separators[1:] if len(separators) > 1 else [" "]

        # Split by separator
        parts = text.split(separator)
        if len(parts) == 1:
            if remaining_separators and remaining_separators != [" "]:
                # This separator doesn't help — try next
                return self._split_recursive(text, remaining_separators, max_tokens, overlap_tokens)
            else:
                # No separator works — hard-chunk by character count
                # Estimate chars per token from current text
                current_tokens = self._tokenizer(text)
                if current_tokens == 0:
                    return [text.strip()] if text.strip() else []
                chars_per_token = max(1, len(text) // current_tokens)
                chunk_size = max(1, max_tokens * chars_per_token)
                chunks = []
                for i in range(0, len(text), chunk_size):
                    chunk = text[i:i + chunk_size].strip()
                    if chunk:
                        chunks.append(chunk)
                return chunks

        # Merge parts into chunks that fit within max_tokens
        chunks: List[str] = []
        current_chunk = ""

        for part in parts:
            candidate = (current_chunk + separator + part) if current_chunk else part
            if self._tokenizer(candidate) <= max_tokens:
                current_chunk = candidate
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                # If single part exceeds max, recursively split it
                if self._tokenizer(part) > max_tokens:
                    sub_chunks = self._split_recursive(
                        part, remaining_separators, max_tokens, overlap_tokens
                    )
                    chunks.extend(sub_chunks)
                    current_chunk = ""
                else:
                    current_chunk = part

        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        # Apply overlap if configured
        if overlap_tokens > 0 and len(chunks) > 1:
            chunks = self._apply_overlap(chunks, overlap_tokens)

        return [c for c in chunks if c.strip()]

    def _apply_overlap(self, chunks: List[str], overlap_tokens: int) -> List[str]:
        """Add overlap between consecutive chunks."""
        if len(chunks) <= 1:
            return chunks

        result = [chunks[0]]
        for i in range(1, len(chunks)):
            # Get tail of previous chunk as overlap prefix
            prev_words = chunks[i - 1].split()
            overlap_words = prev_words[-overlap_tokens:] if len(prev_words) > overlap_tokens else prev_words
            overlap_text = " ".join(overlap_words)
            result.append(overlap_text + " " + chunks[i])

        return result
