"""
OpenAI vectorization provider.

Uses the OpenAI embeddings API (text-embedding-3-small, text-embedding-3-large, etc.).
Requires an API key stored in an environment variable.
"""

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from vitalgraph.vectorization.base import VectorizationProvider

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "text-embedding-3-small"
DEFAULT_DIMENSIONS = 1536
DEFAULT_BATCH_SIZE = 100

# Model → default dimensions mapping
MODEL_DIMENSIONS: Dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


class OpenAIProvider(VectorizationProvider):
    """OpenAI embedding API provider.

    Configuration (via provider_config JSONB):
        api_key_env: Environment variable name containing the API key (required)
        model_name: Model identifier (default: text-embedding-3-small)
        dimensions: Output dimensions (default: model-specific)
        base_url: Custom API endpoint (optional, for Azure OpenAI etc.)
        batch_size: Max texts per API call (default: 100)
    """

    def __init__(
        self,
        api_key: str,
        model_name: str = DEFAULT_MODEL,
        dimensions: Optional[int] = None,
        base_url: Optional[str] = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ):
        import openai

        self._model_name_str = model_name
        self._dim = dimensions or MODEL_DIMENSIONS.get(model_name, DEFAULT_DIMENSIONS)
        self._batch_size = batch_size

        client_kwargs: Dict[str, Any] = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url

        self._client = openai.AsyncOpenAI(**client_kwargs)
        logger.info(
            f"OpenAIProvider initialized: model={model_name}, dims={self._dim}, "
            f"batch_size={batch_size}"
        )

    @property
    def dimensions(self) -> int:
        return self._dim

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model_name_str

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "OpenAIProvider":
        """Create from config dict.

        Required config keys:
            api_key_env: Name of env var containing the OpenAI API key.

        Optional config keys:
            model_name: str (default: text-embedding-3-small)
            dimensions: int (default: model-specific)
            base_url: str (for Azure OpenAI or proxies)
            batch_size: int (default: 100)
        """
        api_key_env = config.get("api_key_env", "OPENAI_API_KEY")
        api_key = os.environ.get(api_key_env, "")
        if not api_key:
            raise ValueError(
                f"OpenAI API key not found in environment variable '{api_key_env}'. "
                f"Set {api_key_env} to your OpenAI API key."
            )

        return cls(
            api_key=api_key,
            model_name=config.get("model_name", DEFAULT_MODEL),
            dimensions=config.get("dimensions"),
            base_url=config.get("base_url"),
            batch_size=config.get("batch_size", DEFAULT_BATCH_SIZE),
        )

    async def vectorize_text(self, text: str) -> List[float]:
        """Vectorize a single text string via OpenAI API."""
        response = await self._client.embeddings.create(
            input=[text],
            model=self._model_name_str,
            dimensions=self._dim,
        )
        return response.data[0].embedding

    async def vectorize_texts(self, texts: List[str]) -> List[List[float]]:
        """Vectorize a batch of texts via OpenAI API.

        Handles batching internally if len(texts) > batch_size.
        """
        if not texts:
            return []

        all_embeddings: List[List[float]] = []

        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            response = await self._client.embeddings.create(
                input=batch,
                model=self._model_name_str,
                dimensions=self._dim,
            )
            # Response data is in same order as input
            batch_embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(batch_embeddings)

        return all_embeddings
