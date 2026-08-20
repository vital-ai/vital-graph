"""One embedder, many threads — the provider must serialise access to it.

`issues/110`. `registry._provider_cache` hands the SAME provider instance to
every caller, and both vectorize entry points offload to `asyncio.to_thread`. The
model behind them wraps a HuggingFace tokenizer, a Rust object behind a RefCell,
which raises when two threads touch it at once:

    RuntimeError: Already borrowed

Measured in one API run against a cold container: 11 occurrences, one
segmentation job failed outright (`_process_job - ERROR - Job 2 failed: Already
borrowed`) and an 83-text auto_sync batch lost.

WHY IT LOOKED LIKE A FLAKY TEST FOR DAYS

It needs overlapping work, which needs a cold container running the full API
suite — segmentation-worker vectorization and auto_sync firing together while
nothing is cached. Every warm run passed, and the test that caught it was
re-run warm each time and passed, twice. Seven warm runs, zero failures; two
cold full-suite runs, two failures. A repeat-until-it-fires loop could never
have found it, because the loop only ever ran warm.

WHAT MADE IT SURVIVE

`vectorization_failed` marks a job `completed` and records the error, on the
argument that segments are already stored and searchable via FTS. So the visible
outcome is a completed job with an error nobody reads, and vectors that silently
are not there. The only thing that ever complained was one assertion in the
Wikipedia end-to-end test.
"""

from __future__ import annotations

import threading
import time

import pytest


class _FakeTokenizerBoundModel:
    """Stands in for the real embedder: raises if entered concurrently.

    This is what the Rust RefCell does — it does not corrupt anything, it
    refuses. Reproducing the refusal is enough to test the lock.
    """

    def __init__(self):
        self._in_use = False
        self.calls = 0

    def vectorize(self, text):
        if self._in_use:
            raise RuntimeError("Already borrowed")
        self._in_use = True
        try:
            time.sleep(0.002)      # a window for a second thread to collide
            self.calls += 1
            return [0.1, 0.2, 0.3]
        finally:
            self._in_use = False

    # the minilm provider's shape
    def vectorize_text(self, text):
        import numpy as np
        return np.array(self.vectorize(text))


class _FakeSharedTokenizer:
    """The tokenizer, which is the object actually shared — refuses re-entry."""

    def __init__(self):
        self._in_use = False
        self.model_max_length = 512

    def _borrow(self):
        if self._in_use:
            raise RuntimeError("Already borrowed")

    def encode(self, text):
        self._borrow()
        self._in_use = True
        try:
            time.sleep(0.002)
            return list(range(len(text.split())))
        finally:
            self._in_use = False


def _hammer(fn, n=12):
    """Run `fn` on n threads; return the exceptions it raised."""
    errors = []
    barrier = threading.Barrier(n)

    def run():
        barrier.wait()             # start together, maximising overlap
        try:
            fn()
        except Exception as exc:   # noqa: BLE001 — the point is to collect them
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return errors


class TestTheHarnessActuallyReproducesIt:
    """A guard whose failure mode cannot be reproduced proves nothing."""

    def test_an_unlocked_shared_model_does_raise(self):
        model = _FakeTokenizerBoundModel()
        errors = _hammer(lambda: model.vectorize("x"))
        assert errors, "the stand-in never collided; the rest of this file is vacuous"
        assert all("Already borrowed" in str(e) for e in errors)


class TestVitalSignsProviderSerialises:

    @pytest.fixture
    def provider(self):
        from vitalgraph.vectorization.vitalsigns_provider import VitalSignsProvider
        p = VitalSignsProvider.__new__(VitalSignsProvider)   # no model download
        p._embedder = _FakeTokenizerBoundModel()
        p._embed_lock = threading.Lock()
        p._dim = 3
        return p

    def test_concurrent_single_calls_do_not_collide(self, provider):
        assert _hammer(lambda: provider._vectorize_sync("x")) == []

    def test_concurrent_batches_do_not_collide(self, provider):
        assert _hammer(lambda: provider._vectorize_batch_sync(["a", "b", "c"])) == []

    def test_the_batch_takes_the_lock_once(self, provider):
        """Re-acquiring per text interleaves the batch with every other caller
        and multiplies the contention the lock exists to remove."""
        import inspect
        src = inspect.getsource(provider._vectorize_batch_sync.__func__)
        body = src[src.index("with self._embed_lock"):]
        assert body.count("with self._embed_lock") == 1
        assert "for t in texts" in body, "the loop must sit INSIDE the lock"


