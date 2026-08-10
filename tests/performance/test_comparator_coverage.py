"""Every comparator the API accepts, asserted against a known count.

Before this, `eq` and `gte` were the only comparators exercised anywhere in the
suite, on any slot class. That is 2 of 15. The consequences were not
theoretical:

  * `ne` on a boolean generated SQL that could not plan at all —
    `operator does not exist: text <> boolean` (issues/049)
  * `is_empty` took over 120 seconds on a 10,000-entity fixture (issues/052)
  * 21 comparator shapes time out at 100k for a 25-row page (issues/053)

None of those needed a subtle test to find. They needed *a* test.

Counts, not smoke
-----------------
Each case asserts an exact number derived from the fixture manifest, because
the failure mode here is a query that returns nothing and looks fast. Several
comparisons during this work "passed" while both sides returned zero rows. A
test that accepts any row count would have passed on every one of the defects
above.

The expectations are related, which is what makes them checkable: `eq` and `ne`
partition the population, `gte` and `lt` partition it, and `has`/`has_all`
degenerate to `eq` on a single-valued slot while `not_has` degenerates to `ne`.
If any assertion here is wrong, the arithmetic stops adding up rather than
quietly drifting.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

import pytest

# Loaded by PATH, not by package name. `import scripts.perf_shape_matrix` is
# ambiguous in this repo: tests/conformance/conftest.py prepends
# vitalgraph_sparql_sql_dev to sys.path, and that directory contains a real
# `scripts/` package with an __init__.py, which then shadows the repo-root
# namespace package. Collected alone this file passed; collected alongside
# tests/conformance every case failed with ModuleNotFoundError. Which suite
# wins a name should not decide whether these assertions run.
_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load_matrix():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_vg_perf_shape_matrix", _ROOT / "scripts" / "perf_shape_matrix.py")
    mod = importlib.util.module_from_spec(spec)
    # Registered before executing: @dataclass resolves its own module through
    # sys.modules, and without this the decorator raises on the module's first
    # dataclass rather than anything to do with the import path.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod

from .conftest import skip_no_pg
from .lead_fixtures import TYPES, require_usable

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

# Slot classes, mirroring the shape matrix so both describe the same fixture.
H = "http://vital.ai/ontology/haley-ai-kg#"
TEXT, DOUBLE, BOOL, INT, DATETIME, CHOICE = (
    H + "KGTextSlot", H + "KGDoubleSlot", H + "KGBooleanSlot",
    H + "KGIntegerSlot", H + "KGDateTimeSlot", H + "KGChoiceSlot")

# Entities in the fixture. Every entity carries every slot, so a slot valued
# for all of them answers `exists` with this number.
N = 2000

SIDECAR = os.environ.get("VG_TEST_SIDECAR_URL", "http://localhost:7071")


def _manifest():
    if TYPES.manifest_path is None or not TYPES.manifest_path.exists():
        pytest.skip(f"manifest not found: {TYPES.manifest_path} — build with "
                    f"scripts/generate_lead_dataset.py")
    return json.loads(TYPES.manifest_path.read_text())["actual_matches"]


def _expected(m):
    """(comparator, slot_class) -> expected row count, from the manifest.

    Only cases whose count the manifest actually pins down. A comparator whose
    expected value would have to be guessed is better left out than asserted
    loosely — a loose assertion is how `is_empty` passed while returning
    nothing.
    """
    eq_text = m["companystatecode_eq"]["CA"]
    eq_choice = m["leadstatus_eq"]["Working"]
    eq_bool = m["mqlv2_true"]
    valued_int = m["empty_slots"]["valued"]
    gte_double = m["mqlrating_gte"]["65"]
    gte_int = m["ratingpoints_gte"]["50"]

    return {
        # equality and its complement partition the population
        ("eq", TEXT): eq_text,
        ("ne", TEXT): N - eq_text,
        ("eq", CHOICE): eq_choice,
        ("ne", CHOICE): N - eq_choice,
        ("eq", BOOL): eq_bool,
        ("ne", BOOL): N - eq_bool,
        # ranges partition too
        ("gte", DOUBLE): gte_double,
        ("lt", DOUBLE): N - gte_double,
        ("gte", INT): gte_int,
        ("lt", INT): valued_int - gte_int,
        # presence
        ("exists", TEXT): N,
        ("exists", DOUBLE): N,
        ("not_exists", TEXT): 0,
        ("not_exists", DOUBLE): 0,
        ("is_empty", INT): m["empty_slots"]["empty"],
        # single-valued slots make the multi-value family degenerate
        ("has", TEXT): eq_text,
        ("has_any", TEXT): eq_text,
        ("has_all", TEXT): eq_text,
        ("not_has", TEXT): N - eq_text,
        ("not_has_any", TEXT): N - eq_text,
        ("has", CHOICE): eq_choice,
        ("has_any", CHOICE): eq_choice,
        ("has_all", CHOICE): eq_choice,
        ("not_has", CHOICE): N - eq_choice,
        ("not_has_any", CHOICE): N - eq_choice,
        # contains, where the needle is the whole value
        ("contains", TEXT): eq_text,
    }


CASES = [
    ("eq", TEXT), ("ne", TEXT), ("eq", CHOICE), ("ne", CHOICE),
    ("eq", BOOL), ("ne", BOOL),
    ("gte", DOUBLE), ("lt", DOUBLE), ("gte", INT), ("lt", INT),
    ("exists", TEXT), ("exists", DOUBLE),
    ("not_exists", TEXT), ("not_exists", DOUBLE), ("is_empty", INT),
    ("has", TEXT), ("has_any", TEXT), ("has_all", TEXT),
    ("not_has", TEXT), ("not_has_any", TEXT),
    ("has", CHOICE), ("has_any", CHOICE), ("has_all", CHOICE),
    ("not_has", CHOICE), ("not_has_any", CHOICE),
    ("contains", TEXT),
]


async def _count(perf_conn, comparator, slot_class) -> int:
    """Rows a criterion selects, run the way the service runs it."""
    matrix = _load_matrix()
    gen = await matrix.sql_for(
        perf_conn, matrix.build_criteria(comparator=comparator,
                                         slot_class=slot_class),
        TYPES.space, TYPES.graph,
        "http://vital.ai/ontology/haley-ai-kg#KGEntity", 100_000, SIDECAR)

    if gen.needs_ordered_scan:
        async with perf_conn.transaction():
            await perf_conn.execute("SET LOCAL enable_sort = off")
            return len(await perf_conn.fetch(gen.sql))
    return len(await perf_conn.fetch(gen.sql))


@pytest.mark.parametrize("comparator,slot_class", CASES,
                         ids=[f"{c}-{sc.split('#')[-1]}" for c, sc in CASES])
async def test_comparator_returns_the_expected_count(perf_conn, comparator,
                                                     slot_class):
    """The comparator selects exactly the subset the manifest describes."""
    reason = await require_usable(perf_conn, TYPES)
    if reason:
        pytest.skip(f"{reason} — build with scripts/load_lead_types_dataset.sh")

    expected = _expected(_manifest())[(comparator, slot_class)]
    got = await _count(perf_conn, comparator, slot_class)

    assert got == expected, (
        f"{comparator} on {slot_class.split('#')[-1]} returned {got} "
        f"rows, expected {expected} from the fixture manifest. A count of 0 "
        f"means the criterion matched nothing, which is how this class of "
        f"defect hides — see issues/049, 052, 053.")


# (slot class, manifest key holding the number of entities with a value)
PARTITIONS = [(DOUBLE, "mqlrating_total"), (INT, "ratingpoints_total")]


@pytest.mark.parametrize("slot_class,total_key", PARTITIONS,
                         ids=[sc.split("#")[-1] for sc, _k in PARTITIONS])
@pytest.mark.parametrize("pair", [("gt", "lte"), ("gte", "lt")],
                         ids=["gt+lte", "gte+lt"])
async def test_range_comparators_partition_the_population(perf_conn, slot_class,
                                                          total_key, pair):
    """`gt`/`lte` and `gte`/`lt` each split the valued entities exactly once.

    This is how `gt` gets tested at all. Its exact count is NOT in the manifest
    and cannot be: mqlrating carries one decimal place, so a couple of entities
    sit exactly on the 65.0 threshold and `gt` differs from `gte` by an amount
    the generator does not tally. The partition identity needs no such tally and
    is still exact — every valued entity falls on exactly one side.

    Worth having beyond bookkeeping. `gt` was the only range comparator that
    emitted an XSD cast, which the num_val push-down cannot carry, so it timed
    out at 60s where `gte` on the same slot and threshold ran in 505ms
    (issues/053). Nothing failed, because nothing ran `gt`. An identity across a
    pair also catches the degenerate pass that a count assertion invites: two
    comparators both returning 0 sum to 0, not to the population.
    """
    reason = await require_usable(perf_conn, TYPES)
    if reason:
        pytest.skip(f"{reason} — build with scripts/load_lead_types_dataset.sh")

    total = _manifest()[total_key]
    lo, hi = pair
    n_lo = await _count(perf_conn, lo, slot_class)
    n_hi = await _count(perf_conn, hi, slot_class)

    assert n_lo + n_hi == total, (
        f"{lo}={n_lo} and {hi}={n_hi} sum to {n_lo + n_hi} on "
        f"{slot_class.split('#')[-1]}, but {total} entities carry a value. "
        f"The two sides must partition the valued population exactly.")
    assert n_lo and n_hi, (
        f"{lo}={n_lo}, {hi}={n_hi} — a zero side means the comparator matched "
        f"nothing, which sums correctly only by accident.")
