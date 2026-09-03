"""A probe that compares a table against the thing that filled it proves nothing.

`issues/149`. `entity_slot_sort_drift` computes "expected" with `_select_rows` —
the same walk `resync_entity_slot_sort` uses to POPULATE the table. When the walk
is what is at fault the two agree exactly and drift reports converged, however
empty the table is relative to the actual data.

Measured on production 2026-09-03, with drift satisfied throughout:

    urn:...:NurtureAction      809 / 76,996  =  1.05%
    urn:...:KGBusiness           0 /  1,254  =  0.00%
    urn:...:KGLead               0 /  1,254  =  0.00%

The listing for NurtureAction therefore has no derived table to sort from and
does a full frame walk, measured end-to-end at 22.7s.

This is `issues/141` again in a different table — there the stats audit sampled
"the end that cannot be wrong". Same defect class: a check whose input is
downstream of the thing it is checking.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import inspect

from vitalgraph.db.sparql_sql import sync_entity_slot_sort as E
from vitalgraph.process import maintenance_job as M


def _body(fn) -> str:
    """Source with the docstring removed.

    The docstring NAMES `_select_rows` when explaining what this probe avoids,
    so a naive substring check on the whole source fails on its own prose.
    """
    src = inspect.getsource(fn)
    doc = fn.__doc__
    return src.replace(doc, "") if doc else src


def test_coverage_counts_from_the_quads_not_from_the_walk():
    """The whole point: the denominator must be independent of the derived
    table and of the walk that fills it."""
    body = _body(E.entity_slot_sort_coverage)
    assert "_rdf_quad" in body, "coverage must count entities from the quads"
    assert "_select_rows" not in body, (
        "using the walk here reproduces exactly the blindness this exists to "
        "fix — it would be confirmed by its own input")
    assert "ENTITY_TYPE_URI" in body, "typed by hasKGEntityType, per type"


def test_it_reports_the_worst_gap_first():
    """A caller acting on one gap per cycle must get the biggest."""
    src = _body(E.entity_slot_sort_coverage)
    assert "ORDER BY (o.of_type - COALESCE(h.in_table, 0)) DESC" in src
    assert "WHERE COALESCE(h.in_table, 0) < o.of_type" in src, (
        "fully covered types are not gaps and must not be reported")


def test_drift_says_it_cannot_see_this():
    """The old probe stays — it catches a different failure — but it must not
    read as sufficient, which is how this hid."""
    doc = E.entity_slot_sort_drift.__doc__ or ""
    assert "same walk" in doc.lower()
    assert "entity_slot_sort_coverage" in doc, (
        "the docstring must point at the probe that CAN see it")


def test_the_maintenance_check_runs_coverage_before_drift():
    """Drift can pick a space and declare it converged. Coverage has to be
    evaluated regardless, or the warning never fires on exactly the space that
    needs it."""
    src = inspect.getsource(M.MaintenanceJob._run_entity_slot_sort_integrity)
    at_cov = src.index("entity_slot_sort_coverage(")
    at_drift = src.index("entity_slot_sort_drift(")
    assert at_cov < at_drift


def test_the_warning_names_the_user_visible_consequence():
    src = inspect.getsource(M.MaintenanceJob._run_entity_slot_sort_integrity)
    assert "cannot use the derived" in src and "full frame walk" in src, (
        "a coverage percentage means nothing on its own; the message must say "
        "that queries sorting this type get no fast path")
    assert "issues/149" in src


def test_the_threshold_is_an_absence_alarm_not_a_drift_threshold():
    assert M.ENTITY_COVERAGE_MIN_RATIO >= 0.5, (
        "this fires when the fast path effectively does not exist for a type; "
        "the observed case was 1.05%, so a low threshold would miss it")
