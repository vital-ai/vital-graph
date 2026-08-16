"""Every write path must maintain every derived table, or say why not.

THE INVARIANT THIS ENFORCES
---------------------------
`{space}_edge`, `{space}_frame_entity`, `{space}_rdf_pred_stats` and
`{space}_rdf_stats` are denormalised mirrors of `rdf_quad`. A write path that
changes quads without updating them leaves them describing a graph that no
longer exists — and the query pipeline TRUSTS them, so the result is a wrong
answer rather than a slow one.

That is not hypothetical. `edge_table_integrity_bug.md` records a production
space whose edge table was ~25% incomplete because "the edge table is
maintained by only ONE of many write paths", and the consequence was entity,
frame and relation queries silently under-counting.

WHY A GENERATED MATRIX RATHER THAN A DOCUMENTED ONE
---------------------------------------------------
Because the documented one went stale, in both directions. As of 2026-08-15
`edge_table_integrity_bug.md`'s root-cause table lists `add_rdf_quads_batch`
and `add_rdf_quad` as NOT syncing the edge table — both since fixed — and does
not list the two delete paths that genuinely do not. Reading it gives exactly
the wrong picture of what is left, and it is the document that says "Not yet
fixed".

A hand-kept matrix describes the code at the moment someone last looked. This
one is derived from the code, so adding a write path without wiring it fails
here instead of surfacing as an under-count months later, and adding a DERIVED
TABLE forces a decision for every write path rather than none.

EXEMPTIONS ARE EXPLICIT AND CARRY A REASON
------------------------------------------
Some pairs genuinely do not apply, and "it does not apply" must be
distinguishable from "nobody thought about it" — that distinction is the whole
point of the exercise. An exemption states the reason, so a future reader can
disagree with it. An omission states nothing.
"""

from __future__ import annotations

import pathlib
import re

import pytest

_IMPL = (pathlib.Path(__file__).resolve().parents[3]
         / "vitalgraph" / "db" / "sparql_sql" / "sparql_sql_space_impl.py")

# The write paths on the space implementation that change quads.
WRITE_PATHS = [
    "add_rdf_quad",
    "add_rdf_quads_batch",
    "add_rdf_quads_batch_bulk",
    "remove_rdf_quad",
    "remove_rdf_quads_batch",
    "remove_rdf_quads_batch_bulk",
    "delete_entity_graph_bulk",
    # SPARQL UPDATE. Named in edge_table_integrity_bug.md's root cause as a
    # path that did not sync, and omitted from the first version of this matrix
    # — which is the failure this test exists to prevent, made by the test
    # itself. Any write path that reaches rdf_quad belongs here.
    "execute_sparql_update",
]

# derived table -> the marker that proves a path maintains it.
DERIVED = {
    "edge": ("sync_edge_table",
             "denormalised edge mirror; the edge-table rewrite is the default "
             "plan for entity/frame/relation queries"),
    "frame_entity": ("sync_frame_entity",
                     "derived from edge; collapses 6 tables per hop"),
    "stats": ("sync_stats_after",
              "rdf_pred_stats + rdf_stats; join reorder and the criterion gate "
              "read them"),
}

# (write path, derived table) -> why it does not apply. A pair that is neither
# maintained nor exempt fails the test.
EXEMPT: dict[tuple[str, str], str] = {}

# Pairs that are KNOWN BROKEN, kept as expected failures so the test passes on
# the current tree while naming what is wrong. Removing an entry here should be
# accompanied by wiring the sync in, not by adding an exemption.
#
# Measured 2026-08-15 by reading each method. See
# `planning_sql/derived_table_maintenance.md`.
KNOWN_GAPS: dict[tuple[str, str], str] = {
    ("add_rdf_quad", "stats"):
        "syncs edge and frame_entity but not stats — its own comment explains "
        "why edge/frame were added ('this path bypasses the bulk sync') and "
        "stats were not included in that reasoning",
    ("remove_rdf_quad", "edge"):
        "deletes a quad and maintains nothing; the _bulk variant of the same "
        "operation does. This is the issues/041 failure mode: a deleted edge "
        "quad leaves a live row in {space}_edge",
    ("remove_rdf_quad", "frame_entity"): "same as edge — no delete-side sync",
    ("remove_rdf_quad", "stats"): "same as edge — no delete-side sync",
    ("remove_rdf_quads_batch", "edge"):
        "deletes quads and maintains nothing; remove_rdf_quads_batch_bulk does",
    ("remove_rdf_quads_batch", "frame_entity"): "same as edge",
    ("remove_rdf_quads_batch", "stats"): "same as edge",
    ("execute_sparql_update", "stats"):
        "syncs edge and frame_entity but not stats. edge_table_integrity_bug.md "
        "notes the delete side separately: sync_stats_after_delete is "
        "subject-driven like the edge hooks, so a WHERE-bound DELETE misses it "
        "the same way",
}


def _method_bodies() -> dict[str, str]:
    """Each write method's source, taking the IMPLEMENTATION not the ABC stub.

    The file carries abstract declarations for several of these names; the
    implementation is the later definition. Taking the first match would read
    a one-line stub and report every table as unmaintained.
    """
    src = _IMPL.read_text(encoding="utf-8").split("\n")
    starts = [(i, m.group(1)) for i, line in enumerate(src)
              if (m := re.match(r"    async def (\w+)\s*\(", line))]
    out: dict[str, str] = {}
    for name in WRITE_PATHS:
        hits = [i for i, n in starts if n == name]
        assert hits, f"{name} is not defined in {_IMPL.name}"
        begin = max(hits)
        after = [i for i, _n in starts if i > begin]
        out[name] = "\n".join(src[begin: after[0] if after else len(src)])
    return out


def _maintains(body: str, marker: str) -> bool:
    return marker in body


