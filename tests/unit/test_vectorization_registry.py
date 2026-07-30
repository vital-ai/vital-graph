"""Vectorization provider registry: canonical names, aliases, cache identity (L0 — no DB, no model load).

The registry maps a `provider` string stored on a {space}_vector_index row to
the class that embeds query text at search time.  Getting the name wrong is
silent: the three local providers below all emit 384 dims, so a mismatched
provider yields a well-formed vector in the wrong space rather than an error.

These tests deliberately avoid instantiating providers — construction loads
ONNX/torch weights.  Instantiation behaviour is covered in
test_scripts/vectorization/test_vectorization_providers.py.
"""

import pytest

from vitalgraph.vectorization.registry import (
    PROVIDER_ALIASES,
    PROVIDER_REGISTRY,
    canonical_provider_name,
    get_provider,
)

pytestmark = pytest.mark.unit

VITALSIGNS = "vitalsigns_onnx"
PARAPHRASE = "paraphrase_multilingual_minilm_l12_v2"


def test_builtin_providers_registered():
    assert set(PROVIDER_REGISTRY) >= {VITALSIGNS, "openai", PARAPHRASE}


def test_provider_names_are_canonical_not_aliases():
    """A name must not be both a registered provider and an alias."""
    assert not (set(PROVIDER_REGISTRY) & set(PROVIDER_ALIASES)), (
        "alias shadows a registered provider — get_provider would silently "
        "redirect away from the real class"
    )


def test_legacy_vitalsigns_name_resolves():
    """Rows written before the rename store the bare name."""
    assert canonical_provider_name("vitalsigns") == VITALSIGNS


def test_canonical_names_pass_through_unchanged():
    for name in PROVIDER_REGISTRY:
        assert canonical_provider_name(name) == name


def test_every_alias_targets_a_registered_provider():
    for alias, target in PROVIDER_ALIASES.items():
        assert target in PROVIDER_REGISTRY, (
            f"alias {alias!r} -> {target!r} which is not registered"
        )


def test_paraphrase_provider_class_declares_matching_name():
    """provider_name is what the cache compares against — it must match the key."""
    from vitalgraph.vectorization.paraphrase_multilingual_minilm_provider import (
        PROVIDER_NAME,
    )
    assert PROVIDER_NAME == PARAPHRASE
    assert PROVIDER_REGISTRY[PARAPHRASE].__name__ == "ParaphraseMultilingualMiniLMProvider"


def test_vitalsigns_provider_class_declares_matching_name():
    from vitalgraph.vectorization.vitalsigns_provider import PROVIDER_NAME
    assert PROVIDER_NAME == VITALSIGNS


def test_unknown_provider_raises_naming_the_requested_string():
    with pytest.raises(ValueError) as exc:
        get_provider("no_such_provider")
    msg = str(exc.value)
    assert "no_such_provider" in msg          # echo what the caller asked for
    assert VITALSIGNS in msg                  # ...and what was available


class TestParaphraseModelSourceResolution:
    """Where the multilingual weights are loaded from (no weights are loaded here).

    The Docker image bakes the model to a directory with save_pretrained().
    Warming the HF cache instead is NOT sufficient: AutoTokenizer still issues a
    model-info API call that fails under HF_HUB_OFFLINE=1.
    """

    @staticmethod
    def _fake_model_dir(tmp_path):
        for f in ("config.json", "tokenizer_config.json"):
            (tmp_path / f).write_text("{}")
        return str(tmp_path)

    def test_env_override_wins(self, tmp_path, monkeypatch):
        from vitalgraph.vectorization import paraphrase_multilingual_minilm_provider as m
        d = self._fake_model_dir(tmp_path)
        monkeypatch.setenv(m.MODEL_PATH_ENV_VAR, d)
        assert m.resolve_model_source() == d

    def test_baked_dir_used_when_present(self, tmp_path, monkeypatch):
        from vitalgraph.vectorization import paraphrase_multilingual_minilm_provider as m
        d = self._fake_model_dir(tmp_path)
        monkeypatch.delenv(m.MODEL_PATH_ENV_VAR, raising=False)
        monkeypatch.setattr(m, "BAKED_MODEL_DIR", d)
        assert m.resolve_model_source() == d

    def test_falls_back_to_hub_id_when_nothing_baked(self, tmp_path, monkeypatch):
        from vitalgraph.vectorization import paraphrase_multilingual_minilm_provider as m
        monkeypatch.delenv(m.MODEL_PATH_ENV_VAR, raising=False)
        monkeypatch.setattr(m, "BAKED_MODEL_DIR", str(tmp_path / "absent"))
        assert m.resolve_model_source() == m.DEFAULT_MODEL

    def test_explicit_bad_override_raises(self, tmp_path, monkeypatch):
        """Don't silently fall back to a network fetch the operator didn't ask for."""
        from vitalgraph.vectorization import paraphrase_multilingual_minilm_provider as m
        monkeypatch.setenv(m.MODEL_PATH_ENV_VAR, str(tmp_path / "nope"))
        with pytest.raises(ValueError, match="not a usable model directory"):
            m.resolve_model_source()

    def test_incomplete_dir_is_not_usable(self, tmp_path, monkeypatch):
        """A dir with config.json but no tokenizer config would fail at load time."""
        from vitalgraph.vectorization import paraphrase_multilingual_minilm_provider as m
        (tmp_path / "config.json").write_text("{}")
        monkeypatch.delenv(m.MODEL_PATH_ENV_VAR, raising=False)
        monkeypatch.setattr(m, "BAKED_MODEL_DIR", str(tmp_path))
        assert m.resolve_model_source() == m.DEFAULT_MODEL

    def test_baked_dir_matches_dockerfile(self):
        """The provider's default path and the Dockerfile's must not drift."""
        import pathlib
        from vitalgraph.vectorization import paraphrase_multilingual_minilm_provider as m
        dockerfile = pathlib.Path(__file__).parents[2] / "Dockerfile"
        assert m.BAKED_MODEL_DIR in dockerfile.read_text(), (
            f"{m.BAKED_MODEL_DIR} not found in Dockerfile — the baked model "
            f"directory and the provider's default have diverged"
        )


def test_alias_lookup_reuses_cached_instance(monkeypatch):
    """Regression: aliases must resolve BEFORE the cache check.

    get_provider validates its cache with `cached.provider_name == name`, and
    provider_name is always canonical.  If the alias were resolved after that
    check, a row storing the legacy 'vitalsigns' would miss on every call —
    evicting and reloading the ONNX model once per query.
    """
    import vitalgraph.vectorization.registry as reg

    created = []

    class FakeProvider:
        provider_name = VITALSIGNS

        @classmethod
        def from_config(cls, config):
            created.append(config)
            return cls()

    monkeypatch.setitem(reg.PROVIDER_REGISTRY, VITALSIGNS, FakeProvider)
    monkeypatch.setitem(reg._provider_cache, "_k", FakeProvider.from_config({}))
    created.clear()

    first = reg.get_provider(VITALSIGNS, {}, cache_key="_k")
    second = reg.get_provider("vitalsigns", {}, cache_key="_k")

    assert first is second, "legacy name did not hit the cached instance"
    assert created == [], "provider was rebuilt despite a warm cache"
