"""Integration tests: frame/slot sequence ordering, end to end.

Resolves the step-0 spike in
``planning/planning_sequence/frame_slot_sequence_sort_paging_plan.md``:

1. Does the sparql_sql backend support COALESCE in ORDER BY (needed for
   missing-sequence-sorts-last, matching the frontend's Infinity fallback),
   or is a BIND workaround required?
2. Do xsd:integer sequence literals sort numerically end-to-end, or
   lexically ("10" < "9")?
3. Can a per-frame nested slot window be expressed in one query, or is the
   bounded-UNION + follow-up-call fallback required?

Fixtures deliberately span 1..12 so a lexical sort is distinguishable from a
numeric one, include unbound sequences, and include duplicate sequence values
to exercise the URI tiebreaker.

Requires PostgreSQL + Jena sidecar.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

EX = "http://example.org/seq"

# Sentinel pushing unbound sequences to the end of an ascending sort,
# mirroring frontend/src/lib/entityGraphBuilder.ts:211.
SEQ_SENTINEL = 2147483647

# Known defect, tracked in the plan: emit_order resolves a variable sort key
# to ``info.sql_name`` — the LEXICAL column — never to ``num_col``
# (emit_order.py:30-32).  So xsd:integer sequences compare as strings and
# 1,2,...,12 comes back as 1,10,11,12,2,...,9.  COALESCE does not rescue it
# either: mixing a text-lane variable with a numeric literal casts every
# argument to TEXT (emit_expressions.py:694-702).
#
# This is a standing backend limitation, NOT scheduled for a fix: changing it
# would mean touching the shared ORDER BY path, which affects every SPARQL
# query that sorts.  It is worked around entirely at the query layer instead —
# see TestSequenceOrderingConstruct for the construct we actually ship.
#
# strict=True so that if the backend ever does gain numeric sort keys, these
# fail loudly and the workaround can be retired.
xfail_lexical_order = pytest.mark.xfail(
    strict=True,
    reason="bare variable sort keys compare lexically; use the xsd:integer "
           "BIND construct instead — see "
           "planning/planning_sequence/frame_slot_sequence_sort_paging_plan.md",
)

PREFIXES = f"""
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX ex: <{EX}#>
"""


def _values(bindings, var):
    return [b[var]["value"] for b in bindings if var in b]


def _local(uri: str) -> str:
    return uri.rsplit("#", 1)[-1]


# ---------------------------------------------------------------------------
# Unknown 2: numeric vs lexical ordering of integer sequences
# ---------------------------------------------------------------------------

class TestIntegerSequenceOrdering:
    """xsd:integer sequences must sort numerically, not lexically.

    A lexical sort is silently correct for 0-9 and wrong from 10 up, so the
    fixture spans 1..12.  If these fail, every sequence-ordered page in the
    plan is wrong for frames/slots numbering into double digits.
    """

    @pytest_asyncio.fixture(autouse=True, loop_scope="session")
    async def seed(self, test_space, sparql_update):
        triples = "\n".join(
            f"    ex:numFrame{i} ex:numSeq \"{i}\"^^xsd:integer ."
            for i in range(1, 13)
        )
        await sparql_update(f"{PREFIXES}\nINSERT DATA {{\n{triples}\n}}", test_space)

    @xfail_lexical_order
    async def test_ascending_is_numeric_not_lexical(
        self, test_space, sparql_execute
    ):
        """ORDER BY ?seq over 1..12 yields 1,2,...,12 — not 1,10,11,12,2,...."""
        bindings = await sparql_execute(f"""
        {PREFIXES}
        SELECT ?frame ?seq WHERE {{
            ?frame ex:numSeq ?seq .
        }} ORDER BY ?seq
        """, test_space)

        seqs = [int(v) for v in _values(bindings, "seq")]
        assert seqs == list(range(1, 13)), (
            "integer sequences sorted lexically, not numerically — "
            f"got {seqs}"
        )

    @xfail_lexical_order
    async def test_descending_is_numeric_not_lexical(
        self, test_space, sparql_execute
    ):
        """ORDER BY DESC(?seq) yields 12,11,...,1."""
        bindings = await sparql_execute(f"""
        {PREFIXES}
        SELECT ?frame ?seq WHERE {{
            ?frame ex:numSeq ?seq .
        }} ORDER BY DESC(?seq)
        """, test_space)

        seqs = [int(v) for v in _values(bindings, "seq")]
        assert seqs == list(range(12, 0, -1))

    async def _page_all(self, sparql_execute, test_space, page_size=5):
        seen = []
        for offset in range(0, 15, page_size):
            bindings = await sparql_execute(f"""
            {PREFIXES}
            SELECT ?frame ?seq WHERE {{
                ?frame ex:numSeq ?seq .
            }} ORDER BY ?seq ?frame LIMIT {page_size} OFFSET {offset}
            """, test_space)
            seen.extend(_values(bindings, "frame"))
        return seen

    async def test_paging_partitions_the_sequence(
        self, test_space, sparql_execute
    ):
        """Iterating all pages at page_size=5 yields each frame exactly once.

        The partition property the plan's paging contract depends on.  Holds
        regardless of whether the sort key compares numerically, because the
        ORDER BY carries a URI tiebreaker and is therefore a total order.
        """
        seen = await self._page_all(sparql_execute, test_space)

        assert len(seen) == 12
        assert len(set(seen)) == 12, "paging returned duplicates"

    @xfail_lexical_order
    async def test_paging_yields_sequence_order_across_pages(
        self, test_space, sparql_execute
    ):
        """Concatenating all pages is monotonic in the integer sequence."""
        seen = await self._page_all(sparql_execute, test_space)

        assert seen == sorted(
            seen, key=lambda u: int(_local(u)[len("numFrame"):]))


# ---------------------------------------------------------------------------
# Unknown 1: COALESCE in ORDER BY for missing-sequence-last
# ---------------------------------------------------------------------------

class TestCoalesceInOrderBy:
    """Missing sequence values must sort last in ascending order.

    Sequence is optional on both KGFrame and KGSlot, so the sort key is an
    OPTIONAL and is frequently unbound.  ``ORDER BY ?seq ?subject`` handles
    that in one construct: sequenced subjects sort by sequence, unsequenced
    ones fall to the end and order among themselves by subject URI.  No
    sentinel and no mode switch — see test_unsequenced_fall_back_to_subject.

    The COALESCE sentinel tests below are retained to document why the
    obvious alternative is worse.
    """

    @pytest_asyncio.fixture(autouse=True, loop_scope="session")
    async def seed(self, test_space, sparql_update):
        # Sequenced 1..3, plus two frames with no sequence at all.
        triples = "\n".join(
            f"    ex:optFrame{i} ex:optSeq \"{i}\"^^xsd:integer ."
            for i in range(1, 4)
        )
        names = "\n".join(
            f"    ex:optFrame{i} ex:optName \"frame{i}\" ."
            for i in range(1, 6)
        )
        await sparql_update(
            f"{PREFIXES}\nINSERT DATA {{\n{triples}\n{names}\n}}", test_space)

    async def test_unbound_optional_already_sorts_last_ascending(
        self, test_space, sparql_execute
    ):
        """A bare OPTIONAL sort key ALREADY puts unbound values last on ASC.

        Unbound sort keys reach SQL as NULL, and PostgreSQL's default for
        ASC is NULLS LAST — which is exactly the missing-sequence-last
        behavior the frontend's Infinity fallback emulates.  So on ascending
        sorts no sentinel is needed at all.
        """
        bindings = await sparql_execute(f"""
        {PREFIXES}
        SELECT ?frame ?seq WHERE {{
            ?frame ex:optName ?name .
            OPTIONAL {{ ?frame ex:optSeq ?seq . }}
        }} ORDER BY ?seq ?frame
        """, test_space)

        assert len(bindings) == 5
        assert len(_values(bindings, "seq")) == 3
        assert all("seq" not in b for b in bindings[3:]), (
            "expected unsequenced frames last; got "
            f"{[b.get('seq', {}).get('value') for b in bindings]}"
        )

    async def test_unsequenced_fall_back_to_subject(
        self, test_space, sparql_execute
    ):
        """Unsequenced subjects order among themselves by subject URI.

        The whole ordering contract in one query: ORDER BY ?seq ?subject
        gives sequence order for the sequenced subjects, then subject order
        for the rest.  Total order, so it is safe to page.
        """
        bindings = await sparql_execute(f"""
        {PREFIXES}
        SELECT ?frame ?seq WHERE {{
            ?frame ex:optName ?name .
            OPTIONAL {{ ?frame ex:optSeq ?seq . }}
        }} ORDER BY ?seq ?frame
        """, test_space)

        frames = [_local(v) for v in _values(bindings, "frame")]
        assert frames[:3] == ["optFrame1", "optFrame2", "optFrame3"]
        # the unsequenced tail is in subject order, not arbitrary order
        tail = frames[3:]
        assert tail == ["optFrame4", "optFrame5"], tail
        assert tail == sorted(tail)

    async def test_unsequenced_subject_fallback_is_stable(
        self, test_space, sparql_execute
    ):
        """Repeating the mixed-sequence query gives identical order.

        Without the subject tiebreaker the unsequenced tail would be free to
        permute between calls, which is what breaks offset paging.
        """
        query = f"""
        {PREFIXES}
        SELECT ?frame ?seq WHERE {{
            ?frame ex:optName ?name .
            OPTIONAL {{ ?frame ex:optSeq ?seq . }}
        }} ORDER BY ?seq ?frame
        """
        first = _values(await sparql_execute(query, test_space), "frame")
        second = _values(await sparql_execute(query, test_space), "frame")
        assert first == second

    async def test_mixed_sequence_paging_partitions(
        self, test_space, sparql_execute
    ):
        """Paging across the sequenced/unsequenced boundary loses nothing.

        page_size=2 puts the boundary mid-page, the case most likely to drop
        or repeat a row.
        """
        seen = []
        for offset in range(0, 6, 2):
            bindings = await sparql_execute(f"""
            {PREFIXES}
            SELECT ?frame ?seq WHERE {{
                ?frame ex:optName ?name .
                OPTIONAL {{ ?frame ex:optSeq ?seq . }}
            }} ORDER BY ?seq ?frame LIMIT 2 OFFSET {offset}
            """, test_space)
            seen.extend(_values(bindings, "frame"))

        assert len(seen) == 5
        assert len(set(seen)) == 5, f"paging duplicated rows: {seen}"

    async def test_current_descending_puts_unsequenced_first(
        self, test_space, sparql_execute
    ):
        """CURRENT behavior: DESC leads with the unsequenced frames.

        PostgreSQL defaults to NULLS FIRST on DESC.  Pinned so the change in
        test_unsequenced_sort_last_descending is visible as a deliberate
        behavior change rather than an accident.  Delete this test when that
        one goes green.
        """
        bindings = await sparql_execute(f"""
        {PREFIXES}
        SELECT ?frame ?seq WHERE {{
            ?frame ex:optName ?name .
            OPTIONAL {{ ?frame ex:optSeq ?seq . }}
        }} ORDER BY DESC(?seq) ?frame
        """, test_space)

        assert len(bindings) == 5
        assert all("seq" not in b for b in bindings[:2]), (
            "expected unsequenced frames first on DESC; got "
            f"{[b.get('seq', {}).get('value') for b in bindings]}"
        )

    async def test_missing_flag_puts_unsequenced_last_descending(
        self, test_space, sparql_execute
    ):
        """A BOUND() flag as the primary sort key fixes the DESC asymmetry.

        PostgreSQL's NULLS FIRST default only applies to the sequence column
        itself.  Sorting on IF(BOUND(?seq), 0, 1) FIRST puts every sequenced
        subject ahead of every unsequenced one regardless of the direction
        applied to the sequence — no NULLS LAST needed, and nothing to change
        in the emitter.

        The flag is 0/1, so it sorts correctly even lexically.
        """
        bindings = await sparql_execute(f"""
        {PREFIXES}
        SELECT ?frame ?seq WHERE {{
            ?frame ex:optName ?name .
            OPTIONAL {{ ?frame ex:optSeq ?seq . }}
            BIND(IF(BOUND(?seq), 0, 1) AS ?missing)
        }} ORDER BY ?missing DESC(?seq) ?frame
        """, test_space)

        assert len(bindings) == 5
        assert [int(v) for v in _values(bindings, "seq")] == [3, 2, 1]
        assert all("seq" not in b for b in bindings[3:]), (
            "expected unsequenced frames last on DESC; got "
            f"{[b.get('seq', {}).get('value') for b in bindings]}"
        )

    async def test_coalesce_in_order_by_is_accepted(
        self, test_space, sparql_execute
    ):
        """ORDER BY COALESCE(?seq, sentinel) compiles and runs.

        Answers unknown 1 directly: if this raises, the plan must use the
        BIND workaround.
        """
        bindings = await sparql_execute(f"""
        {PREFIXES}
        SELECT ?frame ?seq WHERE {{
            ?frame ex:optName ?name .
            OPTIONAL {{ ?frame ex:optSeq ?seq . }}
        }} ORDER BY COALESCE(?seq, {SEQ_SENTINEL}) ?frame
        """, test_space)

        assert len(bindings) == 5

    @xfail_lexical_order
    async def test_coalesce_in_order_by_sorts_missing_last(
        self, test_space, sparql_execute
    ):
        """The sentinel pushes unsequenced frames to the end.

        Currently fails even at single digits: the TEXT cast makes
        "2147483647" sort between "2" and "3", so the sentinel lands in the
        MIDDLE of the result.  A sentinel is strictly worse than the plain
        NULLS-LAST behavior above until numeric ordering is fixed.
        """
        bindings = await sparql_execute(f"""
        {PREFIXES}
        SELECT ?frame ?seq WHERE {{
            ?frame ex:optName ?name .
            OPTIONAL {{ ?frame ex:optSeq ?seq . }}
        }} ORDER BY COALESCE(?seq, {SEQ_SENTINEL}) ?frame
        """, test_space)

        assert len(bindings) == 5
        last_two = bindings[3:]
        assert all("seq" not in b for b in last_two), (
            "expected unsequenced frames last; got "
            f"{[b.get('seq', {}).get('value') for b in bindings]}"
        )
        assert [int(v) for v in _values(bindings, "seq")] == [1, 2, 3]

    @xfail_lexical_order
    async def test_bind_workaround_sorts_missing_last(
        self, test_space, sparql_execute
    ):
        """BIND(COALESCE(...) AS ?sortkey) + ORDER BY ?sortkey.

        The fallback construct for backends that can't take an expression in
        ORDER BY.  It is NOT needed here (COALESCE in ORDER BY compiles
        fine — see the test above) and it does not help: the BIND result is
        still compared lexically, so the sentinel lands mid-result exactly
        as it does inline.
        """
        bindings = await sparql_execute(f"""
        {PREFIXES}
        SELECT ?frame ?seq ?sortkey WHERE {{
            ?frame ex:optName ?name .
            OPTIONAL {{ ?frame ex:optSeq ?seq . }}
            BIND(COALESCE(?seq, {SEQ_SENTINEL}) AS ?sortkey)
        }} ORDER BY ?sortkey ?frame
        """, test_space)

        assert len(bindings) == 5
        last_two = bindings[3:]
        assert all("seq" not in b for b in last_two), (
            "BIND workaround did not sort unsequenced frames last; got "
            f"{[b.get('seq', {}).get('value') for b in bindings]}"
        )


class TestSentinelOrderingIsNumeric:
    """The sentinel construct must stay numeric across the 1..12 boundary.

    This is where the COALESCE text-cast (emit_expressions.py:694-702) would
    bite: under a lexical comparison "10" sorts before "2".
    """

    @pytest_asyncio.fixture(autouse=True, loop_scope="session")
    async def seed(self, test_space, sparql_update):
        triples = "\n".join(
            f"    ex:mixFrame{i:02d} ex:mixSeq \"{i}\"^^xsd:integer ."
            for i in range(1, 13)
        )
        names = "\n".join(
            f"    ex:mixFrame{i:02d} ex:mixName \"frame{i}\" ."
            for i in range(1, 15)
        )
        await sparql_update(
            f"{PREFIXES}\nINSERT DATA {{\n{triples}\n{names}\n}}", test_space)

    @xfail_lexical_order
    async def test_coalesce_sentinel_orders_1_to_12_numerically(
        self, test_space, sparql_execute
    ):
        """ORDER BY COALESCE(?seq, sentinel) over 1..12 plus two unbound."""
        bindings = await sparql_execute(f"""
        {PREFIXES}
        SELECT ?frame ?seq WHERE {{
            ?frame ex:mixName ?name .
            OPTIONAL {{ ?frame ex:mixSeq ?seq . }}
        }} ORDER BY COALESCE(?seq, {SEQ_SENTINEL}) ?frame
        """, test_space)

        assert len(bindings) == 14
        seqs = [int(v) for v in _values(bindings, "seq")]
        assert seqs == list(range(1, 13)), (
            "sentinel ordering is lexical, not numeric — got "
            f"{seqs}"
        )
        assert all("seq" not in b for b in bindings[12:])


# ---------------------------------------------------------------------------
# Tiebreaker: duplicate sequence values
# ---------------------------------------------------------------------------

class TestSequenceTiebreaker:
    """Duplicate sequence values need the URI tiebreaker for stable paging."""

    @pytest_asyncio.fixture(autouse=True, loop_scope="session")
    async def seed(self, test_space, sparql_update):
        # Four frames, two distinct sequence values — every value duplicated.
        triples = "\n".join(
            f"    ex:dupFrame{i} ex:dupSeq \"{i % 2}\"^^xsd:integer ."
            for i in range(4)
        )
        await sparql_update(f"{PREFIXES}\nINSERT DATA {{\n{triples}\n}}", test_space)

    async def test_repeated_query_is_stable(self, test_space, sparql_execute):
        """Same request twice → identical ordering, with the tiebreaker."""
        query = f"""
        {PREFIXES}
        SELECT ?frame ?seq WHERE {{
            ?frame ex:dupSeq ?seq .
        }} ORDER BY ?seq ?frame
        """
        first = _values(await sparql_execute(query, test_space), "frame")
        second = _values(await sparql_execute(query, test_space), "frame")
        assert first == second
        assert len(first) == 4

    async def test_paging_over_duplicates_partitions(
        self, test_space, sparql_execute
    ):
        """page_size=1 over duplicate sequences still yields each URI once."""
        seen = []
        for offset in range(5):
            bindings = await sparql_execute(f"""
            {PREFIXES}
            SELECT ?frame ?seq WHERE {{
                ?frame ex:dupSeq ?seq .
            }} ORDER BY ?seq ?frame LIMIT 1 OFFSET {offset}
            """, test_space)
            seen.extend(_values(bindings, "frame"))

        assert len(seen) == 4
        assert len(set(seen)) == 4, f"duplicate rows across pages: {seen}"


# ---------------------------------------------------------------------------
# The canonical ordering construct — this is what the endpoints emit
# ---------------------------------------------------------------------------

class TestSequenceOrderingConstruct:
    """The full ordering contract, expressed entirely in SPARQL.

        OPTIONAL { ?x <seq_prop> ?seq }
        BIND(IF(BOUND(?seq), 0, 1) AS ?missing)
        BIND(xsd:integer(?seq)     AS ?seq_num)
        ORDER BY ?missing <DIR>(?seq_num) ?anchor

    Three keys, three jobs:
      ?missing  — unsequenced subjects last, in BOTH directions
      ?seq_num  — numeric (not lexical) comparison of the sequence
      ?anchor   — total order, so offset paging is stable

    Nothing here requires a change to the shared ORDER BY emitter: the
    xsd:integer BIND lands the sort key in the numeric lane, and the
    0/1 flag sidesteps NULL placement entirely.
    """

    SEQUENCED = 12
    UNSEQUENCED = 2

    @pytest_asyncio.fixture(autouse=True, loop_scope="session")
    async def seed(self, test_space, sparql_update):
        # 1..12 sequenced (spans the lexical trap), plus 2 unsequenced.
        triples = "\n".join(
            f"    ex:conFrame{i:02d} ex:conSeq \"{i}\"^^xsd:integer ."
            for i in range(1, self.SEQUENCED + 1)
        )
        names = "\n".join(
            f"    ex:conFrame{i:02d} ex:conName \"frame{i}\" ."
            for i in range(1, self.SEQUENCED + self.UNSEQUENCED + 1)
        )
        await sparql_update(
            f"{PREFIXES}\nINSERT DATA {{\n{triples}\n{names}\n}}", test_space)

    def _query(self, direction: str, limit: str = "") -> str:
        order = "?seq_num" if direction == "ASC" else "DESC(?seq_num)"
        return f"""
        {PREFIXES}
        SELECT ?frame ?seq WHERE {{
            ?frame ex:conName ?name .
            OPTIONAL {{ ?frame ex:conSeq ?seq . }}
            BIND(IF(BOUND(?seq), 0, 1) AS ?missing)
            BIND(xsd:integer(?seq) AS ?seq_num)
        }} ORDER BY ?missing {order} ?frame {limit}
        """

    async def test_ascending_numeric_with_unsequenced_last(
        self, test_space, sparql_execute
    ):
        """1..12 in numeric order, then the unsequenced tail."""
        bindings = await sparql_execute(self._query("ASC"), test_space)

        assert len(bindings) == self.SEQUENCED + self.UNSEQUENCED
        assert [int(v) for v in _values(bindings, "seq")] == list(range(1, 13))
        assert all("seq" not in b for b in bindings[self.SEQUENCED:])

    async def test_descending_numeric_with_unsequenced_last(
        self, test_space, sparql_execute
    ):
        """12..1 in numeric order, unsequenced STILL last."""
        bindings = await sparql_execute(self._query("DESC"), test_space)

        assert len(bindings) == self.SEQUENCED + self.UNSEQUENCED
        assert [int(v) for v in _values(bindings, "seq")] == list(range(12, 0, -1))
        assert all("seq" not in b for b in bindings[self.SEQUENCED:]), (
            "unsequenced frames must be last on DESC too; got "
            f"{[b.get('seq', {}).get('value') for b in bindings]}"
        )

    async def test_unsequenced_tail_orders_by_subject(
        self, test_space, sparql_execute
    ):
        """Within the unsequenced tail, subject URI decides — deterministically."""
        bindings = await sparql_execute(self._query("ASC"), test_space)

        tail = [_local(b["frame"]["value"]) for b in bindings[self.SEQUENCED:]]
        assert tail == sorted(tail), tail

    async def test_paging_preserves_order_and_partitions(
        self, test_space, sparql_execute
    ):
        """Every page concatenated == the unpaged result, exactly once each.

        The property the whole paging design rests on, at the page size most
        likely to break it (boundary falling inside the sequenced run and
        again across the sequenced/unsequenced split).
        """
        total = self.SEQUENCED + self.UNSEQUENCED
        unpaged = _values(
            await sparql_execute(self._query("ASC"), test_space), "frame")

        for page_size in (1, 5):
            seen = []
            for offset in range(0, total + page_size, page_size):
                page = await sparql_execute(
                    self._query("ASC", f"LIMIT {page_size} OFFSET {offset}"),
                    test_space)
                seen.extend(_values(page, "frame"))
            assert seen == unpaged, f"page_size={page_size} changed the order"
            assert len(set(seen)) == total, f"page_size={page_size} duplicated"

    async def test_construct_is_stable_across_calls(
        self, test_space, sparql_execute
    ):
        """Same query twice, same order — no reliance on scan order."""
        q = self._query("ASC")
        first = _values(await sparql_execute(q, test_space), "frame")
        second = _values(await sparql_execute(q, test_space), "frame")
        assert first == second


class TestZeroSequenceValue:
    """Sequence 0 is a real value, not a missing one.

    Singleton frames/slots are commonly written with sequence 0, so 0 must
    sort at the FRONT of the sequenced group — never fall into the
    unsequenced tail.  The construct uses IF(BOUND(?seq), ...), which is
    correct here; a falsy check (IF(?seq, ...)) or a COALESCE-with-0 sentinel
    would both silently misplace it.
    """

    @pytest_asyncio.fixture(autouse=True, loop_scope="session")
    async def seed(self, test_space, sparql_update):
        # Sequences 0,1,2 — plus one frame with no sequence at all.
        triples = "\n".join(
            f"    ex:zeroFrame{i} ex:zeroSeq \"{i}\"^^xsd:integer ."
            for i in range(3)
        )
        names = "\n".join(
            f"    ex:zeroFrame{i} ex:zeroName \"frame{i}\" ."
            for i in range(4)
        )
        await sparql_update(
            f"{PREFIXES}\nINSERT DATA {{\n{triples}\n{names}\n}}", test_space)

    def _query(self, direction: str) -> str:
        order = "?seq_num" if direction == "ASC" else "DESC(?seq_num)"
        return f"""
        {PREFIXES}
        SELECT ?frame ?seq WHERE {{
            ?frame ex:zeroName ?name .
            OPTIONAL {{ ?frame ex:zeroSeq ?seq . }}
            BIND(IF(BOUND(?seq), 0, 1) AS ?missing)
            BIND(xsd:integer(?seq) AS ?seq_num)
        }} ORDER BY ?missing {order} ?frame
        """

    async def test_zero_sorts_first_not_last_ascending(
        self, test_space, sparql_execute
    ):
        """0,1,2 then the unsequenced frame — 0 leads, it is not treated as unset."""
        bindings = await sparql_execute(self._query("ASC"), test_space)

        assert len(bindings) == 4
        assert [int(v) for v in _values(bindings, "seq")] == [0, 1, 2]
        assert "seq" not in bindings[3], (
            "sequence 0 must not be confused with a missing sequence; got "
            f"{[b.get('seq', {}).get('value') for b in bindings]}"
        )

    async def test_zero_still_precedes_unsequenced_descending(
        self, test_space, sparql_execute
    ):
        """On DESC, 0 sorts last among the sequenced but still ahead of unset."""
        bindings = await sparql_execute(self._query("DESC"), test_space)

        assert [int(v) for v in _values(bindings, "seq")] == [2, 1, 0]
        assert "seq" not in bindings[3], (
            "unsequenced frame must trail sequence 0 even on DESC; got "
            f"{[b.get('seq', {}).get('value') for b in bindings]}"
        )


# ---------------------------------------------------------------------------
# Unknown 3: per-frame nested slot windows
# ---------------------------------------------------------------------------

class TestNestedSlotWindows:
    """Can one query return the first N slots *per frame*?

    SPARQL sub-SELECTs are evaluated bottom-up and are NOT correlated with
    the enclosing group, so a LIMIT inside a sub-SELECT is a GLOBAL limit,
    not a per-frame one.  These tests pin that semantics: if the per-frame
    window is not expressible, the plan's nested slot paging must use the
    bounded-UNION + follow-up-call fallback instead.
    """

    FRAMES = 3
    SLOTS_PER_FRAME = 5

    @pytest_asyncio.fixture(autouse=True, loop_scope="session")
    async def seed(self, test_space, sparql_update):
        lines = []
        for f in range(3):
            lines.append(f"    ex:winFrame{f} a ex:Frame .")
            for s in range(5):
                lines.append(
                    f"    ex:winFrame{f} ex:hasSlot ex:winSlot{f}_{s} .")
                lines.append(
                    f"    ex:winSlot{f}_{s} ex:slotSeq \"{s}\"^^xsd:integer .")
        await sparql_update(
            f"{PREFIXES}\nINSERT DATA {{\n" + "\n".join(lines) + "\n}", test_space)

    async def test_flat_join_returns_all_slots(self, test_space, sparql_execute):
        """Baseline: the unwindowed join returns frames x slots."""
        bindings = await sparql_execute(f"""
        {PREFIXES}
        SELECT ?frame ?slot ?seq WHERE {{
            ?frame a ex:Frame .
            ?frame ex:hasSlot ?slot .
            ?slot ex:slotSeq ?seq .
        }} ORDER BY ?frame ?seq ?slot
        """, test_space)

        assert len(bindings) == self.FRAMES * self.SLOTS_PER_FRAME

    async def test_subselect_limit_is_global_not_per_frame(
        self, test_space, sparql_execute
    ):
        """A LIMIT inside an uncorrelated sub-SELECT bounds the WHOLE result.

        If this assertion fails with 6 rows (2 per frame) instead of 2, the
        backend is evaluating the sub-SELECT laterally — per-frame windows
        WOULD be expressible in one query and the plan's fallback is
        unnecessary.  Either outcome answers unknown 3.
        """
        limit = 2
        bindings = await sparql_execute(f"""
        {PREFIXES}
        SELECT ?frame ?slot WHERE {{
            ?frame a ex:Frame .
            ?frame ex:hasSlot ?slot .
            {{
                SELECT ?slot WHERE {{
                    ?slot ex:slotSeq ?seq .
                }} ORDER BY ?slot LIMIT {limit}
            }}
        }} ORDER BY ?frame ?slot
        """, test_space)

        assert len(bindings) == limit, (
            "sub-SELECT LIMIT was not applied globally — got "
            f"{len(bindings)} rows (per-frame would be "
            f"{limit * self.FRAMES}); per-frame windows may be expressible"
        )

    async def test_bounded_union_fallback_windows_each_frame(
        self, test_space, sparql_execute
    ):
        """The fallback: one bounded sub-SELECT per frame, UNIONed.

        Verifies the construct the plan falls back to actually produces a
        per-frame window.  Scales with the frame page size, so it is only
        viable for a modest page of frames.
        """
        limit = 2
        branches = " UNION ".join(
            f"""{{
                SELECT ?frame ?slot WHERE {{
                    BIND(ex:winFrame{f} AS ?frame)
                    ?frame ex:hasSlot ?slot .
                    ?slot ex:slotSeq ?seq .
                }} ORDER BY ?seq ?slot LIMIT {limit}
            }}"""
            for f in range(self.FRAMES)
        )
        bindings = await sparql_execute(f"""
        {PREFIXES}
        SELECT ?frame ?slot WHERE {{ {branches} }} ORDER BY ?frame ?slot
        """, test_space)

        assert len(bindings) == limit * self.FRAMES
        per_frame = {}
        for b in bindings:
            per_frame.setdefault(b["frame"]["value"], []).append(
                b["slot"]["value"])
        assert len(per_frame) == self.FRAMES
        assert all(len(v) == limit for v in per_frame.values()), per_frame

    async def test_slot_offset_pages_within_a_frame(
        self, test_space, sparql_execute
    ):
        """Per-frame slot paging: LIMIT/OFFSET on a single frame's slots.

        The per-frame slot endpoint path — iterate one frame's slots in
        sequence order without loading all of them.
        """
        seen = []
        page_size = 2
        for offset in range(0, 6, page_size):
            bindings = await sparql_execute(f"""
            {PREFIXES}
            SELECT ?slot ?seq WHERE {{
                ex:winFrame0 ex:hasSlot ?slot .
                ?slot ex:slotSeq ?seq .
            }} ORDER BY ?seq ?slot LIMIT {page_size} OFFSET {offset}
            """, test_space)
            seen.extend(_values(bindings, "seq"))

        assert [int(v) for v in seen] == list(range(self.SLOTS_PER_FRAME))
