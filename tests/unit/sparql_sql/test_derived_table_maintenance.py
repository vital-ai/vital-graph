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
DERIVED = {
    "edge": (("sync_edge_table", "delete_edges_for_context"),
             "denormalised edge mirror; the edge-table rewrite is the default "
             "plan for entity/frame/relation queries"),
    "frame_entity": (("sync_frame_entity",),
                     "derived from edge; collapses 6 tables per hop"),
    "stats": (("sync_stats_after", "resync_stats_for_predicates"),
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
KNOWN_GAPS: dict[tuple[str, str], str] = {}


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
    full = bodies["add_rdf_quads_batch_bulk"]
    for table, (markers, _why) in DERIVED.items():
        assert _maintains(full, markers), (
            f"add_rdf_quads_batch_bulk does not appear to maintain {table}; "
            f"the markers {markers!r} are probably stale")


@pytest.mark.parametrize("path", WRITE_PATHS)
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

def test_raw_sql_quad_writers_maintain_stats():
    """A module that INSERTs into rdf_quad directly gets no sync hook for free.

    The matrix above reads `sparql_sql_space_impl.py` only, so it proves nothing
    about a module that bypasses those methods and writes the quad table with
    raw SQL. That is not a hypothetical bypass — it is how the drift this test
    was added for happened.

    Measured on the host cluster 2026-08-15: 23 of 77 spaces had predicates
    present in `rdf_quad` with NO row in `rdf_pred_stats`, and on every one of
    them the missing predicates were the three server properties
    (`hasObjectCreationTime`, `hasObjectModificationDateTime`,
    `hasObjectStatusType`) written by `kg_server_properties`' raw-SQL backfill
    before it learned to sync. On `wordnet_frames` that was 3 predicates of 18
    covering 109,745 quads each, and because two of them carry the space's only
    temporal histograms, `rdf_value_stats.pred_rows` backfilled entirely NULL —
    freshness scaling inert on the one space where it had something to scale.

    A MISSING pred_stats row is categorically worse than a stale one. Stale
    gives the planner a number that drifts; missing gives it nothing, and
    nothing is not self-correcting, because the incremental sync only ever
    UPDATEs counts for predicates it already knows.

    Both accepted mechanisms appear here: an incremental sync of what was just
    written, or a full resync afterwards. A full resync is the stronger of the
    two and is what the import path uses.
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[3] / "vitalgraph"
    stats_markers = ("sync_stats_after_insert", "resync_stats_tables",
                     "resync_stats_for_predicates")

    # Modules where a raw quad INSERT is correct without a sync in the same file.
    exempt = {
        # The SQL EMITTER for SPARQL UPDATE. It builds statement text; it does
        # not execute it. Its caller, execute_sparql_update, maintains stats by
        # resync_stats_for_predicates and is covered by the matrix above.
        "db/sparql_sql/emit_update.py":
            "emits SQL text; execute_sparql_update runs it and resyncs",
        # A DIFFERENT BACKEND. The fuseki_postgresql backend does not have
        # these derived tables at all — they are sparql_sql constructs.
        "db/fuseki_postgresql/postgresql_db_impl.py":
            "fuseki backend; rdf_pred_stats is a sparql_sql construct",
    }

    offenders = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel == "db/sparql_sql/sparql_sql_space_impl.py" or rel in exempt:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        # A raw insert into the quad table, whatever local name holds it.
        if not re.search(r"INSERT\s+INTO\s+\{[a-z_]*quad[a-z_]*\}", text, re.I):
            continue
        # A CALL, not a mention. The first version of this check tested `m in
        # text` and passed even with the sync deleted, because the module names
        # `resync_stats_tables` in a log message ("...run resync_stats_tables")
        # — the marker matched prose. That is the false-negative direction the
        # note on DERIVED calls the dangerous one, reproduced here immediately.
        if not any(re.search(rf"\b{m}\s*\(", text) for m in stats_markers):
            offenders.append(rel)

    assert not offenders, (
        "these modules INSERT into rdf_quad with raw SQL but never sync "
        "rdf_pred_stats:\n  " + "\n  ".join(offenders)
        + "\n\nRaw SQL fires none of the incremental hooks in "
          "sparql_sql_space_impl. Call sync_stats_after_insert with the rows "
          "written, or resync_stats_tables afterwards. A predicate written "
          "without either gets NO pred_stats row, and the incremental sync "
          "will never create one — it only updates predicates it already "
          "knows. That left 23 of 77 host spaces with unrecorded predicates.")


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
