"""Fuzzy matching through the API: the space's one index, populate, and ORDER BY.

Three defects found by a client building a funder-name index (2026-11-12):

- `issues/337`: `ORDER BY DESC(?score)` on a `BIND(vg:fuzzyMatch(...) AS ?score)`
  failed with "collations are not supported by type numeric", and
  `xsd:double(?score)` with "operator does not exist: numeric ~ unknown".
- `issues/338`: `POST /fuzzy-mappings/populate` looked the mapping up as
  `kgentity` whatever it was, so a mapping of any other type indexed nothing,
  and the call still answered OK.
- `issues/339`: the query and auto-sync used only the FIRST enabled mapping, so
  a second mapping's properties were never searched or kept current.

The space has one pair of band tables, so its fuzzy index is the union of its
enabled mappings; each test sets the mappings it needs, rebuilds, and asserts
through `vg:fuzzyMatch` or the stats endpoint.
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from vitalgraph.model.sparql_model import SPARQLQueryRequest, SPARQLUpdateRequest

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

HALEY = "http://vital.ai/ontology/haley-ai-kg#"
VC = "http://vital.ai/ontology/vital-core#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
HAS_NAME = f"{VC}hasName"
ALIAS = "urn:fuzzytest:hasAlias"
NS = "urn:fuzzytest:"

# subject -> (rdf:type, hasName, aliases)
SUBJECTS = {
    f"{NS}funder_metrics": (f"{HALEY}KGEntity", "FUNDING METRICS LLC", ["FM LENDING GROUP"]),
    f"{NS}funder_square":  (f"{HALEY}KGEntity", "SQUARE FUNDING LLC", []),
    f"{NS}funder_mason":   (f"{HALEY}KGEntity", "MASON CAPITAL", []),
    f"{NS}mention_merk":   (f"{HALEY}KGEntityMention", "MERK FUNDING INC", []),
}
NAMED = len(SUBJECTS)                                        # subjects with hasName
ENTITIES = sum(1 for t, _, _ in SUBJECTS.values() if t.endswith("#KGEntity"))
WAIT_S = 30.0


def _triples(subject, rdf_type, name, aliases):
    out = [f"<{subject}> <{RDF_TYPE}> <{rdf_type}> .",
           f"<{subject}> <{VC}vitaltype> <{rdf_type}> .",
           f'<{subject}> <{HAS_NAME}> "{name}" .']
    out += [f'<{subject}> <{ALIAS}> "{a}" .' for a in aliases]
    return out


async def _update(vg_client, space, graph, body):
    r = await vg_client.sparql.execute_sparql_update(
        space, SPARQLUpdateRequest(update=f"INSERT DATA {{ GRAPH <{graph}> {{ {body} }} }}"))
    assert getattr(r, "success", True) is not False and not getattr(r, "error", None), r


async def _query(vg_client, space, q):
    r = await vg_client.sparql.execute_sparql_query(space, SPARQLQueryRequest(query=q))
    assert not getattr(r, "error", None), r.error
    return (r.results or {}).get("bindings", [])


def _fuzzy_query(graph, text, min_score, *, rdf_type=None, order=""):
    type_pattern = f"?s <{RDF_TYPE}> <{rdf_type}> ." if rdf_type else ""
    return f"""
        SELECT ?s ?score WHERE {{
            GRAPH <{graph}> {{ ?s <{HAS_NAME}> ?name . {type_pattern} }}
            BIND(<http://vital.ai/ontology/vitalgraph#fuzzyMatch>(?s, "{text}", {min_score}) AS ?score)
            FILTER(?score > 0)
        }} {order}"""


async def _scores(vg_client, space, graph, text, min_score=50, **kw):
    rows = await _query(vg_client, space, _fuzzy_query(graph, text, min_score, **kw))
    return {b["s"]["value"]: float(b["score"]["value"]) for b in rows}


async def _set_mappings(vg_client, space, specs):
    """Replace the space's fuzzy mappings with `specs`: [(mapping_type, [property])]."""
    listed = await vg_client.fuzzy_mappings.list_mappings(space_id=space)
    for m in listed.mappings:
        await vg_client.fuzzy_mappings.delete_mapping(space_id=space, mapping_id=m.mapping_id)
    ids = []
    for mapping_type, props in specs:
        m = await vg_client.fuzzy_mappings.create_mapping(
            space_id=space, index_name="fuzzytest", mapping_type=mapping_type)
        for p in props:
            await vg_client.fuzzy_mappings.add_property(
                space_id=space, mapping_id=m.mapping_id, property_uri=p)
        ids.append(m.mapping_id)
    return ids


async def _populate(vg_client, space, mapping_id, expect_subjects):
    """Populate and wait until the index holds exactly `expect_subjects` subjects."""
    resp = await vg_client.fuzzy_mappings.populate(space_id=space, mapping_id=mapping_id)
    deadline = asyncio.get_running_loop().time() + WAIT_S
    count = None
    while asyncio.get_running_loop().time() < deadline:
        stats = await vg_client.fuzzy_mappings.get_stats(space_id=space, mapping_id=mapping_id)
        count = stats.entity_count
        if count == expect_subjects:
            return resp
        await asyncio.sleep(0.5)
    pytest.fail(f"populate indexed {count} subjects, expected {expect_subjects}; response {resp}")


async def _eventually(fn, timeout=WAIT_S):
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        value = await fn()
        if value or asyncio.get_running_loop().time() >= deadline:
            return value
        await asyncio.sleep(0.5)


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def funders(vg_client, test_space, test_graph):
    body = " ".join(t for s, (ty, n, a) in SUBJECTS.items() for t in _triples(s, ty, n, a))
    await _update(vg_client, test_space, test_graph, body)
    return test_space, test_graph


# ---------------------------------------------------------------------------
# issues/337 — ORDER BY a fuzzy score
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("order", ["ORDER BY DESC(?score)",
                                   "ORDER BY DESC(<http://www.w3.org/2001/XMLSchema#double>(?score))",
                                   "ORDER BY ?score"])
async def test_a_fuzzy_score_can_be_ordered(vg_client, funders, order):
    space, graph = funders
    ids = await _set_mappings(vg_client, space, [("kgentity", [HAS_NAME])])
    await _populate(vg_client, space, ids[0], ENTITIES)

    rows = await _query(vg_client, space,
                        _fuzzy_query(graph, "FUNDING METRICS LLC", 10, order=order))
    scores = [float(b["score"]["value"]) for b in rows]
    assert len(scores) >= 2, rows                      # an order needs two rows to mean anything
    expected = sorted(scores, reverse="DESC" in order)
    assert scores == expected
    assert rows[0 if "DESC" in order else -1]["s"]["value"] == f"{NS}funder_metrics"


# ---------------------------------------------------------------------------
# issues/338 — populate builds the index for any mapping type
# ---------------------------------------------------------------------------

async def test_populate_indexes_a_mapping_with_no_type_filter(vg_client, funders):
    """A `kgframe` mapping has no rdf:type filter: every subject with the property.
    Populate used to resolve it as `kgentity`, find nothing, and index 0."""
    space, graph = funders
    ids = await _set_mappings(vg_client, space, [("kgframe", [HAS_NAME])])
    resp = await _populate(vg_client, space, ids[0], NAMED)
    assert resp.get("status") == "ok", resp

    found = await _scores(vg_client, space, graph, "MERK FUNDING INC", 90,
                          rdf_type=f"{HALEY}KGEntityMention")
    assert set(found) == {f"{NS}mention_merk"}


async def test_populate_of_a_kgentity_mapping_keeps_its_type_filter(vg_client, funders):
    space, _ = funders
    ids = await _set_mappings(vg_client, space, [("kgentity", [HAS_NAME])])
    await _populate(vg_client, space, ids[0], ENTITIES)       # not the mention


async def test_populate_with_nothing_to_index_says_so(vg_client, funders):
    space, _ = funders
    ids = await _set_mappings(vg_client, space, [("kgentity", [])])
    resp = await vg_client.fuzzy_mappings.populate(space_id=space, mapping_id=ids[0])
    assert resp.get("status") == "no_op", resp
    assert "nothing to index" in resp.get("message", "")


# ---------------------------------------------------------------------------
# issues/339 — every enabled mapping is part of the index
# ---------------------------------------------------------------------------

async def test_a_second_mappings_property_is_searched(vg_client, funders):
    space, graph = funders
    ids = await _set_mappings(vg_client, space, [("kgentity", [HAS_NAME]),
                                                 ("kgentity", [ALIAS])])
    await _populate(vg_client, space, ids[1], ENTITIES)

    found = await _scores(vg_client, space, graph, "FM LENDING GROUP", 90)
    assert found.get(f"{NS}funder_metrics") == 100.0, found


async def test_auto_sync_indexes_a_second_mappings_property(vg_client, funders):
    """A write is re-indexed through every mapping, not the first one only."""
    space, graph = funders
    ids = await _set_mappings(vg_client, space, [("kgentity", [HAS_NAME]),
                                                 ("kgentity", [ALIAS])])
    await _populate(vg_client, space, ids[0], ENTITIES)

    await _update(vg_client, space, graph,
                  f'<{NS}funder_square> <{ALIAS}> "SQ CAPITAL PARTNERS" .')
    found = await _eventually(lambda: _scores(vg_client, space, graph, "SQ CAPITAL PARTNERS", 90))
    assert found.get(f"{NS}funder_square") == 100.0, found


async def test_mappings_with_different_settings_are_reported(vg_client, funders):
    space, _ = funders
    await _set_mappings(vg_client, space, [("kgentity", [HAS_NAME])])
    m = await vg_client.fuzzy_mappings.create_mapping(
        space_id=space, index_name="fuzzytest", mapping_type="kgentity", shingle_k=4)
    assert "uses the settings of mapping" in (m.message or ""), m


# The same cast defect without fuzzy matching: any computed number (issues/337).
_X = "http://www.w3.org/2001/XMLSchema#"


@pytest.mark.parametrize("query, expected", [
    (f"SELECT ?y WHERE {{ BIND(1+1 AS ?x) BIND(<{_X}double>(?x) AS ?y) }}", [2.0]),
    (f"SELECT ?y WHERE {{ BIND(2+3 AS ?x) BIND(<{_X}integer>(?x) AS ?y) }}", [5.0]),
    (f"SELECT ?y WHERE {{ BIND(1+1 AS ?x) BIND(<{_X}decimal>(?x) AS ?y) }}", [2.0]),
    (f"SELECT ?y WHERE {{ BIND(<{_X}double>(3 * 4) AS ?y) }}", [12.0]),
    # Rows from a UNION of BINDs; VALUES numbers are covered in test_values_numbers_api.
    (f"SELECT ?y WHERE {{ {{ BIND(1 AS ?a) }} UNION {{ BIND(2 AS ?a) }} BIND(?a * 3 AS ?y) }} "
     f"ORDER BY DESC(<{_X}double>(?y))", [6.0, 3.0]),
])
async def test_a_computed_number_can_be_cast(vg_client, test_space, query, expected):
    rows = await _query(vg_client, test_space, query)
    assert [float(b["y"]["value"]) for b in rows] == expected, rows
