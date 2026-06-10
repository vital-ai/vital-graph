"""
Test script for KGDocument Segmentation Processor.

Verifies the three-tier model output (parent copy + segments + edges).
"""

import sys
sys.path.insert(0, "/Users/hadfield/Local/vital-git/vital-graph")

from vitalgraph.document.kgdocument_segmentation_processor import (
    KGDocumentSegmentationProcessor,
    SegmentationOutput,
    extract_content,
    build_parent_copy_summary,
    strip_html,
)
from vitalgraph.document.segment_config import MarkdownSegmentConfig, PlainSplitConfig


def test_extract_content_priority():
    """Test content extraction priority order."""
    # All three present — extracted wins
    props = {
        "kGDocumentExtractedContent": "extracted text",
        "kGDocumentHTMLContent": "<p>html text</p>",
        "kGDocumentContent": "raw text",
    }
    assert extract_content(props) == "extracted text"

    # Only HTML and raw
    props = {
        "kGDocumentHTMLContent": "<p>html text</p>",
        "kGDocumentContent": "raw text",
    }
    result = extract_content(props)
    assert "html text" in result

    # Only raw
    props = {"kGDocumentContent": "raw text"}
    assert extract_content(props) == "raw text"

    # Empty
    assert extract_content({}) is None
    print("✅ test_extract_content_priority passed")


def test_strip_html():
    """Test HTML stripping."""
    html = "<h1>Title</h1><p>Hello <b>world</b>.</p>"
    result = strip_html(html)
    assert "Title" in result
    assert "Hello" in result
    assert "world" in result
    assert "<" not in result
    print("✅ test_strip_html passed")


def test_build_parent_copy_summary():
    """Test parent copy summary generation."""
    # With summary
    props = {
        "kGDocumentHeadline": "My Paper",
        "kGDocumentSummary": "This paper discusses important findings.",
    }
    result = build_parent_copy_summary(props)
    assert "My Paper" in result
    assert "important findings" in result

    # Without summary — falls back to truncated content
    props = {
        "kGDocumentHeadline": "Article",
        "kGDocumentContent": "Full content of the article goes here.",
    }
    result = build_parent_copy_summary(props)
    assert "Article" in result
    assert "Full content" in result
    print("✅ test_build_parent_copy_summary passed")


def test_processor_markdown():
    """Test full processor with markdown content."""
    processor = KGDocumentSegmentationProcessor()

    original_uri = "urn:doc:test_article_001"
    original_props = {
        "kGGraphURI": "urn:entitygraph:entity_001",
        "kGDocumentContent": """# Introduction

This paper presents novel research findings in the field.
We explore multiple dimensions of the problem.

## Methods

Our methodology involves careful data collection.
We used validated instruments to gather data.

## Results

The results show significant improvements.
Statistical analysis confirms our hypothesis.

## Conclusion

We conclude that our approach is effective.
Future work will expand on these findings.
""",
        "kGDocumentHeadline": "Research Paper on Novel Findings",
        "kGDocumentURL": "https://example.com/paper",
        "kGDocumentSummary": "A paper about novel research findings.",
        "name": "Test Article",
        "primaryLanguageType": "urn:lang:en",
    }

    config = MarkdownSegmentConfig(max_segment_tokens=50, min_segment_tokens=5)
    output = processor.process(original_uri, original_props, config)

    print(f"\n📄 Processor output:")
    print(f"  Method: {output.method_uri}")
    print(f"  Segment count: {output.segment_count}")
    print(f"  Parent URI: {output.parent_copy_properties['URI']}")
    print(f"  Parent kGGraphURI: {output.parent_copy_properties['kGGraphURI']}")
    print(f"  Parent segmentType: {output.parent_copy_properties['kGDocumentSegmentTypeURI']}")
    print(f"  Edge orig→parent: {output.edge_original_to_parent['edgeSource']} → {output.edge_original_to_parent['edgeDestination']}")

    for seg in output.segment_properties_list[:3]:
        print(f"  Segment [{seg['kGDocumentSegmentIndex']}]: {seg['URI']}")
        print(f"    tokens={seg['kGDocumentSegmentTokenLength']}, type={seg['kGDocumentSegmentTypeURI']}")
        print(f"    content={seg['kGDocumentContent'][:50]}...")

    # Assertions
    assert output.segment_count >= 3, f"Expected >= 3 segments, got {output.segment_count}"
    assert output.parent_copy_properties["kGGraphURI"] == "urn:entitygraph:entity_001"
    assert output.parent_copy_properties["kGDocumentSegmentIndex"] == 0
    assert output.parent_copy_properties["kGDocumentSegmentTypeURI"] == "urn:segtype:segmentation_parent"
    assert output.edge_original_to_parent["edgeSource"] == original_uri
    assert output.edge_original_to_parent["edgeDestination"] == output.parent_copy_properties["URI"]
    assert len(output.edge_parent_to_segments) == output.segment_count
    for edge in output.edge_parent_to_segments:
        assert edge["edgeSource"] == output.parent_copy_properties["URI"]
        assert edge["kGGraphURI"] == "urn:entitygraph:entity_001"
    for seg in output.segment_properties_list:
        assert seg["kGGraphURI"] == "urn:entitygraph:entity_001"
        assert seg["kGDocumentSegmentMethodURI"] == "urn:segmethod:markdown_heading_split"
        assert seg["kGDocumentSegmentIndex"] > 0
    print("✅ test_processor_markdown passed")


