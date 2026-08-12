"""
v2 SQL Generator — orchestrates the full SPARQL → SQL pipeline.

Pipeline stages:
  1. Compile (sidecar) → JSON
  2. Map (jena_ast_mapper) → Op tree
  3. Collect → PlanV2
  4. Materialize constants (resolve __CONST__ tokens to UUIDs)
  5. Emit → SQL string
  6. Substitute constants into SQL
  7. Apply var_map renaming

This module is the v2 equivalent of v1's jena_sql_generator.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..jena_sparql.jena_ast_mapper import map_compile_response, CompileResult

from .ir import AliasGenerator
from .collect import collect, _CONST_PREFIX, _CONST_SUFFIX, _esc
from .emit import emit
from .emit_context import EmitContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class GenerateResult:
    """Result of the v2 SQL generation pipeline."""
    sql: str = ""
    var_map: Dict[str, str] = field(default_factory=dict)
    sparql_vars: List[str] = field(default_factory=list)
    ok: bool = True
    error: Optional[str] = None
    trace_json: Optional[str] = None
    # VectorRequests that need server-side vectorization before SQL execution.
    # Non-empty when the query uses vg:vectorSimilarity with a text argument.
    # The orchestrator must vectorize each request's search_text and replace
    # the placeholder token in the SQL with the actual embedding.
    vector_requests: List[Any] = field(default_factory=list)
    # FuzzyRequests that need MinHash LSH + RapidFuzz resolution before execution.
    # Non-empty when the query uses vg:fuzzyMatch with a text argument.
    fuzzy_requests: List[Any] = field(default_factory=list)
    # True when the SQL's O(page) property depends on the planner picking an
    # ordered, early-terminating scan. The executor fences the statement so it
    # cannot fall back to a blocking sort over the whole match set
    # (issues/047).
    needs_ordered_scan: bool = False


# ---------------------------------------------------------------------------
# Constant materialization (copied from v1 for isolation)
# ---------------------------------------------------------------------------

def substitute_constants(sql: str, aliases: AliasGenerator) -> str:
    """Replace __CONST_c_N__ tokens with resolved 'uuid'::uuid literals."""
    if not aliases.constants:
        return sql

    for (text, ttype), col_name in aliases.constants.items():
        token = f"{_CONST_PREFIX}{col_name}{_CONST_SUFFIX}"
        uuid_str = aliases.resolved_constants.get(col_name)
        if uuid_str:
            replacement = f"'{uuid_str}'::uuid"
        else:
            # Fallback: inline scalar subquery
            term_table = "_const"
            replacement = (
                f"(SELECT term_uuid FROM {term_table} "
                f"WHERE term_text = '{_esc(text)}' AND term_type = '{ttype}')"
            )
        sql = sql.replace(token, replacement)

    return sql


def build_constants_cte(aliases: AliasGenerator, term_table: str) -> str:
    """Build WITH _const AS (...) CTE for unresolved constants."""
    if not aliases.constants:
        return ""
    if len(aliases.resolved_constants) == len(aliases.constants):
        return ""
    pairs = [
        (text, ttype) for (text, ttype), col_name in aliases.constants.items()
        if col_name not in aliases.resolved_constants
    ]
    if not pairs:
        return ""
    if len(pairs) == 1:
        text, ttype = pairs[0]
        where = f"term_text = '{_esc(text)}' AND term_type = '{ttype}'"
    else:
        values = ", ".join(
            f"('{_esc(text)}', '{ttype}')" for text, ttype in pairs
        )
        where = f"(term_text, term_type) IN ({values})"
    return (
        f"WITH _const AS (\n"
        f"  SELECT term_text, term_type, term_uuid FROM {term_table}\n"
        f"  WHERE {where}\n"
        f")\n"
    )


def prepend_ctes(sql: str, aliases: AliasGenerator, term_table: str) -> str:
    """Attach the constants CTE and any hoisted push-down term sets.

    Emitted SQL sometimes already opens with its own `WITH` — the
    candidate-driven negation path builds one (`emit_backward.emit_candidate_ctes`).
    Concatenating a second `WITH` in front of that produces
    `WITH a AS (...) WITH b AS (...)`, which is a syntax error, so the clauses
    are MERGED rather than stacked.

    Filter push-down deliberately does NOT register CTEs here — see
    `filter_pushdown._term_set`, where hoisting the term set into a MATERIALIZED
    CTE was implemented, measured, and reverted for being 41x slower.
    """
    parts = []

    const = build_constants_cte(aliases, term_table)
    if const:
        # strip the "WITH " and the trailing newline, keeping just the body
        parts.append(const[len("WITH "):].rstrip("\n"))

    if not parts:
        return sql

    stripped = sql.lstrip()
    if stripped[:5].upper() == "WITH ":
        # Fold this query's own CTEs in after ours, as one WITH clause.
        parts.append(stripped[len("WITH "):].lstrip())
        return "WITH " + ",\n".join(parts)

    return "WITH " + ",\n".join(parts) + "\n" + sql


# ---------------------------------------------------------------------------
# Term constants cache: (space_id, term_text, term_type) → term_uuid
# Populated incrementally by materialize_constants; avoids a DB round
# trip when all requested constants are already known.
# ---------------------------------------------------------------------------

from collections import OrderedDict as _OrderedDict

_TERM_CACHE_MAX = 50_000


class _LRUCache(_OrderedDict):
    """OrderedDict with a max-entry cap (LRU eviction).

    Prevents unbounded growth of the module-global term cache — at billion-scale
    a scan-heavy workload could otherwise push it to tens of GB and OOM the
    process (see 100x_scalability_analysis.md §5.1).
    """

    def __init__(self, maxsize: int):
        super().__init__()
        self._maxsize = maxsize

    def __getitem__(self, key):
        self.move_to_end(key)
        return super().__getitem__(key)

    def get(self, key, default=None):
        if key in self:
            self.move_to_end(key)
            return super().__getitem__(key)
        return default

    def __setitem__(self, key, value):
        if key in self:
            self.move_to_end(key)
        super().__setitem__(key, value)
        while len(self) > self._maxsize:
            self.popitem(last=False)


_term_cache: _LRUCache = _LRUCache(_TERM_CACHE_MAX)   # (space_id, text, type) → uuid str


def invalidate_term_cache(space_id: Optional[str] = None) -> None:
    """Clear cached term UUIDs.  If *space_id* is given, only that space."""
    if space_id is None:
        _term_cache.clear()
    else:
        to_del = [k for k in _term_cache if k[0] == space_id]
        for k in to_del:
            del _term_cache[k]


# ---------------------------------------------------------------------------
# Datatype cache: space_id → {datatype_id: datatype_uri}
# ---------------------------------------------------------------------------

_datatype_cache: Dict[str, Dict[int, str]] = {}


def invalidate_datatype_cache(space_id: Optional[str] = None) -> None:
    """Clear cached datatype mappings."""
    if space_id is None:
        _datatype_cache.clear()
    else:
        _datatype_cache.pop(space_id, None)


# ---------------------------------------------------------------------------
# Predicate cardinality stats for join reordering
# ---------------------------------------------------------------------------

_stats_cache: Dict[str, tuple] = {}


def invalidate_stats_cache(space_id: str) -> None:
    """Clear cached stats for a space so the next query reloads from DB."""
    _stats_cache.pop(space_id, None)


async def _load_quad_stats(
    aliases: 'AliasGenerator',
    space_id: str,
    conn_params: Optional[Dict[str, Any]] = None,
    conn=None,
):
    """Load predicate cardinality stats from stats tables.

    Populates aliases.quad_stats and aliases.pred_stats for use by
    the join reorder heuristic.
    """
    if space_id in _stats_cache:
        aliases.quad_stats, aliases.pred_stats = _stats_cache[space_id]
        return

    from . import db_provider as db

    try:
        pred_rows = await db.execute_query(
            f"SELECT predicate_uuid::text, row_count "
            f"FROM {space_id}_rdf_pred_stats",
            conn_params=conn_params, conn=conn,
        )
        pred_stats = {r["predicate_uuid"]: r["row_count"] for r in pred_rows}

        quad_rows = await db.execute_query(
            # Cap the stats load: at 1B quads rdf_stats can have 50-200M rows;
            # loading all of them transfers GBs and can take minutes. The join
            # reorder heuristic only needs the most selective (lowest row_count)
            # pairs, so take the top 10K by ascending row_count. Uses
            # idx_{space}_rdf_stats_rc. (100x mitigation #4.)
            f"SELECT predicate_uuid::text, object_uuid::text, row_count "
            f"FROM {space_id}_rdf_stats "
            f"WHERE row_count >= 2 AND row_count <= 200000 "
            f"ORDER BY row_count ASC LIMIT 10000",
            conn_params=conn_params, conn=conn,
        )
        quad_stats = {
            (r["predicate_uuid"], r["object_uuid"]): r["row_count"]
            for r in quad_rows
        }

        aliases.quad_stats = quad_stats
        aliases.pred_stats = pred_stats
        _stats_cache[space_id] = (quad_stats, pred_stats)
        logger.debug("Loaded %d pred stats, %d quad stats for %s",
                     len(pred_stats), len(quad_stats), space_id)

    except Exception as e:
        logger.debug("No quad stats for %s (MV may not exist): %s", space_id, e)
        _stats_cache[space_id] = ({}, {})


# ---------------------------------------------------------------------------
# Datatype cache loader
# ---------------------------------------------------------------------------

async def _load_datatype_cache(
    space_id: str,
    conn_params: Optional[Dict[str, Any]] = None,
    conn=None,
) -> Dict[int, str]:
    """Load datatype_id → datatype_uri mapping from {space}_datatype table.

    Results are cached in _datatype_cache keyed by space_id.
    """
    if space_id in _datatype_cache:
        return _datatype_cache[space_id]

    if conn is None and conn_params is None:
        return {}

    from . import db_provider as db

    datatype_table = f"{space_id}_datatype"
    try:
        rows = await db.execute_query(
            f"SELECT datatype_id, datatype_uri FROM {datatype_table}",
            conn_params=conn_params, conn=conn,
        )
        cache = {r["datatype_id"]: r["datatype_uri"] for r in rows}
        _datatype_cache[space_id] = cache
        logger.debug("Loaded %d datatype mappings from %s",
                     len(cache), datatype_table)
        return cache
    except Exception:
        logger.debug("No datatype table for space %s — datatype cache empty",
                     space_id)
        _datatype_cache[space_id] = {}
        return {}


async def warm_stats_cache(
    space_id: str,
    conn_params: Optional[Dict[str, Any]] = None,
    conn=None,
) -> None:
    """Pre-load predicate cardinality stats into the global cache."""
    if space_id in _stats_cache:
        return

    from .ir import AliasGenerator
    dummy = AliasGenerator()
    await _load_quad_stats(dummy, space_id,
                           conn_params=conn_params, conn=conn)


# ---------------------------------------------------------------------------
# Main generator function
# ---------------------------------------------------------------------------

async def materialize_constants(
    aliases: AliasGenerator,
    term_table: str,
    conn_params: Optional[Dict[str, Any]] = None,
    conn=None,
) -> None:
    """Batch-resolve all registered constants to UUIDs via one DB query.

    Uses _term_cache to avoid the DB round trip when all constants are
    already known.  Any newly resolved UUIDs are added to the cache.
    """
    if not aliases.constants:
        return

    # Extract space_id from term_table name (e.g. "myspace_term" → "myspace")
    space_id = term_table.rsplit("_term", 1)[0] if term_table.endswith("_term") else ""

    # Check cache first — resolve as many as possible without DB
    missing_pairs = []
    for (text, ttype), col_name in aliases.constants.items():
        cached = _term_cache.get((space_id, text, ttype))
        if cached is not None:
            aliases.resolved_constants[col_name] = cached
        else:
            missing_pairs.append((text, ttype))

    if not missing_pairs:
        logger.debug("Materialized %d/%d constants (all cached)",
                     len(aliases.resolved_constants), len(aliases.constants))
        return

    from . import db_provider as db

    if len(missing_pairs) == 1:
        text, ttype = missing_pairs[0]
        sql = (
            f"SELECT term_text, term_type, term_uuid FROM {term_table} "
            f"WHERE term_text = '{_esc(text)}' AND term_type = '{ttype}' LIMIT 1"
        )
    else:
        values = ", ".join(
            f"('{_esc(text)}', '{ttype}')" for text, ttype in missing_pairs
        )
        sql = (
            f"SELECT term_text, term_type, term_uuid FROM {term_table} "
            f"WHERE (term_text, term_type) IN ({values})"
        )

    rows = await db.execute_query(sql, conn_params=conn_params, conn=conn)
    text_map = {(r["term_text"], r["term_type"]): str(r["term_uuid"]) for r in rows}

    for (text, ttype), col_name in aliases.constants.items():
        if col_name in aliases.resolved_constants:
            continue  # already resolved from cache
        uuid_str = text_map.get((text, ttype))
        if uuid_str:
            aliases.resolved_constants[col_name] = uuid_str
            _term_cache[(space_id, text, ttype)] = uuid_str
        else:
            logger.debug("Constant not found: text=%r type=%r", text, ttype)

    logger.debug("Materialized %d/%d constants (%d from cache, %d from DB)",
                 len(aliases.resolved_constants), len(aliases.constants),
                 len(aliases.constants) - len(missing_pairs), len(missing_pairs))


# ---------------------------------------------------------------------------
# Unresolved-variable policy (issue 028)
# ---------------------------------------------------------------------------

def _check_unresolved_vars(unresolved) -> None:
    """Raise on a variable that was in scope and still failed to resolve.

    Only the in-scope ones are errors. A variable that was legitimately out of
    scope compiles to NULL because that is what SPARQL specifies, and raising
    on it would reject conformant queries — see set_strict_unresolved_vars.
    """
    if not unresolved:
        return
    gaps = [(v, d, reason) for v, d, in_scope, reason in unresolved if in_scope]
    if not gaps:
        return
    # Raised in production, not only under test. A variable that was in scope
    # and still could not be resolved is always a translator bug — there is no
    # data for which NULL is the right answer — so the fail-open that produced
    # two whole-graph deletes (issues 023, 027) is closed here rather than
    # merely logged. Measured against the DAWG corpus: zero occurrences, so no
    # conformant query is affected.
    from .emit_expressions import UnresolvedVariableError
    detail = ", ".join(f"?{v} ({reason}, depth {d})" for v, d, reason in gaps)
    causes = {reason for _, _, reason in gaps}
    hint = ""
    if "text-not-materialised" in causes:
        hint = (
            " A 'text-not-materialised' variable DID resolve — its term JOIN "
            "was deferred because compute_text_needed_vars believed nothing "
            "referenced it, so its text column is NULL at runtime. Teach the "
            "reference collector about this reference (issue 027's second "
            "half)."
        )
    raise UnresolvedVariableError(
        f"Variable(s) lost their value while in scope: {detail}. Each compiles "
        f"to NULL, silently weakening the enclosing constraint (issues 023, "
        f"027). Being in scope means the translator should have carried the "
        f"value, so this is a translation gap — fix the wiring, do not relax "
        f"the check. A variable legitimately out of scope does not reach "
        f"here.{hint}"
    )


# Bounded so a common pair costs a fixed amount to classify. The gate compares
# match count against candidate count; both saturate at the cap, which only
# blurs the decision for pairs far larger than any page could need.
_PAIR_COUNT_CAP = 50_000
_pair_count_cache: Dict[tuple, int] = {}


# The text probe answers "is this leaf small?" in TWO steps, cheapest first,
# because the naive single count charges the most for the answer that matters
# least. Counting matching QUADS to a 50,000 cap cost 943ms of generation for
# `contains 'CA'`, and 10,000 still cost 604ms — all of it spent establishing
# that a common substring is common, which the gate then ignores.
#
# Step 1 counts matching TERMS to a tiny cap. That is trigram-served and ~1ms
# when the pattern is selective, and when it is not, PostgreSQL stops as soon as
# the cap is reached rather than counting 2.6M rows. Reaching the cap is itself
# the answer: too many terms to be worth driving from.
# Step 2 only runs for a pattern that survived, where the term set is small and
# counting its quads is correspondingly cheap.
_TEXT_TERM_CAP = 200
_TEXT_COUNT_CAP = 10_000


async def _load_missing_pair_stats(plan, aliases, space_id, conn=None,
                                   conn_params=None) -> None:
    """Fetch row counts for the plan's leaf pairs that the preload lacks.

    `_load_quad_stats` caps itself at the 10,000 least-common pairs, which is
    right for join reordering and wrong for a selectivity gate: the anchor's
    pair is common, so it is missing, and the gate cannot tell "common" from
    "unknown". This asks for exactly the handful of pairs this query needs.
    """
    from .semijoin import needed_pairs
    aliases.extra_quad_stats = {}
    aliases.range_stats = {}
    aliases.text_stats = {}
    # Pairs whose count hit _PAIR_COUNT_CAP, so their recorded value is a lower
    # bound rather than a measurement. See where it is populated below.
    aliases.saturated_pairs = set()
    if conn is None and conn_params is None:
        return
    try:
        pairs = needed_pairs(plan, aliases)
        missing = [pr for pr in pairs if pr not in (aliases.quad_stats or {})]
        if not missing:
            return
        from . import db_provider as db
        values = ", ".join(f"('{p}'::uuid, '{o}'::uuid)" for p, o in missing)
        rows = await db.execute_query(
            f"SELECT predicate_uuid::text, object_uuid::text, row_count "
            f"FROM {space_id}_rdf_stats "
            f"WHERE (predicate_uuid, object_uuid) IN ({values})",
            conn=conn, conn_params=conn_params)
        aliases.extra_quad_stats = {
            (r["predicate_uuid"], r["object_uuid"]): r["row_count"] for r in rows
        }

        # rdf_stats does not hold every pair either — the anchor's
        # (vitaltype, KGEntity) is absent from it on a space where it matches
        # 10,000 rows. For what is left, count directly but BOUNDED: the gate
        # only needs to know whether a pair is large, not how large, so a
        # capped count answers it at fixed cost. Cached per process because
        # these move slowly and the alternative is paying it per query.
        still = [pr for pr in missing if pr not in aliases.extra_quad_stats]
        for p_uuid, o_uuid in still:
            ck = (space_id, p_uuid, o_uuid)
            if ck in _pair_count_cache:
                aliases.extra_quad_stats[(p_uuid, o_uuid)] = _pair_count_cache[ck]
                continue
            crows = await db.execute_query(
                f"SELECT count(*) AS n FROM (SELECT 1 FROM {space_id}_rdf_quad "
                f"WHERE predicate_uuid = '{p_uuid}'::uuid "
                f"AND object_uuid = '{o_uuid}'::uuid "
                f"LIMIT {_PAIR_COUNT_CAP}) s",
                conn=conn, conn_params=conn_params)
            n = crows[0]["n"] if crows else 0
            _pair_count_cache[ck] = n
            aliases.extra_quad_stats[(p_uuid, o_uuid)] = n
            # A count that hit the cap is a LOWER BOUND, not a measurement.
            # The gate only asks "is this large?", for which they are the same
            # thing — but ranking two criteria against each other is not, and
            # both drivers in the query at issues/059 report exactly 50,000
            # against an actual 100,000 each. Recorded so a caller that ranks
            # can tell the two apart instead of silently treating a saturated
            # bound as exact (issues/061).
            if n >= _PAIR_COUNT_CAP:
                aliases.saturated_pairs.add((p_uuid, o_uuid))

        # Range leaves: no constant object, so count through the same bounded
        # form. The num_val index makes this an index scan.
        from .semijoin import needed_ranges
        from .sparql_sql_schema import NUMERIC_TERM_COLUMN
        aliases.range_stats = {}
        aliases.text_stats = {}
        for p_uuid, op, literal in needed_ranges(plan, aliases):
            ck = (space_id, p_uuid, op, literal)
            if ck in _pair_count_cache:
                aliases.range_stats[(p_uuid, op, literal)] = _pair_count_cache[ck]
                continue
            crows = await db.execute_query(
                f"SELECT count(*) AS n FROM (SELECT 1 FROM {space_id}_rdf_quad q "
                f"WHERE q.predicate_uuid = '{p_uuid}'::uuid AND q.object_uuid IN "
                f"(SELECT term_uuid FROM {space_id}_term "
                f" WHERE {NUMERIC_TERM_COLUMN} {op} {literal}) "
                f"LIMIT {_PAIR_COUNT_CAP}) s",
                conn=conn, conn_params=conn_params)
            n = crows[0]["n"] if crows else 0
            _pair_count_cache[ck] = n
            aliases.range_stats[(p_uuid, op, literal)] = n

        # Text leaves: no constant object either, and the count is the whole
        # question. A substring matching 2.6M terms and one matching none want
        # opposite plans, and nothing else in this function can tell them apart.
        # The GIN trigram index serves the selective case in ~1ms; the common
        # case hits the cap almost immediately. Both ends are cheap, which is
        # what makes measuring it affordable per query. See issues/070.
        from .semijoin import needed_texts
        for p_uuid, cond in needed_texts(plan, aliases):
            ck = (space_id, p_uuid, cond)
            if ck in _pair_count_cache:
                aliases.text_stats[(p_uuid, cond)] = _pair_count_cache[ck]
                continue
            trows = await db.execute_query(
                f"SELECT count(*) AS n FROM (SELECT 1 FROM {space_id}_term "
                f"WHERE {cond} LIMIT {_TEXT_TERM_CAP}) s",
                conn=conn, conn_params=conn_params)
            t_n = trows[0]["n"] if trows else 0
            if t_n >= _TEXT_TERM_CAP:
                # Common. Record it as saturated-large so the gate reads it as
                # "not selective" without a second, expensive count.
                n = _TEXT_COUNT_CAP
            else:
                crows = await db.execute_query(
                    f"SELECT count(*) AS n FROM (SELECT 1 FROM {space_id}_rdf_quad q "
                    f"WHERE q.predicate_uuid = '{p_uuid}'::uuid AND q.object_uuid IN "
                    f"(SELECT term_uuid FROM {space_id}_term WHERE {cond}) "
                    f"LIMIT {_TEXT_COUNT_CAP}) s",
                    conn=conn, conn_params=conn_params)
                n = crows[0]["n"] if crows else 0
            _pair_count_cache[ck] = n
            aliases.text_stats[(p_uuid, cond)] = n

        logger.debug("semijoin gate: resolved %d/%d pair stats (%d counted), "
                     "%d range(s), %d text(s)",
                     len(aliases.extra_quad_stats), len(missing),
                     len(still), len(aliases.range_stats),
                     len(aliases.text_stats))
    except Exception as e:
        logger.debug("semijoin gate: pair stats lookup failed: %s", e)


async def generate_sql(
    compile_result: CompileResult,
    space_id: str,
    conn_params: Optional[Dict[str, Any]] = None,
    conn=None,
    graph_lock_uri: Optional[str] = None,
    default_graph: Optional[str] = None,
    multi_vector_config: Optional[Dict[str, Any]] = None,
) -> GenerateResult:
    """Generate SQL from a compiled SPARQL query using the v2 pipeline.

    The collect/emit pipeline is pure (no I/O).  Only constant
    materialization, stats loading, datatype loading, and MV checks
    are awaited.
    """
    if not compile_result.ok:
        return GenerateResult(ok=False, error=compile_result.error)

    # --- UPDATE dispatch ---
    if compile_result.update_ops:
        from .emit_update import update_to_sql
        sql = await update_to_sql(compile_result.update_ops, space_id,
                                  conn_params=conn_params, conn=conn,
                                  default_graph_uri=default_graph)
        return GenerateResult(ok=True, sql=sql, var_map={}, sparql_vars=[])

    algebra = compile_result.algebra
    meta = compile_result.meta

    if algebra is None:
        return GenerateResult(ok=False, error="No algebra in compile result")

    try:
        # Stage 1: Collect → PlanV2 (pure, no I/O)
        aliases = AliasGenerator()
        if graph_lock_uri:
            aliases.graph_lock_uri = graph_lock_uri
        if default_graph:
            aliases.default_graph = default_graph
        plan = collect(algebra, space_id, aliases)

        # Inject PROJECT to exclude anonymous blank node variables
        from .var_scope import compute_scope
        from .ir import PlanV2, KIND_PROJECT, KIND_DISTINCT, KIND_REDUCED

        def _is_anon(v: str) -> bool:
            return v.startswith("?") or v.startswith(".")

        def _needs_anon_project(p: PlanV2) -> bool:
            if p.kind == KIND_PROJECT:
                return False
            scope = compute_scope(p)
            return any(_is_anon(v) for v in scope.all_visible)

        if _needs_anon_project(plan):
            if plan.kind in (KIND_DISTINCT, KIND_REDUCED) and plan.children:
                inner = plan.children[0]
                scope = compute_scope(inner)
                named = [v for v in sorted(scope.all_visible)
                         if not _is_anon(v)]
                proj = PlanV2(kind=KIND_PROJECT,
                              project_vars=named,
                              children=[inner])
                plan.children = [proj]
            else:
                scope = compute_scope(plan)
                named = [v for v in sorted(scope.all_visible)
                         if not _is_anon(v)]
                plan = PlanV2(kind=KIND_PROJECT,
                              project_vars=named,
                              children=[plan])

        # Stage 2: Materialize constants
        term_table = f"{space_id}_term"
        if conn is not None or conn_params is not None:
            await materialize_constants(aliases, term_table,
                                        conn_params=conn_params, conn=conn)

        # Stage 2 post: Prune dead UNION branches (constants absent from term table)
        from .prune_union import (prune_dead_union_branches,
                                  query_is_provably_empty)
        plan = prune_dead_union_branches(plan, aliases)

        # Checked AFTER pruning: a constant that survives only inside a branch
        # just removed is not required, and must not condemn the query.
        provably_empty = query_is_provably_empty(plan, aliases)
        if provably_empty:
            logger.info("Query is provably empty — a required constant is "
                        "absent from the term table")

        # Stage 2a: Load predicate cardinality stats
        if conn is not None or conn_params is not None:
            await _load_quad_stats(aliases, space_id,
                                   conn_params=conn_params, conn=conn)

        # Stage 2a.1: Edge table rewrite
        from .ensure_edge_table import ensure_edge_table
        from .ensure_frame_entity_table import ensure_frame_entity_table
        edge_ready = frame_entity_ready = False
        if conn is not None or conn_params is not None:
            edge_ready = await ensure_edge_table(space_id, conn=conn,
                                                 conn_params=conn_params)
            if edge_ready:
                from .rewrite_edge_table import rewrite_edge_table
                plan = rewrite_edge_table(plan, aliases, space_id)

            # Stage 2a.2: Frame-entity table rewrite
            frame_entity_ready = await ensure_frame_entity_table(
                space_id, conn=conn, conn_params=conn_params)
            if frame_entity_ready:
                from .rewrite_frame_entity_table import rewrite_frame_entity_table
                plan = rewrite_frame_entity_table(plan, aliases, space_id)

        # Stage 2a.3: Build the plans inside FILTER EXISTS / NOT EXISTS bodies.
        #
        # Has to happen HERE — after the rewrites, so the bodies get the same
        # treatment as the outer plan, and while a connection is still in scope.
        # Emit is synchronous, so the alternative was collecting the body at
        # emit time, which is what made every negated criterion walk raw quads
        # and resolve each predicate URI with a runtime subquery (issues/057).
        from .exists_subplan import prepare_exists_subplans
        await prepare_exists_subplans(
            plan, space_id, conn=conn, conn_params=conn_params,
            graph_lock_uri=graph_lock_uri,
            edge_table_ready=edge_ready, frame_entity_ready=frame_entity_ready)

        # Stage 2a.4: Edge fan-out, for the traversal-direction gate in
        # emit_slice. Loaded like the other statistics rather than queried at
        # emit time, because emit is synchronous.
        if conn is not None or conn_params is not None:
            try:
                from .sync_edge_fanout import load_edge_fanout
                aliases.edge_fanout = await load_edge_fanout(conn, space_id)
            except Exception:
                aliases.edge_fanout = {}
        else:
            aliases.edge_fanout = {}

        # Stage 2b: Load datatype cache
        datatype_cache = await _load_datatype_cache(
            space_id, conn_params=conn_params, conn=conn)

        # Stage 2c: Compute text-needed vars (skip term JOINs for internal-only vars)
        from .var_scope import compute_text_needed_vars
        text_needed = compute_text_needed_vars(plan)

        # Stage 2d: Vector/geo optimization hints (pure, no I/O)
        from .vg_optimize import vg_optimize
        plan = vg_optimize(plan)

        # Stage 2d.1: Mark joins emittable as existence tests, and the DISTINCT
        # each one makes redundant. After 2c so it sees the plan emit will see.
        from .semijoin import mark_semijoins, needed_pairs
        await _load_missing_pair_stats(plan, aliases, space_id,
                                       conn=conn, conn_params=conn_params)
        plan = mark_semijoins(plan, aliases)

        # Stage 2e: Pre-load vector + FTS index metadata
        vector_index_meta: Dict[str, Dict[str, Any]] = {}
        fts_index_meta: Dict[str, Dict[str, Any]] = {}
        if conn is not None:
            try:
                vi_table = f"{space_id}_vector_index"
                rows = await conn.fetch(
                    f"SELECT index_name, model_name, dimensions "
                    f"FROM {vi_table}")
                vector_index_meta = {
                    r['index_name']: {
                        'model_name': r['model_name'],
                        'dimensions': r['dimensions'],
                    }
                    for r in rows
                }
            except Exception:
                pass  # table may not exist for non-vector spaces
            try:
                fi_table = f"{space_id}_fts_index"
                rows = await conn.fetch(
                    f"SELECT index_name, languages FROM {fi_table}")
                fts_index_meta = {
                    r['index_name']: {
                        'languages': list(r['languages']),
                    }
                    for r in rows
                }
            except Exception:
                pass  # table may not exist for non-FTS spaces

        # Pre-load search mapping → index resolution
        search_mapping_meta: Dict[str, Dict[str, str]] = {}
        if conn is not None:
            try:
                sm_table = f"{space_id}_search_mapping"
                smi_table = f"{space_id}_search_mapping_index"
                rows = await conn.fetch(
                    f"SELECT sm.index_name AS mapping_name, smi.index_type, smi.index_name "
                    f"FROM {sm_table} sm "
                    f"JOIN {smi_table} smi ON sm.mapping_id = smi.mapping_id"
                )
                for r in rows:
                    mapping_name = r['mapping_name']
                    if mapping_name not in search_mapping_meta:
                        search_mapping_meta[mapping_name] = {}
                    search_mapping_meta[mapping_name][r['index_type']] = r['index_name']
            except Exception:
                pass  # tables may not exist

        # Stage 3: Emit → SQL (pure, no I/O)
        from .emit_context import ProcessingTrace
        sparql_text = getattr(meta, 'sparql', '') if meta else ''
        trace = ProcessingTrace(sparql_query=sparql_text)
        base_uri = meta.base_uri if meta else None
        ctx = EmitContext(space_id=space_id, aliases=aliases,
                          graph_lock_uri=graph_lock_uri, base_uri=base_uri,
                          trace=trace, datatype_cache=datatype_cache,
                          text_needed_vars=text_needed)
        if multi_vector_config:
            ctx.multi_vector_config = multi_vector_config
        ctx.vector_index_meta = vector_index_meta
        ctx.fts_index_meta = fts_index_meta
        ctx.search_mapping_meta = search_mapping_meta
        # Every variable NAMED anywhere in the plan, for the unresolved-variable
        # diagnostic. Not compute_scope().all_visible — that is only what is
        # visible at the root, so it excluded the variables most likely to fail
        # to resolve (a FILTER-only reference inside EXISTS, a sibling-scope
        # binding), leaving the diagnostic silent exactly when it was needed.
        # See issues 027 / 028.
        from .var_scope import all_named_vars
        ctx.query_all_vars = frozenset(all_named_vars(plan))
        sql_str = emit(plan, ctx)

        # Issue 028: any variable an expression could not resolve compiled to
        # NULL. Harmless when the variable is legitimately unbound, and a
        # silently-widened constraint when the translator should have resolved
        # it. The emitter marks; the decision is made here, where the whole
        # query has been seen.
        if ctx.unresolved_vars:
            _check_unresolved_vars(ctx.unresolved_vars)

        # Stage 3b: Resolve constants that only EMISSION could register.
        #
        # Filter push-down runs inside emit — it cannot know which BGP a filter
        # belongs to until the plan is being walked — so any constant it
        # registers arrives after Stage 2. `?v IN ("CA","NY")` is the case that
        # matters: as a term-table subquery the leaf has no constant object, and
        # the planner cannot drive the two-phase probe from the correlated
        # candidate, so it enumerates the value side instead. Measured on
        # has_any/Text, 11,679 ms against 37 ms once the uuid is a constant.
        #
        # Skipping this is not incorrect — substitute_constants falls back to a
        # scalar subquery over the _const CTE — only slow.
        if (conn is not None or conn_params is not None) and (
                len(aliases.resolved_constants) < len(aliases.constants)):
            await materialize_constants(aliases, term_table,
                                        conn_params=conn_params, conn=conn)

        # Stage 4: Substitute constants
        sql_str = substitute_constants(sql_str, aliases)

        # Stage 5: Prepend CTEs — unresolved constants, and term sets hoisted
        # out of filter push-down (issues/070).
        sql_str = prepend_ctes(sql_str, aliases, term_table)

        # Stage 5b: A required constant that is not in the term table makes the
        # whole query provably empty. Say so, rather than proving it by scanning
        # (issues/073) — `LIMIT 0` stops the Limit node before it fetches a
        # first tuple, so the subplan never executes, and wrapping preserves the
        # column names and types the caller expects. `eq`/DateTime at 100k: 40s+
        # to return nothing, against ~0 once this fires.
        if provably_empty:
            sql_str = f"SELECT * FROM (\n{sql_str}\n) _empty LIMIT 0"

        # Extract sparql_vars
        sparql_vars = []
        if meta and meta.project_vars:
            sparql_vars = [v for v in meta.project_vars if v != "*"]
        if not sparql_vars and plan.kind == "project" and plan.project_vars:
            sparql_vars = list(plan.project_vars)
        if not sparql_vars:
            from .var_scope import compute_scope
            scope = compute_scope(plan)
            sparql_vars = sorted(scope.all_visible)

        # Build var_map from TypeRegistry
        var_map = {}
        for sparql_name in ctx.types.all_vars():
            info = ctx.types.get(sparql_name)
            if info and info.sql_name:
                var_map[info.sql_name] = sparql_name

        ctx.trace.log_step(0, "final", "generator",
                           f"var_map: {var_map}")

        return GenerateResult(
            sql=sql_str,
            var_map=var_map,
            sparql_vars=sparql_vars,
            trace_json=ctx.trace.to_json(),
            vector_requests=ctx.vector_requests,
            fuzzy_requests=ctx.fuzzy_requests,
            needs_ordered_scan=ctx.needs_ordered_scan,
        )

    except Exception as e:
        logger.error("v2 SQL generation failed: %s", e, exc_info=True)
        return GenerateResult(ok=False, error=str(e))
