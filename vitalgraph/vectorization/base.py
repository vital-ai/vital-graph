"""
Abstract base class for vectorization providers.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


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
        """Return the canonical provider name (e.g., 'vitalsigns_onnx', 'openai')."""
        ...

    @property
    def max_input_tokens(self) -> Optional[int]:
        """
        Longest input the model accepts, in ITS OWN tokens, or None if unknown.

        Text beyond this is truncated by the model, silently — the tail simply
        never reaches the vector. Segmentation uses this to bound segment size,
        so a segment can never be built larger than what will actually be
        embedded. Providers that know their limit should override.
        """
        return None

    @property
    def model_name(self) -> str:
        """Return the model name. Override in subclasses."""
        return ""

    @classmethod
    def expected_dimensions(cls, config: Dict[str, Any]) -> Any:
        """Output width this provider will produce, without instantiating it.

        Lets callers validate a requested vector(N) column against the model
        BEFORE building the model — index creation happens in API handlers and
        migration scripts that must not load ONNX/torch weights or need an API
        key.

        Returns None when the width genuinely cannot be known ahead of time
        (e.g. an arbitrary HuggingFace model id); callers should skip the check
        rather than guess.
        """
        return None

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
