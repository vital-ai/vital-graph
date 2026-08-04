"""Unit tests for the space graph filter — issue 021, site 4.

`FusekiSpaceImpl` enumerated a space's named graphs with an unanchored
`STRSTARTS(STR(?g), "http://vital.ai/graph/{space_id}")`. That prefix has no
boundary, so space `foo` also matched every graph of space `foobar` — and one
of the two callers feeds the result straight into a graph delete.

These are string-construction tests. The fuseki backend needs a running Fuseki
server and is not in the test stack, so the emitted filter is asserted directly
rather than executed; see the issue for what that does and does not cover.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.fuseki.fuseki_space_impl import space_graph_filter

BASE = "http://vital.ai/graph"


class TestSpaceGraphFilter:

    def test_matches_the_base_graph_exactly(self):
        f = space_graph_filter("foo")
        assert f"?g = <{BASE}/foo>" in f

    def test_matches_subgraphs_via_a_slash_boundary(self):
        """A space owns /entities, /connections, … so the prefix arm stays —
        but only with the separator that makes it a boundary."""
        f = space_graph_filter("foo")
        assert f'STRSTARTS(STR(?g), "{BASE}/foo/")' in f

    def test_does_not_match_a_longer_space_id(self):
        """The regression: space 'foo' must not match space 'foobar'.

        Asserted on the filter text because there is no Fuseki in the test
        stack — neither arm can match '<base>/foobar', since it is not equal to
        '<base>/foo' and does not start with '<base>/foo/'.
        """
        f = space_graph_filter("foo")
        assert f"{BASE}/foobar" not in f
        # the prefix arm always carries the trailing separator
        assert f'"{BASE}/foo"' not in f, (
            "unanchored prefix — this is the issue 021 bug: it matches foobar"
        )

    def test_both_arms_are_present(self):
        """Exact-match alone would drop subgraphs; prefix alone is the bug."""
        f = space_graph_filter("foo")
        assert f.startswith("FILTER(") and f.endswith(")")
        assert "||" in f

    @pytest.mark.parametrize("space_id", ["foo", "foo_bar", "a", "space-1"])
    def test_space_id_is_interpolated_into_both_arms(self, space_id):
        f = space_graph_filter(space_id)
        assert f"<{BASE}/{space_id}>" in f
        assert f'"{BASE}/{space_id}/"' in f

    def test_variable_is_configurable(self):
        f = space_graph_filter("foo", var="?graph")
        assert "?graph = <" in f
        assert "STR(?graph)" in f
        assert "?g " not in f


class TestCallSitesUseIt:
    """Guard against a future edit reintroducing the unanchored form."""

    def test_no_unanchored_space_graph_prefix_remains(self):
        import inspect
        from vitalgraph.db.fuseki import fuseki_space_impl

        src = inspect.getsource(fuseki_space_impl)
        # Actual call syntax only — "STRSTARTS" also appears in prose.
        calls = [line.strip() for line in src.splitlines()
                 if "STRSTARTS(STR(" in line]
        assert calls, "expected at least the helper's own STRSTARTS"

        # Every remaining prefix match must carry the trailing separator that
        # makes it a boundary. Without it, space 'foo' matches 'foobar'.
        offenders = [c for c in calls if '/"' not in c]
        assert not offenders, (
            f"unanchored space-graph prefix match reintroduced — this is the "
            f"issue 021 site-4 bug, and one caller deletes what it finds: "
            f"{offenders}"
        )
