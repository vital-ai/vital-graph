"""
VitalSigns local vectorization provider.

Uses the VitalSigns ONNX embedding model (paraphrase-MiniLM, 384 dims)
running locally on CPU via ONNXRuntime. No external API calls or
HuggingFace downloads needed — the model weights are bundled in the
`vital-model-paraphrase-MiniLM-onnx` package.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from vital_ai_vitalsigns.embedding.embedding_model import EmbeddingModel

from vitalgraph.vectorization.base import VectorizationProvider

logger = logging.getLogger(__name__)

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
        self._dim = _ONNX_DIMS
        self._model_name = self._embedder.get_model_id()
        logger.info(
            f"VitalSignsProvider initialized: model={self._model_name}, "
            f"backend=onnxruntime, dims={self._dim}"
        )

    @property
    def dimensions(self) -> int:
        return self._dim

    @property
    def provider_name(self) -> str:
        return "vitalsigns"

    @property
    def model_name(self) -> str:
        return self._model_name

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
        for t in texts:
            result = self._embedder.vectorize(t)  # single string → single array
            if isinstance(result, np.ndarray):
                out.append(result.tolist())
            else:
                out.append(list(result))  # type: ignore[arg-type]
        return out