def test_the_matrix_is_derived_from_real_implementations():
    """Guard the guard: a stub would report everything as unmaintained.

    Several of these names have an abstract declaration earlier in the file. If
    this helper picked those up, every cell would read "not maintained" and the
    test would look maximally alarming while measuring nothing.
    """
    bodies = _method_bodies()
    for name, body in bodies.items():
        assert len(body.split("\n")) > 3, (
            f"{name} resolved to a {len(body.split(chr(10)))}-line body — that "
            f"is an abstract stub, not the implementation")
    # And the one path known to maintain everything must read that way, or the
    # marker strings have drifted from the code.
    full = bodies["add_rdf_quads_batch_bulk"]
    for table, (marker, _why) in DERIVED.items():
        assert _maintains(full, marker), (
            f"add_rdf_quads_batch_bulk does not appear to maintain {table}; "
            f"the marker {marker!r} is probably stale")


@pytest.mark.parametrize("path", WRITE_PATHS)
@pytest.mark.parametrize("table", sorted(DERIVED))
def test_write_path_maintains_derived_table(path, table):
    marker, why = DERIVED[table]
    body = _method_bodies()[path]
    key = (path, table)

    if key in EXEMPT:
        pytest.skip(f"exempt: {EXEMPT[key]}")
    if key in KNOWN_GAPS:
        pytest.xfail(f"KNOWN GAP: {KNOWN_GAPS[key]}")

    assert _maintains(body, marker), (
        f"{path} changes quads but does not maintain {{space}}_{table} "
        f"({why}).\n"
        f"Either call the sync, or add an entry to EXEMPT with the reason it "
        f"does not apply. An omission is indistinguishable from an oversight, "
        f"which is how a production edge table drifted ~25% incomplete.")


def test_known_gaps_are_still_gaps():
    """An xfail that starts passing must be promoted, not left as an xfail.

    Otherwise a fix lands and the matrix keeps claiming the gap exists — the
    same staleness this test replaces, reintroduced one layer up.
    """
    bodies = _method_bodies()
    fixed = [f"{p}/{t}" for (p, t) in KNOWN_GAPS
             if _maintains(bodies[p], DERIVED[t][0])]
    assert not fixed, (
        f"these are listed as KNOWN_GAPS but now maintain their table: "
        f"{fixed}. Remove them from KNOWN_GAPS so the matrix stays true.")


# ---------------------------------------------------------------------------
# Schema comes from ONE place
# ---------------------------------------------------------------------------

def test_no_module_creates_a_per_space_table_outside_the_schema():
    """Every space must have the same schema from the moment it is created.

    On-demand creation makes a space's schema depend on which features have been
    exercised against it, and it has cost twice already: `drop_space` grew a
    self-healing sweep because "on-demand tables keep being added without anyone
    updating it", and one of the two was missed there anyway and leaked an
    orphan table per space ever created — 116 on one local stack.

    A per-space table is recognised by its DDL interpolating a space-scoped
    name. Global admin schema (agent_registry, entity_registry) is a different
    thing and is not in scope: those modules ARE the schema for their tables.

    If this fails, the table belongs in `create_space_tables_sql`, not in the
    module that first needed it.
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[3] / "vitalgraph"
    schema_owner = "sparql_sql_schema.py"
    # Modules that legitimately own global (not per-space) schema.
    global_schema = {"agent_registry_schema.py", "agent_registry_vector_schema.py",
                     "entity_registry_schema.py", "sparql_sql_admin.py"}

    offenders = []
    for path in root.rglob("*.py"):
        if path.name == schema_owner or path.name in global_schema:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for m in re.finditer(r"CREATE\s+TABLE(\s+IF\s+NOT\s+EXISTS)?\s+(\S+)",
                             text, re.IGNORECASE):
            target = m.group(2)
            if "TEMP" in text[max(0, m.start() - 40):m.start()].upper():
                continue                      # scratch tables are not schema
            # Per-space DDL interpolates a space-scoped name.
            if "{space_id}" in target or "{table_name}" in target or \
                    re.search(r"\{t\[", target) or "{vec_table}" in target or \
                    "{table}" in target:
                offenders.append(f"{path.relative_to(root).as_posix()}: {target}")

    # PER-INDEX artifacts are a different category from space schema, and the
    # rule does not apply to them.
    #
    # A space has ONE fixed schema. It also has zero or more vector and FTS
    # INDEXES, each of which brings its own storage table — `{space}_vec_{name}`
    # and `{space}_fts_{name}` — created when that index is created, alongside
    # the document collection or entity type it serves. Their schema cannot be
    # static: the embedding column is `vector(dimensions)`, and the dimensions
    # come from the model chosen at index-creation time.
    #
    # This is not on-demand creation from a data path. The catalogue tables that
    # record which indexes exist — `{space}_vector_index`, `{space}_fts_index` —
    # ARE fixed space schema and are created with the space; the per-index
    # tables are created by the explicit action that creates an index.
    #
    # So: a table named for the SPACE must come from the schema; a table named
    # for an INDEX comes from the action that creates that index.
    allowed_dynamic = {
        "document/vector_index_setup.py",
        "kg_impl/kgtype_index_setup.py",
    }
    offenders = [o for o in offenders
                 if not any(o.startswith(a) for a in allowed_dynamic)]

    assert not offenders, (
        "these modules create per-space tables outside the schema:\n  "
        + "\n  ".join(offenders)
        + "\n\nMove the DDL into SparqlSQLSchema.create_space_tables_sql so every "
          "space gets it at creation. A table created on demand exists only on "
          "spaces where the feature has run, and a second copy of the DDL "
          "diverges from the first — which is exactly what happened to "
          "ensure_edge_table, whose inline copy never gained edge_type_uuid.")

