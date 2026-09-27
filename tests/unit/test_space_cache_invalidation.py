"""Dropping every process-local cache keyed by a space id — issue 232 step 4.

A rename takes effect the instant it commits, and none of the caches notice. The
failure is not that they are empty-but-stale: a term-uuid cache keyed
`(space_id, text, type)` keeps ANSWERING for a space that no longer exists, and
the answers look normal.

THE TEST THAT MATTERS IS `test_every_per_space_cache_is_covered`. A declared list
is only as good as its maintenance, and the failure mode of a stale list is
silent — a cache added next month keeps serving the old id and nothing reports
it. So the list is checked against what can be FOUND in the tree, and a new
per-space cache fails here rather than in production.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from vitalgraph.db.sparql_sql import space_cache_invalidation as M

pytestmark = [pytest.mark.unit]

_ROOT = pathlib.Path(__file__).resolve().parents[2] / "vitalgraph"


class TestItActuallyClears:

    def test_every_invalidator_runs_without_raising(self):
        """Each entry is a live callable, not a name that drifted."""
        result = M.invalidate_space_caches("inttest_no_such_space")
        assert len(result) == len(M.CACHE_INVALIDATORS)
        assert all(v >= 0 for v in result.values()), result

    def test_a_broken_invalidator_does_not_stop_the_others(self, monkeypatch):
        """The caller has already committed the rename by this point. Half the
        caches cleared beats none, so a failure is reported as -1 and the loop
        continues."""
        def _boom(space_id):
            raise RuntimeError("cache exploded")
        monkeypatch.setattr(M, "CACHE_INVALIDATORS",
                            [("broken", _boom)] + list(M.CACHE_INVALIDATORS))
        result = M.invalidate_space_caches("inttest_no_such_space")
        assert result["broken"] == -1
        assert all(v >= 0 for k, v in result.items() if k != "broken")

    def test_the_provider_cache_drops_only_this_space(self):
        """`_provider_cache` is keyed `{space}:{index}`, and the only way to clear
        it used to be the global `clear_cache()` — which throws away every other
        space's providers, each costing a tokenizer and an ONNX session to
        rebuild."""
        from vitalgraph.vectorization import registry
        registry._provider_cache["keep_me:idx"] = object()
        registry._provider_cache["drop_me:idx"] = object()
        registry._provider_cache["drop_me:other"] = object()
        try:
            dropped = registry.invalidate_space("drop_me")
            assert dropped == 2
            assert "keep_me:idx" in registry._provider_cache
            assert not any(k.startswith("drop_me:")
                           for k in registry._provider_cache)
        finally:
            registry._provider_cache.pop("keep_me:idx", None)

    def test_the_instance_cache_is_deliberately_untouched(self):
        """`_instance_by_signature` is keyed by (provider, config), not by space,
        so its entries stay valid across a rename — and they are the expensive
        ones."""
        from vitalgraph.vectorization import registry
        registry._instance_by_signature["sig"] = object()
        try:
            registry.invalidate_space("anything")
            assert "sig" in registry._instance_by_signature
        finally:
            registry._instance_by_signature.pop("sig", None)

    def test_the_ownership_cache_drops_only_this_space(self):
        from vitalgraph.kg_impl.kgentity_frame_update_impl import (
            KGEntityFrameUpdateProcessor as P)
        P._ownership_cache[("drop_me", "urn:f:1")] = ("urn:e:1", 0.0)
        P._ownership_cache[("keep_me", "urn:f:2")] = ("urn:e:2", 0.0)
        try:
            M.invalidate_space_caches("drop_me")
            assert ("keep_me", "urn:f:2") in P._ownership_cache
            assert ("drop_me", "urn:f:1") not in P._ownership_cache
        finally:
            P._ownership_cache.pop(("keep_me", "urn:f:2"), None)

    def test_the_space_manager_record_is_dropped_when_one_is_passed(self):
        class _SM:
            def __init__(self):
                self._spaces = {"drop_me": object(), "keep_me": object()}
        sm = _SM()
        result = M.invalidate_space_caches("drop_me", space_manager=sm)
        assert result["SpaceManager._spaces"] == 1
        assert "drop_me" not in sm._spaces
        assert "keep_me" in sm._spaces


class TestTheListIsKeptHonest:

    #: Caches the module declines to clear, each with its reason stated there.
    EXCLUSIONS = {
        "compile_cache",            # keyed by SPARQL hash, not by space
        "_instance_by_signature",   # keyed by (provider, config)
        "_IN_FLIGHT",               # quiesce CANCELS these; dropping would leak
    }

    @staticmethod
    def _per_space_caches():
        """Module-level dicts the code INDEXES BY `space_id`.

        DERIVED FROM USAGE, not from the declaration. The first version of this
        test looked for `space` on the declaration line and matched NOTHING — 19
        dict declarations, zero hits — so it could never fail. The type says
        `Dict[str, bool]`; only the indexing says the key is a space.
        """
        import re
        decl = re.compile(r"^(_[A-Za-z_]+)\s*[:=]\s*(?:Dict|dict)\[", re.M)
        out = []
        for path in _ROOT.rglob("*.py"):
            if "space_cache_invalidation" in str(path):
                continue
            text = path.read_text()
            for name in set(decl.findall(text)):
                if re.search(
                        rf"{re.escape(name)}(\.(get|pop|setdefault)\(\s*space_id"
                        rf"|\[\s*space_id)", text):
                    out.append((name, str(path.relative_to(_ROOT))))
        return sorted(out)

    def test_the_scan_is_not_vacuous(self):
        """A derived test that finds nothing passes forever. This one found six
        caches `issues/232`'s hand-written list had missed, so it must keep
        finding a realistic number."""
        found = self._per_space_caches()
        assert len(found) >= 10, found

    def test_every_per_space_cache_is_covered_or_excluded(self):
        """A cache added later that nobody wires up fails HERE — the only place
        it would ever be noticed, since a stale per-space cache answers normally.
        """
        source = (_ROOT / "db/sparql_sql/space_cache_invalidation.py").read_text()
        missing = [f"{name} ({path})" for name, path in self._per_space_caches()
                   if name not in self.EXCLUSIONS and name not in source]
        assert not missing, (
            "these are indexed by space_id and are not in CACHE_INVALIDATORS — "
            "a rename would leave them answering for the old id:\n    "
            + "\n    ".join(missing))

    def test_the_readiness_caches_are_covered(self):
        """Named explicitly because they are the dangerous shape: a cached
        'this table is present' for a space whose tables have moved selects a
        fast path over objects that are not there."""
        covered = " ".join(n for n, _ in M.CACHE_INVALIDATORS)
        for name in ("_frame_slot_ready", "_frame_slot_present",
                     "_prop_sort_present", "_frame_prop_sort_present"):
            assert name in covered, name

    def test_each_exclusion_is_justified_in_the_module(self):
        """An exclusion without a reason is indistinguishable from an omission."""
        source = (_ROOT / "db/sparql_sql/space_cache_invalidation.py").read_text()
        for name in self.EXCLUSIONS:
            assert name in source, f"{name} is excluded but not mentioned"
        assert "SPARQL hash" in source
        assert "would leak running work" in source
