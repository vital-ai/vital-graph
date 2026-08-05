"""
Segment size must never exceed what the embedding model can actually embed.

`max_segment_tokens` defaulted to 1024 while the bundled model accepts 512, so
a long section was embedded truncated — its tail never reached the vector, with
nothing logged. The mismatch was hidden because token counts were measured with
a whitespace approximation that under-reported by roughly a third.

Two defences: the default now matches the model, and the segmenter clamps to
the provider's reported ceiling so a stored config asking for more cannot
produce a segment that will be truncated.
"""

import pytest

from vitalgraph.document.document_segmenter import DocumentSegmenter
from vitalgraph.document.segment_config import (
    DEFAULT_MAX_SEGMENT_TOKENS,
    MarkdownSegmentConfig,
    PlainSplitConfig,
)


class TestProviderReportsItsLimit:
    def test_local_model_reports_its_tokenizer_limit(self):
        from vitalgraph.vectorization import get_local_provider
        provider = get_local_provider()
        assert provider.max_input_tokens == 512

    def test_openai_reports_the_api_limit(self):
        from vitalgraph.vectorization.openai_provider import OpenAIProvider
        assert OpenAIProvider.max_input_tokens.fget(None) == 8191

    def test_unknown_by_default_on_the_interface(self):
        """A provider that does not know its limit must say so, not guess."""
        from vitalgraph.vectorization.base import VectorizationProvider
        assert VectorizationProvider.max_input_tokens.fget(None) is None


class TestDefaultsMatchTheModel:
    def test_default_does_not_exceed_the_local_model(self):
        from vitalgraph.vectorization import get_local_provider
        assert DEFAULT_MAX_SEGMENT_TOKENS <= get_local_provider().max_input_tokens

    def test_markdown_config_uses_the_default(self):
        assert MarkdownSegmentConfig().max_segment_tokens == DEFAULT_MAX_SEGMENT_TOKENS

    def test_plain_config_uses_the_default(self):
        assert PlainSplitConfig().max_segment_tokens == DEFAULT_MAX_SEGMENT_TOKENS

    def test_agrees_with_the_stored_config_default(self):
        """
        `segmentation_config_manager` already defaulted stored configs to 512;
        the in-code dataclass said 1024. They must not drift apart again.
        """
        import dataclasses
        from vitalgraph.document.segmentation_config_manager import SegmentationConfigDTO
        field = next(
            f for f in dataclasses.fields(SegmentationConfigDTO)
            if f.name == "max_segment_tokens"
        )
        assert field.default == DEFAULT_MAX_SEGMENT_TOKENS


class TestClamping:
    # One token per character keeps the arithmetic obvious.
    CHAR_TOKENIZER = staticmethod(lambda text: len(text))

    def test_configured_above_the_model_limit_is_clamped(self):
        seg = DocumentSegmenter(tokenizer=self.CHAR_TOKENIZER, max_input_tokens=100)
        assert seg._effective_max_tokens(1024) == 100

    def test_configured_below_the_limit_is_left_alone(self):
        seg = DocumentSegmenter(tokenizer=self.CHAR_TOKENIZER, max_input_tokens=100)
        assert seg._effective_max_tokens(50) == 50

    def test_no_known_limit_means_no_clamping(self):
        seg = DocumentSegmenter(tokenizer=self.CHAR_TOKENIZER)
        assert seg._effective_max_tokens(4096) == 4096

    def test_clamp_warns_once_not_per_section(self, caplog):
        seg = DocumentSegmenter(tokenizer=self.CHAR_TOKENIZER, max_input_tokens=100)
        with caplog.at_level("WARNING"):
            for _ in range(50):
                seg._effective_max_tokens(1024)
        warnings = [r for r in caplog.records if "exceeds the embedding model" in r.message]
        assert len(warnings) == 1, "a per-section warning buries the log on long documents"

    def test_no_segment_exceeds_the_limit_even_when_config_asks_for_more(self):
        text = "\n\n".join(f"# Section {i}\n\n" + ("word " * 400) for i in range(5))
        seg = DocumentSegmenter(tokenizer=self.CHAR_TOKENIZER, max_input_tokens=500)
        segments = seg.segment(text, MarkdownSegmentConfig(max_segment_tokens=100_000))
        assert segments, "expected the document to segment"
        assert all(s.token_length <= 500 for s in segments), \
            [s.token_length for s in segments]


class TestRealModelEndToEnd:
    def test_wikipedia_article_stays_within_the_model_limit(self):
        import os
        path = "test_files/wikipedia/coffee.md"
        if not os.path.exists(path):
            pytest.skip("wikipedia fixture not present")

        from vitalgraph.document.segmentation_worker import SegmentationWorker
        worker = SegmentationWorker.__new__(SegmentationWorker)
        tokenizer = SegmentationWorker._get_tokenizer(worker)
        limit = SegmentationWorker._get_max_input_tokens(worker)

        seg = DocumentSegmenter(tokenizer=tokenizer, max_input_tokens=limit)
        segments = seg.segment(open(path, encoding="utf-8").read(), MarkdownSegmentConfig())
        assert segments
        assert max(s.token_length for s in segments) <= limit