class TestMiniLMProviderSerialises:
    """Nothing about this was specific to the ONNX backend, and this is the
    provider the Wikipedia fixture names by model."""

    @pytest.fixture
    def provider(self):
        from vitalgraph.vectorization.paraphrase_multilingual_minilm_provider import (
            ParaphraseMultilingualMiniLMProvider)
        p = ParaphraseMultilingualMiniLMProvider.__new__(
            ParaphraseMultilingualMiniLMProvider)
        p._vectorizer = _FakeTokenizerBoundModel()
        p._embed_lock = threading.Lock()
        p._dim = 3
        return p

    def test_concurrent_single_calls_do_not_collide(self, provider):
        assert _hammer(lambda: provider._vectorize_sync("x")) == []

    def test_concurrent_batches_do_not_collide(self, provider):
        assert _hammer(lambda: provider._vectorize_batch_sync(["a", "b"])) == []


class TestTheLockIsPerInstanceAndReal:

    @pytest.mark.parametrize("mod,cls", [
        ("vitalgraph.vectorization.vitalsigns_provider", "VitalSignsProvider"),
        ("vitalgraph.vectorization.paraphrase_multilingual_minilm_provider",
         "ParaphraseMultilingualMiniLMProvider"),
    ])
    def test_a_threading_lock_not_an_asyncio_one(self, mod, cls):
        """The collision happens in worker THREADS, and the provider is
        reachable from more than one event loop, so an asyncio.Lock would guard
        the wrong thing."""
        import importlib
        src = importlib.import_module(mod).__file__
        text = open(src).read()
        assert "threading.Lock()" in text
        assert "asyncio.Lock()" not in text


class TestTheTokenizerIsGuardedToo:
    """Locking `vectorize` alone did NOT fix this, and that is the finding.

    Two callers reached into `provider._embedder.tokenizer` and used it for
    SEGMENT SIZING — `segmentation_worker._get_tokenizer` and
    `kgdocuments_endpoint._get_tokenizer`, each returning
    `lambda text: len(tokenizer.encode(text))`. So document segmentation
    tokenized on one thread while auto_sync embedded on another, through the same
    RefCell. The embed lock did not cover the second party, the cold full-suite
    run failed again, and the log showed every survivor was an auto_sync embed
    racing a segmentation job.
    """

    @pytest.fixture
    def provider(self):
        from vitalgraph.vectorization.vitalsigns_provider import VitalSignsProvider
        p = VitalSignsProvider.__new__(VitalSignsProvider)
        model = _FakeTokenizerBoundModel()
        model.tokenizer = _FakeSharedTokenizer()
        p._embedder = model
        p._embed_lock = threading.Lock()
        p._dim = 3
        return p

    def test_counting_and_embedding_do_not_collide(self, provider):
        """The exact pairing that survived the first fix: one thread sizing
        segments, another embedding."""
        def mixed(i=[0]):
            i[0] += 1
            if i[0] % 2:
                provider.count_tokens("some segment text here")
            else:
                provider._vectorize_batch_sync(["a", "b"])
        assert _hammer(mixed, n=16) == []

    def test_max_input_tokens_is_guarded(self, provider):
        """It reads `model_max_length`, which borrows the same RefCell an
        in-flight encode holds. It also swallows exceptions, so an unguarded
        read fails silently as `None` — a segmenter that then stops clamping."""
        def mixed(i=[0]):
            i[0] += 1
            if i[0] % 2:
                assert provider.max_input_tokens == 512
            else:
                provider.count_tokens("text")
        assert _hammer(mixed, n=16) == []


class TestCallersDoNotReachThroughToTheTokenizer:
    """The reach-through is what put the shared object in unguarded hands, and
    it had already caused one bug: the previous version looked for a `_tokenizer`
    the provider does not have, got None, and silently fell back to whitespace
    counting."""

    @pytest.mark.parametrize("rel", [
        "vitalgraph/document/segmentation_worker.py",
        "vitalgraph/endpoint/kgdocuments_endpoint.py",
    ])
    def test_no_caller_takes_the_tokenizer_off_the_provider(self, rel):
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        code = [ln for ln in (root / rel).read_text().splitlines()
                if not ln.lstrip().startswith("#")]
        joined = "\n".join(code)
        assert 'getattr(embedder, "tokenizer"' not in joined
        assert "count_tokens" in joined, "it must go through the locked accessor"
