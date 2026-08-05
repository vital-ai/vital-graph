"""
Vectorization providers for pgvector integration.

Provides a pluggable interface for text-to-embedding conversion using
local models (VitalSigns/sentence-transformers) or external APIs (OpenAI, Cohere).
"""

from vitalgraph.vectorization.base import VectorizationProvider
from vitalgraph.vectorization.registry import (
    LOCAL_PROVIDER_CACHE_KEY,
    PROVIDER_REGISTRY,
    get_local_provider,
    get_provider,
    warm_local_provider,
)

__all__ = [
    "VectorizationProvider",
    "PROVIDER_REGISTRY",
    "get_provider",
    "get_local_provider",
    "warm_local_provider",
    "LOCAL_PROVIDER_CACHE_KEY",
]
