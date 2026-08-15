"""Server-managed properties are stamped during import, not after it.

The background backfill task writes these with raw SQL and maintains no derived
table, so on a freshly loaded space `rdf_pred_stats` held 21 of 24 predicates —
missing exactly hasObjectCreationTime, hasObjectModificationDateTime and
hasObjectStatusType, at 10,000 rows each. Everything keyed on pred_stats loses
them silently: the join reorder's cardinality, the traversal criterion gate,
the value-histogram freshness reference.

Stamping during the import puts them in the same batch the loader already
passes to `sync_stats_after_insert`, so they are counted like anything else.
"""

from datetime import datetime, timezone

from rdflib import Literal, URIRef
from rdflib.namespace import XSD

from vitalgraph.kg_impl.kg_server_properties import (
    CREATION_TIME_URI, DEFAULT_ENTITY_TYPE, DEFAULT_STATUS, ENTITY_TYPE_URI,
    KGENTITY_CLASS_URI, MODIFICATION_TIME_URI, RDF_TYPE_URI, STATUS_TYPE_URI,
    server_property_quads_for_import)

NOW = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
G = URIRef("urn:g")
E = URIRef("urn:e:1")


def _typed(quads):
    return {(str(s), str(p)): o for s, p, o, _g in quads}


def test_a_kgentity_gets_all_four():
    got = server_property_quads_for_import(
        [(E, URIRef(RDF_TYPE_URI), URIRef(KGENTITY_CLASS_URI), G)], NOW)
    preds = {str(p) for _s, p, _o, _g in got}
    assert preds == {CREATION_TIME_URI, MODIFICATION_TIME_URI,
                     STATUS_TYPE_URI, ENTITY_TYPE_URI}
    assert all(str(g) == str(G) for *_x, g in got), "graph must be preserved"


def test_timestamps_are_typed_literals():
    """A plain string would classify as a URI: no dt_val, no histogram.

    The bulk loader decides term type from the rdflib class and falls back to
    'U', so an untyped stamp is stored as a URI and a range query over a
    creation time silently matches nothing.
    """
    got = _typed(server_property_quads_for_import(
        [(E, URIRef(RDF_TYPE_URI), URIRef(KGENTITY_CLASS_URI), G)], NOW))
    ct = got[(str(E), CREATION_TIME_URI)]
    assert isinstance(ct, Literal) and ct.datatype == XSD.dateTime
    assert isinstance(got[(str(E), MODIFICATION_TIME_URI)], Literal)
    # Status and type are URIs, and must stay URIs.
    assert isinstance(got[(str(E), STATUS_TYPE_URI)], URIRef)
    assert str(got[(str(E), STATUS_TYPE_URI)]) == DEFAULT_STATUS
    assert str(got[(str(E), ENTITY_TYPE_URI)]) == DEFAULT_ENTITY_TYPE


def test_a_property_the_batch_already_carries_is_not_duplicated():
    """These are single-valued. A second value is a wrong answer, not a dupe."""
    supplied = Literal("2020-01-01T00:00:00+00:00", datatype=XSD.dateTime)
    got = server_property_quads_for_import([
        (E, URIRef(RDF_TYPE_URI), URIRef(KGENTITY_CLASS_URI), G),
        (E, URIRef(CREATION_TIME_URI), supplied, G),
        (E, URIRef(STATUS_TYPE_URI), URIRef("urn:custom:status"), G),
    ], NOW)
    preds = {str(p) for _s, p, _o, _g in got}
    assert CREATION_TIME_URI not in preds
    assert STATUS_TYPE_URI not in preds
    assert preds == {MODIFICATION_TIME_URI, ENTITY_TYPE_URI}


def test_non_entities_are_left_alone():
    """Frames, slots and edges are not KGEntities and must not be stamped."""
    assert server_property_quads_for_import([
        (URIRef("urn:f:1"), URIRef(RDF_TYPE_URI),
         URIRef("http://vital.ai/ontology/haley-ai-kg#KGFrame"), G),
        (URIRef("urn:s:1"), URIRef("urn:p"), Literal(3), G),
    ], NOW) == []


def test_an_empty_batch_produces_nothing():
    assert server_property_quads_for_import([], NOW) == []


def test_each_entity_is_stamped_independently():
    e2 = URIRef("urn:e:2")
    got = server_property_quads_for_import([
        (E, URIRef(RDF_TYPE_URI), URIRef(KGENTITY_CLASS_URI), G),
        (e2, URIRef(RDF_TYPE_URI), URIRef(KGENTITY_CLASS_URI), G),
        (e2, URIRef(STATUS_TYPE_URI), URIRef("urn:custom"), G),
    ], NOW)
    by_subj = {}
    for s, p, _o, _g in got:
        by_subj.setdefault(str(s), set()).add(str(p))
    assert len(by_subj[str(E)]) == 4
    assert STATUS_TYPE_URI not in by_subj[str(e2)]
    assert len(by_subj[str(e2)]) == 3
