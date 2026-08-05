"""
The local embedding model must be loaded once, not per call.

Building it creates a tokenizer and an ONNX InferenceSession — hundreds of ms
to seconds on a cold container. `_get_tokenizer()` used to call
`get_provider("vitalsigns_onnx")` with no cache key, so it built a whole session
on EVERY segmentation, then looked for a `_tokenizer` attribute the provider
does not have and returned None anyway: full cost, no benefit. That load landed
inside individual requests and, in the E2E suite, inside one test's 30s budget
on the first run after a rebuild.
"""

import pytest

from vitalgraph.vectorization import (
    LOCAL_PROVIDER_CACHE_KEY,
    get_local_provider,
    warm_local_provider,
)
from vitalgraph.vectorization import registry


class TestSharedInstance:
    def test_warm_returns_a_provider(self):
        assert warm_local_provider() is not None

    def test_repeated_calls_reuse_one_instance(self):
        assert get_local_provider() is get_local_provider()

    def test_warm_and_get_share_the_same_instance(self):
        assert warm_local_provider() is get_local_provider()

    def test_instance_lives_under_the_shared_cache_key(self):
        warm_local_provider()
        assert registry._provider_cache.get(LOCAL_PROVIDER_CACHE_KEY) is get_local_provider()

    def test_even_uncached_calls_now_share_one_model(self):
        """
        Superseded behaviour, kept as a marker: calling without a cache_key used
        to build a NEW tokenizer and ONNX session every time, which is what made
        the per-segmentation lookup so expensive. Instances are now shared by
        (provider, config), so even this path reuses the loaded model — the
        cache_key only controls invalidation on index swaps.
        """
        from vitalgraph.vectorization import get_provider
        assert get_provider("vitalsigns_onnx") is get_provider("vitalsigns_onnx")


class TestTokenizerFromSharedProvider:
    @staticmethod
    def _worker_tokenizer():
        from vitalgraph.document.segmentation_worker import SegmentationWorker
        return SegmentationWorker._get_tokenizer(SegmentationWorker.__new__(SegmentationWorker))

    @staticmethod
    def _endpoint_tokenizer():
        from vitalgraph.endpoint.kgdocuments_endpoint import KGDocumentsEndpoint
        return KGDocumentsEndpoint._get_tokenizer(KGDocumentsEndpoint.__new__(KGDocumentsEndpoint))

    def test_worker_gets_a_real_token_counter(self):
        tok = self._worker_tokenizer()
        assert tok is not None, "was None for years — the attribute checked did not exist"
        assert isinstance(tok("hello world"), int)

    def test_endpoint_gets_a_real_token_counter(self):
        tok = self._endpoint_tokenizer()
        assert tok is not None
        assert isinstance(tok("hello world"), int)

    def test_counts_are_model_aligned_not_whitespace(self):
        # The whole point of using the model's tokenizer: subword splitting and
        # special tokens mean counts differ from naive whitespace counting.
        tok = self._worker_tokenizer()
        text = "unbelievably tokenized"
        assert tok(text) > len(text.split())

    def test_building_the_tokenizer_does_not_add_cached_providers(self):
        warm_local_provider()
        before = len(registry._provider_cache)
        self._worker_tokenizer()
        self._endpoint_tokenizer()
        assert len(registry._provider_cache) == before, \
            "tokenizer lookup must reuse the cached provider, not create more"


class TestInstancesAreSharedAcrossCallers:
    """
    Callers key the provider cache by their own identity — agent registry,
    entity registry, each vector index, the startup warm-up. Identical
    configurations must still share ONE instance, or each caller builds its own
    tokenizer and ONNX session. Two were being constructed at startup alone.
    """

    def test_different_cache_keys_share_one_instance(self):
        from vitalgraph.vectorization import get_provider
        a = get_provider("vitalsigns_onnx", cache_key="caller_a")
        b = get_provider("vitalsigns_onnx", cache_key="caller_b")
        assert a is b

    def test_warmed_instance_is_the_one_callers_get(self):
        from vitalgraph.vectorization import get_provider
        assert warm_local_provider() is get_provider("vitalsigns_onnx", cache_key="some_index")

    def test_different_config_gets_its_own_instance(self):
        from vitalgraph.vectorization import get_provider
        default = get_provider("vitalsigns_onnx", cache_key="k1")
        custom = get_provider("vitalsigns_onnx", {"cache_size": 7}, cache_key="k2")
        assert custom is not default

    def test_same_config_written_differently_still_shares(self):
        from vitalgraph.vectorization import get_provider
        a = get_provider("vitalsigns_onnx", {"cache_size": 11}, cache_key="k3")
        b = get_provider("vitalsigns_onnx", {"cache_size": 11}, cache_key="k4")
        assert a is b
