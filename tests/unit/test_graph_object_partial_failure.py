"""One malformed entity must cost that entity, not the whole graph.

`get_entity_graph` 500s about 19 times a day on production because two entities
carry a LIST for a property the ontology declares single-valued.
`_bindings_to_objects` calls `GraphObject.from_property_maps(entries)` ONCE for
every subject in the result, so whatever it rejects takes the entire request
with it — including every well-formed entity in the same graph.

The list itself is built deliberately: two quads for one predicate become
`[existing, value]`, which is the correct SPARQL reading and right for a
genuinely multi-valued property. The defect is a duplicate quad in the DATA. But
a data defect on two entities should cost those two entities.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import pytest

from vitalgraph.kg_impl import kg_graph_retrieval_utils as U


def _b(s, p, o, t="literal"):
    return {"s": {"value": s}, "p": {"value": p}, "o": {"value": o, "type": t}}


_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


@pytest.fixture
def two_subjects():
    """One good subject, one carrying a duplicate quad on the same predicate."""
    return [
        _b("urn:good", _TYPE, "urn:T", "uri"),
        _b("urn:good", "urn:name", "fine"),
        _b("urn:bad", _TYPE, "urn:T", "uri"),
        _b("urn:bad", "urn:name", "one"),
        _b("urn:bad", "urn:name", "two"),      # -> list on a single-valued prop
    ]


def test_a_duplicate_quad_becomes_a_list(two_subjects):
    """Pin the behaviour the fallback exists to survive — it is intentional and
    the fix must not silently change it."""
    captured = {}

    class _GO:
        @staticmethod
        def from_property_maps(entries):
            captured["entries"] = entries
            return [object() for _ in entries]

    _run(two_subjects, _GO)
    bad = next(e for e in captured["entries"] if e["subject_uri"] == "urn:bad")
    assert bad["properties"]["urn:name"] == ["one", "two"]


def test_the_good_entity_survives_a_bad_one(two_subjects, caplog):
    class _GO:
        @staticmethod
        def from_property_maps(entries):
            if any(isinstance(v, list)
                   for e in entries for v in e["properties"].values()):
                raise ValueError("property urn:name is single-valued")
            return [e["subject_uri"] for e in entries]

    with caplog.at_level("WARNING"):
        out = _run(two_subjects, _GO)

    assert out == ["urn:good"], "the well-formed entity must still be returned"
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "urn:bad" in msg, "the unusable entity must be named so data can be fixed"
    assert "urn:name" in msg, "and so must the property that made it unusable"


def test_the_bulk_path_is_still_the_fast_path(two_subjects):
    """The retry must cost nothing when nothing is wrong: exactly one call."""
    calls = []

    class _GO:
        @staticmethod
        def from_property_maps(entries):
            calls.append(len(entries))
            return [e["subject_uri"] for e in entries]

    out = _run(two_subjects, _GO)
    assert len(calls) == 1, "no per-entry retry when the bulk call succeeds"
    assert sorted(out) == ["urn:bad", "urn:good"]


def test_every_entity_failing_returns_empty_not_an_exception(two_subjects):
    """A caller expecting a list must not get an exception instead."""
    class _GO:
        @staticmethod
        def from_property_maps(entries):
            raise ValueError("nothing builds")

    assert _run(two_subjects, _GO) == []


def _run(bindings, fake_graphobject):
    """Invoke the helper with GraphObject replaced.

    It imports GraphObject inside the function body, so the patch has to land on
    the module it is imported FROM.
    """
    import sys
    import types

    mod = types.ModuleType("vital_ai_vitalsigns.model.GraphObject")
    mod.GraphObject = fake_graphobject
    prev = sys.modules.get("vital_ai_vitalsigns.model.GraphObject")
    sys.modules["vital_ai_vitalsigns.model.GraphObject"] = mod
    try:
        return U._bindings_to_objects(bindings)
    finally:
        if prev is not None:
            sys.modules["vital_ai_vitalsigns.model.GraphObject"] = prev
        else:
            del sys.modules["vital_ai_vitalsigns.model.GraphObject"]
