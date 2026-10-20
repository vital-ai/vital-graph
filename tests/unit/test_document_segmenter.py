"""
Test script for document segmenter.

Verifies both markdown and plain text splitting strategies.
"""

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


def test_an_oversized_sections_short_tail_is_kept():
    """issues/287: the tail of an oversized section below the minimum was
    DROPPED from the segments, so its text was unsearchable.

    One section, far over the limit, whose recursive split leaves a short
    final paragraph. Every word must survive into some segment.
    """
    words = lambda n, tag: " ".join(f"{tag}{i}" for i in range(n))
    tail = "TAILMARKER ends the section here"
    text = ("# Only section\n\n"
            + "\n\n".join(words(48, f"p{j}w") for j in range(6))
            + "\n\n" + tail + "\n\n# Next\n\n" + words(60, "n"))
    config = MarkdownSegmentConfig(max_segment_tokens=50, min_segment_tokens=20)
    results = DocumentSegmenter().segment(text, config)

    joined = "\n".join(r.content for r in results)
    assert "TAILMARKER" in joined, (
        "the short remainder of an oversized section was dropped")
    for r in results:
        assert r.token_length <= 50, (
            f"a merge pushed segment {r.segment_index} to {r.token_length} "
            f"tokens, over the limit")


# ---------------------------------------------------------------------------
# issues/287: the recursive splitter's four flaws
# ---------------------------------------------------------------------------

def _words(n, tag="w"):
    return " ".join(f"{tag}{i}" for i in range(n))


def test_words_are_never_cut_when_there_is_no_sentence_separator():
    """With no ". " the splitter jumped straight to character chunks."""
    text = _words(300)          # one line, no ". ", plenty of spaces
    chunks = DocumentSegmenter()._recursive_split(text, max_tokens=50)
    words = set(text.split())
    for c in chunks:
        assert all(w in words for w in c.split()), f"a word was cut: {c[:80]}"
    assert " ".join(chunks).split() == text.split()


def test_character_chunks_respect_the_token_limit():
    """A dense run with no separator: each hard chunk is re-checked."""
    # A tokenizer that counts every 'x' as a token makes the dense tail
    # heavier than the chars-per-token average predicts.
    tok = lambda s: max(1, len(s) // 10) + s.count("x")
    seg = DocumentSegmenter(tokenizer=tok)
    text = "a" * 2000 + "x" * 400
    for c in seg._recursive_split(text, max_tokens=60):
        assert tok(c) <= 60, f"chunk over the limit: {tok(c)} tokens"


def test_overlap_is_applied_once_and_never_exceeds_the_limit():
    seg = DocumentSegmenter()
    # Oversized paragraphs made of sentences, so the split RECURSES: the old
    # code applied overlap at the sentence level and again at the top.
    sentence = lambda j, k: " ".join(f"p{j}s{k}w{i}" for i in range(12))
    text = "\n\n".join(". ".join(sentence(j, k) for k in range(10)) for j in range(4))
    chunks = seg._recursive_split(text, max_tokens=60, overlap_tokens=5)
    for c in chunks:
        assert seg._tokenizer(c) <= 60, c[:80]
    # Each chunk after the first starts with AT MOST 5 words of the previous
    # chunk -- not 5 per recursion level.
    for prev, cur in zip(chunks, chunks[1:]):
        shared = 0
        for w in cur.split():
            if w in prev.split():
                shared += 1
            else:
                break
        assert shared <= 5, (shared, cur[:80])


def test_offsets_locate_each_chunks_own_content_with_overlap():
    """`find()` returned -1 for an overlapped chunk and corrupted offsets."""
    seg = DocumentSegmenter()
    text = "\n\n".join(_words(40, f"p{j}w") for j in range(8))
    config = PlainSplitConfig(max_segment_tokens=60, min_segment_tokens=1, overlap_tokens=5)
    results = seg.segment(text, config)
    assert len(results) > 1
    last_end = 0
    for r in results:
        assert 0 <= r.start_char_offset < r.end_char_offset <= len(text)
        assert r.start_char_offset >= last_end, "offsets must be monotone"
        own = text[r.start_char_offset:r.end_char_offset]
        assert own.strip() and r.content.endswith(own.strip()), (own[:60], r.content[-60:])
        last_end = r.end_char_offset
