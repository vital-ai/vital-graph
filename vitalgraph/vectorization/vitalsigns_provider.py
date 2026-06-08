"""
VitalSigns local vectorization provider.

Uses sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 (384 dims)
running locally on CPU/MPS/CUDA. No external API calls needed.
"""

import asyncio
import logging
import math
from typing import Any, Dict, List, Optional

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

from vitalgraph.vectorization.base import VectorizationProvider

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MAX_BATCH_SIZE = 25


def _best_device() -> str:
    """Return the best available torch device: cuda > mps > cpu."""
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class VitalSignsProvider(VectorizationProvider):
    """Local vectorization using sentence-transformers model.

    Replicates Weaviate's HuggingFaceVectorizer algorithm:
      1. NLTK sent_tokenize splits text into sentences
      2. AutoModel + AutoTokenizer (max_length=500)
      3. Masked mean pooling per sentence batch (batches of 25)
      4. Average across sentences
      5. No L2 normalization
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        device: Optional[str] = None,
    ):
        self._model_name = model_name
        self._device = device or _best_device()
        self._model = AutoModel.from_pretrained(model_name).to(self._device)
        self._tokenizer = AutoTokenizer.from_pretrained(model_name)
        self._model.eval()
        self._dim: int = self._model.config.hidden_size
        logger.info(
            f"VitalSignsProvider initialized: model={model_name}, "
            f"device={self._device}, dims={self._dim}"
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
            model_name: str (default: paraphrase-multilingual-MiniLM-L12-v2)
            device: str (default: auto-detect)
        """
        return cls(
            model_name=config.get("model_name", DEFAULT_MODEL),
            device=config.get("device"),
        )

    async def vectorize_text(self, text: str) -> List[float]:
        """Vectorize a single text string.

        Offloads the synchronous model inference to a thread to avoid
        blocking the event loop.
        """
        vec = await asyncio.to_thread(self._vectorize_sync, text)
        return vec

    async def vectorize_texts(self, texts: List[str]) -> List[List[float]]:
        """Vectorize a batch of texts.

        Processes all texts sequentially in a single thread call to
        maximize GPU/CPU batch efficiency.
        """
        vecs = await asyncio.to_thread(self._vectorize_batch_sync, texts)
        return vecs

    def _vectorize_sync(self, text: str) -> List[float]:
        """Synchronous vectorization of a single text."""
        with torch.no_grad():
            sentences = self._sent_tokenize(text)
            num_sentences = len(sentences)
            number_of_batch_vectors = math.ceil(num_sentences / MAX_BATCH_SIZE)
            batch_sum_vectors = 0
            for i in range(number_of_batch_vectors):
                start = i * MAX_BATCH_SIZE
                end = start + MAX_BATCH_SIZE
                batch = sentences[start:end]
                tokens = self._tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=500,
                    add_special_tokens=True,
                    return_tensors="pt",
                )
                tokens = {k: v.to(self._device) for k, v in tokens.items()}
                outputs = self._model(**tokens)
                embeddings = outputs[0]
                attention_mask = tokens["attention_mask"]
                input_mask_expanded = (
                    attention_mask.unsqueeze(-1).expand(embeddings.size()).float()
                )
                sum_embeddings = torch.sum(embeddings * input_mask_expanded, 1)
                sum_mask = torch.clamp(input_mask_expanded.sum(1), min=1e-9)
                sentence_vecs = sum_embeddings / sum_mask
                batch_sum_vectors += sentence_vecs.sum(0)
            result = batch_sum_vectors / num_sentences
        return result.cpu().numpy().tolist()

    def _vectorize_batch_sync(self, texts: List[str]) -> List[List[float]]:
        """Synchronous batch vectorization."""
        return [self._vectorize_sync(text) for text in texts]

    @staticmethod
    def _sent_tokenize(text: str) -> List[str]:
        """Tokenize text into sentences using NLTK."""
        from nltk.tokenize import sent_tokenize
        return sent_tokenize(" ".join(text.split()))
