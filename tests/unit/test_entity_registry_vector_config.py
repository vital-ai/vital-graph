"""Entity registry embedding-model selection (L0 — no DB, no model load).

The entity registry ignores the `provider` column on its vector-index row and
picks a provider from VITALGRAPH_ENTITY_REGISTRY_VECTOR_PROVIDER instead.  The
write path (populator) and read path (search) both call the same resolver, so
these tests pin the resolution rules rather than the call sites.

Both supported providers emit 384 dims, so a wrong answer here does not raise —
it silently searches the wrong vector space.
"""

import pytest

from vitalgraph.entity_registry import entity_registry_vector_config as cfg

pytestmark = pytest.mark.unit


def test_default_is_vitalsigns_onnx(monkeypatch):
    monkeypatch.delenv(cfg.ENV_VAR, raising=False)
    assert cfg.get_entity_registry_provider_name() == "vitalsigns_onnx"


def test_empty_or_whitespace_falls_back_to_default(monkeypatch):
    for raw in ("", "   "):
        monkeypatch.setenv(cfg.ENV_VAR, raw)
        assert cfg.get_entity_registry_provider_name() == cfg.DEFAULT_PROVIDER


def test_selects_paraphrase_provider(monkeypatch):
    monkeypatch.setenv(cfg.ENV_VAR, "paraphrase_multilingual_minilm_l12_v2")
    assert (
        cfg.get_entity_registry_provider_name()
        == "paraphrase_multilingual_minilm_l12_v2"
    )


def test_surrounding_whitespace_is_tolerated(monkeypatch):
    monkeypatch.setenv(cfg.ENV_VAR, "  paraphrase_multilingual_minilm_l12_v2\n")
    assert (
        cfg.get_entity_registry_provider_name()
        == "paraphrase_multilingual_minilm_l12_v2"
    )


def test_legacy_vitalsigns_spelling_resolves(monkeypatch):
    """Deployments predating the rename may still set the bare name."""
    monkeypatch.setenv(cfg.ENV_VAR, "vitalsigns")
    assert cfg.get_entity_registry_provider_name() == "vitalsigns_onnx"


def test_unknown_value_warns_and_falls_back(monkeypatch, caplog):
    """Fail open: a typo must not take down an otherwise-working deployment."""
    monkeypatch.setenv(cfg.ENV_VAR, "not_a_provider")
    with caplog.at_level("WARNING"):
        assert cfg.get_entity_registry_provider_name() == cfg.DEFAULT_PROVIDER
    assert "not_a_provider" in caplog.text


def test_openai_is_supported(monkeypatch):
    monkeypatch.setenv(cfg.ENV_VAR, "openai")
    assert cfg.get_entity_registry_provider_name() == "openai"


def test_supported_providers_are_all_registered():
    from vitalgraph.vectorization.registry import PROVIDER_REGISTRY
    for name in cfg.SUPPORTED_PROVIDERS:
        assert name in PROVIDER_REGISTRY, f"{name} is not a registered provider"


class TestEmbeddingColumns:
    """One column per model — the config selects which is read and written.

    This replaced a single shared `embedding` column whose width tracked the
    configured model. The shared column meant "whatever model was configured
    when this row was written", so pointing a different model at it returned
    confident nonsense. A per-model column can only hold that model's vectors.
    """

    def test_every_supported_provider_has_a_column(self):
        assert set(cfg.EMBEDDING_COLUMNS) == set(cfg.SUPPORTED_PROVIDERS)

    def test_column_names_are_unique(self):
        names = [c for c, _ in cfg.EMBEDDING_COLUMNS.values()]
        assert len(names) == len(set(names))

    def test_column_widths_match_provider_dimensions(self, monkeypatch):
        for provider, (_, dims) in cfg.EMBEDDING_COLUMNS.items():
            monkeypatch.setenv(cfg.ENV_VAR, provider)
            monkeypatch.delenv(cfg.MODEL_ENV_VAR, raising=False)
            assert cfg.get_entity_registry_dimensions() == dims, provider

    def test_active_column_follows_config(self, monkeypatch):
        for provider, (column, _) in cfg.EMBEDDING_COLUMNS.items():
            monkeypatch.setenv(cfg.ENV_VAR, provider)
            assert cfg.get_entity_registry_embedding_column() == column

    def test_column_names_fit_postgres_identifier_limit(self):
        for column, _ in cfg.EMBEDDING_COLUMNS.values():
            assert len(column) <= 63, column

    def test_column_names_are_sql_safe(self):
        """They are interpolated straight into SQL, so they must be inert."""
        import re
        for column, _ in cfg.EMBEDDING_COLUMNS.values():
            assert re.fullmatch(r"[a-z_][a-z0-9_]*", column), column

    def test_schema_declares_every_column(self):
        """The DDL must create all model columns, not just the active one."""
        from vitalgraph.entity_registry import entity_registry_vector_schema as schema
        ddl = " ".join(schema.create_tables_sql())
        for column, dims in cfg.EMBEDDING_COLUMNS.values():
            assert f"{column} " in ddl, f"{column} missing from DDL"
            assert f"vector({dims})" in ddl

    def test_schema_indexes_every_column(self):
        from vitalgraph.entity_registry import entity_registry_vector_schema as schema
        ddl = " ".join(schema.create_tables_sql())
        for column, _ in cfg.EMBEDDING_COLUMNS.values():
            assert f"hnsw ({column} " in ddl, f"no HNSW index on {column}"

    def test_embedding_columns_are_nullable(self):
        """Only the active model's column is filled; the rest must accept NULL."""
        from vitalgraph.entity_registry import entity_registry_vector_schema as schema
        ddl = " ".join(schema.create_tables_sql())
        for column, dims in cfg.EMBEDDING_COLUMNS.values():
            assert f"{column} vector({dims}) NOT NULL" not in " ".join(ddl.split())


