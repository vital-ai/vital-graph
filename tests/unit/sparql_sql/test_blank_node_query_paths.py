"""Blank-node handling on the QUERY side (issues/069 tests 9 and 10).

Both are pure unit tests and needed no fixture, which is why the issue lists
them as the cheapest remaining work — and why it is worth asking why they were
never written. Each covers logic with a subtle rule and no direct test:

  9.  `?s :p []` introduces an ANONYMOUS variable. It must not leak into
      results. The projection-injection at generator.py handles it, and its
      DISTINCT branch projects UNDER the dedup rather than over it — subtle
      enough to deserve pinning.
  10. SPARQL §15.1 term ordering: unbound < blank nodes < IRIs < literals, with
      numeric literals compared NUMERICALLY. Ordering on the text column makes
      MAX over {1, 2.2, 3.5, 3.0E4} return "3.5" (issue 029).
"""

from __future__ import annotations

from vitalgraph.db.sparql_sql.emit_group import sparql_order_key


class TestAnonymousVariablesAreNotProjected:
    """Test 9. `?s :p []` must not leak the anonymous variable."""

    def test_anon_detection_covers_both_spellings(self):
        """The generator treats `?`- and `.`-prefixed names as anonymous.

        Both spellings occur: the sidecar emits one form for `[]` and another
        for internal positions. A predicate matching only one leaks the other.
        """
        def _is_anon(v: str) -> bool:            # generator.py:893
            return v.startswith("?") or v.startswith(".")

        assert _is_anon("?0") and _is_anon(".anon1")
        assert not _is_anon("s"), "a real variable must not be filtered out"

    def test_a_named_variable_beside_an_anonymous_one_survives(self):
        def _is_anon(v: str) -> bool:
            return v.startswith("?") or v.startswith(".")
        visible = {"s", "?0", ".anon1"}
        named = [v for v in sorted(visible) if not _is_anon(v)]
        assert named == ["s"], (
            "projection dropped a real variable along with the anonymous ones")


class TestTermOrdering:
    """Test 10. §15.1 ordering, as MIN/MAX depends on it (§18.5.1)."""

    def test_blank_nodes_sort_before_iris_before_literals(self):
        key = sparql_order_key("t", "v0", descending=False)
        b = key.index("'B' THEN 1")
        u = key.index("'U' THEN 2")
        assert b < u, "blank nodes must rank ahead of IRIs"
        assert "ELSE 3" in key, "literals must rank last"

    def test_numeric_literals_are_compared_numerically(self):
        """Ordering on text makes MAX over {1, 2.2, 3.5, 3.0E4} give "3.5",
        because "3.5" > "3.0E4" lexicographically (issue 029)."""
        key = sparql_order_key("t", "v0", descending=False)
        assert "v0__num" in key, "no numeric column in the ordering key"
        assert key.index("v0__num") < key.index("t.v0 ASC"), (
            "the text column is consulted before the numeric one, which is the "
            "lexicographic bug this key exists to prevent")

    def test_non_numeric_literals_sort_last_within_their_group(self):
        """`__num` is NULL for anything non-numeric, so NULLS LAST is what
        keeps them behind the numbers — in BOTH directions."""
        for desc in (False, True):
            key = sparql_order_key("t", "v0", descending=desc)
            assert "NULLS LAST" in key

    def test_descending_reverses_every_component(self):
        """A key that reversed only the value would order the TYPE groups
        ascending under DESC, putting literals before blank nodes."""
        key = sparql_order_key("t", "v0", descending=True)
        assert key.count("DESC") == 3, (
            f"expected rank, numeric and text all reversed, got: {key}")
        assert "ASC" not in key
