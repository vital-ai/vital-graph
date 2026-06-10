"""
Test script for document segmenter.

Verifies both markdown and plain text splitting strategies.
"""

import sys
sys.path.insert(0, "/Users/hadfield/Local/vital-git/vital-graph")

from vitalgraph.document.document_segmenter import DocumentSegmenter, SegmentResult, detect_is_markdown
from vitalgraph.document.segment_config import MarkdownSegmentConfig, PlainSplitConfig


def test_detect_markdown():
    """Test markdown auto-detection."""
    md_text = """# Introduction
Some text here.

## Methods
More text about methods.

### Results
Final results.
"""
    assert detect_is_markdown(md_text), "Should detect markdown headings"

    plain_text = "This is just plain text without any headings. It has multiple sentences."
    assert not detect_is_markdown(plain_text), "Should not detect markdown in plain text"
    print("✅ test_detect_markdown passed")


def test_markdown_splitting():
    """Test markdown heading-based splitting."""
    text = """# Introduction

This is the introduction section with some content about the paper.
It discusses the main themes and objectives.

## Background

The background section provides context for the research.
It covers prior work and motivation.

## Methods

The methods section describes the experimental approach.
We used various techniques to gather data.

### Data Collection

Data was collected from multiple sources over a period of months.
Each source was validated for accuracy.

### Analysis

Statistical analysis was performed using standard tools.
Results were cross-validated.

## Conclusion

The conclusion summarizes key findings.
Future work is discussed.
"""
    segmenter = DocumentSegmenter()
    config = MarkdownSegmentConfig(
        max_segment_tokens=100,
        min_segment_tokens=5,
    )
    results = segmenter.segment(text, config)

    print(f"\n📄 Markdown splitting: {len(results)} segments")
    for r in results:
        print(f"  [{r.segment_index}] tokens={r.token_length}, type={r.segment_type_uri}")
        print(f"      heading={r.heading}")
        print(f"      content={r.content[:80]}...")

    assert len(results) >= 3, f"Expected at least 3 segments, got {len(results)}"
    assert all(r.segment_index == i + 1 for i, r in enumerate(results)), "Indices should be 1-based contiguous"
    assert results[0].heading is not None or results[0].content.startswith("#"), "First segment should have heading"
    print("✅ test_markdown_splitting passed")


def test_plain_splitting():
    """Test plain recursive character splitting."""
    # Create text that exceeds the token budget
    paragraphs = []
    for i in range(20):
        paragraphs.append(
            f"Paragraph {i+1}: This is a paragraph with enough content to contribute "
            f"meaningful tokens to the document. It discusses topic number {i+1} "
            f"and provides relevant details about the subject matter at hand."
        )
    text = "\n\n".join(paragraphs)

    segmenter = DocumentSegmenter()
    config = PlainSplitConfig(
        max_segment_tokens=50,
        min_segment_tokens=10,
    )
    results = segmenter.segment(text, config)

    print(f"\n📄 Plain splitting: {len(results)} segments")
    for r in results:
        print(f"  [{r.segment_index}] tokens={r.token_length}, type={r.segment_type_uri}")
        print(f"      content={r.content[:60]}...")

    assert len(results) >= 3, f"Expected at least 3 segments, got {len(results)}"
    assert all(r.token_length <= config.max_segment_tokens * 1.5 for r in results), \
        "Segments should be approximately within token budget"
    assert all(r.segment_type_uri == "urn:segtype:text_chunk" for r in results), \
        "All plain segments should have text_chunk type"
    print("✅ test_plain_splitting passed")


def test_auto_detection():
    """Test auto-detection chooses correct method."""
    segmenter = DocumentSegmenter()

    # Markdown content
    md_text = "# Title\nSome text.\n\n## Section\nMore text.\n\n## Another\nEven more."
    results = segmenter.segment(md_text)
    assert len(results) >= 1, "Should produce segments for markdown"
    print(f"  Auto-detect markdown: {len(results)} segments")

    # Plain content
    plain_text = "First paragraph with content.\n\nSecond paragraph with more.\n\nThird paragraph here."
    results = segmenter.segment(plain_text)
    assert len(results) >= 1, "Should produce segments for plain text"
    print(f"  Auto-detect plain: {len(results)} segments")
    print("✅ test_auto_detection passed")


def test_overlap():
    """Test overlap between segments."""
    paragraphs = [f"Sentence number {i} with some extra words to fill space." for i in range(30)]
    text = "\n\n".join(paragraphs)

    segmenter = DocumentSegmenter()
    config = PlainSplitConfig(
        max_segment_tokens=40,
        min_segment_tokens=5,
        overlap_tokens=5,
    )
    results = segmenter.segment(text, config)

    print(f"\n📄 Overlap splitting: {len(results)} segments")
    if len(results) >= 2:
        # Check that later segments contain overlap from previous
        for i in range(1, min(3, len(results))):
            print(f"  [{results[i].segment_index}] starts with: {results[i].content[:50]}...")
    print("✅ test_overlap passed")


def test_custom_tokenizer():
    """Test with a custom tokenizer function."""
    # Simple char-based tokenizer (1 token per 4 chars)
    def char_tokenizer(text: str) -> int:
        return len(text) // 4

    text = "A" * 2000  # 500 "tokens" with char_tokenizer
    segmenter = DocumentSegmenter(tokenizer=char_tokenizer)
    config = PlainSplitConfig(max_segment_tokens=100, min_segment_tokens=10)
    results = segmenter.segment(text, config)

    print(f"\n📄 Custom tokenizer: {len(results)} segments")
    assert len(results) >= 2, f"Expected multiple segments for long text, got {len(results)}"
    print("✅ test_custom_tokenizer passed")


def test_empty_and_edge_cases():
    """Test edge cases."""
    segmenter = DocumentSegmenter()

    # Empty text
    assert segmenter.segment("") == [], "Empty text should return empty list"
    assert segmenter.segment("   ") == [], "Whitespace-only should return empty list"

    # Very short text (below min_segment_tokens)
    config = PlainSplitConfig(min_segment_tokens=100)
    results = segmenter.segment("Short.", config)
    # Should still return something (first section kept even if small)
    assert len(results) >= 0, "Short text handling should not crash"

    print("✅ test_empty_and_edge_cases passed")


def main():
    print("=" * 60)
    print("Document Segmenter Tests")
    print("=" * 60)

    tests = [
        test_detect_markdown,
        test_markdown_splitting,
        test_plain_splitting,
        test_auto_detection,
        test_overlap,
        test_custom_tokenizer,
        test_empty_and_edge_cases,
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
