"""
KGDocument Segmentation Processor.

Takes a KGDocument object and produces the three-tier segmentation structure:
- Parent copy (marked as segmentation parent)
- N segment KGDocuments
- Edges linking parent copy → segments

The original document is never modified.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, List, Optional, Tuple, Union

from vitalgraph.document.document_segmenter import DocumentSegmenter, SegmentResult
from vitalgraph.document.segment_config import MarkdownSegmentConfig, PlainSplitConfig

logger = logging.getLogger(__name__)

# HTML tag stripping regex (simple fallback; prefer BeautifulSoup if available)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class SegmentationOutput:
    """Output of the segmentation processor."""

    parent_copy_properties: dict
    segment_properties_list: List[dict]
    edge_original_to_parent: dict
    edge_parent_to_segments: List[dict]
    method_uri: str
    segment_count: int


def strip_html(html_content: str) -> str:
    """Strip HTML tags from content. Uses BeautifulSoup if available, else regex."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_content, "html.parser")
        return soup.get_text(separator="\n")
    except ImportError:
        # Fallback to regex
        text = _HTML_TAG_RE.sub("", html_content)
        return text


def extract_content(document_properties: dict) -> Optional[str]:
    """
    Extract text content from a KGDocument using priority order:
    1. kGDocumentExtractedContent (preferred — already parsed/cleaned)
    2. kGDocumentHTMLContent (strip HTML tags)
    3. kGDocumentContent (raw text fallback)

    Args:
        document_properties: Dict of KGDocument property values (using short TS names).

    Returns:
        Extracted text content, or None if no content available.
    """
    # Priority 1: extracted content
    extracted = document_properties.get("kGDocumentExtractedContent")
    if extracted and extracted.strip():
        return extracted.strip()

    # Priority 2: HTML content (strip tags)
    html_content = document_properties.get("kGDocumentHTMLContent")
    if html_content and html_content.strip():
        return strip_html(html_content).strip()

    # Priority 3: raw document content
    raw_content = document_properties.get("kGDocumentContent")
    if raw_content and raw_content.strip():
        return raw_content.strip()

    return None


def build_parent_copy_summary(document_properties: dict, max_chars: int = 2000) -> str:
    """
    Build the summary text for the parent copy's hasKGraphDescription.

    Uses hasKGDocumentSummary if available; otherwise truncates content.

    Args:
        document_properties: Dict of KGDocument property values.
        max_chars: Maximum character length for the summary.

    Returns:
        Summary text suitable for vectorization.
    """
    headline = document_properties.get("kGDocumentHeadline", "")
    summary = document_properties.get("kGDocumentSummary", "")

    if summary:
        text = f"{headline}. {summary}" if headline else summary
        return text[:max_chars]

    # Fallback: truncate content
    content = extract_content(document_properties)
    if content:
        text = f"{headline}. {content}" if headline else content
        return text[:max_chars]

    return headline or ""


