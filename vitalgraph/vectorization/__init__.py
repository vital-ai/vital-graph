"""
Vectorization providers for pgvector integration.

Provides a pluggable interface for text-to-embedding conversion using
local models (VitalSigns/sentence-transformers) or external APIs (OpenAI, Cohere).
"""

from vitalgraph.vectorization.base import VectorizationProvider
from vitalgraph.vectorization.registry import PROVIDER_REGISTRY, get_provider

__all__ = [
    "VectorizationProvider",
    "PROVIDER_REGISTRY",
    "get_provider",
]
