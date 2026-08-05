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

# Instances keyed by what determines their behaviour (provider + config) rather
# than by which caller asked. Several subsystems request "the local model" under
# their own cache keys; without this each gets its own ONNX session.
_instance_by_signature: Dict[str, VectorizationProvider] = {}


def _provider_signature(provider_name: str, config: Optional[Dict[str, Any]]) -> str:
    """Stable key for a (provider, config) pair."""
    import json
    return provider_name + "|" + json.dumps(config or {}, sort_keys=True, default=str)


# Cache key for the process-wide local embedding model.
#
# Loading it builds a tokenizer and an ONNX InferenceSession — hundreds of
# milliseconds to seconds on a cold container. Anything that just needs "the
# local model" must share ONE instance under this key rather than constructing
# its own, or the load is paid again on every call. Warmed at startup by
# `warm_local_provider()` so the cost never lands inside a request.
LOCAL_PROVIDER_CACHE_KEY = "shared:local-embedding-model"


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

    # Reuse an existing instance with the same provider + config, even when the
    # caller asked under a different cache_key.
    #
    # Callers key by their own identity — the agent registry, the entity
    # registry, each vector index, the startup warm-up — so identical
    # configurations each built their own model. For the local ONNX provider
    # that means a separate tokenizer and InferenceSession per caller: two were
    # being constructed at startup alone. Keying instances by what actually
    # determines behaviour collapses those to one.
    signature = _provider_signature(provider_name, config)
    instance = _instance_by_signature.get(signature)
    if instance is None:
        instance = cls.from_config(config or {})
        _instance_by_signature[signature] = instance
    else:
        logger.debug("Reusing provider instance for %s", signature)

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
    _instance_by_signature.clear()


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


def warm_local_provider() -> Optional[VectorizationProvider]:
    """
    Load the local embedding model once, ahead of any request.

    Call during application startup. Returns the cached provider, or None if the
    model is unavailable — warming is an optimisation, so a failure here must not
    stop the app from starting; the first real use will surface the error.
    """
    try:
        from vitalgraph.vectorization.vitalsigns_provider import PROVIDER_NAME
        provider = get_provider(PROVIDER_NAME, cache_key=LOCAL_PROVIDER_CACHE_KEY)
        # Construction builds the session; the FIRST inference is what pays for
        # graph optimisation and memory arena setup, so do one here too.
        embedder = getattr(provider, "_embedder", None)
        if embedder is not None:
            embedder.vectorize("warm")
        logger.info(
            "Local embedding model warmed: %s (%s dims)",
            provider.model_name, provider.dimensions,
        )
        return provider
    except Exception as e:
        logger.warning("Could not warm the local embedding model: %s", e)
        return None


def get_local_provider() -> Optional[VectorizationProvider]:
    """
    The shared local embedding provider, loading it if warming has not run.

    Prefer this over `get_provider(VITALSIGNS_ONNX)` with no cache key — that
    builds and discards a whole ONNX session per call.
    """
    try:
        from vitalgraph.vectorization.vitalsigns_provider import PROVIDER_NAME
        return get_provider(PROVIDER_NAME, cache_key=LOCAL_PROVIDER_CACHE_KEY)
    except Exception as e:
        logger.warning("Local embedding provider unavailable: %s", e)
        return None
