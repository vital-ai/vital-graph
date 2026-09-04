"""Every writer inserts terms in ONE order: ascending term_uuid.

`issues/152`. Locking the term primary key in quad order lets two concurrent
writers whose batches share terms take the same locks in opposite order, which
is a cycle: one transaction is aborted with SQLSTATE 40P01 and its whole batch
discarded. Nothing retries, so in the segmentation worker (`_MAX_CONCURRENT = 4`,
jobs claimed FOR UPDATE SKIP LOCKED) a transient abort is recorded as a
permanent job failure. It is `issues/115` again, in the paths that fix missed.

WHY THE ORDER MUST BE THE SAME ORDER EVERYWHERE, not merely deterministic
per path. Two writers only avoid deadlocking if they agree with EACH OTHER, and
they do not have to be the same kind of writer: a SPARQL UPDATE and a bulk load
can run concurrently and share predicates and graph URIs, which nearly all
batches do. A per-path convention would satisfy a per-path test and still
deadlock across paths, so this file checks the paths TOGETHER against one rule.

The concurrency reproduction lives in
`tests/integration/test_stats_lock_order.py`; it needs a database and catches
this only when the race lands. This is the deterministic half.
"""

from __future__ import annotations

import re
import uuid

from vitalgraph.db.jena_sparql.jena_types import QuadPattern, URINode
from vitalgraph.db.sparql_sql.emit_update import _insert_data_sql


def _term_uuids_in_emitted_order(sql: str) -> list:
    """The term_uuid of each term INSERT, in the order the SQL issues them."""
    return [uuid.UUID(m) for m in re.findall(
        r"INSERT INTO \w*_term \([^)]*\) VALUES \('([0-9a-f-]{36})'", sql)]


def _quads(preds):
    """One quad per predicate, all sharing a graph — the realistic overlap.

    Predicates and graph URIs repeat across nearly every batch, which is why two
    unrelated writers share terms in the first place.
    """
    return [QuadPattern(graph=URINode("urn:t:g"),
                        subject=URINode(f"urn:t:s{i}"),
                        predicate=URINode(p),
                        object=URINode(f"urn:t:o{i}"))
            for i, p in enumerate(preds)]


class TestInsertDataEmitsTermsInUuidOrder:

    def test_terms_are_sorted_by_uuid(self):
        preds = [f"urn:t:p{i}" for i in range(40)]
        sql = _insert_data_sql(_quads(preds), "sp")
        emitted = _term_uuids_in_emitted_order(sql)

        assert emitted, "no term inserts were emitted"
        assert emitted == sorted(emitted), (
            "term inserts are not in ascending term_uuid order, so this path "
            "can deadlock against any other writer (issues/152)")

    def test_reversing_the_input_does_not_change_the_lock_order(self):
        """The property that actually prevents the cycle.

        Two writers handling the same terms in opposite order are the exact
        scenario in the issue. If the emitted order tracks input order at all,
        they can still deadlock — so this compares the two orders directly
        rather than checking each is sorted.
        """
        preds = [f"urn:t:p{i}" for i in range(40)]
        forward = _term_uuids_in_emitted_order(_insert_data_sql(_quads(preds), "sp"))
        reverse = _term_uuids_in_emitted_order(
            _insert_data_sql(_quads(list(reversed(preds))), "sp"))

        assert forward == reverse, (
            "the same terms lock in a different order depending on input "
            "order, which is the deadlock")

    def test_terms_precede_the_quads_that_reference_them(self):
        """Hoisting is required, not tidy — a quad references its terms."""
        sql = _insert_data_sql(_quads(["urn:t:p0", "urn:t:p1"]), "sp")
        last_term = sql.rfind("INTO sp_term")
        first_quad = sql.find("INTO sp_rdf_quad")
        assert last_term < first_quad, (
            "a quad insert is emitted before a term insert it depends on")


class TestTheBatchPathSortsToo:
    """`_ensure_terms` must sort by the same key, by inspection of its source.

    Running it needs a live connection, so the agreement between the two paths
    is checked here structurally and exercised for real by the integration
    reproduction. A cheap check that names the requirement beats no check.
    """

    def test_ensure_terms_sorts_its_insert(self):
        import inspect
        from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl

        src = inspect.getsource(SparqlSQLSpaceImpl._ensure_terms)
        assert "sorted(rows)" in src, (
            "_ensure_terms no longer sorts its rows; `rows` is keyed by "
            "term_uuid, so sorted(rows) IS the shared lock order that keeps "
            "this path from deadlocking against the SPARQL UPDATE path")
