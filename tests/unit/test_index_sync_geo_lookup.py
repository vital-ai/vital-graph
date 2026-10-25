"""The index-sync geo-slot lookup stays fast under a generic cached plan (`issues/309`).

asyncpg prepares the lookup once per connection, and PostgreSQL may switch a
prepared statement to a GENERIC plan after five runs. With its six type URIs
passed as parameters, that plan priced each type lookup by default selectivity,
nested loops through every slot edge of the largest production space, and ran
26,954 calls at a mean 4.4 s (926 more cancelled at 60 s) for 0 rows every time.
The same batch custom-planned took 3.3 ms.

Pinned here: the types are literals, only the graph and the subjects are
parameters, and an uncorrelated geo-slot guard lets a graph without geo slots
skip the statement whatever plan it gets.
"""

import re

from vitalgraph.vectorization import index_sync_worker as W


def _sql():
    return W._geo_slots_of_edges_sql("vgs_test_rdf_quad")


def test_only_the_graph_and_the_subjects_are_parameters():
    assert sorted(set(re.findall(r"\$\d+", _sql()))) == ["$1", "$2"]


def test_every_type_is_a_literal_uuid():
    sql = _sql()
    for uri in (W._VITALTYPE, W._SLOT_EDGE, W._FRAME_EDGE, W._EDGE_SRC,
                W._EDGE_DST, W._GEO_SLOT):
        assert f"'{W._uuid(uri)}'::uuid" in sql, uri


def test_a_graph_without_geo_slots_is_guarded_once():
    """An uncorrelated EXISTS on the geo-slot type, at the top level: one
    InitPlan, evaluated before anything else."""
    sql = " ".join(_sql().split())
    tail = sql[sql.rindex("SELECT DISTINCT s.slot"):]
    assert "WHERE EXISTS (SELECT 1 FROM vgs_test_rdf_quad x WHERE x.context_uuid = $1" in tail
    assert f"x.object_uuid = '{W._uuid(W._GEO_SLOT)}'::uuid" in tail


def test_the_sql_is_built_once_per_table():
    assert W._geo_slots_of_edges_sql("vgs_test_rdf_quad") is _sql()
