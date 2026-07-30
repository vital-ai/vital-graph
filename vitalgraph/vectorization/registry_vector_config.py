"""Shared embedding-model selection for the entity and agent registries.

Both registries share the same problem: they do NOT read the `provider` column
on their vector-index row, they embed with a provider chosen by environment
variable, and the write path (populator) and read path (search) must resolve to
exactly the same one or search compares vectors across embedding spaces.

This module holds that logic once. Each registry supplies its own env-var names
via a :class:`RegistryVectorConfig` instance, so the two can be pointed at
different models independently.

One column per model
--------------------

The vector tables carry a SEPARATE embedding column per supported model, each
at that model's native width, each nullable and each with its own HNSW index
(see EMBEDDING_COLUMNS). The configured provider selects which column is
written and read; the others stay NULL.

That is why switching models needs no DDL and no migration. It also removes the
failure mode a single shared `embedding` column had: that column meant
"whatever model happened to be configured when the row was written", so
pointing a different model at it returned confident nonsense. A per-model
column can only ever hold that model's vectors, so reading the wrong one
returns nothing rather than plausible garbage.

Unpopulated columns are effectively free — measured on pgvector, an HNSW index
over an all-NULL column is 16 kB versus 1.6 MB for a populated one, and the
NULLs cost only a null-bitmap bit in the heap.

Switching still requires re-vectorizing: the new column starts empty, so search
returns no vector hits until a full rebuild. That is a visibly empty result,
not a silently wrong one.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

VITALSIGNS_ONNX = "vitalsigns_onnx"
PARAPHRASE_MULTILINGUAL = "paraphrase_multilingual_minilm_l12_v2"
OPENAI = "openai"

DEFAULT_PROVIDER = VITALSIGNS_ONNX
DEFAULT_OPENAI_KEY_ENV = "OPENAI_API_KEY"

# The only OpenAI embedding model usable here — see PGVECTOR_MAX_INDEX_DIMENSIONS.
OPENAI_MODEL = "text-embedding-3-small"

SUPPORTED_PROVIDERS = (VITALSIGNS_ONNX, PARAPHRASE_MULTILINGUAL, OPENAI)

# provider -> (column name, native width).  Every one of these columns exists on
# the registry vector tables at all times; the configured provider picks which
# is used.
#
# Column names are FROZEN — they are on-disk schema.  Renaming one orphans the
# vectors already stored in it.  Add a new entry to add a model; never repurpose
# an existing one for a different model.
EMBEDDING_COLUMNS = {
    VITALSIGNS_ONNX:         ("embedding_vitalsigns_onnx", 384),
    PARAPHRASE_MULTILINGUAL: ("embedding_paraphrase_multilingual", 384),
    OPENAI:                  ("embedding_openai_3_small", 1536),
}

# Native output width of each local provider's model.
_LOCAL_DIMENSIONS = {VITALSIGNS_ONNX: 384, PARAPHRASE_MULTILINGUAL: 384}

# pgvector's HNSW and ivfflat indexes cannot be built on wider vectors.  The
# registry vector tables are HNSW-indexed, so this is a hard ceiling — it rules
# out text-embedding-3-large (3072).
PGVECTOR_MAX_INDEX_DIMENSIONS = 2000


class RegistryVectorConfig:
    """Embedding-model selection for one registry (entity, agent, ...).

    Args:
        label: Human-readable name used in log messages.
        env_var: Variable naming the provider.
        model_env_var: Variable overriding the model id.
        openai_key_env_var: Variable naming the env var that holds the API key.
    """

    def __init__(
        self,
        label: str,
        env_var: str,
        model_env_var: str,
        openai_key_env_var: str,
    ):
        self.label = label
        self.env_var = env_var
        self.model_env_var = model_env_var
        self.openai_key_env_var = openai_key_env_var

    # -- selection ----------------------------------------------------

    def provider_name(self) -> str:
        """Configured provider, falling back to the default on anything odd.

        Failing open keeps an existing deployment searchable rather than
        crashing it on a typo, and the default is what the vectors were almost
        certainly built with.
        """
        raw = os.environ.get(self.env_var, "").strip()
        if not raw:
            return DEFAULT_PROVIDER

        # Tolerate the legacy spelling of the ONNX provider.
        from vitalgraph.vectorization.registry import canonical_provider_name
        name = canonical_provider_name(raw)

        if name not in SUPPORTED_PROVIDERS:
            logger.warning(
                "%s=%r is not a supported %s provider (supported: %s) — "
                "falling back to %r",
                self.env_var, raw, self.label,
                ", ".join(SUPPORTED_PROVIDERS), DEFAULT_PROVIDER,
            )
            return DEFAULT_PROVIDER
        return name

    def model_name(self) -> str:
        """Model id for the configured provider."""
        override = os.environ.get(self.model_env_var, "").strip()
        if override:
            return override

        provider = self.provider_name()
        if provider == OPENAI:
            return OPENAI_MODEL
        if provider == PARAPHRASE_MULTILINGUAL:
            from vitalgraph.vectorization.paraphrase_multilingual_minilm_provider import (
                DEFAULT_MODEL,
            )
            return DEFAULT_MODEL
        return "paraphrase-MiniLM-L3-v2"

    def dimensions(self) -> int:
        """Native embedding width of the configured provider + model.

        Must be resolvable WITHOUT instantiating the provider: the DDL is
        generated by migration scripts that may hold no API key.
        """
        provider = self.provider_name()

        local = _LOCAL_DIMENSIONS.get(provider)
        if local is not None:
            return local

        from vitalgraph.vectorization.openai_provider import (
            DEFAULT_DIMENSIONS, MODEL_DIMENSIONS,
        )
        model = self.model_name()
        dims = MODEL_DIMENSIONS.get(model)
        if dims is None:
            logger.warning(
                "Unknown OpenAI embedding model %r — assuming %d dims. Set %s "
                "to a known model (%s) if the tables come out the wrong width.",
                model, DEFAULT_DIMENSIONS, self.model_env_var,
                ", ".join(sorted(MODEL_DIMENSIONS)),
            )
            dims = DEFAULT_DIMENSIONS

        if dims > PGVECTOR_MAX_INDEX_DIMENSIONS:
            raise ValueError(
                f"Embedding model {model!r} emits {dims} dims, but the {self.label} "
                f"vector tables are HNSW-indexed and pgvector supports at most "
                f"{PGVECTOR_MAX_INDEX_DIMENSIONS} dimensions per index. Use "
                f"{OPENAI_MODEL} ({MODEL_DIMENSIONS[OPENAI_MODEL]} dims)."
            )
        return dims

    def embedding_column(self) -> str:
        """The per-model column this provider reads and writes."""
        return EMBEDDING_COLUMNS[self.provider_name()][0]

    def provider_config(self) -> dict:
        """provider_config dict for the configured provider."""
        provider = self.provider_name()
        config: dict = {}

        if provider == OPENAI:
            config["api_key_env"] = (
                os.environ.get(self.openai_key_env_var, "").strip()
                or DEFAULT_OPENAI_KEY_ENV
            )
            config["model_name"] = self.model_name()
            # Deliberately no "dimensions": emit the model's native width.
        else:
            model = os.environ.get(self.model_env_var, "").strip()
            if model:
                config["model_name"] = model

        return config

    # -- instantiation ------------------------------------------------

    def get_provider(self, cache_key: str):
        """Instantiate the configured provider, asserting its output width.

        Args:
            cache_key: Registry cache key — the read and write paths use
                       different keys so each holds its own instance, but both
                       resolve the same provider name and config.
        """
        from vitalgraph.vectorization.registry import get_provider

        name = self.provider_name()
        expected = self.dimensions()
        provider = get_provider(name, self.provider_config(), cache_key=cache_key)

        if provider.dimensions != expected:
            raise ValueError(
                f"{self.label} provider {name!r} emits {provider.dimensions} "
                f"dims, but this module sizes the {self.label} vector tables at "
                f"vector({expected}). Refusing to start: inserts would fail and "
                f"searches would be meaningless."
            )

        if name != DEFAULT_PROVIDER:
            logger.info(
                "%s embeddings using non-default provider %r (via %s). Stored "
                "vectors must have been built with this same model — when the "
                "widths match, a mismatch degrades silently rather than erroring.",
                self.label, name, self.env_var,
            )
        logger.info(
            "%s vectorization provider: %s (model=%s, dims=%d)",
            self.label, provider.provider_name, provider.model_name,
            provider.dimensions,
        )
        return provider
