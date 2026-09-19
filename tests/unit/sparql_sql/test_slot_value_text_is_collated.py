"""A `value_text` comparison must carry COLLATE "C", or it cannot seek.

`idx_{space}_ess_text` indexes `value_text COLLATE "C"`; the database collation
is `en_US.utf8`. An equality written in the default collation cannot use that
index column, so PostgreSQL seeks on the columns before it and applies the value
as a FILTER. Measured on `lead_nurture_grouped` (4,064,500 slot-sort rows), same
query, one row returned:

    without COLLATE   Filter, 99,999 rows removed   92,139 buffers   2,231 ms
    with COLLATE      Index Cond on value_text           192 buffers      8 ms

480x the buffers. Constraining the leading columns does NOT rescue it —
`component_intersect`'s shape, with entity_type and slot_type both given, still
filtered 99,999 rows at 71,313 buffers.

ASSERTED ON THE GENERATED SQL, which is the lesson `issues/162` wrote down after
losing two measurement rounds to a narrowing that never fired: for an ADDITIVE
optimisation a missing clause changes nothing observable except speed, and speed
on these fixtures varies by more than the effect. The string is the only honest
witness.
"""

from __future__ import annotations

import re

import pytest

MODULES = [
    "vitalgraph.db.sparql_sql.slot_sort_range",
    "vitalgraph.db.sparql_sql.component_intersect",
]


@pytest.mark.parametrize("mod", MODULES, ids=[m.rsplit(".", 1)[-1] for m in MODULES])
def test_every_emitted_value_text_equality_is_collated(mod):
    """Scan the module source for an equality on value_text without COLLATE.

    Source-level rather than behavioural because both call sites need a live
    space, a resolved constant and a matching slot type to reach; the clause
    either appears in the emitted string or it does not.
    """
    import importlib, inspect
    src = inspect.getsource(importlib.import_module(mod))
    # f-string fragments that compare value_text, ignoring comments/docstrings
    offenders = []
    for line in src.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if not re.search(r'value_text\s*(COLLATE\s*\\?"C\\?")?\s*=', stripped):
            continue
        if "value_text COLLATE" in stripped:
            continue
        # `value_text = ''` in prose/examples inside a docstring has no f-prefix
        if 'f"' not in stripped and "f'" not in stripped:
            continue
        offenders.append(stripped[:100])
    assert not offenders, (
        f"{mod} emits an uncollated value_text equality; it will FILTER rather "
        f"than seek and the narrowing costs more than it saves:\n  "
        + "\n  ".join(offenders))


def test_the_collation_matches_the_index_definition():
    """If the schema's index collation ever changes, these must change together.

    Pinned because the two are separated by a whole module: the index is
    declared in `sparql_sql_schema` and the comparison is emitted in
    `slot_sort_range`, and nothing but this cell ties them.
    """
    import inspect, re
    from vitalgraph.db.sparql_sql import sparql_sql_schema
    schema_src = inspect.getsource(sparql_sql_schema)
    # The DDL escapes its quotes in source: `value_text COLLATE \"C\"`.
    assert re.search(r'value_text COLLATE \\?"C\\?"', schema_src), (
        'the text index no longer declares COLLATE "C" — if the collation '
        "changed, every emitted comparison must change with it or silently "
        "stop seeking")

    # The schema comment at the index already ASSUMED the generator collates,
    # and it was right about ORDER BY and wrong about equality for as long as
    # the equality narrowing existed. Both now hold.
    assert 'COLLATE "C" matches what the generator emits' in schema_src
