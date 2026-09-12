"""Every write path must maintain every derived table, or say why not.

THE INVARIANT THIS ENFORCES
---------------------------
`{space}_edge`, `{space}_frame_slot`, `{space}_rdf_pred_stats` and
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

_ROOT = pathlib.Path(__file__).resolve().parents[3]

# EVERY module containing a quad-changing write path, not just the space impl.
#
# `issues/185`: this test promised "every write path" and read ONE file, so the
# quad-changing paths in the other modules were not exempt and not listed as
# gaps — they were invisible. Deleting all three maintenance calls from
# `kg_backend_utils` left the suite green. A test written to prevent "one path
# was missed" that itself scans one file reproduces the original failure at the
# level of the guard.
MODULES = {
    "space_impl": _ROOT / "vitalgraph/db/sparql_sql/sparql_sql_space_impl.py",
    "kg_backend": _ROOT / "vitalgraph/kg_impl/kg_backend_utils.py",
    "data_import": _ROOT / "vitalgraph/endpoint/impl/data_import_impl.py",
    "bulk_export": _ROOT / "vitalgraph/db/sparql_sql/bulk_export.py",
}

# MODULES DELIBERATELY NOT LISTED, with the reason — the judgement this test is
# designed to force rather than allow to be skipped:
#
#   * `resync_all.py` — `resync_all_auxiliary_tables` REBUILDS every derived
#     table from the quads. It does not change quads, so the invariant does not
#     apply: it is the repair mechanism, not a path that can leave a mirror
#     stale.
#   * `bulk_export.export_space` — COPY OUT only. Reads quads, writes a file.
#
# `bulk_export.import_space` IS in the matrix: it COPYs quads back in.
#
# Membership was established by scanning each module's functions for direct
# `INSERT INTO`/`DELETE FROM`/`COPY` against `rdf_quad`, not by reading names.

# (module, function) for every write path that changes quads.
WRITE_PATHS = [
    ("space_impl", "add_rdf_quad"),
    ("space_impl", "add_rdf_quads_batch"),
    ("space_impl", "add_rdf_quads_batch_bulk"),
    ("space_impl", "remove_rdf_quad"),
    ("space_impl", "remove_rdf_quads_batch"),
    ("space_impl", "remove_rdf_quads_batch_bulk"),
    ("space_impl", "delete_entity_graph_bulk"),
    # SPARQL UPDATE. Named in edge_table_integrity_bug.md's root cause as a
    # path that did not sync, and omitted from the first version of this matrix
    # — which is the failure this test exists to prevent, made by the test
    # itself. Any write path that reaches rdf_quad belongs here.
    ("space_impl", "execute_sparql_update"),

    # Four DELETE-from-rdf_quad paths. These are the ones `issues/185`
    # demonstrated were invisible: removing their maintenance calls left the
    # suite green.
    ("kg_backend", "upsert_objects_atomic"),
    ("kg_backend", "update_entity_graph"),
    ("kg_backend", "update_entity_subject_only"),
    ("kg_backend", "update_subjects_graph"),

    # The import paths. `import_ntriples_bulk` COPYs and then resyncs
    # wholesale; the three incremental ones INSERT and DELETE per batch.
    ("data_import", "import_ntriples_bulk"),
    ("data_import", "import_ntriples_incremental"),
    ("data_import", "import_jsonl_quads_incremental"),
    ("data_import", "import_vital_block_incremental"),

    # Restores a space by COPYing quads back in.
    ("bulk_export", "import_space"),
]

# derived table -> (markers that prove a path maintains it, why it matters).
#
# MARKERS ARE A PROXY AND CAN BE WRONG IN BOTH DIRECTIONS. The first version of
# this test accepted only `sync_stats_after` for stats and therefore reported
# execute_sparql_update as a gap — it maintains them by
# `resync_stats_for_predicates`, a full per-predicate RECOUNT rather than
# incremental deltas, which is the stronger mechanism here because a recount is
# immune both to the WHERE-bound subject problem and to the issues/062
# resurrection bug.
#
# A false negative is the dangerous direction. "Fixing" that reported gap by
# adding sync_stats_after_insert on top of the recount would have DOUBLE
# COUNTED. So each entry lists every accepted mechanism, and adding a new one
# means adding it here.
# Accepted for EVERY table: a full rebuild is strictly stronger than an
# incremental delta, the same reasoning that accepts `resync_stats_for_predicates`.
# `import_ntriples_bulk` maintains everything this way and read as a triple gap
# until this was added.
_REBUILD = "resync_all_auxiliary_tables"

DERIVED = {
    # `resync_all_auxiliary_tables` is accepted for every table below. It
    # REBUILDS all of them from the quads, which is strictly stronger than an
    # incremental delta — the same reasoning that accepts
    # `resync_stats_for_predicates` above. `import_ntriples_bulk` maintains
    # everything this way and read as a triple gap until this was added.
    "edge": (("sync_edge_table", "delete_edges_for_context", _REBUILD),
             "denormalised edge mirror; the edge-table rewrite is the default "
             "plan for entity/frame/relation queries"),
    # `frame_entity` was RETIRED (`issues/183`): it named two `hasKGSlotType`
    # VALUES in its columns, so it could only serve frames using those two
    # roles, and 26 of 29 local spaces use others. `frame_slot` replaces it —
    # one row per (frame, slot) with the role as data — and is a structural
    # mirror on exactly the same terms: the collapse READS it, so a stale row
    # is a wrong answer rather than a slow query.
    "frame_slot": (("sync_frame_slot", "resync_frame_slot",
                    "delete_frame_slot_for_context", _REBUILD),
                   "derived from edge; collapses each slot arm of a hop"),
    # issues/096. A stale row here is a WRONG SORT ORDER, not a slow query —
    # the sort reads the value straight off this table — so it is a structural
    # mirror on the same terms as edge and frame_slot.
    "entity_slot_sort": (("sync_entity_slot_sort",
                          "delete_entity_slot_sort_for_context", _REBUILD),
                         "denormalised entity->frame->slot sort values; a slot "
                         "sort reads its ORDER from this table"),
    # ADDED 2026-09-12. These were absent while `entity_slot_sort` was present,
    # which is the blind spot `issues/185` was about repeating one level down:
    # the matrix can only report on tables it lists.
    #
    # WORSE FAILURE MODE THAN THE SLOT TABLE, and that is why they belong here.
    # `entity_slot_sort` going stale mis-ORDERS a page. These two are read by a
    # FILTER as well, and their read gate (`prop_sort_block`) is a BLOCK-LIST —
    # absence means SERVE — so a short table is not declined, it answers with a
    # plausible SUBSET and a count that agrees with it.
    "entity_prop_sort": (("sync_entity_prop_sort",
                          "delete_entity_prop_sort_for_context", _REBUILD),
                         "denormalised direct entity properties; a property "
                         "sort or FILTER reads this table"),
    "frame_prop_sort": (("sync_frame_prop_sort",
                         "delete_frame_prop_sort_for_context", _REBUILD),
                        "the same for top-level (Assertion) frames"),
    # STATS IS DELIBERATELY NOT IN THIS MATRIX ANY MORE.
    #
    # `rdf_stats` is no longer a write-path-maintained mirror. It is RECOMPUTED
    # from the quads by `recompute_stats_tables`, which is now its only writer
    # (`planning/planning_performance/rdf_stats_recompute_not_accumulate_plan.md`).
    #
    # The invariant this file enforces — "a write path that changes quads
    # without updating the mirror leaves it describing a graph that no longer
    # exists" — is exactly right for `edge`, `frame_slot` and
    # `entity_slot_sort`, whose staleness produces WRONG ANSWERS. It was wrong
    # for stats, and enforcing it here is what kept the accumulator alive:
    #
    #   * a stale stat produces a worse PLAN, never a wrong answer;
    #   * the accumulator could not validate itself, so a wrong delta was
    #     permanent and invisible (`issues/139`, `issues/142`);
    #   * and its two halves disagreed — the delete path decremented while the
    #     insert path refused to re-increment for a `pruned` predicate, so
    #     every pruned pair ratcheted to zero and the table drained from
    #     millions of rows to single digits.
    #
    # Adding stats back to this matrix would require re-introducing that
    # accumulator. If a future change makes a write path maintain stats again,
    # this comment is the thing to argue with first.
}

# (write path, derived table) -> why it does not apply. A pair that is neither
# maintained nor exempt fails the test.
_SUBJECT_ONLY = (
    "deletes ONLY quads whose subject IS the entity, leaving its frames, slots "
    "and edges in place. The entity subject carries no edge-source/dest "
    "properties and is not a frame, so no edge, frame_slot or slot-sort row can "
    "describe it. This reason is stated in the method's own docstring, which is "
    "why it is an exemption rather than a gap."
)

EXEMPT: dict[tuple[str, str], str] = {
    (("kg_backend", "update_entity_subject_only"), "edge"): _SUBJECT_ONLY,
    (("kg_backend", "update_entity_subject_only"), "frame_slot"): _SUBJECT_ONLY,
    (("kg_backend", "update_entity_subject_only"), "entity_slot_sort"): _SUBJECT_ONLY,
    # `frame_prop_sort` for the SAME reason as `frame_slot`: an entity subject is
    # not a frame, so no top-level-frame property row can describe it.
    (("kg_backend", "update_entity_subject_only"), "frame_prop_sort"): _SUBJECT_ONLY,
    # `entity_prop_sort` is DELIBERATELY NOT EXEMPT HERE. The reason above stops
    # exactly short of it: the entity subject carries no edge and is not a frame,
    # but its OWN direct quads are precisely what `entity_prop_sort` indexes. A
    # path that deletes them and leaves that table is the one case where
    # "subject only" makes the mirror wrong rather than irrelevant. Listed in
    # KNOWN_GAPS below, and it is the most severe of them.
}

# Pairs that are KNOWN BROKEN, kept as expected failures so the test passes on
# the current tree while naming what is wrong. Removing an entry here should be
# accompanied by wiring the sync in, not by adding an exemption.
#
# Measured 2026-08-15 by reading each method. See
# `planning_sql/derived_table_maintenance.md`.
# Pairs that are KNOWN BROKEN, kept as expected failures so the suite passes on
# the current tree while naming what is wrong. Removing an entry should be
# accompanied by wiring the sync in, not by adding an exemption.
#
# EMPTY as of 2026-08-15. Every write path maintains every derived table:
#
#   * remove_rdf_quad / remove_rdf_quads_batch gained all three (d56a4ca) —
#     they previously deleted quads and maintained nothing, the issues/064
#     orphan class on the REST delete paths;
#   * add_rdf_quad gained stats;
#   * execute_sparql_update was never a gap. It maintains stats by
#     `resync_stats_for_predicates`, and the first version of this test simply
#     did not recognise that mechanism. See the note on DERIVED.
_ESS_GAP = (
    "maintains `edge` and `frame_slot` but NOT `entity_slot_sort`, with no "
    "stated reason. Found 2026-09-11 by widening this matrix past one module "
    "(`issues/185`) — the question that issue listed as NOT ESTABLISHED, "
    "answered: yes, another derived table is also unmaintained on the modules "
    "the matrix could not see. A stale slot-sort row is a WRONG SORT ORDER, "
    "because the sort reads its value straight off this table. Tracked in "
    "`issues/187`; these stay named here until wired."
)

_PROP_GAP = (
    "maintains `edge` and `frame_slot` but NEITHER prop-sort table. Surfaced "
    "2026-09-12 by adding them to DERIVED; they were simply absent before, which "
    "is `issues/185` one level down -- the matrix reports only on tables it "
    "lists. WORSE THAN THE SLOT-TABLE GAP: these are read by a FILTER as well as "
    "a sort, and their gate (`prop_sort_block`) is a BLOCK-LIST, so absence means "
    "SERVE. A short table is not declined -- it answers with a plausible SUBSET "
    "and a count that agrees with it. Tracked in `issues/190`."
)

_EPS_SUBJECT_GAP = (
    "THE SEVERE ONE. `update_entity_subject_only` deletes exactly the quads "
    "hanging off the entity subject, and those are precisely what "
    "`entity_prop_sort` indexes -- so unlike `edge`, `frame_slot` and "
    "`entity_slot_sort`, which are legitimately exempt on this path, here the "
    "mirror is left describing properties the entity no longer has. A FILTER on "
    "a removed value still matches. Tracked in `issues/190`."
)

KNOWN_GAPS: dict[tuple[str, str], str] = {
    (("kg_backend", "upsert_objects_atomic"), "entity_slot_sort"): _ESS_GAP,
    (("kg_backend", "update_entity_graph"), "entity_slot_sort"): _ESS_GAP,
    (("kg_backend", "update_subjects_graph"), "entity_slot_sort"): _ESS_GAP,
    (("data_import", "import_ntriples_incremental"), "entity_slot_sort"): _ESS_GAP,
    (("data_import", "import_jsonl_quads_incremental"), "entity_slot_sort"): _ESS_GAP,
    (("data_import", "import_vital_block_incremental"), "entity_slot_sort"): _ESS_GAP,
    # `entity_prop_sort` / `frame_prop_sort`, surfaced 2026-09-12 by listing them
    # in DERIVED at all. See `issues/190`. Same seven paths as the slot table,
    # plus the subject-only path for `entity_prop_sort` (see EXEMPT above).
    (("kg_backend", "update_entity_subject_only"), "entity_prop_sort"): _EPS_SUBJECT_GAP,
    (("kg_backend", "upsert_objects_atomic"), "entity_prop_sort"): _PROP_GAP,
    (("kg_backend", "update_entity_graph"), "entity_prop_sort"): _PROP_GAP,
    (("kg_backend", "update_subjects_graph"), "entity_prop_sort"): _PROP_GAP,
    (("data_import", "import_ntriples_incremental"), "entity_prop_sort"): _PROP_GAP,
    (("data_import", "import_jsonl_quads_incremental"), "entity_prop_sort"): _PROP_GAP,
    (("data_import", "import_vital_block_incremental"), "entity_prop_sort"): _PROP_GAP,
    (("kg_backend", "upsert_objects_atomic"), "frame_prop_sort"): _PROP_GAP,
    (("kg_backend", "update_entity_graph"), "frame_prop_sort"): _PROP_GAP,
    (("kg_backend", "update_subjects_graph"), "frame_prop_sort"): _PROP_GAP,
    (("data_import", "import_ntriples_incremental"), "frame_prop_sort"): _PROP_GAP,
    (("data_import", "import_jsonl_quads_incremental"), "frame_prop_sort"): _PROP_GAP,
    (("data_import", "import_vital_block_incremental"), "frame_prop_sort"): _PROP_GAP,
}


def _method_bodies() -> dict[tuple[str, str], str]:
    """(module, function) -> source text, via AST.

    AST rather than the previous `    async def ` regex, which assumed a
    four-space indent and therefore only ever matched methods on one class. The
    write paths outside the space implementation are module-level functions and
    methods at other depths; a pattern that cannot see them is how they stayed
    invisible (`issues/185`).
    """
    import ast

    out: dict[tuple[str, str], str] = {}
    for mod, path in MODULES.items():
        src = path.read_text()
        lines = src.splitlines()
        tree = ast.parse(src)
        found: dict[str, str] = {}
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = "\n".join(lines[node.lineno - 1:(node.end_lineno or node.lineno)])
            # A name may appear twice (an abstract declaration and the real
            # implementation). Keep the longest.
            if len(body) > len(found.get(node.name, "")):
                found[node.name] = body
        for m, name in WRITE_PATHS:
            if m != mod:
                continue
            assert name in found, f"{name} is not defined in {path.name}"
            out[(mod, name)] = found[name]
    return out


def _maintains(body: str, markers) -> bool:
    return any(m in body for m in markers)


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
    full = bodies[("space_impl", "add_rdf_quads_batch_bulk")]
    for table, (markers, _why) in DERIVED.items():
        assert _maintains(full, markers), (
            f"add_rdf_quads_batch_bulk does not appear to maintain {table}; "
            f"the markers {markers!r} are probably stale")


@pytest.mark.parametrize("path", WRITE_PATHS, ids=lambda p: f"{p[0]}.{p[1]}")
@pytest.mark.parametrize("table", sorted(DERIVED))
def test_write_path_maintains_derived_table(path, table):
    markers, why = DERIVED[table]
    body = _method_bodies()[path]
    key = (path, table)

    if key in EXEMPT:
        pytest.skip(f"exempt: {EXEMPT[key]}")
    if key in KNOWN_GAPS:
        pytest.xfail(f"KNOWN GAP: {KNOWN_GAPS[key]}")

    assert _maintains(body, markers), (
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



# ---------------------------------------------------------------------------
# Quad writers OUTSIDE the space implementation
# ---------------------------------------------------------------------------

def test_raw_sql_quad_writers_no_longer_need_to_sync_stats():
    """RETIRED, and the reason is the point.

    This used to assert that every module doing a raw `INSERT INTO ..._rdf_quad`
    also synced `rdf_pred_stats`. It was written against a real production bug:
    five spaces had predicates present in `rdf_quad` with NO row in
    `rdf_pred_stats` — the three server properties written by a raw-SQL backfill
    before it learned to sync — and on `wordnet_frames` that was 3 predicates of
    18 covering 109,745 quads each.

    Its stated rationale was:

        "A MISSING pred_stats row is categorically worse than a stale one.
         Stale gives the planner a number that drifts; missing gives it
         nothing, and nothing is not self-correcting, because the incremental
         sync only ever UPDATEs counts for predicates it already knows."

    That last clause was true of the ACCUMULATOR and is false now.
    `recompute_stats_tables` rebuilds `rdf_pred_stats` wholesale from the quads
    on every run, so a predicate written by any path — raw SQL, COPY, an
    operator's psql session — appears at the next recompute. "Missing" is
    self-correcting by construction.

    Keeping the assertion would force every raw-SQL writer to call a sync that
    no longer exists. Its guarantee is now covered by
    `tests/integration/test_stats_recompute.py::test_pred_stats_is_rebuilt_too`.
    """
    from vitalgraph.db.sparql_sql import sync_stats_tables as S
    assert hasattr(S, "recompute_stats_tables"), (
        "the guarantee that replaced this test lives in recompute_stats_tables")
    for gone in ("sync_stats_after_insert", "sync_stats_after_delete",
                 "sync_stats_for_deleted_subjects"):
        assert not hasattr(S, gone), (
            f"{gone} is back — the accumulator returning means this test's "
            f"original invariant is live again and should be restored with it")
def test_geo_config_predicate_defaults_agree_across_all_three_copies():
    """The geo_config defaults exist in three places and must not diverge.

    `DEFAULT_LAT_PREDICATES` in geo_config_manager, the `CREATE TABLE` in
    sparql_sql_schema, and a second `CREATE TABLE` in migrate_vector_geo_schema
    all state the same list. They HAD diverged: the deployed tables defaulted to
    a set including W3C Basic Geo `wgs84_pos`, while both DDL copies had been
    narrowed to a single vital-aimp URI, and a schema realignment then propagated
    the narrower list over the wider one on 16 of 77 host tables.

    These are RECOGNITION lists — matched against predicates already in the data,
    never minted — so a missing entry is a silent under-population and an extra
    one is free. That asymmetry is why divergence here is worth a test rather
    than a comment.
    """
    import pathlib
    import re

    from vitalgraph.vectorization.geo_config_manager import (
        DEFAULT_LAT_PREDICATES, DEFAULT_LON_PREDICATES)
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema

    def ddl_default(text: str, column: str) -> tuple[str, ...]:
        m = re.search(rf"{column}\s+TEXT\[\]\s+NOT NULL DEFAULT ARRAY\[([^\]]*)\]",
                      text, re.S)
        assert m, f"no {column} default found"
        return tuple(re.findall(r"'([^']+)'", m.group(1)))

    probe = "\x00SPACE\x00"
    schema_ddl = [s for s in SparqlSQLSchema().create_space_tables_sql(probe)
                  if f"{probe}_geo_config (" in s][0]
    migration = (pathlib.Path(__file__).resolve().parents[3] / "vitalgraph" / "db"
                 / "migrations" / "migrate_vector_geo_schema.py").read_text()

    for column, constant in (("lat_predicates", DEFAULT_LAT_PREDICATES),
                             ("lon_predicates", DEFAULT_LON_PREDICATES)):
        from_schema = ddl_default(schema_ddl, column)
        from_migration = ddl_default(migration, column)
        assert tuple(constant) == from_schema == from_migration, (
            f"{column} disagrees across its three definitions:\n"
            f"  geo_config_manager      : {tuple(constant)}\n"
            f"  sparql_sql_schema       : {from_schema}\n"
            f"  migrate_vector_geo_schema: {from_migration}")

    # The namespace that appears in RDF is http://. The https:// form serves the
    # vocabulary document and would match no predicate in any dataset.
    joined = " ".join(DEFAULT_LAT_PREDICATES + DEFAULT_LON_PREDICATES)
    assert "https://www.w3.org/2003/01/geo" not in joined, (
        "W3C Basic Geo predicates must use the http:// namespace; the https:// "
        "URL is the document, not the namespace, and matches nothing.")
    assert "http://www.w3.org/2003/01/geo/wgs84_pos#lat" in DEFAULT_LAT_PREDICATES
    assert "http://www.w3.org/2003/01/geo/wgs84_pos#long" in DEFAULT_LON_PREDICATES


def test_geo_predicates_are_real_predicates():
    """Every configured geo predicate must exist in a vocabulary we can point to.

    The sibling test above only checks the three copies AGREE. They agreed
    perfectly while all three carried `haley-ai-kg#hasLatitude` and
    `#hasLongitude`, which that ontology does not define — it has
    `hasLongSlotValue` and `hasLongTextSlotValue`, nothing geo. Consistency is
    not correctness, and a fabricated URI propagated cleanly through all three
    copies and into 77 deployed tables precisely because they were consistent.

    They were added on the reasoning that an entry matching nothing is free.
    That holds for query cost and fails for everything else: a URI listed as a
    default reads as evidence the predicate exists, and the next reader has no
    way to tell an invented one from a researched one.

    Vital predicates are checked against the domain schema, which is the
    authority for what the ontologies define. W3C Basic Geo is external and
    allowlisted by exact term — `lat`, `long`, `alt` are the three it defines.
    """
    import json
    import pathlib

    from vitalgraph.vectorization.geo_config_manager import (
        DEFAULT_LAT_PREDICATES, DEFAULT_LON_PREDICATES)

    root = pathlib.Path(__file__).resolve().parents[3]
    schema_text = "".join(
        p.read_text(encoding="utf-8")
        for p in (root / "domain_schema").glob("*.json"))

    WGS84 = "http://www.w3.org/2003/01/geo/wgs84_pos#"
    wgs84_terms = {"lat", "long", "alt"}

    unknown = []
    for uri in DEFAULT_LAT_PREDICATES + DEFAULT_LON_PREDICATES:
        if uri.startswith(WGS84):
            if uri[len(WGS84):] not in wgs84_terms:
                unknown.append(f"{uri} (not a W3C Basic Geo term)")
        elif f'"{uri}"' not in schema_text:
            unknown.append(f"{uri} (not defined in domain_schema)")

    assert not unknown, (
        "these geo predicates are not defined by any vocabulary in the tree:\n  "
        + "\n  ".join(unknown)
        + "\n\nA default that names a nonexistent predicate matches nothing and "
          "misleads every later reader into thinking it exists. Verify the URI "
          "against domain_schema before adding it.")
