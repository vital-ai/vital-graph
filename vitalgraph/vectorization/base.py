"""
Abstract base class for vectorization providers.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any


class VectorizationProvider(ABC):
    """Abstract base for all vectorization providers.

    Each provider wraps a specific embedding model (local or remote).
    Providers are instantiated per vector-index and cached for reuse.
    """

    @abstractmethod
    async def vectorize_text(self, text: str) -> List[float]:
        """Vectorize a single text string.

        Args:
            text: Input text to embed.

        Returns:
            List of floats representing the embedding vector.
        """
        ...

    @abstractmethod
    async def vectorize_texts(self, texts: List[str]) -> List[List[float]]:
        """Vectorize a batch of text strings.

        Implementations should handle batching internally for optimal throughput.

        Args:
            texts: List of input texts to embed.

        Returns:
            List of embedding vectors, one per input text.
        """
        ...

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Return the output dimension of this provider's model."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the canonical provider name (e.g., 'vitalsigns', 'openai')."""
        ...

    @property
    def model_name(self) -> str:
        """Return the model name. Override in subclasses."""
        return ""

    @classmethod
    @abstractmethod
    def from_config(cls, config: Dict[str, Any]) -> "VectorizationProvider":
        """Instantiate a provider from a config dict (provider_config JSONB).

        Args:
            config: Provider-specific configuration. May include model_name,
                    api_key_env, device, batch_size, etc.

        Returns:
            Configured provider instance.
        """
        ...
