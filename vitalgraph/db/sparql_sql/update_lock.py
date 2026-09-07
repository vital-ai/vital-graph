"""Serialise a WHERE-bound SPARQL update against entity and frame writes.

`issues/174` item 5. A raw SPARQL update can modify the same subjects an entity
upsert or an entity-graph delete is replacing. Those paths hold an advisory lock
on the GROUPING — the entity, or the frame for a standalone one — so an update
that does not take the same lock is not excluded from them, and the two
interleave: the update's write is silently overwritten, or its DELETE misses a
value the entity write has already replaced and its INSERT adds a second one.

It cannot name its subjects from the AST — `_concrete_subjects_from_update_ops`
says so and is right about the AST. But the emitted SQL materialises the WHERE
before it writes anything, so the subjects exist at RUNTIME. This runs that
materialisation early, on the caller's connection, purely to find out what to
lock.

WHY A SEPARATE PROBE TABLE, rather than splitting the generated SQL: the emitter
joins its statements into one string with a separator a literal could contain, so
splitting the blob back apart in the caller is unsafe. Materialising into a
probe table of our own leaves the generated SQL untouched and running exactly as
before — it creates its own `_upd_bindings` afterwards, under the locks this
already took.

THE LOOP IS NOT OPTIONAL. Re-materialising under the locks can reveal subjects
the previous pass did not see, in groupings not yet held, so one pass is not a
fixed point. Advisory locks are transaction-scoped and accumulate, so each pass
blocks strictly more concurrent writers than the last, which is why this
converges instead of spinning. Uncontended — nearly always — the second pass
merely confirms the set is stable.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Set

from .entity_lock import lock_entities
from .sparql_sql_space_impl import _generate_term_uuid

logger = logging.getLogger(__name__)

HAS_KG_GRAPH_URI = "http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI"

# Passes before giving up. Two is the expected cost — derive, lock, confirm — so
# a third means the binding set is still moving under an accumulating lock set.
MAX_PASSES = 3

_PROBE = "_vg_lock_probe"


async def _subjects_for_plan(conn, plan) -> Set[str]:
    """Subject URIs this update will touch, from a freshly materialised probe."""
    subjects: Set[str] = set(plan.subject_constants or [])
    cols = list(plan.subject_columns or [])
    if cols:
        await conn.execute(f"DROP TABLE IF EXISTS {_PROBE}")
        await conn.execute(
            f"CREATE TEMP TABLE {_PROBE} ON COMMIT DROP AS {plan.where_sql}")
        # Quoted because these are SPARQL variable names mapped to columns, and
        # the mapping does not promise a lower-case identifier.
        sel = ", ".join(f'"{c}"' for c in cols)
        for row in await conn.fetch(f"SELECT DISTINCT {sel} FROM {_PROBE}"):
            for v in row:
                if v:
                    subjects.add(str(v))
        await conn.execute(f"DROP TABLE IF EXISTS {_PROBE}")
    return subjects


async def _groupings_for(conn, space_id: str, subjects: Iterable[str],
                         changeset: Optional[Dict[str, str]] = None) -> Set[str]:
    """The grouping each subject belongs to — what must actually be locked.

    Precedence, and the order matters:

    1. **The change set.** A subject being CREATED has no row to look up, so a
       `hasKGGraphURI` triple the update itself writes is the only place its
       grouping exists. This is the ONLY reason the change set comes first —
       frames are never reparented, so it is not about an update moving an
       existing subject to a different owner.
    2. **The store.** An existing subject carries `hasKGGraphURI` pointing at its
       entity — slots and frames both do — so this resolves a change set that
       mentions only a slot value quad and nothing about the entity enclosing it.
       THIS IS THE STEP THAT IS EASY TO OMIT: every test written from the change
       set alone passes without it, and the production shape it exists for is a
       single slot value changing inside an entity graph.
    3. **The subject itself.** A standalone frame, or a subject in general RDF
       that no entity write will touch.

    `hasKGGraphURI` and not `hasFrameGraphURI` where a subject carries both:
    entity upsert and entity-graph delete hold the ENTITY key, so that is the key
    that has to collide. A frame-keyed lock would be correct in isolation and
    useless against the writers it must exclude.
    """
    subjects = list(subjects)
    if not subjects:
        return set()
    changeset = changeset or {}
    out: Set[str] = set()
    to_lookup = [s for s in subjects if s not in changeset]
    out.update(changeset[s] for s in subjects if s in changeset)

    resolved: Dict[str, str] = {}
    if to_lookup:
        uuid_to_uri = {_generate_term_uuid(s, "U"): s for s in to_lookup}
        rows = await conn.fetch(
            f"SELECT q.subject_uuid, t.term_text"
            f"  FROM {space_id}_rdf_quad q"
            f"  JOIN {space_id}_term t ON t.term_uuid = q.object_uuid"
            f" WHERE q.predicate_uuid = $1 AND q.subject_uuid = ANY($2::uuid[])",
            _generate_term_uuid(HAS_KG_GRAPH_URI, "U"), list(uuid_to_uri))
        for r in rows:
            uri = uuid_to_uri.get(r["subject_uuid"])
            if uri:
                resolved[uri] = r["term_text"]

    for s in to_lookup:
        out.add(resolved.get(s, s))
    return out


async def acquire_update_locks(conn, space_id: str, plans: List[Any]) -> List[str]:
    """Take the grouping locks a set of WHERE-bound updates needs. Returns them.

    Must be called INSIDE the transaction that will run the update, on the same
    connection: `pg_advisory_xact_lock` releases at commit, so a lock taken on
    any other connection protects nothing.

    Returns the grouping URIs locked, for logging. An empty list means the
    update named no subjects — nothing to serialise against.
    """
    if not plans:
        return []
    held: Set[str] = set()
    for attempt in range(1, MAX_PASSES + 1):
        found: Set[str] = set()
        for plan in plans:
            subjects = await _subjects_for_plan(conn, plan)
            found |= await _groupings_for(
                conn, space_id, subjects,
                getattr(plan, "changeset_groupings", None))
        new = found - held
        if not new:
            return sorted(held)
        # Sorted inside lock_entities, so two updates taking overlapping sets in
        # different orders queue rather than deadlock.
        await lock_entities(conn, sorted(new))
        held |= new
        # Re-derive the GROUPING as well as the subjects on each pass, not just
        # the subjects. Frames are never reparented, so a frame's grouping does
        # not move under us — but this path also resolves subjects the KG layer
        # does not own, where nothing promises that, and re-deriving costs
        # nothing because the resolution query runs per pass anyway.
    logger.warning(
        "update lock set still growing after %d passes for space=%s (%d groupings "
        "held); proceeding. The WHERE clause is matching new subjects faster than "
        "locks are being taken, which is worth understanding rather than "
        "retrying indefinitely (issues/174).", MAX_PASSES, space_id, len(held))
    return sorted(held)
