"""
Segmentation configuration dataclasses.

Defines the configuration for each supported segmentation method.
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class MarkdownSegmentConfig:
    """Configuration for markdown heading-based document segmentation."""

    max_segment_tokens: int = 512
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

    max_segment_tokens: int = 512
    min_segment_tokens: int = 50
    overlap_tokens: int = 0
    segment_method_uri: str = "urn:segmethod:plain_recursive_split"
    segment_type_uri: str = "urn:segtype:text_chunk"
    segment_document_type_uri: str = "urn:kgdoctype:document_segment"
