"""Unit tests for ColumnInfo's NULL-provenance vocabulary — issue 030.

SQL `NULL` encodes several unrelated conditions in the generated SQL, and every
consumer has had to re-infer which one it is looking at. Two of those
conditions are properties of the *variable*, knowable at emit time, and belong
on `ColumnInfo`:

- **has term identity** — the value came from a triple, so `__uuid` is a real
  term-table reference. Values synthesized by VALUES/BIND/aggregates carry a
  literal `NULL::uuid`. Reading that NULL as "unbound" is what made MINUS a
  silent no-op (issue 026).
- **text materialized** — whether the term JOIN was actually emitted. When the
  `text_needed_vars` optimisation defers it, the variable is bound and its
  `__uuid` is real, but the text column is NULL. That is *not* "unbound", and
  conflating the two is why `emit_distinct` reaches for `null_companions()`
  (which means unbound) and then patches the `__uuid` entry back.

These tests pin the vocabulary so the consumer migrations (issue 030 phase 2)
build on something asserted rather than assumed.
"""
# pyright: reportOperatorIssue=false, reportArgumentType=false

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.sql_type_generation import ColumnInfo


class TestHasTermIdentity:
    """True only when the value can be compared by term UUID."""

    def test_bgp_variable_has_identity(self):
        info = ColumnInfo.simple_output("s", "v0", from_triple=True)
        assert info.has_term_identity() is True

    def test_synthesized_value_has_no_identity(self):
        """VALUES / BIND / aggregate outputs — from_triple defaults False."""
        info = ColumnInfo.simple_output("s", "v0")
        assert info.has_term_identity() is False

    def test_no_uuid_column_means_no_identity(self):
        """Aggregates without companion columns."""
        info = ColumnInfo(sparql_name="c", sql_name="v0", from_triple=True,
                          uuid_col=None)
        assert info.has_term_identity() is False

    def test_is_not_the_same_question_as_text_materialized(self):
        """A deferred term JOIN does not remove term identity — the __uuid is
        still real. Collapsing the two is the issue-030 conflation."""
        info = ColumnInfo.simple_output("s", "v0", from_triple=True,
                                        text_materialized=False)
        assert info.has_term_identity() is True
        assert info.text_materialized is False


class TestTextMaterialized:

    def test_defaults_to_true(self):
        """Producers that always emit a text value need not opt in."""
        assert ColumnInfo.simple_output("s", "v0").text_materialized is True

    def test_can_be_declared_false(self):
        info = ColumnInfo.simple_output("s", "v0", text_materialized=False)
        assert info.text_materialized is False


class TestBgpPopulatesTheVocabulary:
    """The producer must stamp what it actually did — otherwise phase 2 builds
    on an assumption."""

    def _register(self, text_needed):
        """Run emit_bgp's registration path for one variable."""
        from vitalgraph.db.sparql_sql.ir import PlanV2, KIND_BGP, VarSlot, TableRef
        from .emit_helpers import _make_ctx
        from vitalgraph.db.sparql_sql.emit_bgp import emit_bgp

        ctx = _make_ctx({})
        ctx.text_needed_vars = text_needed
        plan = PlanV2(kind=KIND_BGP)
        plan.tables.append(TableRef(ref_id="q0", kind="quad",
                                    table_name="sp_rdf_quad", alias="q0"))
        plan.tables.append(TableRef(ref_id="t0", kind="term",
                                    table_name="sp_term", alias="t0"))
        plan.var_slots["s"] = VarSlot(name="s", term_ref_id="t0")
        plan.var_slots["s"].uuid_cols = ["q0.subject_uuid"]
        emit_bgp(plan, ctx)
        return ctx.types.get("s")

    def test_text_needed_marks_materialized(self):
        info = self._register(text_needed={"s"})
        assert info is not None
        assert info.text_materialized is True

    def test_deferred_term_join_marks_unmaterialized(self):
        """The variable is still bound and still has term identity — only the
        text column is absent."""
        info = self._register(text_needed=set())
        assert info is not None
        assert info.text_materialized is False
        assert info.has_term_identity() is True

    def test_none_means_resolve_all(self):
        """text_needed_vars=None is the safe fallback: resolve everything."""
        info = self._register(text_needed=None)
        assert info is not None
        assert info.text_materialized is True


class TestDeferredTextCompanions:
    """The primitive that `emit_distinct` used to hand-roll.

    `null_companions` means *unbound* and NULLs the UUID too; a variable whose
    term JOIN was deferred is bound and must keep it. Using the wrong one and
    patching the UUID back afterwards was the workaround this replaces.
    """

    def _cols(self):
        from vitalgraph.db.sparql_sql.sql_type_generation import TypeRegistry
        return TypeRegistry.deferred_text_companions("v0", "r0")

    def test_uuid_passes_through(self):
        assert "r0.v0__uuid AS v0__uuid" in self._cols()

    def test_text_and_text_derived_companions_are_null(self):
        cols = self._cols()
        assert "NULL AS v0" in cols
        assert "NULL AS v0__type" in cols
        assert "NULL AS v0__lang" in cols
        assert "NULL AS v0__datatype" in cols

    def test_typed_lanes_keep_their_casts(self):
        """Postgres needs the type on a NULL in a UNION/DISTINCT position."""
        cols = self._cols()
        assert "NULL::numeric AS v0__num" in cols
        assert "NULL::boolean AS v0__bool" in cols
        assert "NULL::timestamp AS v0__dt" in cols

    def test_matches_null_companions_except_for_the_uuid(self):
        """Pins the equivalence the replaced workaround relied on: identical
        output except the UUID, in identical order."""
        from vitalgraph.db.sparql_sql.sql_type_generation import TypeRegistry
        deferred = self._cols()
        unbound = TypeRegistry.null_companions("v0")
        assert len(deferred) == len(unbound)
        for d, u in zip(deferred, unbound):
            if d.endswith("AS v0__uuid"):
                assert u == "NULL::uuid AS v0__uuid"
                assert d == "r0.v0__uuid AS v0__uuid"
            else:
                assert d == u

    def test_unbound_still_nulls_the_uuid(self):
        """Guard the distinction from the other direction."""
        from vitalgraph.db.sparql_sql.sql_type_generation import TypeRegistry
        assert "NULL::uuid AS v0__uuid" in TypeRegistry.null_companions("v0")


class TestValuesProducesNoTermIdentity:
    """emit_table (VALUES) is the producer that caused issue 026."""

    def test_values_var_has_no_term_identity(self):
        from vitalgraph.db.sparql_sql.ir import PlanV2, KIND_TABLE
        from vitalgraph.db.jena_sparql.jena_types import URINode
        from .emit_helpers import _make_ctx
        from vitalgraph.db.sparql_sql.emit_table import emit_table

        ctx = _make_ctx({})
        plan = PlanV2(kind=KIND_TABLE, values_vars=["s"],
                      values_rows=[{"s": URINode(value="urn:x")}])
        emit_table(plan, ctx)
        info = ctx.types.get("s")
        assert info is not None
        assert info.has_term_identity() is False, (
            "a VALUES row has NULL::uuid — treating it as term identity is "
            "what made MINUS a no-op (issue 026)"
        )
