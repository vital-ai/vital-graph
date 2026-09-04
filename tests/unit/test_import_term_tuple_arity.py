"""Every term tuple must match the INSERT it is bound to.

The regression this exists for: `issues/157` added `datatype_id` to the term
INSERT in `_flush_incremental_batch`, and three of fourteen tuple-construction
sites were updated. All THREE incremental import formats then failed at runtime
with

    asyncpg.exceptions._base.InterfaceError:
        the server expects 6 arguments for this query, 5 were passed

Nothing caught it before it shipped. The 53M validation import used the BULK
path, which was updated correctly; the unit suite never bound a real prepared
statement; and the arity only disagrees at execute time. E2E found it.

This is a SOURCE-level check on purpose. Exercising the real path needs a
database, and the defect is statically visible: a literal tuple whose length
does not match the placeholder count of the statement it is passed to.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

SRC = (Path(__file__).resolve().parents[2]
       / "vitalgraph" / "endpoint" / "impl" / "data_import_impl.py")


def _tree():
    return ast.parse(SRC.read_text(encoding="utf-8"))


def _insert_placeholder_count(name: str) -> int:
    """Highest $N in the INSERT that consumes `name`."""
    text = SRC.read_text(encoding="utf-8")
    # The statement is built from adjacent f-string fragments; find the VALUES
    # clause that follows the table this batch is flushed into.
    m = re.search(r"INSERT INTO \{term_tbl\}.*?VALUES \(([^)]*)\)", text, re.S)
    assert m, "could not find the term INSERT — has it been restructured?"
    return len(re.findall(r"\$\d+", m.group(1)))


def _appends(list_name: str):
    for node in ast.walk(_tree()):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "append"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == list_name
                and node.args
                and isinstance(node.args[0], ast.Tuple)):
            yield node.lineno, len(node.args[0].elts)


def test_the_term_insert_still_takes_six_columns():
    """Pins the number this file's tuples are written against."""
    assert _insert_placeholder_count("term_tbl") == 6


def test_every_term_tuple_has_the_arity_the_insert_expects():
    expected = _insert_placeholder_count("term_tbl")
    sites = list(_appends("term_batch"))
    assert sites, "no term_batch.append sites found — has this been renamed?"
    wrong = [(ln, n) for ln, n in sites if n != expected]
    assert not wrong, (
        f"term_batch tuples disagree with the INSERT's {expected} columns at "
        f"lines {[ln for ln, _ in wrong]} (arities {[n for _, n in wrong]}). "
        f"Every incremental import format shares this flush, so ONE bad site "
        f"breaks n-triples, JSONL quads and vital-block alike.")


def test_every_quad_tuple_has_a_consistent_arity():
    """Same failure mode, one statement over."""
    sites = list(_appends("quad_batch"))
    assert sites
    arities = {n for _, n in sites}
    assert len(arities) == 1, (
        f"quad_batch tuples have mixed arities {sorted(arities)} at "
        f"{[ln for ln, _ in sites]}")
