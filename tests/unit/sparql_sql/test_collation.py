"""SPARQL string ordering is pinned to code point, not inherited from the cluster.

SPARQL 1.1 §15.1 orders simple literals by Unicode CODE POINT. PostgreSQL orders
`text` by the collation the cluster was created with. They agree only when that
is `C`. Demonstrated, same three values:

    ORDER BY v COLLATE "C"            ->  Banana < Zebra < apple    (codepoint)
    ORDER BY v COLLATE "en-US-x-icu"  ->  apple < Banana < Zebra    (locale)

Before this, `COLLATE` appeared 0 times in the emitter, so conformance was a
property of `initdb` rather than of this repository — the same code returning
different rows on two deployments, with no error anywhere. It reaches past
ordering: LIMIT over a sorted query returns DIFFERENT ROWS, and §18.5.1 defines
MIN/MAX by the ORDER BY ordering, so aggregates return a different term.

These tests assert the generated SQL. Comparing results across two real
collations would need a second database created with a locale collation, which
is heavier than the defect warrants; the emitter is where the property now lives,
so the emitter is what is checked.
"""

from __future__ import annotations

from vitalgraph.db.sparql_sql.collation import SPARQL_COLLATION, collate
from vitalgraph.db.sparql_sql.emit_group import sparql_order_key


class TestCollationHelper:

    def test_the_pinned_collation_is_C(self):
        assert SPARQL_COLLATION == '"C"', (
            "SPARQL orders by code point; only C (or C.UTF-8) does that")

    def test_collate_appends_the_clause(self):
        assert collate("t.v0") == 't.v0 COLLATE "C"'


class TestMinMaxOrdering:
    """§18.5.1 defines MIN/MAX BY the ORDER BY ordering, so this changes which
    TERM an aggregate returns, not merely row order."""

    def test_the_text_component_is_collated(self):
        key = sparql_order_key("t", "v0", descending=False)
        assert 't.v0 COLLATE "C"' in key

    def test_the_numeric_component_is_not_collated(self):
        """PostgreSQL raises on COLLATE over numeric — it is an error, not a
        no-op, so collating indiscriminately turns working queries into failing
        ones."""
        key = sparql_order_key("t", "v0", descending=False)
        assert 'v0__num COLLATE' not in key

    def test_the_rank_component_is_not_collated(self):
        key = sparql_order_key("t", "v0", descending=False)
        assert "END ASC" in key or "END DESC" in key
        assert "END COLLATE" not in key

    def test_a_typed_lane_column_is_not_collated(self):
        """A variable on the numeric or boolean lane has a NUMERIC sql_name.

        Caught by DAWG aggregates/COUNT 8b: collating unconditionally produced
        "collations are not supported by type numeric" and turned a passing
        conformance case into a hard error.
        """
        key = sparql_order_key("t", "v0", descending=False, collatable=False)
        assert "COLLATE" not in key

    def test_descending_still_reverses_every_component(self):
        """Guard: adding COLLATE must not disturb the DESC placement, which
        would order the type groups ascending and put literals before blank
        nodes."""
        key = sparql_order_key("t", "v0", descending=True)
        assert key.count("DESC") == 3 and "ASC" not in key


class TestEmitterHasNoUncollatedTextOrdering:

    def test_the_order_emitter_pins_a_collation(self):
        import inspect
        from vitalgraph.db.sparql_sql import emit_order
        src = inspect.getsource(emit_order)
        assert "collate(" in src, (
            "emit_order no longer pins a collation, so a user's ORDER BY ?v "
            "inherits the cluster's and stops being SPARQL-conformant")

    def test_the_comparison_emitter_pins_a_collation(self):
        import inspect
        from vitalgraph.db.sparql_sql import emit_expressions
        src = inspect.getsource(emit_expressions)
        assert "collate(" in src, (
            "string comparison no longer pins a collation, so FILTER(?a < ?b) "
            "admits different rows on a locale-collated cluster")
