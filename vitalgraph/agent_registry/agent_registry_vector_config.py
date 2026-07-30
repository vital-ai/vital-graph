"""Agent registry embedding-model selection.

Mirrors the entity registry: the agent registry does NOT read the `provider`
column on its `agent_registry_vector_index` row. It embeds with a provider
chosen here, used by both the write path (AgentRegistryVectorPopulator) and the
read path (AgentRegistryImpl.search_agents_semantic, which reuses the
populator's provider instance).

Environment variables
---------------------

    VITALGRAPH_AGENT_REGISTRY_VECTOR_PROVIDER     default: vitalsigns_onnx
    VITALGRAPH_AGENT_REGISTRY_VECTOR_MODEL        default: provider-specific
    VITALGRAPH_AGENT_REGISTRY_OPENAI_API_KEY_ENV  default: OPENAI_API_KEY

Deliberately SEPARATE from the entity registry's variables: the two registries
hold different corpora and may want different models (staging's entity data is
multilingual; its agent data is not).

Supported providers and widths are shared with the entity registry — see
:mod:`vitalgraph.vectorization.registry_vector_config`. The agent vector table
carries the same one-column-per-model layout, so switching models needs no
schema migration, and a wrong-model read returns nothing rather than nonsense.
"""

import logging

from vitalgraph.vectorization.registry_vector_config import (
    DEFAULT_OPENAI_KEY_ENV,
    DEFAULT_PROVIDER,
    EMBEDDING_COLUMNS,
    OPENAI,
    OPENAI_MODEL,
    PARAPHRASE_MULTILINGUAL,
    PGVECTOR_MAX_INDEX_DIMENSIONS,
    SUPPORTED_PROVIDERS,
    VITALSIGNS_ONNX,
    RegistryVectorConfig,
)

logger = logging.getLogger(__name__)

ENV_VAR = "VITALGRAPH_AGENT_REGISTRY_VECTOR_PROVIDER"
MODEL_ENV_VAR = "VITALGRAPH_AGENT_REGISTRY_VECTOR_MODEL"
OPENAI_KEY_ENV_VAR = "VITALGRAPH_AGENT_REGISTRY_OPENAI_API_KEY_ENV"

_CONFIG = RegistryVectorConfig(
    label="Agent registry",
    env_var=ENV_VAR,
    model_env_var=MODEL_ENV_VAR,
    openai_key_env_var=OPENAI_KEY_ENV_VAR,
)


def get_agent_registry_provider_name() -> str:
    """Return the configured provider name for agent registry embeddings."""
    return _CONFIG.provider_name()


def get_agent_registry_model_name() -> str:
    """Return the model id for the configured provider."""
    return _CONFIG.model_name()


def get_agent_registry_dimensions() -> int:
    """Return the native embedding width of the configured provider + model."""
    return _CONFIG.dimensions()


def get_agent_registry_embedding_column() -> str:
    """Return the embedding column the configured provider reads and writes."""
    return _CONFIG.embedding_column()


def get_agent_registry_provider_config() -> dict:
    """Build the provider_config dict for the configured provider."""
    return _CONFIG.provider_config()


def get_agent_registry_provider(cache_key: str):
    """Instantiate the configured provider, asserting its output dimensions."""
    return _CONFIG.get_provider(cache_key)


__all__ = [
    "ENV_VAR", "MODEL_ENV_VAR", "OPENAI_KEY_ENV_VAR",
    "DEFAULT_PROVIDER", "DEFAULT_OPENAI_KEY_ENV", "OPENAI_MODEL",
    "VITALSIGNS_ONNX", "PARAPHRASE_MULTILINGUAL", "OPENAI",
    "SUPPORTED_PROVIDERS", "EMBEDDING_COLUMNS",
    "PGVECTOR_MAX_INDEX_DIMENSIONS",
    "get_agent_registry_provider_name",
    "get_agent_registry_model_name",
    "get_agent_registry_dimensions",
    "get_agent_registry_embedding_column",
    "get_agent_registry_provider_config",
    "get_agent_registry_provider",
]
