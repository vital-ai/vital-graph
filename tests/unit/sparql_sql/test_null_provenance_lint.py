"""Lint: emitters must not infer meaning from a NULL __uuid — issue 030.

The mistake that produced issue 026 was a single line: `emit_minus` tested a
`__uuid` column directly to decide whether a shared variable was bound. That
column is a literal `NULL::uuid` for any value synthesized by VALUES, BIND or
an aggregate, so a bound value read as unbound, the domain-intersection test
became unsatisfiable, and the whole MINUS silently became a no-op — widening
any DELETE guarded by it.

The column cannot answer the question. `ColumnInfo.has_term_identity()` can.

This is a source-level lint rather than a behavioural test because the defect
is a *habit*: the SQL it produces is valid and the results are plausible, so
nothing downstream catches it. Guarding the habit is the only thing that
generalises to emitters nobody has written yet.
"""
# pyright: reportOperatorIssue=false, reportArgumentType=false

from __future__ import annotations

import re
from pathlib import Path

import pytest

_EMIT_DIR = Path(__file__).resolve().parents[3] / "vitalgraph" / "db" / "sparql_sql"

# Modules that legitimately construct identity/boundness expressions. Each owns
# exactly one helper that is allowed to name a __uuid column for this purpose;
# everything else must go through ColumnInfo.
_SANCTIONED_HELPERS = {
    "emit_minus.py": "_identity_expr",
    "emit_join.py": "_boundness_col",
}

# Testing a __uuid column for NULL-ness in emitted SQL — the issue 026 bug.
_NULL_TEST = re.compile(r"__uuid\s+IS\s+(?:NOT\s+)?NULL", re.IGNORECASE)


def _emitter_sources():
    return sorted(_EMIT_DIR.glob("emit_*.py"))


def test_emitters_exist():
    """Guard the guard — a bad glob would make this file vacuously pass."""
    names = {p.name for p in _emitter_sources()}
    assert {"emit_minus.py", "emit_join.py", "emit_bgp.py"} <= names


@pytest.mark.parametrize("path", _emitter_sources(), ids=lambda p: p.name)
def test_no_direct_null_test_on_uuid_column(path: Path):
    """No emitter may write `<something>__uuid IS [NOT] NULL` into SQL.

    A NULL __uuid means "no term identity", which is not the same as "unbound"
    — ask ColumnInfo.has_term_identity() instead of the column.
    """
    offenders = []
    for lineno, line in enumerate(path.read_text().splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("*"):
            continue  # prose, including the comments explaining this rule
        if _NULL_TEST.search(line):
            offenders.append(f"{path.name}:{lineno}: {stripped}")

    assert not offenders, (
        "A __uuid column is being tested for NULL to infer boundness or "
        "identity. That column is NULL::uuid for VALUES/BIND/aggregate values, "
        "so this reads a bound value as unbound (issue 026). Use "
        "ColumnInfo.has_term_identity().\n  " + "\n  ".join(offenders)
    )


@pytest.mark.parametrize(
    "module,helper", sorted(_SANCTIONED_HELPERS.items()),
)
def test_sanctioned_helper_still_exists(module: str, helper: str):
    """The allowance above is scoped to a named helper in each module.

    If one is renamed or inlined, this fails — so the exemption cannot quietly
    become a licence for the whole file.
    """
    src = (_EMIT_DIR / module).read_text()
    assert f"def {helper}(" in src, (
        f"{module} no longer defines {helper}. If identity handling moved, "
        f"update _SANCTIONED_HELPERS so the lint keeps describing reality."
    )


def test_column_info_exposes_the_alternative():
    """The lint tells people to use has_term_identity(); it must exist."""
    from vitalgraph.db.sparql_sql.sql_type_generation import ColumnInfo
    assert hasattr(ColumnInfo, "has_term_identity")
    assert ColumnInfo.simple_output("s", "v0").has_term_identity() is False
    assert ColumnInfo.simple_output(
        "s", "v0", from_triple=True).has_term_identity() is True
