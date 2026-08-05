"""
Segmentation configuration dataclasses.

Defines the configuration for each supported segmentation method.
"""

from dataclasses import dataclass, field
from typing import List

# Default segment ceiling, in embedding-model tokens.
#
# MUST NOT exceed the embedding model's own input limit: anything longer is
# truncated at embed time and its tail never reaches the vector, silently. The
# bundled local model (paraphrase-MiniLM) accepts 512, which is also what
# `segmentation_config_manager` already defaults stored configs to. This was
# 1024 — double the model's limit — which went unnoticed because the token count
# was measured with a whitespace approximation that under-reported by ~30%.
#
# Providers report their own ceiling via `max_input_tokens`, and segmentation
# clamps to it at runtime, so this is a default rather than a hard cap: a
# larger-context provider (OpenAI accepts 8191) can be configured higher.
DEFAULT_MAX_SEGMENT_TOKENS = 512


@dataclass
class MarkdownSegmentConfig:
    """Configuration for markdown heading-based document segmentation."""

    max_segment_tokens: int = DEFAULT_MAX_SEGMENT_TOKENS
    min_segment_tokens: int = 50
    overlap_tokens: int = 0
    heading_levels: List[int] = field(default_factory=lambda: [1, 2, 3])
    preserve_heading: bool = True
    segment_method_uri: str = "urn:segmethod:markdown_heading_split"
    segment_type_uri: str = "urn:segtype:markdown_section"
    segment_document_type_uri: str = "urn:kgdoctype:document_segment"


@dataclass
class PlainSplitConfig:
    """Configuration for plain recursive character-based document segmentation."""

    max_segment_tokens: int = DEFAULT_MAX_SEGMENT_TOKENS
    min_segment_tokens: int = 50
    overlap_tokens: int = 0
    segment_method_uri: str = "urn:segmethod:plain_recursive_split"
    segment_type_uri: str = "urn:segtype:text_chunk"
    segment_document_type_uri: str = "urn:kgdoctype:document_segment"
