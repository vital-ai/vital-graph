"""An unresolved constant is not automatically a REQUIRED one.

The empty-constant short circuit rewrites a query to return nothing when a
constant it needs is not in the term table. That is a large win on the shape it
was built for, and a silent wrong answer whenever "needs" is decided too
loosely: `1 = 0` is not an error, and zero rows is a legitimate answer to a
query that matches nothing.

It was decided too loosely. `aliases.constants` registers every constant OFFERED
during collection, not the ones the query depends on, and the check simply
counted the unresolved ones. Measured on the `mql` KG shape against
sp_lead_synth_100k: three unresolved constants -- KGNewsEntity, KGProductEntity
and KGWebEntity, entity types that space does not contain -- against 72 plan
constraints, NONE of which referenced any of them. The query matched thousands
of rows through the types that DO exist, and returned zero. Caught by
`tests/performance/test_kgquery_generated_sql_plans.py`, which asserts a
non-empty result before reading anything into a plan.

The second case here is `issues/093`, which the same over-loose reading caused
once before in `prune_union`: `GRAPH ?g` compiles to `IS DISTINCT FROM` against
the default graph precisely so a missing term reads as "no exclusion", and
treating that absence as fatal emptied every such query. These tests exist so
the two cannot drift apart again -- the rule now delegates to the function that
fix produced, rather than offering a second opinion.
"""

from __future__ import annotations

from vitalgraph.db.sparql_sql.collect import _CONST_PREFIX, _CONST_SUFFIX
from vitalgraph.db.sparql_sql.generator import required_missing_constants


def _tok(col: str) -> str:
    return f"{_CONST_PREFIX}{col}{_CONST_SUFFIX}"


class _Node:
    """The smallest thing the rule walks: constraints plus children."""

    def __init__(self, constraints=None, tagged=None, children=None):
        self.constraints = constraints or []
        self.tagged_constraints = tagged or []
        self.children = children or []


def test_a_constant_no_constraint_mentions_is_not_required():
    """The measured regression: unresolved, unreferenced, and NOT fatal."""
    plan = _Node(constraints=[f"q0.object_uuid = {_tok('c_1')}"])
    assert required_missing_constants(plan, ["c_3", "c_4", "c_9"]) == [], (
        "constants that no constraint references cannot make a query empty; "
        "treating them as fatal returned 0 rows for the mql shape")


def test_an_equality_against_a_missing_constant_is_required():
    """The case the short circuit exists for — it must still fire."""
    plan = _Node(constraints=[f"q0.object_uuid = {_tok('c_3')}"])
    assert required_missing_constants(plan, ["c_3"]) == ["c_3"]


def test_is_distinct_from_a_missing_constant_is_not_required():
    """`issues/093`. Absence there means NO exclusion, not no rows."""
    plan = _Node(constraints=[f"q0.context_uuid IS DISTINCT FROM {_tok('c_3')}"])
    assert required_missing_constants(plan, ["c_3"]) == [], (
        "`GRAPH ?g` emits IS DISTINCT FROM against the default graph; reading a "
        "missing term as fatal empties every such query")


def test_it_finds_constraints_on_children_and_on_tags():
    """Constraints live in two lists and at any depth; missing either would
    silently under-report and let a genuinely empty query walk the data."""
    child = _Node(tagged=[("q1", f"q1.subject_uuid = {_tok('c_7')}")])
    plan = _Node(constraints=["q0.predicate_uuid = x"], children=[child])
    assert required_missing_constants(plan, ["c_7"]) == ["c_7"]


def test_a_token_is_not_matched_by_prefix():
    """`c_1` must not match `__CONST_c_10__`, or one missing constant would
    condemn every query using a longer name that starts with it."""
    plan = _Node(constraints=[f"q0.object_uuid = {_tok('c_10')}"])
    assert required_missing_constants(plan, ["c_1"]) == []
