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


class TestUnregisteredTypes:
    """VitalSigns raises KeyError for an unregistered type before recording
    anything for it, so an unknown class never produces a dropped-predicate
    report: the conversion fails loudly instead, as it always has."""

    def test_unregistered_type_raises_and_is_not_reported(self, caplog):
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            with pytest.raises(KeyError):
                qfu.quad_list_to_graphobjects(
                    _quads((f"{H}anything", '"x"'), type_uri="urn:not:a:registered:class"))
        assert not any("anything" in m for m in _warnings(caplog))

    def test_known_objects_in_a_failing_batch_are_still_reported(self, caplog):
        """Reported in `finally`: the batch raises on the unknown type, and the
        predicate dropped from the object converted before it is still logged."""
        quads = (_quads((f"{H}hasTotallyMadeUpProperty", '"x"'))
                 + _quads((f"{H}other", '"y"'), subject="urn:t:2",
                          type_uri="urn:not:a:registered:class"))
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            with pytest.raises(KeyError):
                qfu.quad_list_to_graphobjects(quads)
        assert any("hasTotallyMadeUpProperty" in m for m in _warnings(caplog))


class TestOnlyWhatWasActuallyDropped:
    """VitalSigns reports what the conversion did not store, so the check
    cannot accuse a predicate the object kept. The check it replaced read a
    class's allowed properties itself, and once read the narrow set: it
    accused four inherited properties on every entity fetch."""

    def test_inherited_properties_are_not_reported(self, caplog):
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            qfu.quad_list_to_graphobjects(
                _quads((f"{H}hasKGGraphURI", "<urn:t:1>"),
                       ("http://vital.ai/ontology/vital-aimp#hasObjectCreationTime",
                        '"2026-11-16T10:00:00Z"^^<http://www.w3.org/2001/XMLSchema#dateTime>'),
                       type_uri=f"{H}KGEntity"))
        assert _warnings(caplog) == []

    def test_annotations_are_not_reported(self, caplog):
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            qfu.quad_list_to_graphobjects(
                _quads(("http://www.w3.org/2000/01/rdf-schema#label", '"a label"@en')))
        assert _warnings(caplog) == []

    def test_one_warning_per_class_not_per_object(self, caplog):
        quads = (_quads((f"{H}madeUp", '"x"'), subject="urn:t:1")
                 + _quads((f"{H}madeUp", '"y"'), subject="urn:t:2"))
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            qfu.quad_list_to_graphobjects(quads)
        msgs = [m for m in _warnings(caplog) if "madeUp" in m]
        assert len(msgs) == 1 and "1 predicate(s)" in msgs[0]
