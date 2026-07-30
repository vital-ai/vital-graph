"""Agent registry embedding-model selection (L0 — no DB, no model load).

Mirrors the entity registry, but with its OWN environment variables: staging's
entity corpus is multilingual while its agent corpus is not, so the two must be
settable independently.
"""

import pytest

from vitalgraph.agent_registry import agent_registry_vector_config as cfg
from vitalgraph.entity_registry import entity_registry_vector_config as entity_cfg

pytestmark = pytest.mark.unit


def test_default_is_vitalsigns_onnx(monkeypatch):
    monkeypatch.delenv(cfg.ENV_VAR, raising=False)
    assert cfg.get_agent_registry_provider_name() == "vitalsigns_onnx"


def test_selects_paraphrase_provider(monkeypatch):
    monkeypatch.setenv(cfg.ENV_VAR, "paraphrase_multilingual_minilm_l12_v2")
    assert (
        cfg.get_agent_registry_provider_name()
        == "paraphrase_multilingual_minilm_l12_v2"
    )


def test_legacy_vitalsigns_spelling_resolves(monkeypatch):
    monkeypatch.setenv(cfg.ENV_VAR, "vitalsigns")
    assert cfg.get_agent_registry_provider_name() == "vitalsigns_onnx"


def test_unknown_value_warns_and_falls_back(monkeypatch, caplog):
    monkeypatch.setenv(cfg.ENV_VAR, "not_a_provider")
    with caplog.at_level("WARNING"):
        assert cfg.get_agent_registry_provider_name() == cfg.DEFAULT_PROVIDER
    assert "not_a_provider" in caplog.text


def test_env_vars_are_distinct_from_entity_registry():
    """Shared code, separate knobs — the two corpora may need different models."""
    assert cfg.ENV_VAR != entity_cfg.ENV_VAR
    assert cfg.MODEL_ENV_VAR != entity_cfg.MODEL_ENV_VAR
    assert cfg.OPENAI_KEY_ENV_VAR != entity_cfg.OPENAI_KEY_ENV_VAR


def test_registries_resolve_independently(monkeypatch):
    """Setting one must not move the other."""
    monkeypatch.setenv(cfg.ENV_VAR, "paraphrase_multilingual_minilm_l12_v2")
    monkeypatch.delenv(entity_cfg.ENV_VAR, raising=False)

    assert cfg.get_agent_registry_provider_name() == "paraphrase_multilingual_minilm_l12_v2"
    assert entity_cfg.get_entity_registry_provider_name() == "vitalsigns_onnx"


def test_openai_config_does_not_pin_dimensions(monkeypatch):
    monkeypatch.setenv(cfg.ENV_VAR, "openai")
    config = cfg.get_agent_registry_provider_config()
    assert "dimensions" not in config
    assert config["model_name"] == "text-embedding-3-small"


def test_openai_key_env_is_overridable(monkeypatch):
    monkeypatch.setenv(cfg.ENV_VAR, "openai")
    monkeypatch.setenv(cfg.OPENAI_KEY_ENV_VAR, "AGENT_KEY")
    assert cfg.get_agent_registry_provider_config()["api_key_env"] == "AGENT_KEY"


def test_text_embedding_3_large_is_refused(monkeypatch):
    monkeypatch.setenv(cfg.ENV_VAR, "openai")
    monkeypatch.setenv(cfg.MODEL_ENV_VAR, "text-embedding-3-large")
    with pytest.raises(ValueError, match="2000"):
        cfg.get_agent_registry_dimensions()


class TestAgentEmbeddingColumns:
    def test_active_column_follows_config(self, monkeypatch):
        for provider, (column, _) in cfg.EMBEDDING_COLUMNS.items():
            monkeypatch.setenv(cfg.ENV_VAR, provider)
            assert cfg.get_agent_registry_embedding_column() == column

    def test_columns_match_entity_registry(self):
        """Both registries use the same layout — one migration serves both."""
        assert cfg.EMBEDDING_COLUMNS == entity_cfg.EMBEDDING_COLUMNS

    def test_schema_declares_and_indexes_every_column(self):
        from vitalgraph.agent_registry import agent_registry_vector_schema as schema
        ddl = " ".join(schema.create_tables_sql())
        for column, dims in cfg.EMBEDDING_COLUMNS.values():
            assert f"{column} " in ddl, f"{column} missing from agent DDL"
            assert f"vector({dims})" in ddl
            assert f"hnsw ({column} " in ddl, f"no HNSW index on {column}"

    def test_schema_dimensions_track_config(self):
        from vitalgraph.agent_registry import agent_registry_vector_schema as schema
        assert schema.DIMENSIONS == cfg.get_agent_registry_dimensions()

    def test_no_legacy_shared_embedding_column_in_ddl(self):
        """The single shared column is what the per-model layout replaced."""
        from vitalgraph.agent_registry import agent_registry_vector_schema as schema
        ddl = " ".join(" ".join(s.split()) for s in schema.create_tables_sql())
        assert "embedding vector(" not in ddl
