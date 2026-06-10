"""
KGDocument segmentation and processing.

Provides document splitting strategies for creating indexed segments
from KGDocument objects, supporting vector similarity search over
document chunks.
"""

from vitalgraph.document.document_segmenter import (
    DocumentSegmenter,
    SegmentResult,
)
from vitalgraph.document.segment_config import (
    MarkdownSegmentConfig,
    PlainSplitConfig,
)
from vitalgraph.document.kgdocument_segmentation_processor import (
    KGDocumentSegmentationProcessor,
    SegmentationOutput,
    extract_content,
    build_parent_copy_summary,
)
from vitalgraph.document.auto_segmentation import AutoSegmentationHook
from vitalgraph.document.vector_index_setup import (
    setup_document_segments_vectorization,
    DOCUMENT_SEGMENTS_INDEX_NAME,
)

__all__ = [
    "DocumentSegmenter",
    "SegmentResult",
    "MarkdownSegmentConfig",
    "PlainSplitConfig",
    "KGDocumentSegmentationProcessor",
    "SegmentationOutput",
    "extract_content",
    "build_parent_copy_summary",
    "AutoSegmentationHook",
    "setup_document_segments_vectorization",
    "DOCUMENT_SEGMENTS_INDEX_NAME",
]
