"""Compute `{space}_edge_fanout`: how much one traversal step multiplies rows.

The statistic nothing else expresses. `rdf_stats` and PostgreSQL's
`stat_*_quad_po` both describe single-table selectivity; the errors that matter
in a multi-hop traversal are **join** cardinality — measured at 305x and 4,761x
underestimates, which is the whole of the 700ms vs >200s gap in `issues/059`.
Fan-out is what multiplies through those hops, and PostgreSQL cannot infer it
from column statistics because it is a property of the join, not of a column.

Why the key is (edge type, relation type, direction)
----------------------------------------------------
Measured on `sp_kg_rel`, where all four are `Edge_hasKGRelation`:

    reportsTo   forward 1.00 / max 1     backward 4.77 / max 5      a tree
    worksFor    forward 1.00 / max 1     backward 39.00 / max 886   a hub

Recorded per edge type those average into a number describing neither, and per
space the whole table reports 1.80 / 1.51, which hides both. The granularity has
to reach `hasKGRelationType`.

Why the tail and not just the mean
----------------------------------
`wordnet_frames`' slot-value in-degree averages 5.20 with a maximum of 1,342 — a
258x mean-to-max ratio. A plan chosen on the average can be that far wrong, and
the cost of being wrong here is a timeout rather than a slightly worse plan. p99
and max are stored alongside avg so a caller can plan for the tail when the
downside is asymmetric.

What the numbers are good for
-----------------------------
Direction choice, primarily. Containment edges are a tree — a slot has exactly
one parent, a frame none or one — so backward fan-out is 1 *by construction*,
and walking them backward cannot amplify. Relations have no safe direction: an
entity may be source or destination in many. A rewrite that picks a traversal
direction needs to know which case it is in, and this is the only place that
records it.
"""

from __future__ import annotations

import logging
import uuid
from typing import Dict

logger = logging.getLogger(__name__)

NO_RELATION = uuid.UUID("00000000-0000-0000-0000-000000000000")

_RELATION_TYPE_URI = "http://vital.ai/ontology/haley-ai-kg#hasKGRelationType"
_VITALGRAPH_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
_REL_TYPE_UUID = uuid.uuid5(_VITALGRAPH_NS, f"{_RELATION_TYPE_URI}\x00U")


