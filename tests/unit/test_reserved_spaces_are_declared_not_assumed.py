"""A space with tables and no registry row is either debris or declared.

`scripts/cleanup_orphan_space_tables.py` drops an unregistered space once it
holds no quads. That is right for the residue it was written for — half-created
`inttest_*` spaces — and wrong for `dawg_test`, the conformance suite's own
space: created from the canonical DDL outside the space manager, then TRUNCATED
and reloaded per case, so between runs it holds zero quads and matches the drop
condition exactly. `--apply` would have taken it.

The alternative to declaring it was leaving it as a permanent false positive in
every reconciliation of tables against the registry. A check with a standing
false positive is one people learn to wave through, and then the real orphan gets
waved through too — which is how `perf_edgehop` sat there being called a
leftover, twice, until someone read the code.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from devtools.reserved_spaces import (UNREGISTERED_BY_DESIGN,
                                      is_unregistered_by_design, reason)

ROOT = Path(__file__).resolve().parents[2]
SWEEP = ROOT / "scripts" / "cleanup_orphan_space_tables.py"


class TestTheDeclarationIsUsable:

    def test_dawg_test_is_declared(self):
        assert is_unregistered_by_design("dawg_test")

    def test_an_ordinary_space_is_not(self):
        assert not is_unregistered_by_design("inttest_abc123")

    @pytest.mark.parametrize("space_id", sorted(UNREGISTERED_BY_DESIGN))
    def test_every_entry_says_why_and_what_recreates_it(self, space_id):
        """An unexplained entry is an exemption nobody can re-evaluate. Adding to
        this list is a claim that something creates the tables deliberately AND
        will recreate them."""
        why = reason(space_id)
        assert len(why) > 80, f"{space_id} needs a real justification, got {why!r}"


class TestTheSweepActuallyConsultsIt:
    """A declaration nothing reads is a comment. These assert the wiring, since
    the runtime path needs a database with the fixture present."""

    def test_the_sweep_imports_it(self):
        src = SWEEP.read_text()
        assert "reserved_spaces" in src, (
            "the sweep is the destructive path; if it does not read the "
            "declaration, the declaration protects nothing")

    def test_the_sweep_skips_before_the_quad_count(self):
        """The exemption has to come first. The drop decision is "no registry row
        AND zero quads", and a truncated fixture satisfies both."""
        src = SWEEP.read_text()
        skip = src.index("is_unregistered_by_design")
        count = src.index('SELECT count(*) FROM "{sid}_rdf_quad"')
        assert skip < count

    def test_the_sweep_reports_what_it_skipped(self):
        """Silently filtering would make the sweep unauditable — and the point of
        declaring an exemption is that it is visible where it is applied."""
        src = SWEEP.read_text()
        assert "RESERVED, not touched" in src


class TestTheTestSuiteUsesTheSameList:

    def test_protected_spaces_derives_from_the_declaration(self):
        from tests.integration.conftest import PROTECTED_SPACES
        assert set(UNREGISTERED_BY_DESIGN) <= set(PROTECTED_SPACES), (
            "listed in two places for two reasons, and only one got updated")

    def test_sp_kg_types_is_protected_but_not_exempt(self):
        """The two concepts are different: sp_kg_types IS registered and is
        protected from test teardown; dawg_test is protected AND unregistered.
        Collapsing them would exempt a real space from the orphan sweep."""
        from tests.integration.conftest import PROTECTED_SPACES
        assert "sp_kg_types" in PROTECTED_SPACES
        assert not is_unregistered_by_design("sp_kg_types")


class TestPerfEdgehopIsNoLongerOneOfThese:
    """It was the other unregistered group, and it was NOT deliberate — it came
    from calling SparqlSQLSchema.create_space directly, the call the integration
    conftest documents as the one never to make. Fixed by routing it through the
    space manager rather than by exempting it."""

    def test_it_is_not_exempted(self):
        assert not is_unregistered_by_design("perf_edgehop"), (
            "exempting it would have hidden the bug instead of fixing it")

    def test_it_creates_through_the_space_manager(self):
        src = (ROOT / "tests" / "performance" / "test_frame_nesting_hops.py").read_text()
        assert "create_space_with_tables" in src
        assert "SparqlSQLSchema.create_space(" not in src

    def test_it_tears_down_through_the_space_manager(self):
        """Dropping only the tables would leave a `space` row pointing at
        nothing — the mirror image of the residue this fixed."""
        src = (ROOT / "tests" / "performance" / "test_frame_nesting_hops.py").read_text()
        assert "delete_space_with_tables" in src
        assert "SparqlSQLSchema.drop_space(" not in src
