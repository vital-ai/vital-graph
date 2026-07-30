"""Vector index dimension validation (L0 — no DB, no model load).

Arbitrary vector widths are not supported: an index must be created at its
model's native width. Truncation is refused too — a narrowed vector is a
different, weaker embedding, and the entity registry's per-model columns are
reserved to the exact models declared for them.

Before this check, `provider="openai", dimensions=384` was accepted. It built a
vector(384) column and only failed much later at reindex, when the model tried
to write 1536 values into it.
"""

import pytest

from vitalgraph.endpoint.vector_indexes_endpoint import _validate_dimensions
from vitalgraph.vectorization.registry import (
    PGVECTOR_MAX_INDEX_DIMENSIONS,
    native_dimensions,
)

pytestmark = pytest.mark.unit

VITALSIGNS = "vitalsigns_onnx"
PARAPHRASE = "paraphrase_multilingual_minilm_l12_v2"


class _Body:
    """Minimal stand-in for CreateVectorIndexRequest."""

    def __init__(self, provider, dimensions, provider_config=None):
        self.provider = provider
        self.dimensions = dimensions
        self.provider_config = provider_config
        self.index_name = "test_idx"
        self.distance_metric = "cosine"


class TestNativeDimensions:
    def test_local_providers_report_384_without_loading(self):
        assert native_dimensions(VITALSIGNS) == 384
        assert native_dimensions(PARAPHRASE) == 384

    def test_openai_width_follows_model(self):
        assert native_dimensions("openai") == 1536
        assert native_dimensions("openai", {"model_name": "text-embedding-3-small"}) == 1536
        assert native_dimensions("openai", {"model_name": "text-embedding-3-large"}) == 3072

    def test_unknown_model_is_unknowable_not_guessed(self):
        assert native_dimensions("openai", {"model_name": "made-up"}) is None
        assert native_dimensions(PARAPHRASE, {"model_name": "some/other-model"}) is None

    def test_legacy_alias_resolves(self):
        assert native_dimensions("vitalsigns") == 384

    def test_unregistered_provider_raises(self):
        with pytest.raises(ValueError):
            native_dimensions("not_a_provider")


class TestValidateDimensions:
    @pytest.mark.parametrize("provider,dims", [
        (VITALSIGNS, 384),
        (PARAPHRASE, 384),
        ("openai", 1536),
        ("vitalsigns", 384),          # legacy alias
    ])
    def test_native_width_accepted(self, provider, dims):
        assert _validate_dimensions(_Body(provider, dims)) is None

    def test_openai_at_384_rejected(self):
        """The exact mismatch the UI could previously produce."""
        err = _validate_dimensions(_Body("openai", 384))
        assert err and "384" in err and "1536" in err

    def test_local_provider_at_1536_rejected(self):
        err = _validate_dimensions(_Body(VITALSIGNS, 1536))
        assert err and "does not match provider" in err

    def test_explicit_truncation_rejected(self):
        """OpenAI supports Matryoshka truncation; we deliberately do not."""
        err = _validate_dimensions(
            _Body("openai", 384, {"dimensions": 384}),
        )
        assert err and "truncate" in err

    def test_matching_explicit_dimensions_allowed(self):
        """Redundant but consistent — not an error."""
        assert _validate_dimensions(
            _Body("openai", 1536, {"dimensions": 1536}),
        ) is None

    def test_model_exceeding_pgvector_limit_rejected(self):
        """text-embedding-3-large is 3072; HNSW tops out at 2000."""
        err = _validate_dimensions(
            _Body("openai", 3072, {"model_name": "text-embedding-3-large"}),
        )
        assert err and str(PGVECTOR_MAX_INDEX_DIMENSIONS) in err

    def test_unknown_model_still_capped_by_pgvector(self):
        """Width unknowable, but the index ceiling still applies."""
        err = _validate_dimensions(
            _Body("openai", 4096, {"model_name": "made-up"}),
        )
        assert err and str(PGVECTOR_MAX_INDEX_DIMENSIONS) in err

    def test_unknown_model_under_limit_is_allowed(self):
        """Cannot validate the width, so do not guess — only the cap applies."""
        assert _validate_dimensions(
            _Body("openai", 512, {"model_name": "made-up"}),
        ) is None

    def test_none_provider_config_is_handled(self):
        assert _validate_dimensions(_Body("openai", 1536, None)) is None


def test_pgvector_limit_matches_entity_registry_constant():
    """Two modules encode this ceiling; they must agree."""
    from vitalgraph.entity_registry.entity_registry_vector_config import (
        PGVECTOR_MAX_INDEX_DIMENSIONS as registry_limit,
    )
    assert registry_limit == PGVECTOR_MAX_INDEX_DIMENSIONS
