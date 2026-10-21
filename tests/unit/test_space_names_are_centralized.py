"""Every per-space object name is built from `space_names.space_prefix`.

Stage 1 of the storage-key change (`planning/planning_db/space_storage_key_plan.md`):
the prefix is the space id today and becomes `vgs_<storage key>` later. That
switch is one edit to `space_names` ONLY IF nothing else spells a name from the
id itself — an `f"{space_id}_rdf_quad"` left anywhere keeps working today and
breaks on the day the prefix changes, silently for any caller that swallows
"relation does not exist".

Two checks, because each misses what the other catches:

* a SOURCE scan for f-strings that put a space id directly in front of `_`;
* a CANARY run of the DDL generators with the prefix changed, which catches
  names assembled some way the scan does not recognise.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from vitalgraph.db.sparql_sql import space_names
from vitalgraph.db.sparql_sql.space_names import space_id_for_prefix, space_prefix

ROOT = Path(__file__).resolve().parents[2]

#: Expressions that hold a space id where object names are built.
ID_EXPRS = {"space_id", "sid", "space", "ctx.space_id", "self.space_id",
            "self.SPACE_ID", "self._space_id", "best_space", "s"}

#: `(path, text after the id)` that is NOT a database object name, or a module
#: that legitimately works on prefixes directly. Each says why.
ALLOWED = {
    # LISTEN/NOTIFY channel names; not stored objects, and sender and listener
    # both use the id.
    ("vitalgraph/db/postgresql_signal_manager.py", "_events"),
}
ALLOWED_FILES = {
    # Moves objects from one prefix to another; documents why it maps ids.
    "vitalgraph/db/sparql_sql/space_rename.py",
    "vitalgraph/db/sparql_sql/space_names.py",
}


def _violations(path: Path):
    src = path.read_text()
    rel = path.relative_to(ROOT).as_posix()
    for node in ast.walk(ast.parse(src)):
        # `space_id + "_term"`: the same name, spelled by concatenation.
        if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add)
                and isinstance(node.right, ast.Constant)
                and isinstance(node.right.value, str)
                and node.right.value.startswith(("_", "\\_"))
                and ast.get_source_segment(src, node.left) in ID_EXPRS):
            yield (f"{rel}:{node.lineno}: "
                   f"{ast.get_source_segment(src, node.left)} + "
                   f"{node.right.value!r}")
            continue
        if not isinstance(node, ast.JoinedStr):
            continue
        vals = node.values
        for v, nxt in zip(vals, vals[1:]):
            if not (isinstance(v, ast.FormattedValue)
                    and isinstance(nxt, ast.Constant)
                    and isinstance(nxt.value, str)
                    and nxt.value.startswith(("_", "\\_"))):
                continue
            expr = ast.get_source_segment(src, v.value)
            if expr not in ID_EXPRS:
                continue
            after = nxt.value.split()[0] if nxt.value.split() else nxt.value
            if (rel, after) in ALLOWED:
                continue
            yield f"{rel}:{v.value.lineno}: {{{expr}}}{after}"


def _package_files():
    for p in sorted((ROOT / "vitalgraph").rglob("*.py")):
        if p.relative_to(ROOT).as_posix() not in ALLOWED_FILES:
            yield p


def test_no_name_is_spelled_from_a_space_id():
    found = [v for p in _package_files() for v in _violations(p)]
    assert not found, (
        "build per-space object names with "
        "f\"{space_prefix(space_id)}_…\", not from the id:\n  "
        + "\n  ".join(found))


def test_the_scan_sees_what_it_is_meant_to(tmp_path):
    """A scan that matches nothing passes forever."""
    root = tmp_path / "vitalgraph"
    root.mkdir()
    bad = root / "bad.py"
    bad.write_text('def f(space_id):\n'
                   '    return f"SELECT * FROM {space_id}_rdf_quad"\n'
                   'def e(space_id):\n'
                   '    return f"{space_id}\\\\_%"\n'
                   'def g(space_id):\n'
                   '    return f"SELECT * FROM {space_prefix(space_id)}_rdf_quad"\n'
                   'def h(space_id):\n'
                   '    """A docstring naming {space_id}_term is notation."""\n'
                   'def c(sid):\n'
                   '    return sid + "_term"\n')
    global ROOT
    saved, ROOT = ROOT, tmp_path
    try:
        assert sorted(v.split(": ", 1)[1] for v in _violations(bad)) == [
            "sid + '_term'", "{space_id}\\_%", "{space_id}_rdf_quad"]
    finally:
        ROOT = saved


def test_the_prefix_round_trips():
    for sid in ("x", "prod_kg", "prod_kg_test"):
        assert space_id_for_prefix(space_prefix(sid)) == sid


@pytest.fixture
def canary_prefix(monkeypatch):
    """Make the prefix differ from the id. Callers import the function by name,
    so the function's code is swapped rather than the module attribute."""
    monkeypatch.setattr(space_names.space_prefix, "__code__",
                        (lambda space_id: "zzcanary_" + space_id).__code__)
    monkeypatch.setattr(space_names.space_id_for_prefix, "__code__",
                        (lambda prefix: prefix[len("zzcanary_"):]).__code__)


def _generated_identifiers(sid: str):
    from vitalgraph.db.sparql_sql import uri_limit
    from vitalgraph.db.sparql_sql.sparql_sql_schema import (
        SparqlSQLSchema, identifiers_in, numeric_term_index_sql)
    from vitalgraph.vectorization import index_sync_trigger

    s = SparqlSQLSchema()
    stmts = (s.create_space_tables_sql(sid)
             + s.create_space_tables_sql(sid, partition_quads=4)
             + s.create_space_indexes_sql(sid)
             + s.drop_space_tables_sql(sid)
             + s.drop_space_indexes_sql(sid)
             + s.retired_table_sql(sid)
             + s.create_vector_data_table_sql(sid, "emb", 384)
             + s.create_fts_data_table_sql(sid, "txt", ["english"])
             + [numeric_term_index_sql(sid, s.get_table_names(sid)["term"]),
                uri_limit.uri_limit_constraint_sql(sid)]
             + index_sync_trigger.create_sql(sid))
    names = identifiers_in(stmts)
    names += list(s.get_table_names(sid).values())
    names += [s.vec_table_name(sid, "emb"), s.fts_table_name(sid, "txt"),
              uri_limit.uri_limit_constraint_name(sid),
              index_sync_trigger.function_name(sid),
              *index_sync_trigger.trigger_names(sid)]
    return names


def test_every_generated_name_carries_the_prefix(canary_prefix):
    sid = "prod_kg"
    names = _generated_identifiers(sid)
    assert len(names) > 100
    # `identifiers_in` also picks up the keyword after some DDL verbs.
    raw = sorted({n for n in names
                  if "zzcanary_prod_kg" not in n and not n.isupper()})
    assert not raw, f"named from the id, not the prefix: {raw[:10]}"


def test_table_attribution_goes_through_the_prefix(canary_prefix):
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
    ids = ["prod_kg", "prod_kg_test"]
    got = SparqlSQLSchema.classify_space_table("zzcanary_prod_kg_test_rdf_quad", ids)
    assert (got["space_id"], got["suffix"], got["role"]) == (
        "prod_kg_test", "rdf_quad", "schema")
    assert SparqlSQLSchema.orphan_tables_for_space(
        ["zzcanary_prod_kg_term", "zzcanary_prod_kg_test_term", "prod_kg_term"],
        "prod_kg", ["prod_kg_test"]) == ["zzcanary_prod_kg_term"]