class KGDocumentSegmentationProcessor:
    """
    Processes a KGDocument into segments following the three-tier model.

    Input: Original KGDocument properties + segmentation config
    Output: SegmentationOutput containing all properties for parent copy,
            segments, and edges (ready to be converted to VitalSigns objects
            and stored in the RDF quad store).
    """

    def __init__(self, tokenizer: Optional[Callable[[str], int]] = None):
        """
        Args:
            tokenizer: Token counting function matching vector provider.
                       If None, uses whitespace approximation.
        """
        self._segmenter = DocumentSegmenter(tokenizer=tokenizer)

    def process(
        self,
        original_uri: str,
        original_properties: dict,
        config: Optional[Union[MarkdownSegmentConfig, PlainSplitConfig]] = None,
        kg_graph_uri: Optional[str] = None,
    ) -> SegmentationOutput:
        """
        Segment a KGDocument and produce the three-tier output.

        Args:
            original_uri: URI of the original KGDocument.
            original_properties: Properties dict of the original KGDocument
                                 (using short TS property names).
            config: Segmentation config. If None, auto-detects method.
            kg_graph_uri: kGGraphURI for grouping. Defaults to original_uri.

        Returns:
            SegmentationOutput with all properties for storage.

        Raises:
            ValueError: If no content can be extracted from the document.
        """
        if kg_graph_uri is None:
            kg_graph_uri = original_properties.get("kGGraphURI", original_uri)

        # Extract content
        content = extract_content(original_properties)
        if not content:
            raise ValueError(f"No content found in document {original_uri}")

        # Auto-detect config if not specified
        if config is None:
            from vitalgraph.document.document_segmenter import detect_is_markdown
            if detect_is_markdown(content):
                config = MarkdownSegmentConfig()
            else:
                config = PlainSplitConfig()

        # Run segmentation
        segments = self._segmenter.segment(content, config)
        if not segments:
            raise ValueError(f"Segmentation produced no segments for {original_uri}")

        method_uri = config.segment_method_uri
        now = datetime.now(timezone.utc).isoformat()

        # Determine parent copy URI (deterministic)
        # Use method short name in URI for multi-method coexistence
        method_suffix = method_uri.split(":")[-1] if ":" in method_uri else "segmented"
        parent_uri = f"{original_uri}_parent_{method_suffix}"

        # Build parent copy properties
        parent_summary = build_parent_copy_summary(original_properties)
        parent_copy_properties = {
            "URI": parent_uri,
            "kGGraphURI": kg_graph_uri,
            "kGDocumentContent": parent_summary,
            "kGraphDescription": parent_summary,
            "kGDocumentType": config.segment_document_type_uri,
            "kGDocumentSegmentTypeURI": "urn:segtype:segmentation_parent",
            "kGDocumentSegmentMethodURI": method_uri,
            "kGDocumentSegmentIndex": 0,
            "kGIndexDateTime": now,
            # Copy metadata from original
            "kGDocumentHeadline": original_properties.get("kGDocumentHeadline", ""),
            "kGDocumentURL": original_properties.get("kGDocumentURL", ""),
            "primaryLanguageType": original_properties.get("primaryLanguageType", ""),
            "name": original_properties.get("name", "") + f" [Segments: {method_suffix}]",
        }

        # Build segment properties
        segment_properties_list = []
        for seg in segments:
            seg_uri = f"{parent_uri}_seg_{seg.segment_index}"
            seg_props = {
                "URI": seg_uri,
                "kGGraphURI": kg_graph_uri,
                "kGDocumentContent": seg.content,
                "kGraphDescription": seg.content,
                "kGDocumentType": config.segment_document_type_uri,
                "kGDocumentSegmentMethodURI": method_uri,
                "kGDocumentSegmentTypeURI": seg.segment_type_uri,
                "kGDocumentSegmentIndex": seg.segment_index,
                "kGDocumentSegmentTokenLength": seg.token_length,
                "kGDocumentStartTokenIndex": seg.start_char_offset,
                "kGDocumentEndTokenIndex": seg.end_char_offset,
                "kGIndexDateTime": now,
                # Copy metadata from original
                "kGDocumentHeadline": seg.heading or original_properties.get("kGDocumentHeadline", ""),
                "kGDocumentURL": original_properties.get("kGDocumentURL", ""),
                "primaryLanguageType": original_properties.get("primaryLanguageType", ""),
                "name": f"Segment {seg.segment_index}: {seg.heading or ''}".strip(": "),
            }
            segment_properties_list.append(seg_props)

        # Build edge: original → parent copy
        edge_orig_to_parent = {
            "URI": f"{original_uri}_edge_to_{method_suffix}_parent",
            "edgeSource": original_uri,
            "edgeDestination": parent_uri,
            "kGGraphURI": kg_graph_uri,
            "type": "Edge_hasKGDocumentSegment",
        }

        # Build edges: parent copy → segments
        edge_parent_to_segments = []
        for seg in segments:
            seg_uri = f"{parent_uri}_seg_{seg.segment_index}"
            edge = {
                "URI": f"{parent_uri}_edge_to_seg_{seg.segment_index}",
                "edgeSource": parent_uri,
                "edgeDestination": seg_uri,
                "kGGraphURI": kg_graph_uri,
                "type": "Edge_hasKGDocumentSegment",
            }
            edge_parent_to_segments.append(edge)

        return SegmentationOutput(
            parent_copy_properties=parent_copy_properties,
            segment_properties_list=segment_properties_list,
            edge_original_to_parent=edge_orig_to_parent,
            edge_parent_to_segments=edge_parent_to_segments,
            method_uri=method_uri,
            segment_count=len(segments),
        )
