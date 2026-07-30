"""
Vectorization provider registry.

Maps provider names to classes and provides a factory function
for instantiating providers from config dicts.
"""

import logging
from typing import Any, Dict, Optional, Type

from vitalgraph.vectorization.base import VectorizationProvider

logger = logging.getLogger(__name__)

# Global registry mapping canonical provider name → class
PROVIDER_REGISTRY: Dict[str, Type[VectorizationProvider]] = {}

# Deprecated/legacy provider names → canonical name.  Rows already stored in
# {space}_vector_index with an old name keep resolving.
PROVIDER_ALIASES: Dict[str, str] = {}

# Cache of instantiated providers (keyed by a unique config fingerprint)
_provider_cache: Dict[str, VectorizationProvider] = {}


def register_provider(name: str, cls: Type[VectorizationProvider]) -> None:
    """Register a vectorization provider class by its canonical name."""
    PROVIDER_REGISTRY[name] = cls
    logger.debug(f"Registered vectorization provider: {name} -> {cls.__name__}")


def register_alias(alias: str, canonical: str) -> None:
    """Register a legacy provider name that resolves to a canonical one."""
    PROVIDER_ALIASES[alias] = canonical
    logger.debug(f"Registered vectorization provider alias: {alias} -> {canonical}")


def canonical_provider_name(provider_name: str) -> str:
    """Resolve a possibly-legacy provider name to its canonical form."""
    return PROVIDER_ALIASES.get(provider_name, provider_name)


def get_provider(
    provider_name: str,
    config: Optional[Dict[str, Any]] = None,
    *,
    cache_key: Optional[str] = None,
) -> VectorizationProvider:
    """Get or create a vectorization provider instance.

    Args:
        provider_name: Registered provider name ('vitalsigns_onnx', 'openai',
                       etc.), or a legacy alias from PROVIDER_ALIASES.
        config: Provider-specific configuration dict (from provider_config JSONB).
        cache_key: Optional cache key for reusing provider instances.
                   If provided, the same instance is returned for the same key.
                   Typically use the vector index name as cache key.

    Returns:
        Configured VectorizationProvider instance.

    Raises:
        ValueError: If provider_name is not registered.
    """
    # Resolve aliases BEFORE the cache check: the check compares against
    # instance.provider_name, which is always canonical.  Comparing a legacy
    # name against it would miss on every call and reload the model each time.
    requested = provider_name
    provider_name = canonical_provider_name(provider_name)

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
            f"Unknown vectorization provider '{requested}'. "
            f"Available providers: {available}"
        )

    instance = cls.from_config(config or {})

    if cache_key:
        _provider_cache[cache_key] = instance

    return instance


# pgvector's HNSW and ivfflat indexes cannot be built on wider vectors, and
# every vector data table this codebase creates is HNSW-indexed.
PGVECTOR_MAX_INDEX_DIMENSIONS = 2000


def native_dimensions(
    provider_name: str, config: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    """Output width a provider will produce, without instantiating it.

    Used to validate a requested vector(N) column at index-creation time, where
    building the provider is not an option (no API key, no model load in an API
    handler).

    Returns None when the width is genuinely unknowable — an unrecognised
    OpenAI model, or an arbitrary HuggingFace id — so callers can skip the
    check instead of guessing.

    Raises:
        ValueError: If provider_name is not registered.
    """
    name = canonical_provider_name(provider_name)
    cls = PROVIDER_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown vectorization provider '{provider_name}'")
    return cls.expected_dimensions(config or {})


def validate_index_dimensions(
    provider_name: str,
    dimensions: int,
    provider_config: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Reject a vector width the chosen model will not actually produce.

    Arbitrary widths are not supported: an index must be created at its model's
    native size. Truncation (OpenAI's Matryoshka `dimensions` parameter) is
    refused too — a narrowed vector is a different, weaker embedding.

    Shared by every index-creation path so they cannot drift:
    ``vector_indexes_endpoint.create_index`` (REST) and
    ``vector_index_lifecycle.ensure_index`` (programmatic).

    Returns an error message, or None if the request is consistent.
    """
    config = provider_config or {}
    expected = native_dimensions(provider_name, config)

    if expected is None:
        # Unrecognised model — width is unknowable without loading it, so the
        # only check left is the index ceiling.
        if dimensions > PGVECTOR_MAX_INDEX_DIMENSIONS:
            return (
                f"dimensions={dimensions} exceeds pgvector's "
                f"{PGVECTOR_MAX_INDEX_DIMENSIONS}-dimension limit for HNSW indexes."
            )
        return None

    if expected > PGVECTOR_MAX_INDEX_DIMENSIONS:
        return (
            f"Provider '{provider_name}' with model "
            f"'{config.get('model_name', 'default')}' emits {expected} dims, "
            f"which exceeds pgvector's {PGVECTOR_MAX_INDEX_DIMENSIONS}-dimension "
            f"limit for HNSW indexes. Choose a narrower model."
        )

    override = config.get("dimensions")
    if override is not None and override != expected:
        return (
            f"provider_config.dimensions={override} would truncate "
            f"'{provider_name}' output from its native {expected}. Arbitrary "
            f"vector widths are not supported — omit it."
        )

    if dimensions != expected:
        return (
            f"dimensions={dimensions} does not match provider "
            f"'{provider_name}', which emits {expected}. Create the index at "
            f"{expected} — arbitrary vector widths are not supported."
        )

    return None


def clear_cache() -> None:
    """Clear the provider instance cache."""
    _provider_cache.clear()


def _register_builtin_providers() -> None:
    """Register built-in providers. Called at module import time."""
    from vitalgraph.vectorization.vitalsigns_provider import (
        PROVIDER_NAME as VITALSIGNS_ONNX,
        VitalSignsProvider,
    )
    from vitalgraph.vectorization.openai_provider import OpenAIProvider
    from vitalgraph.vectorization.paraphrase_multilingual_minilm_provider import (
        PROVIDER_NAME as PARAPHRASE_MULTILINGUAL_MINILM,
        ParaphraseMultilingualMiniLMProvider,
    )

    register_provider(VITALSIGNS_ONNX, VitalSignsProvider)
    register_provider("openai", OpenAIProvider)
    register_provider(PARAPHRASE_MULTILINGUAL_MINILM, ParaphraseMultilingualMiniLMProvider)

    # Legacy name: the provider was registered as bare 'vitalsigns' before the
    # canonical name was aligned with the schema defaults.  Existing
    # {space}_vector_index rows and test fixtures still carry it.
    register_alias("vitalsigns", VITALSIGNS_ONNX)


# Auto-register built-in providers on import
_register_builtin_providers()
