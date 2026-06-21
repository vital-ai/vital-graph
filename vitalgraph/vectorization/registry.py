"""
Vectorization provider registry.

Maps provider names to classes and provides a factory function
for instantiating providers from config dicts.
"""

import logging
from typing import Any, Dict, Optional, Type

from vitalgraph.vectorization.base import VectorizationProvider

logger = logging.getLogger(__name__)

# Global registry mapping provider name → class
PROVIDER_REGISTRY: Dict[str, Type[VectorizationProvider]] = {}

# Cache of instantiated providers (keyed by a unique config fingerprint)
_provider_cache: Dict[str, VectorizationProvider] = {}


def register_provider(name: str, cls: Type[VectorizationProvider]) -> None:
    """Register a vectorization provider class by name."""
    PROVIDER_REGISTRY[name] = cls
    logger.debug(f"Registered vectorization provider: {name} -> {cls.__name__}")


def get_provider(
    provider_name: str,
    config: Optional[Dict[str, Any]] = None,
    *,
    cache_key: Optional[str] = None,
) -> VectorizationProvider:
    """Get or create a vectorization provider instance.

    Args:
        provider_name: Registered provider name ('vitalsigns', 'openai', etc.)
        config: Provider-specific configuration dict (from provider_config JSONB).
        cache_key: Optional cache key for reusing provider instances.
                   If provided, the same instance is returned for the same key.
                   Typically use the vector index name as cache key.

    Returns:
        Configured VectorizationProvider instance.

    Raises:
        ValueError: If provider_name is not registered.
    """
    # Check cache first — validate provider_name matches to handle index swaps
    if cache_key and cache_key in _provider_cache:
        cached = _provider_cache[cache_key]
        if cached.provider_name == provider_name:
            return cached
        # Stale cache entry (provider was swapped) — evict and recreate
        logger.info(
            "Provider cache stale for '%s': cached=%s, requested=%s — evicting",
            cache_key, cached.provider_name, provider_name,
        )
        del _provider_cache[cache_key]

    cls = PROVIDER_REGISTRY.get(provider_name)
    if cls is None:
        available = ", ".join(sorted(PROVIDER_REGISTRY.keys()))
        raise ValueError(
            f"Unknown vectorization provider '{provider_name}'. "
            f"Available providers: {available}"
        )

    instance = cls.from_config(config or {})

    if cache_key:
        _provider_cache[cache_key] = instance

    return instance


def clear_cache() -> None:
    """Clear the provider instance cache."""
    _provider_cache.clear()


def _register_builtin_providers() -> None:
    """Register built-in providers. Called at module import time."""
    from vitalgraph.vectorization.vitalsigns_provider import VitalSignsProvider
    from vitalgraph.vectorization.openai_provider import OpenAIProvider

    register_provider("vitalsigns", VitalSignsProvider)
    register_provider("openai", OpenAIProvider)


# Auto-register built-in providers on import
_register_builtin_providers()
