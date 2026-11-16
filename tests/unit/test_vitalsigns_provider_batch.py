"""`VitalSignsProvider.vectorize_texts` embeds in batches, in input order.

vitalsigns < 0.1.56 returned cached results ahead of newly computed ones from
`EmbeddingModel.vectorize(list)`, so the provider had to embed one text at a
time. 0.1.56 (3c92d18) fills results by position, and the provider now makes one
model run per chunk of `_BATCH_CHUNK` texts.

What would go wrong silently: a batch that mixes cached and uncached texts gets
its vectors shuffled, and every vector is written against the wrong subject.
Nothing errors; search just returns the wrong things. So the test is against
the per-text output, with a partly warm cache and a batch crossing a chunk
boundary.
"""

from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")


@pytest.fixture(scope="module")
def provider():
    try:
        from vitalgraph.vectorization.vitalsigns_provider import VitalSignsProvider
        return VitalSignsProvider(cache_size=1000)
    except Exception as exc:  # model package not installed
        pytest.skip(f"VitalSigns ONNX model unavailable: {exc}")


def _per_text(provider, texts):
    return [provider._vectorize_sync(t) for t in texts]


class TestBatchMatchesPerText:

    def test_mixed_cache_across_a_chunk_boundary(self, provider):
        from vitalgraph.vectorization import vitalsigns_provider as mod
        n = mod._BATCH_CHUNK + 7
        texts = [f"batch order probe {i} about subject {i * 7}" for i in range(n)]
        texts[3] = texts[n - 2]          # a duplicate within the batch
        expected = _per_text(provider, texts)   # warms the cache for all

        # New texts interleaved with cached ones: the case 0.1.55 got wrong.
        fresh = [f"fresh uncached text number {i}" for i in range(n)]
        mixed = [t for pair in zip(texts, fresh) for t in pair]
        got = provider._vectorize_batch_sync(mixed)

        assert len(got) == len(mixed)
        for i, t in enumerate(texts):
            assert np.allclose(got[2 * i], expected[i], atol=1e-5), f"row {2 * i} ({t!r})"
        fresh_expected = _per_text(provider, fresh)
        for i in range(n):
            assert np.allclose(got[2 * i + 1], fresh_expected[i], atol=1e-5)

    def test_rows_are_plain_float_lists(self, provider):
        got = provider._vectorize_batch_sync(["one", "two"])
        assert all(isinstance(r, list) and len(r) == provider.dimensions for r in got)
        assert all(isinstance(x, float) for x in got[0])

    def test_empty_batch(self, provider):
        assert provider._vectorize_batch_sync([]) == []
