"""Unit tests for dropped-predicate diagnostics — issue 036.

A quad whose predicate is not a property of the object's class is discarded
during `quads → GraphObject` conversion. No error, no warning, and the write
reports success — so a client that sends a typo, a renamed property, or a
class/property confusion loses that data with no signal. It cost a real
debugging session in issue 018.

These tests pin the diagnostic, not a behaviour change: the predicates are
still dropped. Rejecting them would break callers that rely on extra
predicates being tolerated, and the failure mode here is *silence*, not
permissiveness.
"""

from __future__ import annotations

import logging

import pytest

from vitalgraph.model.quad_model import Quad
from vitalgraph.utils import quad_format_utils as qfu

H = "http://vital.ai/ontology/haley-ai-kg#"
V = "http://vital.ai/ontology/vital-core#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

LOGGER = "vitalgraph.utils.quad_format_utils"


def _quads(*preds, subject="urn:t:1", type_uri=f"{H}KGDocument"):
    out = [Quad(s=f"<{subject}>", p=f"<{RDF_TYPE}>", o=f"<{type_uri}>")]
    for p, o in preds:
        out.append(Quad(s=f"<{subject}>", p=f"<{p}>", o=o))
    return out


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


class TestWarnsOnDroppedPredicates:

    def test_unknown_predicate_is_reported(self, caplog):
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            qfu.quad_list_to_graphobjects(
                _quads((f"{H}hasTotallyMadeUpProperty", '"x"')))
        msgs = _warnings(caplog)
        assert msgs, "an unknown predicate was dropped with no warning"
        assert "hasTotallyMadeUpProperty" in msgs[0]
        assert "KGDocument" in msgs[0]

    def test_valid_predicates_produce_no_warning(self, caplog):
        """The check must not cry wolf on ordinary writes."""
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            qfu.quad_list_to_graphobjects(_quads((f"{V}hasName", '"Doc"')))
        assert _warnings(caplog) == []

    def test_predicates_are_still_dropped_not_rejected(self, caplog):
        """Diagnostic only — behaviour is unchanged."""
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            objs = qfu.quad_list_to_graphobjects(
                _quads((f"{V}hasName", '"Doc"'),
                       (f"{H}hasTotallyMadeUpProperty", '"x"')))
        assert len(objs) == 1
        out = qfu.graphobjects_to_quad_list(objs, "urn:g:1")
        assert any("hasName" in q.p for q in out)
        assert not any("hasTotallyMadeUpProperty" in q.p for q in out)

    def test_reports_the_count(self, caplog):
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            qfu.quad_list_to_graphobjects(
                _quads((f"{H}madeUpOne", '"x"'), (f"{H}madeUpTwo", '"y"')))
        assert "2 predicate(s)" in _warnings(caplog)[0]


class TestClassUsedAsPredicate:
    """A class URI written where a property belongs.

    The hint resolves the URI it is handed and derives nothing. An earlier
    version built `<namespace>Edge_<localname>` to guess which Edge class a
    property-style name "meant" — that requires splitting a URI and appending
    to it on a naming convention, which is guessing rather than resolving.
    """

    def test_a_class_uri_is_named_as_a_class(self, caplog):
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            qfu.quad_list_to_graphobjects(
                _quads((f"{H}Edge_hasKGDocumentFileNode", "<urn:file:1>")))
        assert "Edge_hasKGDocumentFileNode is a class, not a property" in _warnings(caplog)[0]

    def test_property_style_name_is_reported_without_a_guess(self, caplog):
        """`hasKGDocumentFileNode` is not itself a class, so it gets no hint —
        but it is still reported, which is what stops the silence."""
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            qfu.quad_list_to_graphobjects(
                _quads((f"{H}hasKGDocumentFileNode", "<urn:file:1>")))
        msg = _warnings(caplog)[0]
        assert f"{H}hasKGDocumentFileNode" in msg
        assert "is a class" not in msg

    def test_plain_unknown_predicate_gets_no_hint(self, caplog):
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            qfu.quad_list_to_graphobjects(
                _quads((f"{H}hasTotallyMadeUpProperty", '"x"')))
        assert "is a class" not in _warnings(caplog)[0]

    def test_predicates_are_reported_as_full_uris(self, caplog):
        """Abbreviating would mean splitting on a separator this code has no
        business assuming, and two namespaces can share a local name."""
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            qfu.quad_list_to_graphobjects(
                _quads((f"{H}hasTotallyMadeUpProperty", '"x"')))
        assert f"{H}hasTotallyMadeUpProperty" in _warnings(caplog)[0]


class TestBothConversionPaths:
    """The fast path and the rdflib fallback use different VitalSigns entry
    points and do not share a fix site. The fallback is reached only when the
    fast path raised — exactly when losing a diagnostic is worst."""

    def test_rdflib_fallback_also_warns(self, caplog):
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            qfu._quad_list_to_graphobjects_rdflib(
                _quads((f"{H}hasTotallyMadeUpProperty", '"x"')))
        assert any("hasTotallyMadeUpProperty" in m for m in _warnings(caplog))


class TestDoesNotGuessWhenItCannotResolve:

    def test_unresolvable_type_is_silent(self, caplog):
        """An unregistered class is not evidence a predicate is wrong — saying
        nothing beats a false accusation on every custom type.

        Exercised through `_warn_dropped_predicates` directly: a full
        conversion with an unregistered type *raises* (VitalSigns
        `get_vitalsigns_class` throws), so that case is already loud and is not
        what this issue is about. The silent case is a **known** class with an
        unknown predicate.
        """
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            qfu._warn_dropped_predicates({
                "urn:t:1": {"type_uri": "urn:not:a:registered:class",
                            "properties": {f"{H}anything": "x"}},
            })
        assert _warnings(caplog) == []

    def test_subject_without_a_type_is_silent(self, caplog):
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            qfu._warn_dropped_predicates(
                {"urn:t:1": {"type_uri": None, "properties": {f"{H}x": "v"}}})
        assert _warnings(caplog) == []


class TestAllowedPropertyLookup:

    def test_resolves_a_known_class(self):
        allowed = qfu._allowed_property_uris(f"{H}KGDocument")
        assert allowed is not None
        assert f"{V}hasName" in allowed
        assert f"{H}hasKGDocumentFileNode" not in allowed

    def test_unknown_class_returns_none_not_empty(self):
        """None means "cannot say"; an empty set would mean "nothing is
        allowed" and would make every predicate look wrong."""
        assert qfu._allowed_property_uris("urn:not:a:class") is None

    def test_result_is_cached(self):
        qfu._allowed_property_uris(f"{H}KGDocument")
        assert f"{H}KGDocument" in qfu._ALLOWED_PROPS_CACHE