class TestDimensions:
    """Vector width is the model's native size — never truncated to fit."""

    def test_local_providers_are_384(self, monkeypatch):
        for name in (cfg.VITALSIGNS_ONNX, cfg.PARAPHRASE_MULTILINGUAL):
            monkeypatch.setenv(cfg.ENV_VAR, name)
            assert cfg.get_entity_registry_dimensions() == 384

    def test_openai_is_native_1536_not_truncated(self, monkeypatch):
        """text-embedding-3-small stored at full width, not shortened to 384."""
        monkeypatch.setenv(cfg.ENV_VAR, "openai")
        monkeypatch.delenv(cfg.MODEL_ENV_VAR, raising=False)
        assert cfg.get_entity_registry_model_name() == "text-embedding-3-small"
        assert cfg.get_entity_registry_dimensions() == 1536

    def test_openai_config_does_not_pin_dimensions(self, monkeypatch):
        """Passing `dimensions` would truncate — the provider must emit native width."""
        monkeypatch.setenv(cfg.ENV_VAR, "openai")
        config = cfg.get_entity_registry_provider_config()
        assert "dimensions" not in config
        assert config["model_name"] == "text-embedding-3-small"
        assert config["api_key_env"] == "OPENAI_API_KEY"

    def test_openai_api_key_env_is_overridable(self, monkeypatch):
        monkeypatch.setenv(cfg.ENV_VAR, "openai")
        monkeypatch.setenv(cfg.OPENAI_KEY_ENV_VAR, "MY_KEY_VAR")
        assert cfg.get_entity_registry_provider_config()["api_key_env"] == "MY_KEY_VAR"

    def test_text_embedding_3_large_is_refused(self, monkeypatch):
        """3072 dims exceeds pgvector's HNSW index limit of 2000."""
        monkeypatch.setenv(cfg.ENV_VAR, "openai")
        monkeypatch.setenv(cfg.MODEL_ENV_VAR, "text-embedding-3-large")
        with pytest.raises(ValueError, match="2000"):
            cfg.get_entity_registry_dimensions()

    def test_schema_dimensions_track_config(self):
        """The DDL width and the resolver must not diverge."""
        from vitalgraph.entity_registry.entity_registry_vector_schema import DIMENSIONS
        assert DIMENSIONS == cfg.get_entity_registry_dimensions()

    def test_pgvector_limit_is_below_large(self):
        assert cfg.PGVECTOR_MAX_INDEX_DIMENSIONS < 3072


def test_dimension_mismatch_is_refused(monkeypatch):
    """A provider whose real output disagrees with the DDL must not be handed back."""
    class WrongDims:
        provider_name = "vitalsigns_onnx"
        model_name = "fake"
        dimensions = 1536

    monkeypatch.setattr(cfg, "get_entity_registry_provider_name", lambda: "vitalsigns_onnx")
    monkeypatch.setattr(cfg, "get_entity_registry_dimensions", lambda: 384)
    monkeypatch.setattr(
        "vitalgraph.vectorization.registry.get_provider",
        lambda name, config=None, cache_key=None: WrongDims(),
    )
    with pytest.raises(ValueError, match="1536"):
        cfg.get_entity_registry_provider(cache_key="test")


def test_read_and_write_paths_resolve_identically(monkeypatch):
    """Populator and search must never diverge — that is the silent-failure mode."""
    monkeypatch.setenv(cfg.ENV_VAR, "paraphrase_multilingual_minilm_l12_v2")
    resolved = {
        key: cfg.get_entity_registry_provider_name()
        for key in ("entity_registry", "entity_registry_search")
    }
    assert len(set(resolved.values())) == 1, resolved