def test_processor_plain():
    """Test full processor with plain text content."""
    processor = KGDocumentSegmentationProcessor()

    original_uri = "urn:doc:plain_001"
    paragraphs = [
        f"Paragraph {i}: This contains detailed information about topic {i}. "
        f"The content is rich enough to be split into meaningful chunks."
        for i in range(10)
    ]
    original_props = {
        "kGDocumentContent": "\n\n".join(paragraphs),
        "kGDocumentHeadline": "Plain Document",
        "name": "Plain Doc",
    }

    config = PlainSplitConfig(max_segment_tokens=40, min_segment_tokens=5)
    output = processor.process(original_uri, original_props, config)

    print(f"\n📄 Plain processor output:")
    print(f"  Segment count: {output.segment_count}")
    print(f"  Method: {output.method_uri}")

    assert output.segment_count >= 2
    assert output.method_uri == "urn:segmethod:plain_recursive_split"
    for seg in output.segment_properties_list:
        assert seg["kGDocumentSegmentTypeURI"] == "urn:segtype:text_chunk"
    print("✅ test_processor_plain passed")


def test_processor_auto_detect():
    """Test processor with auto-detection."""
    processor = KGDocumentSegmentationProcessor()

    # Markdown content — should auto-detect
    md_props = {
        "kGDocumentContent": "# Title\nSome content.\n\n## Section\nMore content here.\n\n## Another\nEven more.",
        "name": "Auto MD",
    }
    output = processor.process("urn:doc:auto_md", md_props)
    assert output.method_uri == "urn:segmethod:markdown_heading_split"
    print(f"  Auto-detected markdown: {output.segment_count} segments")

    # Plain content — should auto-detect
    plain_props = {
        "kGDocumentContent": "First paragraph.\n\nSecond paragraph.\n\nThird paragraph.\n\nFourth paragraph.",
        "name": "Auto Plain",
    }
    output = processor.process("urn:doc:auto_plain", plain_props)
    assert output.method_uri == "urn:segmethod:plain_recursive_split"
    print(f"  Auto-detected plain: {output.segment_count} segments")
    print("✅ test_processor_auto_detect passed")


def test_processor_no_content():
    """Test processor raises on empty content."""
    processor = KGDocumentSegmentationProcessor()
    try:
        processor.process("urn:doc:empty", {})
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "No content" in str(e)
    print("✅ test_processor_no_content passed")


def test_multi_method_coexistence():
    """Test that different methods produce different URIs."""
    processor = KGDocumentSegmentationProcessor()

    original_uri = "urn:doc:multi_method"
    props = {
        "kGDocumentContent": "# A\nContent A.\n\n## B\nContent B.\n\n## C\nContent C.",
        "name": "Multi",
    }

    md_output = processor.process(original_uri, props, MarkdownSegmentConfig())
    plain_output = processor.process(original_uri, props, PlainSplitConfig())

    # Parent URIs should differ
    assert md_output.parent_copy_properties["URI"] != plain_output.parent_copy_properties["URI"]
    # Edge URIs should differ
    assert md_output.edge_original_to_parent["URI"] != plain_output.edge_original_to_parent["URI"]
    print(f"  MD parent: {md_output.parent_copy_properties['URI']}")
    print(f"  Plain parent: {plain_output.parent_copy_properties['URI']}")
    print("✅ test_multi_method_coexistence passed")


def main():
    print("=" * 60)
    print("KGDocument Segmentation Processor Tests")
    print("=" * 60)

    tests = [
        test_extract_content_priority,
        test_strip_html,
        test_build_parent_copy_summary,
        test_processor_markdown,
        test_processor_plain,
        test_processor_auto_detect,
        test_processor_no_content,
        test_multi_method_coexistence,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"❌ {test.__name__} FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
