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

    def __init__(
        self,
        tokenizer: Optional[Callable[[str], int]] = None,
        max_input_tokens: Optional[int] = None,
    ):
        """
        Args:
            tokenizer: Function that returns token count for a given text.
                       If None, uses a simple whitespace-based approximation.
            max_input_tokens: Hard ceiling from the embedding model. Segment
                       sizes are clamped to it, so a stored config asking for
                       more cannot produce segments the model would truncate.
        """
        self._tokenizer = tokenizer or self._default_tokenizer
        self._max_input_tokens = max_input_tokens
        self._clamp_warned = False

    def _effective_max_tokens(self, configured: int) -> int:
        """Configured segment ceiling, bounded by what the model can embed."""
        if self._max_input_tokens and configured > self._max_input_tokens:
            # Once per segmenter — this is consulted per section, and a
            # per-section warning buries the log for a large document.
            if self._clamp_warned:
                return self._max_input_tokens
            self._clamp_warned = True
            logger.warning(
                "max_segment_tokens=%d exceeds the embedding model's limit of %d; "
                "clamping — longer segments would be truncated at embed time.",
                configured, self._max_input_tokens,
            )
            return self._max_input_tokens
        return configured

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

            if token_count <= self._effective_max_tokens(config.max_segment_tokens):
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
                max_tokens = self._effective_max_tokens(config.max_segment_tokens)
                sub_chunks = self._recursive_split_spans(
                    section_text, max_tokens, config.overlap_tokens)
                for chunk, own_start, own_end in sub_chunks:
                    chunk_tokens = self._tokenizer(chunk)
                    # The chunk's own span in the section (issues/287).
                    chunk_start = section["start"] + own_start
                    chunk_end = section["start"] + own_end
                    if chunk_tokens < config.min_segment_tokens and results:
                        # A short remainder is MERGED, never dropped. This
                        # branch used to skip it, so the tail of every
                        # oversized section under the minimum vanished from
                        # the segments -- and from search -- with no trace
                        # (issues/287). Merged only while the result still
                        # fits the embedding limit; otherwise it stands alone.
                        prev = results[-1]
                        merged_content = prev.content + "\n\n" + chunk
                        merged_tokens = self._tokenizer(merged_content)
                        if merged_tokens <= max_tokens:
                            results[-1] = SegmentResult(
                                content=merged_content,
                                segment_index=prev.segment_index,
                                start_char_offset=prev.start_char_offset,
                                end_char_offset=chunk_end,
                                token_length=merged_tokens,
                                segment_type_uri=prev.segment_type_uri,
                                heading=prev.heading,
                            )
                            continue
                    results.append(SegmentResult(
                        content=chunk,
                        segment_index=segment_index,
                        start_char_offset=chunk_start,
                        end_char_offset=chunk_end,
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
        chunks = self._recursive_split_spans(
            text, self._effective_max_tokens(config.max_segment_tokens), config.overlap_tokens
        )

        results: List[SegmentResult] = []

        for i, (chunk, own_start, own_end) in enumerate(chunks):
            token_count = self._tokenizer(chunk)
            if token_count < config.min_segment_tokens and results:
                # Merge with previous
                prev = results[-1]
                merged = prev.content + "\n\n" + chunk
                results[-1] = SegmentResult(
                    content=merged,
                    segment_index=prev.segment_index,
                    start_char_offset=prev.start_char_offset,
                    end_char_offset=own_end,
                    token_length=self._tokenizer(merged),
                    segment_type_uri=config.segment_type_uri,
                )
            else:
                results.append(SegmentResult(
                    content=chunk,
                    segment_index=i + 1,
                    start_char_offset=own_start,
                    end_char_offset=own_end,
                    token_length=token_count,
                    segment_type_uri=config.segment_type_uri,
                ))

        # Re-index
        for i, result in enumerate(results):
            result.segment_index = i + 1

        return results

    # -------------------------------------------------------------------------
    # Recursive character splitter (shared utility)
    # -------------------------------------------------------------------------

    _SEPARATORS = ["\n\n", "\n", ". ", " "]

    def _recursive_split(
        self, text: str, max_tokens: int, overlap_tokens: int = 0
    ) -> List[str]:
        """Split `text` at natural boundaries until every chunk fits.

        Hierarchy: paragraphs -> newlines -> sentences -> words, and only then
        character chunks. Overlap, when configured, is applied ONCE to the
        final chunks (`issues/287`). See `_recursive_split_spans` for offsets.
        """
        return [c for c, _s, _e in self._recursive_split_spans(text, max_tokens, overlap_tokens)]

    def _recursive_split_spans(
        self, text: str, max_tokens: int, overlap_tokens: int = 0
    ) -> List[tuple]:
        """`(content, start, end)` per chunk.

        `start`/`end` locate the chunk's OWN content in `text` -- not the overlap
        prefix borrowed from the previous chunk, which is not contiguous with it
        in the source. They used to come from `text.find(chunk)`, which returns
        -1 for an overlapped chunk and corrupted every offset after it
        (`issues/287`).
        """
        base = self._split_recursive(text, self._SEPARATORS, max_tokens)
        spans, cursor = [], 0
        for chunk in base:
            pos = text.find(chunk, cursor)
            if pos < 0:          # cannot happen for substrings; keep monotone
                pos = cursor
            spans.append((chunk, pos, pos + len(chunk)))
            cursor = pos + len(chunk)
        if overlap_tokens > 0 and len(spans) > 1:
            contents = self._apply_overlap([c for c, _s, _e in spans],
                                           overlap_tokens, max_tokens)
            spans = [(c, st, en) for c, (_c, st, en) in zip(contents, spans)]
        return spans

    def _split_recursive(
        self, text: str, separators: List[str], max_tokens: int
    ) -> List[str]:
        """Recursive implementation of character text splitting.

        Every returned chunk is a stripped SUBSTRING of `text` that fits
        `max_tokens`. Overlap is not applied here.
        """
        if not text.strip():
            return []
        if self._tokenizer(text) <= max_tokens:
            return [text.strip()]

        # The first separator that actually splits the text, trying each in
        # turn down to words. This used to stop BEFORE the word separator --
        # `remaining_separators != [" "]` -- and fall to character chunks, so a
        # paragraph with no ". " was cut mid-word (`issues/287`).
        for i, separator in enumerate(separators):
            parts = text.split(separator)
            if len(parts) > 1:
                remaining = separators[i + 1:]
                break
        else:
            return self._hard_chunk(text, max_tokens)

        chunks: List[str] = []
        current = ""
        for part in parts:
            candidate = (current + separator + part) if current else part
            if self._tokenizer(candidate) <= max_tokens:
                current = candidate
                continue
            if current.strip():
                chunks.append(current.strip())
            if self._tokenizer(part) > max_tokens:
                chunks.extend(self._split_recursive(part, remaining, max_tokens))
                current = ""
            else:
                current = part
        if current.strip():
            chunks.append(current.strip())
        return [c for c in chunks if c]

    def _hard_chunk(self, text: str, max_tokens: int) -> List[str]:
        """Character chunks for text with no separator at all, each CHECKED
        against `max_tokens` and halved until it fits.

        The size comes from an average chars-per-token estimate, which a dense
        stretch exceeds; the chunk was never re-checked, so it could go past the
        embedding limit and be truncated there (`issues/287`).
        """
        text = text.strip()
        if not text:
            return []
        if self._tokenizer(text) <= max_tokens or len(text) == 1:
            return [text]
        tokens = max(1, self._tokenizer(text))
        size = max(1, (len(text) * max_tokens) // tokens)
        out: List[str] = []
        for i in range(0, len(text), size):
            piece = text[i:i + size].strip()
            if not piece:
                continue
            if self._tokenizer(piece) <= max_tokens or len(piece) == 1:
                out.append(piece)
            else:
                mid = len(piece) // 2
                out.extend(self._hard_chunk(piece[:mid], max_tokens))
                out.extend(self._hard_chunk(piece[mid:], max_tokens))
        return out

    def _apply_overlap(self, chunks: List[str], overlap_tokens: int,
                       max_tokens: Optional[int] = None) -> List[str]:
        """Prefix each chunk with the tail of the previous one.

        Measured with the TOKENIZER, not by counting whitespace words, and
        shrunk so an overlapped chunk never exceeds `max_tokens`. It used to be
        applied at every level of recursion, compounding, and could push a chunk
        past the limit (`issues/287`).
        """
        if len(chunks) <= 1:
            return chunks
        result = [chunks[0]]
        for i in range(1, len(chunks)):
            words = chunks[i - 1].split()
            tail: List[str] = []
            for w in reversed(words):
                if self._tokenizer(" ".join([w] + tail)) > overlap_tokens:
                    break
                tail.insert(0, w)
            while tail and max_tokens is not None and \
                    self._tokenizer(" ".join(tail) + " " + chunks[i]) > max_tokens:
                tail.pop(0)
            result.append((" ".join(tail) + " " + chunks[i]) if tail else chunks[i])
        return result
