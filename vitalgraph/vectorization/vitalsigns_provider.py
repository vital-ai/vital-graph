"""
VitalSigns local vectorization provider.

Uses the VitalSigns ONNX embedding model (paraphrase-MiniLM, 384 dims)
running locally on CPU via ONNXRuntime. No external API calls or
HuggingFace downloads needed — the model weights are bundled in the
`vital-model-paraphrase-MiniLM-onnx` package.
"""

import asyncio
import logging
import threading
from typing import Any, Dict, List, Optional

from vital_ai_vitalsigns.embedding.embedding_model import EmbeddingModel

from vitalgraph.vectorization.base import VectorizationProvider

logger = logging.getLogger(__name__)

PROVIDER_NAME = "vitalsigns_onnx"

# Dimensions produced by the bundled ONNX model
_ONNX_DIMS = 384


class VitalSignsProvider(VectorizationProvider):
    """Local vectorization using VitalSigns ONNX embedding model.

    Uses the bundled paraphrase-MiniLM ONNX model (384 dims, CPU-only).
    The model is loaded from the `vital-model-paraphrase-MiniLM-onnx` package
    with no network access required.
    """

    def __init__(self, cache_size: int = 1000):
        self._embedder = EmbeddingModel(cache_size=cache_size)
        # ONE embedder, shared by every caller: `registry._provider_cache`
        # hands the same instance to all of them. Its HuggingFace tokenizer is a
        # Rust object behind a RefCell, and both vectorize entry points offload
        # to `asyncio.to_thread`, so two concurrent callers touch it from two
        # threads and it raises
        #
        #     RuntimeError: Already borrowed
        #
        # That is not hypothetical and not rare enough to ignore: 11 occurrences
        # in one API run, which failed a segmentation job outright
        # (`_process_job - ERROR - Job 2 failed: Already borrowed`) and lost an
        # 83-text auto_sync batch. It only appears when work overlaps — a cold
        # container running the full suite, where segmentation-worker
        # vectorization and auto_sync fire together — which is why it read as a
        # flaky test for days (`issues/110`).
        #
        # A threading.Lock, not an asyncio one: the collision happens in worker
        # THREADS, and the provider is reachable from more than one event loop.
        # It serialises embedding, which is the cost of a model that cannot be
        # shared; the alternative is losing vectors silently.
        self._embed_lock = threading.Lock()
        self._dim = _ONNX_DIMS
        self._model_name = self._embedder.get_model_id()
        logger.info(
            f"VitalSignsProvider initialized: model={self._model_name}, "
            f"backend=onnxruntime, dims={self._dim}"
        )

    @property
    def dimensions(self) -> int:
        return self._dim

    def count_tokens(self, text: str) -> int:
        """Token count for `text`, under the embed lock.

        THE TOKENIZER IS THE SHARED OBJECT, not just the embed call. Two callers
        reached straight into `provider._embedder.tokenizer` and used it for
        segment sizing — `segmentation_worker._get_tokenizer` and
        `kgdocuments_endpoint._get_tokenizer`, both returning
        `lambda text: len(tokenizer.encode(text))` — so document segmentation
        tokenized on one thread while auto_sync embedded on another, through the
        same Rust RefCell, and it raised `RuntimeError: Already borrowed`.

        Locking only `vectorize` did NOT fix it, which is how this was found:
        the lock landed, the cold full-suite run still failed, and the log showed
        the survivors were all auto_sync embeds racing a segmentation job.

        Exposed as a method so callers stop reaching through a private
        attribute. That reach-through has already caused one bug: the previous
        version looked for a `_tokenizer` the provider does not have, silently
        got None, and fell back to whitespace counting.
        """
        with self._embed_lock:
            return len(self._embedder.tokenizer.encode(text))

    @property
    def max_input_tokens(self) -> Optional[int]:
        """Read from the bundled model's tokenizer rather than hardcoded.

        Under the lock too: reading `model_max_length` borrows the same RefCell
        an in-flight encode holds.
        """
        try:
            with self._embed_lock:
                limit = int(self._embedder.tokenizer.model_max_length)
            # Some tokenizers use a sentinel (very large int) for "no limit".
            return limit if 0 < limit < 1_000_000 else None
        except Exception:
            return None

    @property
    def provider_name(self) -> str:
        return PROVIDER_NAME

    @property
    def model_name(self) -> str:
        return self._model_name

    @classmethod
    def expected_dimensions(cls, config: Dict[str, Any]) -> Optional[int]:
        """Fixed: the bundled ONNX model has one output width."""
        return _ONNX_DIMS

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "VitalSignsProvider":
        """Create from config dict.

        Supported config keys:
            cache_size: int (default: 1000) — LRU embedding cache size
        """
        return cls(
            cache_size=config.get("cache_size", 1000),
        )

    async def vectorize_text(self, text: str) -> List[float]:
        """Vectorize a single text string.

        Offloads the synchronous ONNX inference to a thread to avoid
        blocking the event loop.
        """
        vec = await asyncio.to_thread(self._vectorize_sync, text)
        return vec

    async def vectorize_texts(self, texts: List[str]) -> List[List[float]]:
        """Vectorize a batch of texts.

        Processes all texts in a single thread call.
        """
        vecs = await asyncio.to_thread(self._vectorize_batch_sync, texts)
        return vecs

    def _vectorize_sync(self, text: str) -> List[float]:
        """Synchronous vectorization of a single text."""
        import numpy as np
        with self._embed_lock:
            result = self._embedder.vectorize(text)  # type: ignore[arg-type]
        # EmbeddingModel returns numpy ndarray for single string
        if isinstance(result, np.ndarray):
            return result.tolist()
        return list(result)  # type: ignore[arg-type]

    def _vectorize_batch_sync(self, texts: List[str]) -> List[List[float]]:
        """Synchronous batch vectorization.

        NOTE: We vectorize one-at-a-time to preserve positional order.
        The upstream EmbeddingModel.vectorize(list) has a cache-ordering bug
        where cached results are placed before newly-computed ones, breaking
        the correspondence between input texts and output embeddings.
        """
        import numpy as np
        out: List[List[float]] = []
        # Held across the whole batch rather than per text: re-acquiring 83
        # times interleaves this batch with every other caller and multiplies
        # the contention it exists to remove.
        with self._embed_lock:
            for t in texts:
                result = self._embedder.vectorize(t)  # single string → single array
                if isinstance(result, np.ndarray):
                    out.append(result.tolist())
                else:
                    out.append(list(result))  # type: ignore[arg-type]
        return out
