"""Entity registry embedding-model selection.

The entity registry does NOT read the `provider` column on its
`entity_registry_vector_index` row — it embeds with a provider chosen here, on
both the write path (EntityRegistryVectorPopulator) and the read path
(EntityRegistrySearch).  Both MUST resolve to the same provider or search
compares vectors across two different embedding spaces.

Environment variables
---------------------

    VITALGRAPH_ENTITY_REGISTRY_VECTOR_PROVIDER     default: vitalsigns_onnx
    VITALGRAPH_ENTITY_REGISTRY_VECTOR_MODEL        default: provider-specific
    VITALGRAPH_ENTITY_REGISTRY_OPENAI_API_KEY_ENV  default: OPENAI_API_KEY

Supported providers, and the vector width each implies
------------------------------------------------------

    vitalsigns_onnx                         384   paraphrase-MiniLM-L3-v2,
                                                  bundled ONNX, CPU, English.
    paraphrase_multilingual_minilm_l12_v2   384   paraphrase-multilingual-MiniLM
                                                  -L12-v2, multilingual, matches
                                                  Weaviate.  Baked into the image.
    openai                                 1536   text-embedding-3-small, remote
                                                  API, billed per call.

text-embedding-3-large (3072) is NOT usable here: the registry vector tables
carry an HNSW index, and pgvector's HNSW/ivfflat support tops out at 2000
dimensions.  A model wider than that is rejected up front rather than failing at
CREATE INDEX time.

The selection rules, the per-model column map, and the dimension guards live in
:mod:`vitalgraph.vectorization.registry_vector_config`, shared with the agent
registry.  This module is the entity registry's binding of them; the two
registries can be pointed at different models independently.
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

ENV_VAR = "VITALGRAPH_ENTITY_REGISTRY_VECTOR_PROVIDER"
MODEL_ENV_VAR = "VITALGRAPH_ENTITY_REGISTRY_VECTOR_MODEL"
OPENAI_KEY_ENV_VAR = "VITALGRAPH_ENTITY_REGISTRY_OPENAI_API_KEY_ENV"

_CONFIG = RegistryVectorConfig(
    label="Entity registry",
    env_var=ENV_VAR,
    model_env_var=MODEL_ENV_VAR,
    openai_key_env_var=OPENAI_KEY_ENV_VAR,
)


def get_entity_registry_provider_name() -> str:
    """Return the configured provider name for entity registry embeddings."""
    return _CONFIG.provider_name()


def get_entity_registry_model_name() -> str:
    """Return the model id for the configured provider."""
    return _CONFIG.model_name()


def get_entity_registry_dimensions() -> int:
    """Return the native embedding width of the configured provider + model."""
    return _CONFIG.dimensions()


def get_entity_registry_embedding_column() -> str:
    """Return the embedding column the configured provider reads and writes."""
    return _CONFIG.embedding_column()


def get_entity_registry_provider_config() -> dict:
    """Build the provider_config dict for the configured provider."""
    return _CONFIG.provider_config()


def get_entity_registry_provider(cache_key: str):
    """Instantiate the configured provider, asserting its output dimensions."""
    return _CONFIG.get_provider(cache_key)


__all__ = [
    "ENV_VAR", "MODEL_ENV_VAR", "OPENAI_KEY_ENV_VAR",
    "DEFAULT_PROVIDER", "DEFAULT_OPENAI_KEY_ENV", "OPENAI_MODEL",
    "VITALSIGNS_ONNX", "PARAPHRASE_MULTILINGUAL", "OPENAI",
    "SUPPORTED_PROVIDERS", "EMBEDDING_COLUMNS",
    "PGVECTOR_MAX_INDEX_DIMENSIONS",
    "get_entity_registry_provider_name",
    "get_entity_registry_model_name",
    "get_entity_registry_dimensions",
    "get_entity_registry_embedding_column",
    "get_entity_registry_provider_config",
    "get_entity_registry_provider",
]