async def compute_edge_fanout(conn, space_id: str) -> int:
    """Recompute the fan-out table from the edge table. Returns rows written.

    One pass per direction over `{space}_edge`, grouped by edge type and (where
    present) relation type. Requires `edge_type_uuid` to be populated — without
    it every edge pools into one bucket and the result describes nothing
    (`issues/060`).

    Not incremental. Fan-out is a structural property of the schema and moves
    slowly, so recomputing it on the maintenance cadence is enough; making it
    incremental would mean maintaining a distribution under every write, which
    is far more machinery than the thing is worth.
    """
    t_edge = f"{space_id}_edge"
    t_quad = f"{space_id}_rdf_quad"
    t_fan = f"{space_id}_edge_fanout"

    has_type = await conn.fetchval(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = $1 AND column_name = 'edge_type_uuid'", t_edge)
    if not has_type:
        logger.info("compute_edge_fanout(%s): edge_type_uuid absent, skipping "
                    "— every edge would pool into one bucket", space_id)
        return 0

    written = 0
    for direction, group_col, count_col in (
        ("forward", "source_node_uuid", "dest_node_uuid"),
        ("backward", "dest_node_uuid", "source_node_uuid"),
    ):
        # `typed` attaches the relation type where there is one. LEFT JOIN, so a
        # containment edge keeps its row and lands in the NO_RELATION bucket
        # rather than vanishing.
        rows = await conn.fetch(f"""
            WITH typed AS (
                SELECT e.edge_type_uuid,
                       COALESCE(rt.object_uuid, $1) AS relation_type_uuid,
                       e.{group_col} AS node,
                       e.{count_col} AS other
                FROM {t_edge} e
                LEFT JOIN {t_quad} rt
                       ON rt.subject_uuid = e.edge_uuid
                      AND rt.predicate_uuid = $2
                      AND rt.context_uuid = e.context_uuid
            ),
            per_node AS (
                SELECT edge_type_uuid, relation_type_uuid, node,
                       count(*) AS n
                FROM typed
                GROUP BY edge_type_uuid, relation_type_uuid, node
            )
            SELECT edge_type_uuid, relation_type_uuid,
                   avg(n)::double precision AS avg_fanout,
                   percentile_disc(0.99) WITHIN GROUP (ORDER BY n) AS p99_fanout,
                   max(n) AS max_fanout,
                   count(*) AS sample_nodes
            FROM per_node
            GROUP BY edge_type_uuid, relation_type_uuid
        """, NO_RELATION, _REL_TYPE_UUID)

        for r in rows:
            await conn.execute(f"""
                INSERT INTO {t_fan} (edge_type_uuid, relation_type_uuid,
                                     direction, avg_fanout, p99_fanout,
                                     max_fanout, sample_nodes, updated_time)
                VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
                ON CONFLICT (edge_type_uuid, relation_type_uuid, direction)
                DO UPDATE SET avg_fanout = EXCLUDED.avg_fanout,
                              p99_fanout = EXCLUDED.p99_fanout,
                              max_fanout = EXCLUDED.max_fanout,
                              sample_nodes = EXCLUDED.sample_nodes,
                              updated_time = NOW()
            """, r["edge_type_uuid"], r["relation_type_uuid"], direction,
                 float(r["avg_fanout"] or 0), int(r["p99_fanout"] or 0),
                 int(r["max_fanout"] or 0), int(r["sample_nodes"] or 0))
            written += 1

    # Buckets whose edges are all gone should not linger claiming a fan-out.
    await conn.execute(f"""
        DELETE FROM {t_fan} f WHERE NOT EXISTS (
            SELECT 1 FROM {t_edge} e WHERE e.edge_type_uuid = f.edge_type_uuid)
    """)

    logger.info("compute_edge_fanout(%s): %d bucket(s)", space_id, written)
    return written


# A hop whose tail exceeds this is not safe to walk: the cost of being wrong is
# a timeout, not a slightly worse plan, so the bound is deliberately tight. Set
# above the containment tree (1) and the observed friend-graph tail (6) but far
# below a hub (886 on worksFor, 1,342 on wordnet slot values).
MAX_SAFE_HOP_TAIL = 16

# Amplification a whole path may reach before the walk stops being worth it.
# Three containment hops at the observed forward fan-out of ~4 land at ~71x,
# which is the case issues/059 measures as 700ms backward against >200s forward.
MAX_SAFE_PATH_AMPLIFICATION = 100


def assess_traversal(fanout: Dict[tuple, dict], hops, direction: str,
                     path_bound: bool = True) -> dict:
    """Is walking `hops` in `direction` bounded, and by how much?

    `hops` is an ordered list of `(edge_type_uuid, relation_type_uuid)`, the
    path a traversal follows. Returns:

        {"safe": bool, "amplification": float, "worst_hop": ..., "reason": str}

    Uses the TAIL (p99, falling back to max) rather than the average, because
    the distributions here are skewed enough that the mean is not the typical
    cost of being wrong: `worksFor` backward averages 39 with a p99 of 468, and
    wordnet's slot-value in-degree averages 5.20 against a maximum of 1,342. A
    plan chosen on the mean is off by that ratio, and off means a timeout.

    A hop with NO recorded fan-out is treated as unsafe rather than as 1. The
    table is recomputed on the maintenance cadence, so a missing entry means
    "not measured", and assuming the favourable value for unmeasured data is how
    a rewrite ships looking correct and behaves badly on the shapes nobody
    profiled.

    `path_bound=False` drops the whole-path amplification check and keeps only
    the per-hop tail. Use it when the consumer SHORT-CIRCUITS — an
    `EXISTS (SELECT 1 ...)` probe stops at the first matching row, so fan-out
    changes how quickly a match is found, not how many rows are produced, and
    compounding it describes work that is never done. Getting this wrong was
    measured at 640x: a two-criteria KGQuery declined at "path amplification
    10000 exceeds 100" and fell back to a blocking sort, 25 s against 39 ms.

    The per-hop tail still applies in both modes, and is the check that earns
    its keep: one hop that genuinely explodes (`worksFor` backward, p99 468)
    means the probe may scan a great deal before finding its first match, or
    never find one.
    """
    amplification = 1.0
    worst = None
    worst_tail = 0

    for hop in hops:
        edge_type, relation_type = hop
        stats = fanout.get((edge_type, relation_type or NO_RELATION, direction))
        if stats is None:
            return {"safe": False, "amplification": float("inf"),
                    "worst_hop": hop,
                    "reason": f"no fan-out recorded for {hop} {direction}"}

        tail = stats.get("p99") or stats.get("max") or 0
        if tail > worst_tail:
            worst_tail, worst = tail, hop
        if tail > MAX_SAFE_HOP_TAIL:
            return {"safe": False, "amplification": float("inf"),
                    "worst_hop": hop,
                    "reason": (f"hop tail {tail} exceeds {MAX_SAFE_HOP_TAIL} "
                               f"— this direction fans out")}
        # Compound on the MEAN, not the tail. Multiplying p99 at every hop
        # assumes they all hit their tail at once, whose probability is the
        # product of the individual tail probabilities — vanishing over a chain.
        # Over four hops of tail 10 it reports 10,000 and declines everything.
        #
        # Measured cost of getting this wrong: a two-criteria KGQuery
        # (LeadStatus eq + MQLRating gte) was declined at "path amplification
        # 10000 exceeds 100" and fell back to a blocking sort — 25 s against
        # 39 ms once two-phase was allowed to engage. 640x, on an ordinary shape.
        #
        # The tail still guards the case it was built for, one hop above: a
        # single hop that genuinely explodes (`worksFor` backward, p99 468) is
        # refused outright regardless of what the means multiply to. That is the
        # asymmetry worth keeping — one bad hop is a real risk, four mediocre
        # hops all misbehaving together is not.
        avg = stats.get("avg")
        amplification *= max(1.0, float(avg if avg is not None else tail))

    if path_bound and amplification > MAX_SAFE_PATH_AMPLIFICATION:
        return {"safe": False, "amplification": amplification,
                "worst_hop": worst,
                "reason": (f"path amplification {amplification:.0f} exceeds "
                           f"{MAX_SAFE_PATH_AMPLIFICATION}")}
    return {"safe": True, "amplification": amplification, "worst_hop": worst,
            "reason": "bounded"}


def choose_direction(fanout: Dict[tuple, dict], hops) -> dict:
    """Which direction to walk a traversal, if either is safe.

    Returns the assessment of the chosen direction with a `direction` key, or
    `direction=None` when neither is bounded — which is the honest answer for a
    relation graph, where an entity may be source or destination in many and
    NEITHER direction is safe. A rewrite that assumed one always was would be
    wrong on exactly that shape, and the tree-only fixtures could not have shown
    it (`issues/061`).

    Prefers backward when both qualify: the constrained end of a negation is
    normally the far end, so walking back to the anchor visits the selective set
    once rather than probing from every anchor row.
    """
    back = assess_traversal(fanout, hops, "backward")
    if back["safe"]:
        return {**back, "direction": "backward"}
    fwd = assess_traversal(fanout, hops, "forward")
    if fwd["safe"]:
        return {**fwd, "direction": "forward"}
    return {"direction": None, "safe": False,
            "amplification": min(back["amplification"], fwd["amplification"]),
            "worst_hop": back["worst_hop"],
            "reason": f"neither direction bounded (backward: {back['reason']})"}


_VITALTYPE_URI = "http://vital.ai/ontology/vital-core#vitaltype"
_VITALTYPE_UUID = uuid.uuid5(_VITALGRAPH_NS, f"{_VITALTYPE_URI}\x00U")


def extract_traversal(plan, aliases) -> list:
    """The ordered edge hops a BGP walks, as `(edge_type_uuid, relation_type)`.

    Reads the edge tables out of a BGP and pairs each with the constant its
    `vitaltype` constraint names — that is where the edge type lives after
    `rewrite_edge_table`, since the edge table itself carries no type in the
    join (it is a separate quad, aliased and constrained alongside).

    Returns `[]` when the shape is not a plain edge chain, which is the
    conservative answer: an empty traversal makes any caller decline rather than
    reason about a shape it did not recognise.

    Deliberately does NOT infer direction. Direction is a property of how the
    caller intends to walk the chain, not of the plan, and conflating the two is
    how a rewrite ends up assuming the direction it happens to have emitted.
    """
    import re

    tables = getattr(plan, "tables", None) or []
    edges = [t for t in tables if getattr(t, "kind", None) == "edge"]
    if not edges:
        return []

    # constant column -> resolved uuid, so a __CONST_ token can be read back
    const_uuid = {}
    for col, resolved in (getattr(aliases, "resolved_constants", None) or {}).items():
        try:
            const_uuid[col] = uuid.UUID(str(resolved))
        except Exception:
            continue

    # alias -> {predicate_const, object_const} from the tagged constraints
    by_alias: dict = {}
    for owner, sql in (getattr(plan, "tagged_constraints", None) or []):
        m = re.search(r"\.(predicate_uuid|object_uuid|subject_uuid)\s*=\s*"
                      r"__CONST_(\w+)__", sql)
        if m:
            by_alias.setdefault(owner, {})[m.group(1)] = m.group(2)
        m2 = re.search(r"(\w+)\.edge_uuid\s*=\s*(\w+)\.subject_uuid", sql)
        if m2:
            by_alias.setdefault(m2.group(1), {})["type_via"] = m2.group(2)

    hops = []
    for e in edges:
        info = by_alias.get(e.alias, {})
        type_alias = info.get("type_via")
        if not type_alias:
            return []          # no vitaltype join: not a shape we recognise
        tinfo = by_alias.get(type_alias, {})
        pred_const = tinfo.get("predicate_uuid")
        obj_const = tinfo.get("object_uuid")
        if not pred_const or not obj_const:
            return []
        if const_uuid.get(pred_const) != _VITALTYPE_UUID:
            return []          # constrained on something other than the type
        edge_type = const_uuid.get(obj_const)
        if edge_type is None:
            return []          # unresolved constant — do not guess
        hops.append((edge_type, None))
    return hops


async def load_edge_fanout(conn, space_id: str) -> Dict[tuple, dict]:
    """Read the table into `{(edge_type, relation_type, direction): stats}`.

    For a planner-side caller. Returns an empty dict rather than raising when
    the table does not exist yet, so a space that predates it simply has no
    fan-out information rather than failing every query.
    """
    t_fan = f"{space_id}_edge_fanout"
    try:
        rows = await conn.fetch(
            f"SELECT edge_type_uuid, relation_type_uuid, direction, "
            f"avg_fanout, p99_fanout, max_fanout, sample_nodes FROM {t_fan}")
    except Exception:
        return {}
    return {
        (r["edge_type_uuid"], r["relation_type_uuid"], r["direction"]): {
            "avg": r["avg_fanout"], "p99": r["p99_fanout"],
            "max": r["max_fanout"], "nodes": r["sample_nodes"],
        }
        for r in rows
    }
