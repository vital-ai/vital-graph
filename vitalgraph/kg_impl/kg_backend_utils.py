"""
KG Backend Abstraction Layer

This module provides a unified interface for KG operations across space backends.
It abstracts backend-specific implementation details and provides a consistent API
for KG endpoint implementations.

There is ONE adapter today (`SparqlSQLBackendAdapter`). The interface is kept
because it is what the kg_impl processors are written against, not because a
second backend is expected — `issues/241`.
"""

import asyncio
import contextlib
import logging
import os
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple, Union, cast
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# VitalSigns imports
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame

# Model imports
from ..model.kgentities_model import EntityCreateResponse, EntityUpdateResponse

# Graph retrieval utilities
from .kg_graph_retrieval_utils import GraphObjectRetriever
from ..db.connection_config import require


# ---------------------------------------------------------------------------
# Fast default-listing helpers (shared by KGEntities and the generic
# list_objects path for KGRelations / KGTypes).
#
# These bypass the SPARQL pipeline for the *plain default* listing: order by
# the internal ``subject_uuid`` (index-friendly) and resolve text only for the
# page, avoiding the ``ORDER BY ?s`` full-URI resolution that dominates cold
# renders on large spaces.  They key on whatever type predicate the caller's
# SPARQL uses (``vitaltype`` for entities, ``rdf:type`` for the generic path)
# with the exact same type-URI set, and use COUNT(DISTINCT)/SELECT DISTINCT so
# the result equals the SPARQL ``COUNT(DISTINCT ?x)`` regardless of multi-typing.
# ---------------------------------------------------------------------------

RDF_TYPE_URI = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
VITALTYPE_URI = 'http://vital.ai/ontology/vital-core#vitaltype'
HAS_FRAME_GRAPH_URI = 'http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI'
HAS_KG_GRAPH_URI = 'http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI'
HAS_EDGE_SOURCE = 'http://vital.ai/ontology/vital-core#hasEdgeSource'
HAS_EDGE_DESTINATION = 'http://vital.ai/ontology/vital-core#hasEdgeDestination'
EDGE_HAS_KG_FRAME = 'http://vital.ai/ontology/haley-ai-kg#Edge_hasKGFrame'
EDGE_HAS_ENTITY_KG_FRAME = 'http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame'


def graph_is_uri(graph_id: Optional[str]) -> bool:
    """True if graph_id is an absolute IRI whose context UUID we can derive.

    Accepts ``http(s)://…`` and ``urn:…``; rejects empty and the literal
    ``"default"`` (a bare word with no scheme → ambiguous context).
    """
    return bool(graph_id) and graph_id != "default" and ":" in graph_id


def _resolve_space_impl(backend):
    """Return the SparqlSQLSpaceImpl from either the impl itself or an adapter.

    Callers pass whatever `self.backend` they hold — sometimes the space impl
    directly (KGEntities/KGFrames), sometimes a backend adapter wrapping it
    (the generic list_objects path). The direct-SQL helpers need the impl's
    `.schema` and `.db_impl`; return None for non-sparql_sql backends so the
    caller falls back to SPARQL.
    """
    if hasattr(backend, 'schema') and hasattr(backend, 'db_impl'):
        return backend
    inner = getattr(backend, 'backend', None)
    if inner is not None and hasattr(inner, 'schema') and hasattr(inner, 'db_impl'):
        return inner
    return None


async def fast_typed_subject_count(backend, space_id: str, graph_id: str,
                                   type_predicate_uri: str,
                                   type_uris) -> Optional[int]:
    """`COUNT(DISTINCT subject_uuid)` for subjects of the given type(s), or None."""
    if not graph_is_uri(graph_id):
        return None
    impl = _resolve_space_impl(backend)
    if impl is None:
        return None
    try:
        from ..db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
        t = impl.schema.get_table_names(space_id)
        p_uuid = _generate_term_uuid(type_predicate_uri, 'U')
        obj_uuids = [_generate_term_uuid(u, 'U') for u in type_uris]
        g_uuid = _generate_term_uuid(graph_id, 'U')
        async with impl.db_impl.connection_pool.acquire() as conn:
            n = await conn.fetchval(
                f"SELECT COUNT(DISTINCT subject_uuid) FROM {t['rdf_quad']} "
                f"WHERE predicate_uuid = $1 AND object_uuid = ANY($2::uuid[]) "
                f"AND context_uuid = $3",
                p_uuid, obj_uuids, g_uuid,
            )
        return int(n or 0)
    except Exception:
        logging.getLogger(__name__).warning(
            "fast_typed_subject_count failed, caller will fall back", exc_info=True)
        return None


async def fast_typed_subject_page(backend, space_id: str, graph_id: str,
                                  type_predicate_uri: str, type_uris,
                                  page_size: int, offset: int) -> Optional[list]:
    """Ordered (`subject_uuid`) page of subject URIs of the given type(s), or None."""
    if not graph_is_uri(graph_id):
        return None
    impl = _resolve_space_impl(backend)
    if impl is None:
        return None
    try:
        from ..db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
        t = impl.schema.get_table_names(space_id)
        p_uuid = _generate_term_uuid(type_predicate_uri, 'U')
        obj_uuids = [_generate_term_uuid(u, 'U') for u in type_uris]
        g_uuid = _generate_term_uuid(graph_id, 'U')
        async with impl.db_impl.connection_pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT tt.term_text AS uri "
                f"FROM (SELECT DISTINCT subject_uuid FROM {t['rdf_quad']} "
                f"      WHERE predicate_uuid = $1 "
                f"      AND object_uuid = ANY($2::uuid[]) "
                f"      AND context_uuid = $3 "
                f"      ORDER BY subject_uuid LIMIT $4 OFFSET $5) sub "
                f"JOIN {t['term']} tt ON tt.term_uuid = sub.subject_uuid "
                f"ORDER BY sub.subject_uuid",
                p_uuid, obj_uuids, g_uuid, page_size, offset,
            )
        return [r['uri'] for r in rows]
    except Exception:
        logging.getLogger(__name__).warning(
            "fast_typed_subject_page failed, caller will fall back", exc_info=True)
        return None


# `issues/175` class 2. Defined in the db layer, which kg_impl already
# depends on; the reverse would invert the layering.
from ..db.sparql_sql.conn_scope import write_conn as _write_conn
from ..db.sparql_sql.entity_lock import EntityLockTimeout
from ..utils.exception_detail import describe_exception
from ..utils.background import BackgroundTasks
# For the re-raises below. Imports nothing from vitalgraph, so this cannot cycle.
from .refusals import RequestRefused

# Post-write aux-table ANALYZE, scheduled per space (`issues/253`).
_AUX_ANALYZE_TASKS = BackgroundTasks("aux-table ANALYZE")


# How long one subject-level write may take, end to end (`issues/253`).
#
# WHY A WRITE NEEDS ITS OWN BOUND. Every other fence covers a different thing and
# together they leave a hole: `statement_timeout` bounds each STATEMENT (60 s on
# production), `lock_timeout` each LOCK WAIT (10 s), and
# `idle_in_transaction_session_timeout` bounds IDLENESS — by destroying the
# connection, 60 s after the transaction went quiet, which is how five writes
# were lost on 2026-09-30. Nothing bounded the write as a whole, so a write that
# parked between statements for any reason ended as a loss the caller could not
# see: the connection was killed, the rollback failed, and the error named the
# rollback rather than the cause.
#
# 25 s, not lower: the measured write is 0.273 s median and 1.1 s at p99, and the
# worst legitimate case seen was ~11 s, so this fences the pathological case and
# not a slow-but-working one. And not higher: the caller's own read timeout is
# 30 s, and a fence above that is one only the client ever reaches — which is the
# situation it replaces. 0 disables it.
_DEFAULT_WRITE_DEADLINE_S = 25.0


def _write_deadline_s() -> float:
    raw = os.environ.get("VITALGRAPH_WRITE_DEADLINE_S")
    if raw is None:
        return _DEFAULT_WRITE_DEADLINE_S
    try:
        return max(0.0, float(raw))
    except ValueError:
        logger.warning("VITALGRAPH_WRITE_DEADLINE_S=%r is not a number; using %.1fs",
                       raw, _DEFAULT_WRITE_DEADLINE_S)
        return _DEFAULT_WRITE_DEADLINE_S


def _stamp_keys(space_id: str, graph_id: str, subject_uri: str):
    """The (table names, subject, predicate, graph) uuids the stamp lives under."""
    from ..db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
    from ..db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
    from .kg_server_properties import MODIFICATION_TIME_URI

    return (SparqlSQLSchema.get_table_names(space_id),
            _generate_term_uuid(subject_uri, 'U'),
            _generate_term_uuid(MODIFICATION_TIME_URI, 'U'),
            _generate_term_uuid(graph_id, 'U'))


async def _compare_stamp(conn, space_id: str, graph_id: str,
                         subject_uri: str,
                         if_unmodified_since: Optional[str]) -> None:
    """Refuse the write if *subject_uri* has moved since the caller read it.

    SUBJECT, not entity. The entity-frame routes key this on the owning entity,
    which is what their callers hold. The standalone-frame routes have no owning
    entity at all — `_create_frames` says so in its own docstring — so they key it
    on the FRAME. The mechanism never cared; only the name did (`issues/253`).

    Direct SQL rather than a SPARQL update, for two reasons: it has to run on the
    CALLER's connection inside the open transaction, and the SPARQL path
    (`touch_entity_modification_time`) issues its own statement outside any
    transaction of ours, which is the window this closes.

    The comparison is on the string form, which is what the caller was given. A
    datetime comparison would be more forgiving of formatting, and forgiveness is
    wrong here: if the stored text differs from what the caller read, something
    rewrote it, and refusing is the safe answer.
    """
    t, s_uuid, p_uuid, g_uuid = _stamp_keys(space_id, graph_id, subject_uri)

    # LIMIT 2, not LIMIT 1, and no `ORDER BY` needed because two rows is already
    # the answer. `LIMIT 1` without an order made this nondeterministic the
    # moment the single-valued invariant broke — the guard would pass or fail on
    # whichever row the scan reached first. `issues/173` IS that invariant
    # breaking, which is why the write side replaces rather than adds; this is
    # the read side refusing to guess.
    rows = await conn.fetch(
        f"SELECT tt.term_text AS stamp FROM {t['rdf_quad']} q "
        f"JOIN {t['term']} tt ON tt.term_uuid = q.object_uuid "
        f"WHERE q.subject_uuid = $1 AND q.predicate_uuid = $2 "
        f"AND q.context_uuid = $3 LIMIT 2",
        s_uuid, p_uuid, g_uuid)
    if len(rows) > 1:
        raise AmbiguousStamp(subject_uri, [r["stamp"] for r in rows])
    actual = rows[0]["stamp"] if rows else None

    if if_unmodified_since is not None and actual != if_unmodified_since:
        raise StaleWrite(subject_uri, if_unmodified_since, actual)


async def _stamp_subject(conn, space_id: str, graph_id: str,
                         subject_uri: str) -> str:
    """Record that *subject_uri* was just written. Returns the stamp.

    SEPARATE FROM THE COMPARE, and it has to run AFTER the write (`issues/253`).
    The stamped subject may itself be among the subjects the write is replacing —
    which is exactly the standalone-frame case, where the guarded frame is also
    the thing being rewritten. Stamping before the subject-level DELETE put the
    stamp in front of the statement that removes it, so the frame came out of a
    successful write carrying no stamp and the caller had nothing to send next
    time. Stamping afterwards also makes the value mean "this write finished",
    which is what the next writer compares against.
    """
    from datetime import datetime, timezone

    t, s_uuid, p_uuid, g_uuid = _stamp_keys(space_id, graph_id, subject_uri)
    now = datetime.now(timezone.utc).isoformat()
    # Replace rather than add: the property is single-valued, and `issues/173`
    # is what happens when a write leaves two of them behind.
    await conn.execute(
        f"DELETE FROM {t['rdf_quad']} WHERE subject_uuid = $1 "
        f"AND predicate_uuid = $2 AND context_uuid = $3",
        s_uuid, p_uuid, g_uuid)
    await _insert_stamp(conn, t, s_uuid, p_uuid, g_uuid, now,
                        subject_uri=subject_uri)
    return now


async def _delete_subjects_synced(conn, space_id: str, t, del_uuids,
                                  g_uuid) -> Tuple[int, Tuple[float, ...]]:
    """Delete every quad of `del_uuids` in one graph, keeping the aux tables in step.

    ONE implementation for the subject-level writes and the frame deletes
    (`issues/256`): four delete paths that each did this their own way is how
    they drifted apart. The caller owns the transaction and the lock.

    Returns the quads deleted and how long each step took (frame_slot, edge,
    entity_slot_sort, delete), which the write path logs.
    """
    import time as _time
    from ..db.sparql_sql.sync_frame_slot_table import sync_frame_slot_before_delete
    from ..db.sparql_sql.sync_edge_table import sync_edge_table_before_delete
    from ..db.sparql_sql.sync_entity_slot_sort import sync_entity_slot_sort_before_delete
    from ..db.sparql_sql.sync_entity_prop_sort import sync_entity_prop_sort_after_change
    from ..db.sparql_sql.sync_frame_prop_sort import sync_frame_prop_sort_after_change

    # TIMED INDIVIDUALLY because the aggregate was misleading: `FRAME_CREATE
    # step2` is 7.52s mean / 22.8s max on production for FOURTEEN subjects, of
    # which the insert is ~0.3s, and the caller's log attributed the whole thing
    # to "update_subjects_graph" with no way to tell which of these statements
    # owned it. Each one scans for the affected quads before the DELETE, so any
    # of them could.
    _s0 = _time.monotonic()
    await sync_frame_slot_before_delete(conn, space_id, del_uuids, context_uuid=g_uuid)
    _s1 = _time.monotonic()
    await sync_edge_table_before_delete(conn, space_id, del_uuids, context_uuid=g_uuid)
    _s2 = _time.monotonic()
    # `entity_slot_sort` BEFORE the delete (`issues/194`): its rows are reached
    # through the edge table the delete invalidates, so afterwards they cannot be
    # found — and a stale row makes a sort order by a value that is gone.
    await sync_entity_slot_sort_before_delete(conn, space_id, del_uuids, context_uuid=g_uuid)
    _s3 = _time.monotonic()
    result = await conn.execute(
        f"DELETE FROM {t['rdf_quad']} "
        f"WHERE subject_uuid = ANY($1) AND context_uuid = $2",
        del_uuids, g_uuid)
    _s4 = _time.monotonic()
    # AND THE PROP TABLES AFTER IT, because a delete there is a RECOMPUTE against
    # the survivors rather than a row drop: they store the MIN of a multi-valued
    # property, and for a subject deleted outright this empties its rows. Before
    # the delete it would re-derive the value being removed.
    await sync_entity_prop_sort_after_change(conn, space_id, del_uuids, context_uuid=g_uuid)
    await sync_frame_prop_sort_after_change(conn, space_id, del_uuids, context_uuid=g_uuid)
    deleted = int(result.split()[-1]) if result else 0
    return deleted, (_s1 - _s0, _s2 - _s1, _s3 - _s2, _s4 - _s3)


async def _insert_stamp(conn, t, s_uuid, p_uuid, g_uuid, value: str,
                        subject_uri: Optional[str] = None) -> None:
    """Insert the timestamp term and its quad, all idempotently.

    THE PREDICATE TERM TOO, and leaving it out wrote a quad that existed and
    could not be read (`issues/253`). A quad references terms by uuid, and every
    read joins the term table to get the text back — so a quad whose predicate
    has no term row is dropped by the join. Silently: the row is there, the write
    reports success, and the value is invisible to the API, to SPARQL and to the
    caller that is about to send it back as `if_unmodified_since`.

    It never showed on the ENTITY path because an entity already carries this
    predicate from the ordinary server-property stamping, so the term row was
    always already there. A standalone FRAME in a fresh space is the first
    subject to be stamped without one, and the frame came back with no stamp at
    all while the quad sat in the table.
    """
    from ..db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
    from .kg_server_properties import MODIFICATION_TIME_URI
    XSD_DT = "http://www.w3.org/2001/XMLSchema#dateTime"

    # The predicate, and the subject when it was given: a stamped subject is not
    # always one this write inserted — the slot routes stamp the FRAME while
    # writing only its slots.
    _terms = [(p_uuid, MODIFICATION_TIME_URI)]
    if subject_uri is not None:
        _terms.append((s_uuid, subject_uri))
    for _uuid, _text in _terms:
        await conn.execute(
            f"INSERT INTO {t['term']} (term_uuid, term_text, term_type, lang, datatype_id) "
            f"VALUES ($1, $2, 'U', NULL, NULL) ON CONFLICT DO NOTHING",
            _uuid, _text)
    dt_id = await conn.fetchval(
        f"INSERT INTO {t['datatype']} (datatype_uri) VALUES ($1) "
        f"ON CONFLICT (datatype_uri) DO UPDATE SET datatype_uri = EXCLUDED.datatype_uri "
        f"RETURNING datatype_id", XSD_DT)
    o_uuid = _generate_term_uuid(value, 'L', None, dt_id)
    await conn.execute(
        f"INSERT INTO {t['term']} (term_uuid, term_text, term_type, lang, datatype_id) "
        f"VALUES ($1, $2, 'L', NULL, $3) ON CONFLICT DO NOTHING",
        o_uuid, value, dt_id)
    await conn.execute(
        f"INSERT INTO {t['rdf_quad']} "
        f"(subject_uuid, predicate_uuid, object_uuid, context_uuid) "
        f"VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
        s_uuid, p_uuid, o_uuid, g_uuid)


class StaleWrite(Exception):
    """The caller's write was refused because the entity moved under it.

    THE LOST UPDATE (`issues/253`), which no amount of locking prevents. The
    entity lock makes one WRITE atomic; the race spans a caller's READ, its merge
    and its write, issued as three separate requests. Production reported a
    slower save overwriting a newer one with every request reporting success, and
    an autosave that sent 138 writes for one lead in four minutes is exactly the
    shape that loses them.

    So the caller may pass the `hasObjectModificationDateTime` it read, and the
    write is refused if the stored value has moved. Compared INSIDE the write
    transaction and under the entity lock, because a check anywhere else is a
    race of its own: the endpoint already stamped this property AFTER the write
    and OUTSIDE the lock, which leaves a window where the next writer reads a
    value the previous writer has not published yet.
    """

    def __init__(self, subject_uri: str, expected: str, actual: Optional[str]):
        self.subject_uri = subject_uri
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"{subject_uri} changed since it was read: expected "
            f"modification time {expected!r}, found {actual!r}")


class GuardUnsatisfiable(Exception):
    """The conditional write could not be DECIDED, so nothing was written.

    `issues/253`. Base for the two ways that happens — no subject to compare
    against, and more than one stored stamp. Shared so an endpoint widens one
    `except` tuple instead of growing a handler per case, and so the next such
    case inherits the mapping.

    **STORE_FAILED in an HTTP 200, not a 500.** This codebase answers every
    DOMAIN outcome in the body and reserves non-200 for the service itself
    failing (`model/result_status.py`: `STORE_FAILED` is "write failed for a
    describable data reason"; `ERROR` is "server-level internal error"). A
    wiring error and a violated data invariant are both describable data
    reasons. An earlier draft of these docstrings asserted the opposite three
    times over, and a reviewer reading them recommended adding a bare `raise`
    that would have produced exactly the 500 the convention forbids — which is
    the best evidence that what a comment claims about status codes matters as
    much as the code.

    And the reason has to REACH the body, which is the other half of what
    `STORE_FAILED` promises. These carry the useful text — the subjects, or the
    conflicting stamps — so they are re-raised out of `update_subjects_graph`
    rather than collapsed into its `False`, and the handlers render `str(e)`.
    Collapsing them left the cause log-only while the body said "slot update, N
    subjects".
    """


class UnguardableWrite(GuardUnsatisfiable):
    """`if_unmodified_since` was supplied with no subject to compare it against.

    A wiring error, not a caller error: `update_subjects_graph` derives the
    guarded subject from `guard_subject`, falling back to the first lock URI, and
    with neither it cannot honour the precondition. The previous code SKIPPED the
    comparison in that case and returned success, which is an unconditional write
    reported as a conditional one.

    Every live call site passes `guard_subject`, so reaching this means a new
    call site threaded the parameter without the means to satisfy it. Named in
    the response rather than hidden: see `GuardUnsatisfiable` on why that is a
    200 with `STORE_FAILED` and not a 500. Compare `AmbiguousPrecondition`,
    which is the CALLER's doing and is answered as INVALID_REQUEST.
    """

    def __init__(self, subject_uris):
        self.subject_uris = list(subject_uris or [])
        super().__init__(
            "if_unmodified_since was supplied but the write names no subject to "
            "compare it against (no guard_subject, no lock_uris); refusing "
            f"rather than writing unconditionally. subjects={self.subject_uris[:5]}")


class AmbiguousStamp(GuardUnsatisfiable):
    """The guarded subject carries MORE THAN ONE modification stamp.

    `issues/253`. The read used `LIMIT 1` with no `ORDER BY`, so a violated
    single-valued invariant made the guard nondeterministic: it passed or failed
    depending on which row the scan happened to reach first, which is the worst
    possible behaviour for a check whose entire purpose is to be decisive.

    The invariant is real and `issues/173` is it being broken, which is why the
    stamp WRITE replaces rather than adds. This is the read side defending
    itself. Only CONDITIONAL writes are affected; an unconditional write never
    reads the stamp.

    NOT a CONFLICT and not a 500. A conflict tells the caller to re-read and
    retry, and re-reading cannot resolve duplicate stamps, so that would loop
    forever. A 500 is for the service failing; duplicate stored values are a
    describable data reason, which is `STORE_FAILED` — with both values in the
    message, because that is the only place the next person can see them.
    """

    def __init__(self, subject_uri: str, found):
        self.subject_uri = subject_uri
        self.found = list(found)
        super().__init__(
            f"{subject_uri} carries {len(self.found)} modification stamps, so "
            f"if_unmodified_since cannot be decided: {self.found[:3]}")


class AmbiguousPrecondition(Exception):
    """One `if_unmodified_since` was sent for a write covering several frames.

    `issues/253`. A precondition names ONE version of ONE thing. The
    standalone-frame route accepts any number of frames in a call, and there is
    no honest reading of a single stamp across them: comparing it against one
    and ignoring the rest would report success while leaving the others
    unguarded, which is the failure the caller used the parameter to avoid.

    Refused as INVALID_REQUEST rather than silently narrowed, so a caller that
    batches frames finds out at once instead of believing it is protected.
    """

    def __init__(self, frame_count: int):
        self.frame_count = frame_count
        super().__init__(
            f"if_unmodified_since covers one frame, but this write covers "
            f"{frame_count}. Send the frames one at a time to write "
            f"conditionally, or omit it to keep last-writer-wins.")


class DeleteRefused(RequestRefused):
    """A delete the CALLER asked for that the contract does not allow.

    `issues/256`. Decided inside the delete's transaction, after the lock, so
    what it says was true when the delete would have run: an entity that has
    members (delete it with its graph), a frame that belongs to another entity or
    to none, a frame with children and no `recursive`, an entity's frame named
    on `/kgframes`. Nothing is deleted. INVALID_REQUEST in a 200, with `str(e)`
    as the message, because the request is what has to change.
    """


class EntityAbsent(RequestRefused):
    """The entity a frame is being written onto does not exist (`issues/256`).

    Decided under the entity lock, because a delete takes the same lock: checked
    before it, a create could pass, wait while the entity was deleted, and then
    write frames onto nothing.
    """

    def __init__(self, entity_uri: str, space_id: str):
        self.entity_uri = entity_uri
        super().__init__(f"Target entity {entity_uri} not found in space {space_id}")


class FrameOwnedByEntity(RequestRefused):
    """`/kgframes` named a frame that belongs to an entity (`issues/256`, decision 3).

    That route does not take the entity's lock, so it may not write, replace or
    delete an entity's frame, nor attach a frame under one: one frame has one
    route, one lock and one stamp.
    """


async def refuse_entity_frames(conn, space_id: str, graph_id: str,
                               uris: List[str], what: str = "named") -> None:
    """Raise `FrameOwnedByEntity` if any of *uris* carries a `hasKGGraphURI`.

    For `/kgframes`, inside its transaction and after its lock.
    """
    if not uris:
        return
    from ..db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
    from ..db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
    t = SparqlSQLSchema.get_table_names(space_id)
    rows = await conn.fetch(
        f"SELECT ts.term_text AS frame, tt.term_text AS entity "
        f"FROM {t['rdf_quad']} k "
        f"JOIN {t['term']} ts ON ts.term_uuid = k.subject_uuid "
        f"JOIN {t['term']} tt ON tt.term_uuid = k.object_uuid "
        f"WHERE k.subject_uuid = ANY($1) AND k.predicate_uuid = $2 "
        f"AND k.context_uuid = $3 LIMIT 5",
        [_generate_term_uuid(u, 'U') for u in uris],
        _generate_term_uuid(HAS_KG_GRAPH_URI, 'U'),
        _generate_term_uuid(graph_id, 'U'))
    if rows:
        raise FrameOwnedByEntity(
            f"/kgframes does not take an entity's lock, so the frames of an entity "
            f"are written, replaced and deleted through /kgentities/kgframes; "
            f"nothing was written. The {what} frame(s) belong to an entity: "
            + ", ".join(f"{r['frame']} (entity {r['entity']})" for r in rows))


class FrameNotOwned(RequestRefused):
    """An entity-frame write named a frame of another entity, or of none (`issues/256`)."""


class FrameAbsent(RequestRefused):
    """An `update` named a frame that does not exist (`issues/256` item 3)."""

    status = "not_found"


async def owned_by_entity(conn, space_id: str, graph_id: str, entity_uri: str,
                          frame_uuids) -> set:
    """The subset of *frame_uuids* that belongs to *entity_uri*.

    A root through an `Edge_hasEntityKGFrame` from the entity, or any frame
    through `hasKGGraphURI` = the entity — the rule `validate_frame_ownership`
    applied. Shared by the frame delete and the entity-frame upsert, so the two
    cannot disagree about what an entity owns.

    Starts from the frames and looks each candidate edge up by SUBJECT: as plain
    joins the planner hashed every `Edge_hasEntityKGFrame` in the space instead.
    """
    if not frame_uuids:
        return set()
    from ..db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
    from ..db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
    U = lambda u: _generate_term_uuid(u, 'U')  # noqa: E731
    q = SparqlSQLSchema.get_table_names(space_id)['rdf_quad']
    rows = await conn.fetch(
        f"WITH d AS MATERIALIZED ("
        f" SELECT subject_uuid, object_uuid AS f FROM {q} "
        f" WHERE context_uuid = $4 AND predicate_uuid = $8 "
        f" AND object_uuid = ANY($1::uuid[])) "
        f"SELECT d.f FROM d "
        f"CROSS JOIN LATERAL (SELECT 1 FROM {q} s "
        f" WHERE s.subject_uuid = d.subject_uuid AND s.context_uuid = $4 "
        f" AND s.predicate_uuid = $5 AND s.object_uuid = $3 LIMIT 1) src "
        f"CROSS JOIN LATERAL (SELECT 1 FROM {q} vt "
        f" WHERE vt.subject_uuid = d.subject_uuid AND vt.context_uuid = $4 "
        f" AND vt.predicate_uuid = $6 AND vt.object_uuid = $7 LIMIT 1) typ "
        f"UNION "
        f"SELECT f FROM unnest($1::uuid[]) AS f "
        f"CROSS JOIN LATERAL (SELECT 1 FROM {q} k "
        f" WHERE k.subject_uuid = f AND k.predicate_uuid = $2 "
        f" AND k.object_uuid = $3 AND k.context_uuid = $4 LIMIT 1) member",
        list(frame_uuids), U(HAS_KG_GRAPH_URI), U(entity_uri), U(graph_id),
        U(HAS_EDGE_SOURCE), U(VITALTYPE_URI), U(EDGE_HAS_ENTITY_KG_FRAME),
        U(HAS_EDGE_DESTINATION))
    return {r['f'] for r in rows}


async def _present(conn, space_id: str, graph_id: str, uris: List[str]) -> set:
    """Which of *uris* are the subject of some quad in the graph."""
    if not uris:
        return set()
    from ..db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
    from ..db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
    q = SparqlSQLSchema.get_table_names(space_id)['rdf_quad']
    by_uuid = {_generate_term_uuid(u, 'U'): u for u in uris}
    rows = await conn.fetch(
        f"SELECT DISTINCT subject_uuid FROM {q} "
        f"WHERE subject_uuid = ANY($1) AND context_uuid = $2",
        list(by_uuid), _generate_term_uuid(graph_id, 'U'))
    return {by_uuid[r['subject_uuid']] for r in rows}


def entity_frames_precheck(space_id: str, graph_id: str, entity_uri: str,
                           frame_uris: List[str]):
    """The entity-frame UPSERT precondition (`issues/256` item 2).

    The entity exists, and every frame named that already exists belongs to it.
    Upsert skipped both: it overwrote another entity's frame and re-stamped its
    `hasKGGraphURI`, and wrote frames onto an entity that did not exist.
    """
    present_check = entity_present_precheck(space_id, graph_id, entity_uri)

    async def _check(conn):
        await present_check(conn)
        from ..db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
        existing = await _present(conn, space_id, graph_id, list(frame_uris))
        if not existing:
            return
        owned = await owned_by_entity(
            conn, space_id, graph_id, entity_uri,
            [_generate_term_uuid(u, 'U') for u in existing])
        foreign = [u for u in existing if _generate_term_uuid(u, 'U') not in owned]
        if foreign:
            raise FrameNotOwned(
                f"{len(foreign)} frame(s) belong to another entity or to none, not "
                f"{entity_uri}; nothing was written: " + ", ".join(sorted(foreign)[:5]))
    return _check


def standalone_precheck(space_id: str, graph_id: str, frame_uris: List[str],
                        parent_uri: Optional[str] = None,
                        require_existing: bool = False):
    """The `/kgframes` write precondition: no entity's frame, as target or parent.

    `require_existing` for `update`, which refuses a missing frame with
    NOT_FOUND rather than creating it (`issues/256` item 3).
    """
    async def _check(conn):
        if require_existing:
            missing = sorted(set(frame_uris) - await _present(
                conn, space_id, graph_id, list(frame_uris)))
            if missing:
                raise FrameAbsent(
                    f"{len(missing)} frame(s) do not exist; update does not create "
                    f"(use upsert): " + ", ".join(missing[:5]))
        await refuse_entity_frames(conn, space_id, graph_id, list(frame_uris))
        if parent_uri:
            await refuse_entity_frames(conn, space_id, graph_id, [parent_uri],
                                       what="parent")
    return _check


def entity_present_precheck(space_id: str, graph_id: str, entity_uri: str):
    """The entity-frame write precondition: the entity still exists."""
    async def _check(conn):
        t, s_uuid, _p, g_uuid = _stamp_keys(space_id, graph_id, entity_uri)
        if not await conn.fetchval(
                f"SELECT 1 FROM {t['rdf_quad']} "
                f"WHERE subject_uuid = $1 AND context_uuid = $2 LIMIT 1",
                s_uuid, g_uuid):
            raise EntityAbsent(entity_uri, space_id)
    return _check


class WriteDeadlineExceeded(Exception):
    """A subject-level write ran past its budget and was rolled back.

    CANCELLATION IS THE POINT, and it is the opposite call from
    `api/request_bounds.py`, which refuses to cancel a write — deliberately,
    because a client that hung up "may well have intended the write" and a
    rollback it cannot observe is silent data loss. That reasoning does not apply
    here: the caller IS still waiting, the rollback is REPORTED to it as a
    failure, and the alternative is not a slow write but a lost one. A
    cooperative check between phases could not do this, because the parks that
    cost production its writes were parks INSIDE an await that never returned.
    """

    def __init__(self, waited_s: float, budget_s: float, phases: str):
        self.waited_s = waited_s
        self.budget_s = budget_s
        self.phases = phases
        super().__init__(
            f"write exceeded its {budget_s:.1f}s budget after {waited_s:.1f}s; "
            f"{phases}")


# Phases of one write, in the order they complete. Printing them in a fixed order
# with a placeholder for the ones that never happened is the point: on the
# failures this exists for, the TAIL IS MISSING and where it stops is the answer.
_WRITE_PHASES = ("acquire", "begin", "lock", "presync", "insert", "commit")


def _phase_breakdown(started: float, marks: Dict[str, float]) -> str:
    """`phases acquire=0.001s begin=0.000s lock=0.002s presync=0.198s …`.

    Each number is the time that phase TOOK, i.e. the gap from the previous mark,
    so the figures sum to the elapsed total rather than repeating it. A phase that
    did not complete prints `-`, and everything after it is `-` too; a write that
    died waiting with its transaction open therefore reads as
    `acquire=… begin=… lock=… presync=- insert=- commit=-`, which says it stopped
    between the lock and the end of the scans without needing another deploy to
    find out (`issues/253`).
    """
    out, prev = [], started
    for name in _WRITE_PHASES:
        at = marks.get(name)
        if at is None:
            out.append(f"{name}=-")
            continue
        out.append(f"{name}={at - prev:.3f}s")
        prev = at
    return "phases " + " ".join(out)


@dataclass
class FrameSubtreeDelete:
    """What `delete_frame_subtrees` did.

    `deleted_frames`: every frame removed, descendants included.
    `absent_frames`: requested frames that were not there (NO_OP, not failure).
    `member_uris`: every subject removed, for auto-sync.
    """
    deleted_frames: List[str]
    absent_frames: List[str]
    member_uris: List[str]


@dataclass
class BackendOperationResult:
    """Result of a backend operation."""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    objects: Optional[List[GraphObject]] = None


class KGBackendInterface(ABC):
    """Abstract interface for KG backend operations."""
    
    @abstractmethod
    async def store_objects(self, space_id: str, graph_id: str, objects: List[GraphObject]) -> BackendOperationResult:
        """Store VitalSigns objects in the backend."""
        pass
    
    @abstractmethod
    async def object_exists(self, space_id: str, graph_id: str, uri: str) -> bool:
        """Check if an object exists in the backend."""
        pass
    
    @abstractmethod
    async def delete_object(self, space_id: str, graph_id: str, uri: str) -> BackendOperationResult:
        """Delete an object from the backend."""
        pass
    
    @abstractmethod
    async def execute_sparql_query(self, space_id: str, query: str) -> Dict[str, Any]:
        """Execute a SPARQL query against the backend."""
        pass
    
    @abstractmethod
    async def validate_parent_connection(self, space_id: str, graph_id: str, 
                                       parent_uri: str, child_uri: str) -> bool:
        """Validate that a parent-child relationship exists."""
        pass
    
    @abstractmethod
    async def update_quads(self, space_id: str, graph_id: str, 
                          delete_quads: List[tuple], insert_quads: List[tuple]) -> bool:
        """
        Atomically update quads by deleting old ones and inserting new ones.
        
        Implementation Strategy:
        1. Execute DELETE and INSERT within single PostgreSQL transaction
        2. PostgreSQL transaction provides atomicity guarantee

        This used to have a third step — synchronising a second store after the
        commit — which is where the second-store tri-state came from. With one
        store there is nothing to be out of sync WITH, so the operation either
        commits or it does not (`issues/241`).
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier (full URI)
            delete_quads: List of (subject, predicate, object, graph) tuples to delete
            insert_quads: List of (subject, predicate, object, graph) tuples to insert
            
        Returns:
            bool: True if operation succeeded, False otherwise
        """
        pass

    @abstractmethod
    async def get_objects_by_uris(self, space_id: str, uris: List[str],
                                  graph_id: Optional[str] = None) -> List[GraphObject]:
        """Retrieve multiple objects by URI list as VitalSigns GraphObjects."""
        pass


class SparqlSQLBackendAdapter(KGBackendInterface):
    """Adapter for the pure-PostgreSQL sparql_sql backend.

    Wraps ``SparqlSQLSpaceImpl`` and exposes the ``KGBackendInterface``
    consumed by kg_impl processors (KGEntityCreateProcessor, etc.).
    """

    def __init__(self, backend_impl):
        self.backend = backend_impl
        self.logger = logging.getLogger(f"{__name__}.SparqlSQLBackendAdapter")
        self.retriever = GraphObjectRetriever(backend_impl)
        # PostgreSQL config for thread-offloaded ANALYZE (avoids event loop stalls)
        self._pg_config = getattr(backend_impl, 'postgresql_config', None)

    # ------------------------------------------------------------------
    # store_objects
    # ------------------------------------------------------------------

    async def store_objects(self, space_id: str, graph_id: str,
                            objects: List[GraphObject],
                            conn=None) -> BackendOperationResult:
        try:
            import time as _time
            from rdflib import URIRef

            _t0 = _time.monotonic()
            graph_uri = URIRef(graph_id)

            def _build_quads():
                result = []
                for obj in objects:
                    try:
                        for s, p, o in obj.to_triples():
                            result.append((s, p, o, graph_uri))
                    except Exception as e:
                        pass  # logged below via count mismatch
                return result

            quads = await asyncio.to_thread(_build_quads)

            _t1 = _time.monotonic()
            self.logger.info("⏱️  BACKEND to_triples: %.3fs (%d objects → %d quads)",
                             _t1 - _t0, len(objects), len(quads))

            inserted = await self.backend.add_rdf_quads_batch_bulk(
                space_id, quads, connection=conn)
            _t2 = _time.monotonic()
            self.logger.info("⏱️  BACKEND add_rdf_quads_batch_bulk: %.3fs (%d inserted)",
                             _t2 - _t1, inserted)

            if inserted == 0 and len(quads) > 0:
                self.logger.error(
                    "store_objects: 0 quads inserted out of %d — "
                    "likely a PostgreSQL index overflow or constraint error",
                    len(quads),
                )
                return BackendOperationResult(
                    success=False,
                    message=f"Failed to insert quads: 0 of {len(quads)} stored",
                    error=f"0 quads inserted (check server logs for index overflow errors)",
                )

            # Refresh planner statistics for the auxiliary tables after a write.
            #
            # rdf_quad and term are deliberately EXCLUDED. Measured on prod, this
            # block ran 27k+ times per space over 45 days at ~4.2s per ANALYZE of
            # rdf_quad alone, accounting for 28.7% of all database time — and
            # column statistics on a 26.8M-row table barely move when one
            # applicant's entities are appended. MaintenanceJob and autovacuum own
            # those two tables now.
            # See planning/planning_performance/prod_db_saturation_plan.md
            # SCHEDULED, NEVER AWAITED (`issues/253`). This was
            # `await self._maybe_analyze_aux_tables(...)`, measured at 3.389 s on
            # production — charged to a user's write, for work that is deferrable
            # by definition. It is also the LATENT TWIN of the defect that lost
            # five writes: `store_objects` takes a `conn` parameter, so the first
            # caller to pass one would have had this ANALYZE awaited inside its
            # transaction, and `idle_in_transaction_session_timeout` is 60 s.
            # Nobody passes one today; scheduling it means nobody can.
            self._schedule_analyze_aux_tables(space_id)

            self.logger.info("⏱️  BACKEND store_objects total: %.3fs", _time.monotonic() - _t0)

            return BackendOperationResult(
                success=True,
                message=f"Successfully stored {len(objects)} objects ({inserted} quads)",
                data={"stored_count": len(objects), "quad_count": inserted},
            )
        except Exception as e:
            self.logger.error("store_objects failed: %s", describe_exception(e))
            return BackendOperationResult(success=False, message=str(e), error=str(e))

    # ------------------------------------------------------------------
    # Post-write ANALYZE of auxiliary tables (three-tier guard)
    # ------------------------------------------------------------------

    async def _get_analyze_lock_manager(self):
        """Lazily create the process lock manager used to serialise ANALYZE."""
        if getattr(self, '_analyze_lock_manager', None) is None:
            if not self._pg_config:
                return None
            from ..process.process_lock_manager import ProcessLockManager
            mgr = ProcessLockManager(self._pg_config)
            await mgr.connect()
            self._analyze_lock_manager = mgr
        return self._analyze_lock_manager

    def _schedule_analyze_aux_tables(self, space_id: str) -> None:
        """Schedule the post-write aux-table ANALYZE. Never awaited.

        The tier-0 guard is checked HERE, in process and free, so an ordinary
        write creates no task at all — the body re-checks it, which keeps the
        body correct for anyone calling it directly.
        """
        from ..db.sparql_sql.auto_analyze import (
            ANALYZE_LOCAL_GUARD_SECONDS, was_analyzed_recently,
        )
        if was_analyzed_recently(space_id,
                                 max_age_seconds=ANALYZE_LOCAL_GUARD_SECONDS):
            return
        _AUX_ANALYZE_TASKS.schedule(
            self._maybe_analyze_aux_tables(space_id), key=space_id)

    async def _maybe_analyze_aux_tables(self, space_id: str,
                                        since: Optional[float] = None) -> bool:
        """ANALYZE the auxiliary tables for *space_id*, rate-limited across processes.

        Three tiers, each covering a case the previous one cannot:

        * **Tier 0** — in-process timestamp. Avoids a catalog roundtrip on the hot
          write path.
        * **Tier 1** — ``pg_stat_user_tables.last_analyze``, which PostgreSQL keeps
          globally. This is the guard that actually holds across workers and task
          restarts; the in-process dict never did.
        * **Tier 2** — non-blocking advisory lock. ``last_analyze`` only advances
          when ANALYZE *completes*, so during a run every other process still reads
          a stale timestamp and would start its own. The lock closes that window —
          which is also the restart-stampede case, when every task comes up with an
          empty Tier 0 simultaneously.

        Returns True if ANALYZE actually ran.
        """
        import time as _time
        # Timed from ENTRY when the caller does not supply a start. It used to be
        # handed the write's own `_t2`, which measured "write start to ANALYZE
        # end" — meaningless now that this is scheduled rather than awaited.
        if since is None:
            since = _time.monotonic()
        from ..db.sparql_sql.auto_analyze import (
            was_analyzed_recently, set_last_analyze_time, fetch_last_analyze_age,
            ANALYZE_LOCAL_GUARD_SECONDS, ANALYZE_MIN_INTERVAL,
        )
        from ..db.sparql_sql.sparql_sql_schema import SparqlSQLSchema

        # Tier 0 — fast path, no DB roundtrip.
        if was_analyzed_recently(space_id, max_age_seconds=ANALYZE_LOCAL_GUARD_SECONDS):
            self.logger.debug("⏱️  BACKEND ANALYZE: skipped (local guard)")
            return False

        t = SparqlSQLSchema.get_table_names(space_id)
        # `frame_slot`, not `frame_entity`. The retired key was removed from
        # `get_table_names` (`issues/183`), so this raised KeyError while
        # BUILDING the list — before any ANALYZE ran. Not "the dropped table's
        # ANALYZE fails": ALL FIVE were skipped, silently, because the caller
        # logs it as non-fatal. Prod showed it as
        # `ANALYZE after bulk insert failed (non-fatal): 'frame_entity'`
        # on every bulk write.
        # `entity_slot_sort` ADDED 2026-09-11. It was the one derived table the
        # query path plans against that nothing ever analyzed — not this
        # function, and not reliably autovacuum either, because these tables are
        # populated by bulk load. Found with 3,877,000 rows and `last_analyze`
        # NULL on `sp_lead_synth_100k`, and 304,923 rows never analyzed on
        # `<space>`, where the planner consequently estimated `rows=1` for it.
        # That estimate is what `issues/096` noticed in its plans without
        # tracing it back here. Compensating for bulk load is the whole reason
        # this function exists, so excluding the biggest bulk-loaded table was
        # backwards.
        tables = [t['rdf_pred_stats'], t['rdf_stats'], t['datatype'],
                  t['edge'], t['frame_slot'], t['entity_slot_sort']]
        # Only a rate-limit proxy for "has this space been analyzed recently",
        # not a claim about size: `entity_slot_sort` outgrows `edge` on some
        # spaces (3.9M against 365k). Kept as `edge` because every space has one
        # and changing it would reset the shared clock for all of them.
        representative = t['edge']

        # Tier 1 — shared clock.
        # INTERNAL pool (`issues/231`): both the catalog probe below and the
        # ANALYZE fallback further down are deferrable maintenance, and on the
        # request pool they compete with the readers this is supposed to be
        # speeding up. Falls back to the request pool so an impl without the
        # split keeps working.
        from ..db.pool import internal_pool_for
        pool = internal_pool_for(self.backend.db_impl)
        if pool is not None:
            async with pool.acquire() as conn:
                age = await fetch_last_analyze_age(conn, representative)
            if age is not None and age < ANALYZE_MIN_INTERVAL:
                # Re-arm Tier 0 so we don't re-query the catalog on every batch
                # for the remainder of the interval.
                set_last_analyze_time(space_id)
                self.logger.debug(
                    "⏱️  BACKEND ANALYZE: skipped (shared guard, %.0fs ago)", age)
                return False

        # Tier 2 — non-blocking lock. If another process is mid-ANALYZE, skip;
        # never block, or writers queue behind maintenance.
        lock_mgr = await self._get_analyze_lock_manager()
        if lock_mgr is not None and not await lock_mgr.try_acquire("analyze", space_id):
            self.logger.debug("⏱️  BACKEND ANALYZE: skipped (another process holds the lock)")
            return False
        try:
            if self._pg_config:
                await asyncio.to_thread(self._sync_analyze_tables, tables)
            elif pool is not None:
                async with pool.acquire() as conn:
                    for tbl in tables:
                        await conn.execute(f"ANALYZE {tbl}")
            set_last_analyze_time(space_id)
            self.logger.info("⏱️  BACKEND ANALYZE (aux tables): %.3fs",
                             _time.monotonic() - since)
            return True
        finally:
            if lock_mgr is not None:
                await lock_mgr.release("analyze", space_id)

    # ------------------------------------------------------------------
    # Thread-offloaded ANALYZE helper
    # ------------------------------------------------------------------

    def _sync_analyze_tables(self, tables: List[str]) -> int:
        """Run ANALYZE on each table via a short-lived psycopg sync connection.

        Designed to be called via ``asyncio.to_thread()`` so the event loop
        is never blocked.  Mirrors MaintenanceJob._sync_run_tables().
        """
        import psycopg
        from psycopg import sql as psql

        cfg = self._pg_config
        assert cfg is not None, "_sync_analyze_tables requires _pg_config"
        conn = psycopg.connect(
            host=require(cfg, 'host'),
            port=require(cfg, 'port'),
            dbname=require(cfg, 'database'),
            user=require(cfg, 'username'),
            password=require(cfg, 'password'),
            autocommit=True,
        )
        completed = 0
        try:
            for table in tables:
                try:
                    conn.execute(psql.SQL("ANALYZE {}").format(psql.Identifier(table)))
                    completed += 1
                except Exception as e:
                    self.logger.warning("ANALYZE %s failed: %s", table, e)
        finally:
            conn.close()
        return completed

    # ------------------------------------------------------------------
    # object_exists
    # ------------------------------------------------------------------

    async def object_exists(self, space_id: str, graph_id: str, uri: str) -> bool:
        try:
            query = f"""
                SELECT ?p ?o WHERE {{
                    GRAPH <{graph_id}> {{ <{uri}> ?p ?o . }}
                }} LIMIT 1
            """
            result = await self.backend.execute_sparql_query(space_id, query)
            bindings = result.get('results', {}).get('bindings', [])
            return len(bindings) > 0
        except Exception as e:
            self.logger.error("object_exists failed: %s", e)
            return False

    async def batch_check_uris_exist(self, space_id: str, graph_id: str,
                                      uris: List[str]) -> List[str]:
        """Return URIs that already exist as subjects in the graph (direct SQL)."""
        try:
            return await self.backend.check_subjects_exist(space_id, graph_id, uris)
        except Exception as e:
            self.logger.error("batch_check_uris_exist failed: %s", e)
            return []

    async def frames_lacking_link(self, space_id: str, graph_id: str,
                                  frame_uris: List[str], source_uri: str,
                                  edge_class_uri: str) -> List[str]:
        """The frames in *frame_uris* with no *edge_class_uri* edge from *source_uri*.

        For the entity-frame upsert (`issues/256` item 2), which writes the link
        a frame lacks. Read outside the write's transaction on purpose: the link
        URIs are deterministic (`edge_uris`), so a concurrent writer adding the
        same link writes the same subject, and nothing is duplicated.
        """
        if not frame_uris:
            return []
        from ..db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
        U = lambda u: _generate_term_uuid(u, 'U')  # noqa: E731
        q = self.backend.schema.get_table_names(space_id)['rdf_quad']
        by_uuid = {U(u): u for u in frame_uris}
        async with self.backend.db_impl.connection_pool.acquire() as conn:
            rows = await conn.fetch(
                f"WITH d AS MATERIALIZED ("
                f" SELECT subject_uuid, object_uuid AS f FROM {q} "
                f" WHERE context_uuid = $2 AND predicate_uuid = $3 "
                f" AND object_uuid = ANY($1::uuid[])) "
                f"SELECT DISTINCT d.f FROM d "
                f"CROSS JOIN LATERAL (SELECT 1 FROM {q} s "
                f" WHERE s.subject_uuid = d.subject_uuid AND s.context_uuid = $2 "
                f" AND s.predicate_uuid = $4 AND s.object_uuid = $5 LIMIT 1) src "
                f"CROSS JOIN LATERAL (SELECT 1 FROM {q} vt "
                f" WHERE vt.subject_uuid = d.subject_uuid AND vt.context_uuid = $2 "
                f" AND vt.predicate_uuid = $6 AND vt.object_uuid = $7 LIMIT 1) typ",
                list(by_uuid), U(graph_id), U(HAS_EDGE_DESTINATION),
                U(HAS_EDGE_SOURCE), U(source_uri), U(VITALTYPE_URI),
                U(edge_class_uri))
        linked = {r['f'] for r in rows}
        return [u for k, u in by_uuid.items() if k not in linked]

    # ------------------------------------------------------------------
    # get_object / get_entity / get_entity_graph
    # ------------------------------------------------------------------

    async def get_object(self, space_id: str, graph_id: str,
                         object_uri: str) -> BackendOperationResult:
        try:
            triples = await self.retriever.get_object_triples(
                space_id, graph_id, object_uri, include_materialized_edges=False
            )
            if not triples:
                return BackendOperationResult(success=True, message="Object not found", objects=[])
            objects = await self._triples_to_vitalsigns(triples)
            return BackendOperationResult(success=True, message="OK", objects=objects)
        except Exception as e:
            self.logger.error("get_object failed: %s", e)
            return BackendOperationResult(success=False, message=str(e), error=str(e), objects=[])

    async def get_entity(self, space_id: str, graph_id: str,
                         entity_uri: str) -> BackendOperationResult:
        return await self.get_object(space_id, graph_id, entity_uri)

    async def get_entity_graph(self, space_id: str, graph_id: str,
                               entity_uri: str) -> BackendOperationResult:
        try:
            objects = await self.retriever.get_entity_graph_as_objects(
                space_id, graph_id, entity_uri, include_materialized_edges=False
            )
            if not objects:
                return BackendOperationResult(
                    success=False, message=f"Entity graph not found: {entity_uri}", objects=[])
            return BackendOperationResult(success=True, message="OK", objects=objects)
        except Exception as e:
            self.logger.error("get_entity_graph failed: %s", e)
            return BackendOperationResult(success=False, message=str(e), error=str(e), objects=[])

    async def get_entity_by_reference_id(self, space_id: str, graph_id: str,
                                         reference_id: str) -> BackendOperationResult:
        try:
            triples = await self.retriever.get_entity_by_reference_id(
                space_id, graph_id, reference_id, include_materialized_edges=False
            )
            if not triples:
                return BackendOperationResult(success=True, message="Not found", objects=[])
            objects = await self._triples_to_vitalsigns(triples)
            return BackendOperationResult(success=True, message="OK", objects=objects)
        except Exception as e:
            self.logger.error("get_entity_by_reference_id failed: %s", e)
            return BackendOperationResult(success=False, message=str(e), error=str(e), objects=[])

    async def get_entity_graph_by_reference_id(self, space_id: str, graph_id: str,
                                               reference_id: str) -> BackendOperationResult:
        try:
            objects = await self.retriever.get_entity_graph_by_reference_id_as_objects(
                space_id, graph_id, reference_id, include_materialized_edges=False
            )
            if not objects:
                return BackendOperationResult(
                    success=False, message=f"Not found: {reference_id}", objects=[])
            return BackendOperationResult(success=True, message="OK", objects=objects)
        except Exception as e:
            self.logger.error("get_entity_graph_by_reference_id failed: %s", e)
            return BackendOperationResult(success=False, message=str(e), error=str(e), objects=[])

    # ------------------------------------------------------------------
    # delete_object
    # ------------------------------------------------------------------

    async def delete_object(self, space_id: str, graph_id: str,
                            uri: str, conn=None) -> BackendOperationResult:
        try:
            delete_query = f"""
                DELETE {{
                    GRAPH <{graph_id}> {{ <{uri}> ?p ?o . }}
                }}
                WHERE {{
                    GRAPH <{graph_id}> {{ <{uri}> ?p ?o . }}
                }}
            """
            await self.backend.execute_sparql_update(
                space_id, delete_query, conn=conn)
            return BackendOperationResult(success=True, message=f"Deleted {uri}")
        except Exception as e:
            self.logger.error("delete_object failed: %s", e)
            return BackendOperationResult(success=False, message=str(e), error=str(e))

    # ------------------------------------------------------------------
    # SPARQL execution
    # ------------------------------------------------------------------

    async def execute_sparql_query(self, space_id: str, query: str) -> Dict[str, Any]:
        return await self.backend.execute_sparql_query(space_id, query)

    async def execute_sparql_update(self, space_id: str, update_query: str):
        try:
            return await self.backend.execute_sparql_update(space_id, update_query)
        except Exception as e:
            self.logger.error("execute_sparql_update failed: %s", e)
            return False

    # ------------------------------------------------------------------
    # fast_entity_count — direct-SQL count for the default KGEntity listing
    # ------------------------------------------------------------------

    # The four KGEntity subclass objects (must stay in sync with
    # _KGENTITY_TYPE_CLAUSE in kgentity_list_impl.py). Entities key on
    # ``vitaltype`` (one per object → the fast count is exact).
    _KGENTITY_TYPE_URIS = (
        'http://vital.ai/ontology/haley-ai-kg#KGEntity',
        'http://vital.ai/ontology/haley-ai-kg#KGNewsEntity',
        'http://vital.ai/ontology/haley-ai-kg#KGProductEntity',
        'http://vital.ai/ontology/haley-ai-kg#KGWebEntity',
    )

    async def fast_entity_count(self, space_id: str, graph_id: str,
                                entity_type_uri: Optional[str] = None,
                                search: Optional[str] = None,
                                prop_filters: str = "",
                                sort_by: Optional[str] = None,
                                filters: Optional[dict] = None) -> Optional[int]:
        """Exact entity count, from `entity_prop_sort` when it can serve the
        shape and from the quads for the plain default listing.

        THE COUNT MUST TRACK THE PAGE. Both run concurrently and the request
        waits for both, so a fast page beside a slow count is worth nothing.
        This declined every typed/filtered/sorted shape while
        `fast_entity_page` had already been taught to serve them: the page
        came back in 0.4 ms and the count took a `COUNT(DISTINCT)` over the
        quads, so the request took 30 s and was killed by the transaction
        timeout. Deterministic on the FIRST page of a listing; every later page
        hit the count cache and looked fine.
        """
        if search:
            logger.info(
                "fast_entity_count DECLINE(%s): search is set; text lives in the "
                "FTS index, not entity_prop_sort", space_id)
            return None
        # `sort_by` is NOT a routing condition here, where it is for the page.
        # A sort changes the ORDER of a result set, never its SIZE, so a bare
        # sort is the plain count and belongs to `fast_typed_subject_count`.
        # Routing it into the prop-sort branch made a sort-only listing decline
        # its count and fall to SPARQL for a number the plain path already had.
        if entity_type_uri or prop_filters:
            impl = _resolve_space_impl(self.backend)
            if impl is None or not graph_is_uri(graph_id):
                logger.info(
                    "fast_entity_count DECLINE(%s): impl_resolved=%s graph_is_uri=%s",
                    space_id, impl is not None, graph_is_uri(graph_id))
                return None
            from ..db.sparql_sql.fast_prop_sort import fast_entity_prop_count
            return await fast_entity_prop_count(
                impl, space_id, graph_id, entity_type_uri=entity_type_uri,
                filters=filters, sort_by=sort_by)
        return await fast_typed_subject_count(
            self.backend, space_id, graph_id, VITALTYPE_URI, self._KGENTITY_TYPE_URIS)

    async def fast_entity_page(self, space_id: str, graph_id: str,
                               page_size: int, offset: int,
                               entity_type_uri: Optional[str] = None,
                               search: Optional[str] = None,
                               prop_filters: str = "",
                               sort_by: Optional[str] = None,
                               filters: Optional[dict] = None,
                               sort_order: str = "asc") -> Optional[List[str]]:
        """Ordered page of entity URIs, or ``None`` → SPARQL fallback.

        Two fast paths now, and they cover different shapes:

        * the PLAIN default listing, ordered by `subject_uuid`, from the quads
        * a SORTED or FILTERED listing, from `{space}_entity_prop_sort`

        SEARCH still declines. Text lives in `{space}_fts_{index}` and composing
        it with this table is a join whose driving side depends on how selective
        the search is — measured, not guessed, per
        `planning_ui/kg_search_filter_sort_fts_plan.md`. `issues/172` is what
        guessing costs.
        """
        # THESE TWO DECLINES WERE SILENT, and that cost a second production
        # diagnosis. `fast_entity_prop_page` logs its own reasons at INFO, but
        # both returns below happen BEFORE it is called — so a listing that
        # declined here produced no line at all, and the absence of a
        # `prop_sort DECLINE` was read as "the fast path is not declining".
        # An unexplained decline is indistinguishable from an absent one.
        if search:
            logger.info(
                "fast_entity_page DECLINE(%s): search is set and text lives in "
                "the FTS index, not entity_prop_sort; composing them is not yet "
                "measured. NOTE: a UI that only enables sorting once a search "
                "narrows the set makes this the COMMON path, not a rare one.",
                space_id)
            return None
        if entity_type_uri or prop_filters or sort_by:
            impl = _resolve_space_impl(self.backend)
            if impl is None or not graph_is_uri(graph_id):
                logger.info(
                    "fast_entity_page DECLINE(%s): impl_resolved=%s graph_is_uri=%s "
                    "— the space impl could not be resolved from %s, or the graph "
                    "is not a URI", space_id, impl is not None,
                    graph_is_uri(graph_id), type(self.backend).__name__)
                return None
            from ..db.sparql_sql.fast_prop_sort import fast_entity_prop_page
            return await fast_entity_prop_page(
                impl, space_id, graph_id, page_size, offset,
                entity_type_uri=entity_type_uri, filters=filters,
                sort_by=sort_by, sort_order=sort_order)
        return await fast_typed_subject_page(
            self.backend, space_id, graph_id, VITALTYPE_URI,
            self._KGENTITY_TYPE_URIS, page_size, offset)

    # ------------------------------------------------------------------
    # validate_parent_connection
    # ------------------------------------------------------------------

    async def validate_parent_connection(self, space_id: str, graph_id: str,
                                         parent_uri: str, child_uri: str) -> bool:
        try:
            query = f"""
                SELECT ?edge WHERE {{
                    GRAPH <{graph_id}> {{
                        ?edge <http://vital.ai/ontology/vital-core#edgeSource> <{parent_uri}> .
                        ?edge <http://vital.ai/ontology/vital-core#edgeDestination> <{child_uri}> .
                    }}
                }} LIMIT 1
            """
            result = await self.backend.execute_sparql_query(space_id, query)
            bindings = result.get('results', {}).get('bindings', [])
            return len(bindings) > 0
        except Exception as e:
            self.logger.error("validate_parent_connection failed: %s", e)
            return False

    # ------------------------------------------------------------------
    # update_quads
    # ------------------------------------------------------------------

    async def update_quads(self, space_id: str, graph_id: str,
                           delete_quads: List[tuple],
                           insert_quads: List[tuple]) -> bool:
        try:
            # This transaction syncs the stats tables TWICE — once down for the
            # removes, once up for the inserts — and the two calls lock their
            # own key ranges in sorted order without being sorted against each
            # other. So a remove of {C} plus an insert of {B} takes C then B,
            # while a concurrent update doing the reverse takes B then C: a
            # cycle that per-batch ordering cannot see (issues/115).
            #
            # The bulk paths retry themselves, but only when they own the
            # transaction. Here the transaction is ours, so the retry is too.
            async def _do_update(conn):
                # Both halves hand their stats deltas back instead of applying
                # them inline, so the hot predicate rows are locked once, at the
                # end, rather than from the first remove through the last
                # insert. Measured on this shape: 98.4% of the transaction spent
                # holding them, against 7.7% for a plain insert (issues/115).
                sink: list = []
                if delete_quads:
                    await self.backend.remove_rdf_quads_batch_bulk(
                        space_id, delete_quads, connection=conn, stats_sink=sink)
                if insert_quads:
                    await self.backend.add_rdf_quads_batch_bulk(
                        space_id, insert_quads, connection=conn, stats_sink=sink)

            from vitalgraph.db.sparql_sql.deadlock_retry import with_deadlock_retry
            await with_deadlock_retry(
                self.backend.db_impl.connection_pool, _do_update,
                what=f"update_quads({space_id}, {graph_id})")
            return True
        except Exception as e:
            self.logger.error("update_quads failed: %s", describe_exception(e))
            return False

    def _lock_timeout_failed(self, where: str, exc: EntityLockTimeout,
                             subjects: int, phases: str = "") -> bool:
        """Log a lock timeout NAMING THE ENTITY, and report the write as failed.

        Reported from production (`issues/253`): "a failure cannot be traced to a
        lead, so nothing can be reconciled." PostgreSQL says `canceling statement
        due to lock timeout`, which identifies the STATEMENT — and every write to
        every lead issues the same one. The lock key is the only thing that says
        which entity was being written, so it belongs on the error line.
        """
        self.logger.error(
            "%s LOCK TIMEOUT after %.3fs waiting on entity %s (key %d); "
            "%d subject(s) NOT written %s",
            where, exc.waited_s, exc.uri, exc.key, subjects, phases)
        return False

    async def upsert_objects_atomic(self, space_id: str, graph_id: str,
                                    entity_uris: List[str],
                                    objects: List[GraphObject],
                                    conn=None) -> bool:
        """Replace one or more entity graphs in ONE locked transaction.

        `issues/173`. UPSERT used to be `delete_object` then `store_objects`,
        two independent operations with nothing holding them together. A client
        that timed out and retried while the first request was still in flight
        got: A sees nothing committed and starts storing; B also sees nothing
        committed, so skips the delete, and stores too. Both landed.

        Only the server-stamped timestamps showed the damage, which is why it
        went unnoticed for two months: every client-supplied property carries
        the same value on each attempt, so the quad primary key dedupes the
        retry silently. The timestamps come from `datetime.now()` per request,
        so each attempt wrote a distinct row that no constraint could collapse.

        The lock is taken FIRST, before anything is read, so the existence check
        the caller made outside this transaction cannot be acted on by two
        writers at once. Everything else happens exactly as
        `update_entity_graph` does it, per entity.
        """
        import time as _time
        from ..db.sparql_sql.entity_lock import lock_entities
        from ..db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
        from ..db.sparql_sql.sync_frame_slot_table import sync_frame_slot_before_delete
        from ..db.sparql_sql.sync_edge_table import sync_edge_table_before_delete
        from ..db.sparql_sql.sync_entity_slot_sort import (
            sync_entity_slot_sort_before_delete)
        from ..db.sparql_sql.sync_entity_prop_sort import (
            sync_entity_prop_sort_after_change)
        from ..db.sparql_sql.sync_frame_prop_sort import (
            sync_frame_prop_sort_after_change)
        from rdflib import URIRef

        try:
            _t0 = _time.monotonic()
            t = self.backend.schema.get_table_names(space_id)
            g_uuid = _generate_term_uuid(graph_id, 'U')
            p_uuid = _generate_term_uuid(
                'http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI', 'U')
            graph_uri = URIRef(graph_id)

            def _build_quads():
                out = []
                for obj in objects:
                    try:
                        for sub, pred, o in obj.to_triples():
                            out.append((sub, pred, o, graph_uri))
                    except Exception:
                        pass
                return out

            quads = await asyncio.to_thread(_build_quads)

            async with _write_conn(self.backend.db_impl.connection_pool, conn) as conn:
                async with conn.transaction():
                    # Sorted inside `lock_entities`, so a multi-entity upsert
                    # cannot deadlock against one taking the same entities in a
                    # different order.
                    await lock_entities(conn, entity_uris)

                    for entity_uri in entity_uris:
                        e_uuid = _generate_term_uuid(entity_uri, 'U')
                        rows = await conn.fetch(
                            f"SELECT DISTINCT subject_uuid FROM {t['rdf_quad']} "
                            f"WHERE predicate_uuid = $1 AND object_uuid = $2 "
                            f"  AND context_uuid = $3",
                            p_uuid, e_uuid, g_uuid)
                        subject_uuids = [r['subject_uuid'] for r in rows]
                        if not subject_uuids:
                            continue
                        # The auxiliary tables are derived from the quads, so
                        # they have to be told before the rows go, not after.
                        await sync_frame_slot_before_delete(
                            conn, space_id, subject_uuids, context_uuid=g_uuid)
                        await sync_edge_table_before_delete(
                            conn, space_id, subject_uuids, context_uuid=g_uuid)
                        # `entity_slot_sort` BEFORE the delete for the same
                        # reason (`issues/194`): its rows are reached through
                        # the edge table this delete invalidates, and a stale
                        # row makes a sort order by a value that is gone.
                        await sync_entity_slot_sort_before_delete(
                            conn, space_id, subject_uuids, context_uuid=g_uuid)
                        await conn.execute(
                            f"DELETE FROM {t['rdf_quad']} "
                            f"WHERE subject_uuid = ANY($1) AND context_uuid = $2",
                            subject_uuids, g_uuid)
                        # AND THE PROP TABLES AFTER IT. A delete there is a
                        # RECOMPUTE: they store the MIN of a multi-valued
                        # property, so removing the lexically first of three
                        # values must move the MIN to the next survivor while
                        # the row itself survives. Re-deriving before the
                        # delete would restore the value being removed.
                        await sync_entity_prop_sort_after_change(
                            conn, space_id, subject_uuids, context_uuid=g_uuid)
                        await sync_frame_prop_sort_after_change(
                            conn, space_id, subject_uuids, context_uuid=g_uuid)

                    if quads:
                        await self.backend.add_rdf_quads_batch_bulk(
                            space_id, quads, connection=conn)

            self.logger.info(
                "\u23f1\ufe0f  upsert_objects_atomic: %.3fs (%d entit(y/ies), %d quads)",
                _time.monotonic() - _t0, len(entity_uris), len(quads))
            return True
        except EntityLockTimeout as e:
            return self._lock_timeout_failed("upsert_objects_atomic", e, len(entity_uris))
        except Exception as e:
            self.logger.error("upsert_objects_atomic failed: %s", describe_exception(e))
            return False

    async def update_entity_graph(self, space_id: str, graph_id: str,
                                   entity_uri: str,
                                   insert_quads: List[tuple],
                                     conn=None) -> bool:
        """Atomically replace an entity graph: subject-level delete + insert.

        Uses direct SQL to find all subjects belonging to the entity graph
        (via hasKGGraphURI) and deletes all their quads, then inserts the
        new quads — all within a single transaction.  This avoids the SPARQL
        pipeline's datatype-propagation issues that cause quad-level deletes
        to miss rows.
        """
        import time as _time
        try:
            _t0 = _time.monotonic()
            schema = self.backend.schema
            t = schema.get_table_names(space_id)
            from ..db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
            g_uuid = _generate_term_uuid(graph_id, 'U')
            HAS_KG_GRAPH_URI = 'http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI'
            p_uuid = _generate_term_uuid(HAS_KG_GRAPH_URI, 'U')
            entity_uuid = _generate_term_uuid(entity_uri, 'U')

            async with _write_conn(self.backend.db_impl.connection_pool, conn) as conn:
                async with conn.transaction():
                    # Step 0: SERIALIZE ON THE ENTITY (`issues/173`).
                    #
                    # This transaction was already atomic; it was not exclusive.
                    # Two concurrent writers both run Step 1, both find the same
                    # subjects (or both find none, for an entity that does not
                    # exist yet), and both insert. Atomicity alone does not stop
                    # that — neither transaction does anything invalid on its
                    # own. The lock releases when this transaction ends.
                    from ..db.sparql_sql.entity_lock import lock_entities
                    await lock_entities(conn, [entity_uri])

                    # Step 1: Find all subjects in the entity graph
                    rows = await conn.fetch(
                        f"SELECT DISTINCT subject_uuid FROM {t['rdf_quad']} "
                        f"WHERE predicate_uuid = $1 AND object_uuid = $2 AND context_uuid = $3",
                        p_uuid, entity_uuid, g_uuid,
                    )
                    subject_uuids = [r['subject_uuid'] for r in rows]
                    if not subject_uuids:
                        self.logger.warning("update_entity_graph: no subjects found for %s", entity_uri)
                        # Still insert the new quads (entity may not have kGGraphURI on itself)
                    else:
                        # Step 2: Sync auxiliary tables before delete
                        from ..db.sparql_sql.sync_frame_slot_table import sync_frame_slot_before_delete
                        await sync_frame_slot_before_delete(conn, space_id, subject_uuids, context_uuid=g_uuid)
                        from ..db.sparql_sql.sync_edge_table import sync_edge_table_before_delete
                        await sync_edge_table_before_delete(conn, space_id, subject_uuids, context_uuid=g_uuid)
                        # THE SORT TABLES TOO (`issues/194`). The insert side is
                        # already covered: `add_rdf_quads_batch_bulk` maintains
                        # all five derived tables. What was missing is the
                        # DELETE side, and it fails differently for each:
                        #
                        #   `entity_slot_sort` keeps rows pointing at quads that
                        #   no longer exist, so a sort orders by a value that is
                        #   gone. Dropped BEFORE the delete, like edge and
                        #   frame_slot, because the rows are identified through
                        #   the edge table the delete is about to invalidate.
                        #
                        #   The two prop tables hold the MIN of a multi-valued
                        #   property, so a delete is a RECOMPUTE, not a row
                        #   drop — removing the lexically first of three values
                        #   must move the stored MIN to the next survivor while
                        #   the ROW SURVIVES. That cannot run before the delete
                        #   (the doomed value is still there to be re-derived),
                        #   so it runs after, below.
                        from ..db.sparql_sql.sync_entity_slot_sort import (
                            sync_entity_slot_sort_before_delete)
                        await sync_entity_slot_sort_before_delete(
                            conn, space_id, subject_uuids, context_uuid=g_uuid)

                        # Step 3: Delete all quads for those subjects
                        result = await conn.execute(
                            f"DELETE FROM {t['rdf_quad']} "
                            f"WHERE subject_uuid = ANY($1) AND context_uuid = $2",
                            subject_uuids, g_uuid,
                        )
                        deleted = int(result.split()[-1]) if result else 0
                        self.logger.info("update_entity_graph: deleted %d quads for %d subjects",
                                         deleted, len(subject_uuids))

                    # Step 4: Insert new quads in the same transaction
                    if insert_quads:
                        await self.backend.add_rdf_quads_batch_bulk(
                            space_id, insert_quads, connection=conn)

                    # AND THE PROP TABLES, AFTER the delete (`issues/194`).
                    # A delete here is a recompute against the survivors: for a
                    # subject that is gone entirely this empties its rows, and
                    # for one that lost a single value of several it moves the
                    # stored MIN. Running it before the delete would re-derive
                    # the value being removed.
                    if subject_uuids:
                        from ..db.sparql_sql.sync_entity_prop_sort import (
                            sync_entity_prop_sort_after_change)
                        from ..db.sparql_sql.sync_frame_prop_sort import (
                            sync_frame_prop_sort_after_change)
                        await sync_entity_prop_sort_after_change(
                            conn, space_id, subject_uuids, context_uuid=g_uuid)
                        await sync_frame_prop_sort_after_change(
                            conn, space_id, subject_uuids, context_uuid=g_uuid)

            _t1 = _time.monotonic()
            self.logger.info("⏱️  update_entity_graph: %.3fs", _t1 - _t0)
            return True
        except EntityLockTimeout as e:
            return self._lock_timeout_failed("update_entity_graph", e, 1)
        except Exception as e:
            self.logger.error("update_entity_graph failed: %s", describe_exception(e))
            return False

    async def update_entity_subject_only(self, space_id: str, graph_id: str,
                                          entity_uri: str,
                                          insert_quads: List[tuple]) -> bool:
        """Atomically replace only the entity's own quads (subject = entity_uri).

        Unlike update_entity_graph which deletes ALL subjects with hasKGGraphURI,
        this only deletes quads where the subject IS the entity itself, preserving
        all frames, slots, and edges in the entity graph.

        No edge / frame_slot / entity_slot_sort sync is needed: the entity subject
        carries no edge-source/dest properties and is not a frame, so no row in
        those tables can describe it.

        `entity_prop_sort` IS needed, and this docstring said otherwise until
        2026-09-12 (`issues/194`). That table indexes properties hanging STRAIGHT
        OFF THE ENTITY — which is exactly the set of quads this method deletes.
        The reasoning that exempts the other three stops one step short of it:
        being neither an edge nor a frame says nothing about the entity's own
        properties. Left unsynced, a filter on a removed value still matched it.
        `frame_prop_sort` stays exempt, for the stated reason — an entity is not
        a frame.
        """
        import time as _time
        try:
            _t0 = _time.monotonic()
            schema = self.backend.schema
            t = schema.get_table_names(space_id)
            from ..db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
            g_uuid = _generate_term_uuid(graph_id, 'U')
            entity_uuid = _generate_term_uuid(entity_uri, 'U')

            async with self.backend.db_impl.connection_pool.acquire() as conn:
                async with conn.transaction():
                    # Delete only entity's own quads
                    result = await conn.execute(
                        f"DELETE FROM {t['rdf_quad']} "
                        f"WHERE subject_uuid = $1 AND context_uuid = $2",
                        entity_uuid, g_uuid,
                    )
                    deleted = int(result.split()[-1]) if result else 0
                    self.logger.info("update_entity_subject_only: deleted %d quads for %s",
                                     deleted, entity_uri)

                    # Insert new entity quads
                    if insert_quads:
                        await self.backend.add_rdf_quads_batch_bulk(
                            space_id, insert_quads, connection=conn)

                    # AFTER the write, not before: a delete here is a RECOMPUTE
                    # against the surviving values, so re-deriving first would
                    # restore the value being removed. One call covers both the
                    # delete and the insert, which is why this table has a
                    # single `after_change` where the slot table needs two.
                    from ..db.sparql_sql.sync_entity_prop_sort import (
                        sync_entity_prop_sort_after_change)
                    await sync_entity_prop_sort_after_change(
                        conn, space_id, [entity_uuid], context_uuid=g_uuid)

            _t1 = _time.monotonic()
            self.logger.info("⏱️  update_entity_subject_only: %.3fs", _t1 - _t0)
            return True
        except Exception as e:
            self.logger.error("update_entity_subject_only failed: %s", e)
            return False

    async def update_subjects_graph(self, space_id: str, graph_id: str,
                                     subject_uris: List[str],
                                     insert_quads: List[tuple],
                                     lock_uris: Optional[List[str]] = None,
                                     conn=None,
                                     if_unmodified_since: Optional[str] = None,
                                     guard_subject: Optional[str] = None,
                                     stamp_subjects: Optional[List[str]] = None,
                                     replace_frame_graphs: Optional[List[str]] = None,
                                     removed_uris: Optional[List[str]] = None,
                                     precheck=None) -> bool:
        """Atomically replace quads for a list of subject URIs.

        ``precheck``, if given, is awaited as ``precheck(conn)`` right after the
        lock and before the guard, on this transaction's connection. It raises a
        `RequestRefused` to refuse the write, and that reaches the caller as
        itself. It exists for the checks that are only TRUE under the lock
        (`issues/256`): that the entity a frame is written onto still exists, and
        that a `/kgframes` write does not touch an entity's frame. Checked before
        the lock, a delete or an entity-frame write landing in between makes the
        answer stale by the time the write runs.

        ``replace_frame_graphs`` REPLACES WHOLE FRAME GRAPHS (`issues/256`).
        For each frame named, every subject whose `hasFrameGraphURI` is that
        frame, and the frame itself, is deleted along with `subject_uris`, so a
        slot, slot edge or anything else the frame owns that the caller did not
        re-send is GONE afterwards. Without it this deletes only the subjects
        it is given, which made frame update and upsert a MERGE: a slot left
        out of the request survived, still attached. `hasFrameGraphURI` IS the
        frame graph (decided 2026-10-03); a parent -> child `Edge_hasKGFrame`
        carries none, so child frames and their links are never in it and the
        replace stays shallow. The members are resolved INSIDE the transaction,
        after the lock, so a slot added concurrently cannot slip between the
        read and the delete.

        ``removed_uris``, if given, receives after the commit the URI of every
        subject this deleted that the caller did not re-send, so the caller's
        auto-sync can clear their vector, geo and fuzzy rows. Their FTS rows are
        cleared here, in the transaction.

        Subject-level delete + insert in a single transaction.  Avoids the
        fragile quad-level UUID matching in ``remove_rdf_quads_batch_bulk``.
        Used by frame create/update paths where the subject URIs are known.

        ``guard_subject`` AND ``stamp_subjects`` ARE DIFFERENT QUESTIONS, and
        collapsing them into one parameter built a trap (`issues/253`). The guard
        compares ONE subject — a precondition over several has no meaning, so a
        caller writing many frames must either pick one or go unconditional. The
        stamp advances the version of EVERY subject this write changed, which is
        what the next caller reads. With one parameter for both, a write touching
        several frames could only stamp one of them, so the others came out of a
        successful write with their version unchanged — and a caller polling that
        version would see "nobody wrote" and overwrite, which is the lost update
        this whole mechanism exists to stop, reintroduced by the fix.

        `stamp_subjects` defaults to `[guard_subject]`, so guarding one subject
        keeps advancing it without the caller saying so twice.

        ``lock_uris`` SERIALISES ON THE GROUPING, not on the subjects being
        written (`issues/174`). This transaction was already atomic; it was not
        exclusive, which is the same gap `update_entity_graph` had. The key must
        be what OWNS these subjects — the entity for an entity-scoped frame, the
        frame itself for a standalone one — because entity upsert and
        entity-graph delete hold the entity key, and advisory locks only exclude
        writers that share a key. Locking the frame subjects instead would
        contend with nobody while looking correct.

        Do NOT derive the key from `hasKGFormType`: a frame whose form type is
        unset defaults to Assertion while still being entity-scoped, and on the
        production space that is roughly 275,000 of 482,000 frames. The caller
        knows which grouping it is writing; that is where the decision belongs.
        """
        import time as _time
        # PHASE MARKS, and they are kept OUTSIDE the `try` on purpose: the losses
        # this exists to explain all END IN AN EXCEPTION (`issues/253`), so a
        # breakdown logged only on the happy path would miss every one of them.
        # `_mark` records when a phase COMPLETED; a phase that never completed is
        # absent, and its absence is the answer — it says where the request
        # stopped.
        #
        # WHY THESE PHASES. Production loses writes to
        # `idle_in_transaction_session_timeout`: the transaction is open, NO
        # statement is running, and nothing arrives for 60 s. The database log
        # cannot show that (three of four killed sessions have no slow statement
        # at all) and the four scans are already timed, so what is missing is the
        # time around them — acquiring the connection, BEGIN, the lock, the two
        # prop-sort syncs, the insert, and the COMMIT.
        _marks: Dict[str, float] = {}

        def _mark(name: str) -> None:
            _marks[name] = _time.monotonic()

        try:
            if not subject_uris and not insert_quads:
                return True
            _t0 = _time.monotonic()
            schema = self.backend.schema
            t = schema.get_table_names(space_id)
            from ..db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid

            g_uuid = _generate_term_uuid(graph_id, 'U')
            s_uuids = [_generate_term_uuid(uri, 'U') for uri in subject_uris]

            _removed: List[str] = []

            async with _write_conn(self.backend.db_impl.connection_pool, conn) as conn:
                _mark("acquire")

                async def _txn() -> None:
                    async with conn.transaction():
                        _mark("begin")
                        if lock_uris:
                            from ..db.sparql_sql.entity_lock import lock_entities
                            await lock_entities(conn, lock_uris)
                        _mark("lock")
                        if precheck is not None:
                            await precheck(conn)

                        # COMPARE-AND-SET, under the lock and in this
                        # transaction (`issues/253`). Anywhere else is a race:
                        # the endpoint stamps this property AFTER the write and
                        # OUTSIDE the lock, so the next writer can read a value
                        # its predecessor has not published yet.
                        # SUBJECT, not entity: the entity-frame routes pass the
                        # owning entity, the standalone-frame routes pass the
                        # frame, because they have no entity to pass.
                        _guard = guard_subject or (lock_uris[0] if lock_uris else None)
                        if if_unmodified_since is not None:
                            # RAISE rather than skip when there is nothing to
                            # compare against (`issues/253`). This read
                            # `if _guard and if_unmodified_since is not None`,
                            # so a caller that passed a precondition with
                            # neither `guard_subject` nor `lock_uris` had the
                            # comparison SILENTLY DROPPED and got a success for
                            # an unconditional write — the one shape this whole
                            # mechanism exists to prevent, and the shape the
                            # deploy note calls worse than not shipping the
                            # feature because it looks like it works.
                            #
                            # Unreachable today: every call site passes
                            # `guard_subject` equal to its single lock URI, from
                            # required route parameters. So this is a wiring
                            # error in a FUTURE call site rather than a caller
                            # mistake — which is why it is not a 4xx like
                            # `AmbiguousPrecondition` (that one IS the caller's
                            # doing). It answers STORE_FAILED in a 200, naming
                            # the subjects: a wiring error is still a
                            # DESCRIBABLE DATA REASON, and this codebase
                            # reserves non-200 for the service itself failing.
                            # An earlier version of this comment said 500, and
                            # a reviewer reading it recommended a change that
                            # would have produced one.
                            if not _guard:
                                raise UnguardableWrite(subject_uris)
                            await _compare_stamp(
                                conn, space_id, graph_id, _guard,
                                if_unmodified_since)
                            _marks["guard"] = _time.monotonic()

                        # The FRAME GRAPHS being replaced (`issues/256`). The
                        # frames themselves are included even without a
                        # self-grouping, so a frame stored before its grouping
                        # was set is still replaced, not merged.
                        _del = list(s_uuids)
                        if replace_frame_graphs:
                            _f_uuids = [_generate_term_uuid(u, 'U')
                                        for u in replace_frame_graphs]
                            _members = await conn.fetch(
                                f"SELECT DISTINCT subject_uuid FROM {t['rdf_quad']} "
                                f"WHERE predicate_uuid = $1 AND object_uuid = ANY($2) "
                                f"AND context_uuid = $3",
                                _generate_term_uuid(HAS_FRAME_GRAPH_URI, 'U'),
                                _f_uuids, g_uuid)
                            _sent = set(s_uuids)
                            _extra = list(dict.fromkeys(
                                [u for u in _f_uuids if u not in _sent]
                                + [r['subject_uuid'] for r in _members
                                   if r['subject_uuid'] not in _sent]))
                            if _extra:
                                _del += _extra
                                _removed[:] = [r['term_text'] for r in await conn.fetch(
                                    f"SELECT term_text FROM {t['term']} "
                                    f"WHERE term_uuid = ANY($1)", _extra)]
                                from ..db.sparql_sql.sync_fts_delete import sync_fts_before_delete
                                await sync_fts_before_delete(
                                    conn, space_id, _extra, context_uuid=g_uuid)
                            _marks["resolve"] = _time.monotonic()

                        if _del:
                            deleted, (_tf, _te, _ts, _td) = await _delete_subjects_synced(
                                conn, space_id, t, _del, g_uuid)
                            self.logger.info(
                                "⏱️  update_subjects_graph presync: frame_entity=%.3fs "
                                "edge=%.3fs stats=%.3fs delete=%.3fs "
                                "(%d subjects, %d quads deleted)",
                                _tf, _te, _ts, _td, len(_del), deleted)
                        _mark("presync")

                        # Insert new quads
                        if insert_quads:
                            await self.backend.add_rdf_quads_batch_bulk(
                                space_id, insert_quads, connection=conn)
                        _mark("insert")

                        # AFTER the insert, for the reason in `_stamp_subject`:
                        # a standalone frame guards on itself, so a stamp
                        # written before the delete above would not survive it.
                        #
                        # EVERY subject whose version this write advanced, not
                        # just the guarded one — see the note on the parameters.
                        _to_stamp = (stamp_subjects if stamp_subjects is not None
                                     else ([guard_subject] if guard_subject else []))
                        for _s in _to_stamp:
                            await _stamp_subject(conn, space_id, graph_id, _s)
                        if _to_stamp:
                            _marks["stamp"] = _time.monotonic()

                # BOUNDED AS A WHOLE, measured from entry so the acquire counts
                # too (`issues/253`). `wait_for` and not a cooperative check
                # between phases: the parks that cost production its writes were
                # parks INSIDE an await that never returned, which a check can
                # only notice once the await comes back — by which time
                # PostgreSQL has already destroyed the connection.
                _budget = _write_deadline_s()
                if _budget <= 0:
                    await _txn()
                else:
                    _left = _budget - (_time.monotonic() - _t0)
                    try:
                        await asyncio.wait_for(_txn(), max(0.001, _left))
                    except (asyncio.TimeoutError, TimeoutError):
                        raise WriteDeadlineExceeded(
                            _time.monotonic() - _t0, _budget,
                            _phase_breakdown(_t0, _marks)) from None
                # The COMMIT itself, which is the one phase that happens after
                # the last statement the database will ever log for this session.
                _mark("commit")

            # After the commit, so a failed transaction reports nothing removed.
            if removed_uris is not None:
                removed_uris.extend(_removed)
            _t1 = _time.monotonic()
            self.logger.info("⏱️  update_subjects_graph: %.3fs (%d subjects) %s",
                             _t1 - _t0, len(subject_uris),
                             _phase_breakdown(_t0, _marks))
            return True
        except StaleWrite as e:
            # REFUSED, not applied over the top. A domain outcome the caller can
            # act on: re-read, re-merge, retry.
            self.logger.warning("update_subjects_graph REFUSED (stale): %s", e)
            raise
        except RequestRefused:
            # A `precheck` refusal (`issues/256`), or an `UngroupableSlot` the
            # day a caller assigns groupings closer in. Either way the caller's
            # to fix, so it leaves as itself: the broad handler below would turn
            # it into a generic failure with the reason in the log.
            raise
        except GuardUnsatisfiable as e:
            # UNDECIDABLE, so nothing was written. Re-raised rather than
            # collapsed into the `False` below, because these carry the only
            # description of what went wrong and `STORE_FAILED` promises the
            # body will have one. Collapsed, the caller built a fresh
            # `SubjectWriteFailed("slot update", N)` and the cause lived only in
            # the log.
            self.logger.error("update_subjects_graph UNDECIDABLE: %s", e)
            raise
        except WriteDeadlineExceeded as e:
            # Reported, not silent — which is the whole difference from the
            # losses this came out of: the transaction rolled back on a LIVE
            # connection and the caller is told, with the phase that parked.
            self.logger.error(
                "update_subjects_graph DEADLINE: %s (%d subject(s) NOT written)",
                e, len(subject_uris))
            return False
        except EntityLockTimeout as e:
            return self._lock_timeout_failed(
                "update_subjects_graph", e, len(subject_uris),
                phases=_phase_breakdown(_t0, _marks))
        except Exception as e:
            self.logger.error("update_subjects_graph failed: %s | %s",
                              describe_exception(e),
                              _phase_breakdown(_t0, _marks))
            return False

    async def delete_entity_graph_direct(self, space_id: str, graph_id: str,
                                          entity_uri: str,
                                          collected_uris: Optional[List[str]] = None,
                                          if_unmodified_since: Optional[str] = None,
                                          entity_only: bool = False) -> int:
        """Delete entire entity graph via direct SQL (no SPARQL pipeline).

        `entity_only` deletes the entity subject alone and REFUSES
        (`DeleteRefused`) when the entity has members; `if_unmodified_since`
        guards on the entity's stamp. Both are decided in the delete's own
        transaction, under the entity lock — see `delete_entity_graph_bulk`.

        Returns the quads deleted; 0 means the entity graph was ABSENT. A
        failure RAISES. This used to log and return 0, which made a failed
        delete and an absent entity the same answer, so the endpoint could only
        report both as STORE_FAILED (`issues/256`). `delete_entity_graph_bulk`
        raises for exactly this reason (its own comment, `issues/100`).
        """
        try:
            return await self.backend.delete_entity_graph_bulk(
                space_id, graph_id, entity_uri, collected_uris=collected_uris,
                if_unmodified_since=if_unmodified_since, entity_only=entity_only)
        except (StaleWrite, GuardUnsatisfiable, RequestRefused):
            raise
        except Exception as e:
            self.logger.error("delete_entity_graph_direct failed: %s", e)
            raise

    async def delete_frame_subtrees(self, space_id: str, graph_id: str,
                                    frame_uris: List[str], *,
                                    recursive: bool = False,
                                    owner_entity_uri: Optional[str] = None,
                                    if_unmodified_since: Optional[str] = None,
                                    guard_subject: Optional[str] = None,
                                    conn=None,
                                    insert_quads: Optional[list] = None,
                                    insert_subjects: Optional[List[str]] = None,
                                    keep_outside_links: bool = False,
                                    lock_extra: Optional[List[str]] = None,
                                    stamp_subjects: Optional[List[str]] = None,
                                    precheck=None) -> "FrameSubtreeDelete":
        """Delete frames and everything they own, in ONE locked transaction.

        REPLACE IS THIS WITH SOMETHING TO INSERT (`issues/256` item 4). Given
        `insert_quads`, the same transaction then writes them, so a refused or
        failed replace leaves the old subtree exactly as it was — the two replace
        routes deleted with separate statements first and could leave neither the
        old frames nor the new. For a replace:
        - `insert_subjects` are deleted too, so nothing stale survives a rewrite;
        - frames that do not exist yet are not ABSENT but created, and a guard is
          compared whenever something is written, as the writes do;
        - `keep_outside_links` keeps a link into a root from a frame or entity
          OUTSIDE the subtree, so a replace that does not re-send its parent link
          stays attached. A request that re-creates the link passes False;
        - `lock_extra` adds lock keys (the frames being written), and
          `stamp_subjects` the subjects whose version the write advances.
        `precheck(conn)` runs after the lock, as in `update_subjects_graph`.

        `issues/256`. Both frame delete routes come here. They were two
        implementations — SPARQL discovery then a quad-level `DELETE DATA` on
        the entity route, five SPARQL updates per frame on `/kgframes` — with no
        lock, and discovery outside the delete, so a frame write landing in
        between left its new slots behind, and a failure part-way through a
        recursive delete left half a subtree.

        Everything is decided INSIDE the transaction, after the lock:

        - which requested frames exist. One that does not is ABSENT, which is
          not a failure (NO_OP);
        - ownership. On the entity route (`owner_entity_uri` given) every
          existing requested frame must belong to that entity — a root through
          `Edge_hasEntityKGFrame`, a child through `hasKGGraphURI`. On
          `/kgframes` (no owner) NO frame in the subtree may belong to an entity:
          that route does not take the entity's lock, so it cannot safely touch
          one. Either violation refuses the WHOLE request (`DeleteRefused`), so
          the outcome cannot depend on the order the frames were named in;
        - children. Without `recursive`, a frame with a child frame refuses the
          request; with it, every descendant is in the subtree;
        - the guard, compared after the lock as the writes do. Only when
          something requested exists: deleting what is already gone has done
          what was asked, even if someone else did it (NO_OP, not CONFLICT).

        THE LOCK. The entity route locks the ENTITY, the key every entity-frame
        write takes (`issues/174`). `/kgframes` locks every frame in the
        subtree, because a write to a descendant locks on its own grouping and
        must be excluded too. That set is only known by reading, so it is read,
        locked, and read again until no new frame appears.

        THE DELETE SET: every subtree frame, every subject grouped with one
        (`hasFrameGraphURI`), every edge out of one, and every
        `Edge_hasKGFrame` / `Edge_hasEntityKGFrame` into one — including the
        link from a parent outside the subtree, which would otherwise point at
        nothing. Subject-level, with the aux tables and FTS kept in step, as
        `update_subjects_graph` does.

        On the entity route the entity's modification time is advanced in the
        same transaction, so the next guarded writer sees the delete. It was
        stamped after the commit, outside the lock.

        Returns what was deleted, what was absent, and the URI of every subject
        removed, so the caller's auto-sync can clear vector, geo and fuzzy rows
        for the slots too and not only the frames.
        """
        from ..db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
        from ..db.sparql_sql.entity_lock import lock_entities
        from ..db.sparql_sql.sync_fts_delete import sync_fts_before_delete

        def U(uri):
            return _generate_term_uuid(uri, 'U')

        t = self.backend.schema.get_table_names(space_id)
        q = t['rdf_quad']
        g = U(graph_id)
        p_vt, p_src, p_dst = U(VITALTYPE_URI), U(HAS_EDGE_SOURCE), U(HAS_EDGE_DESTINATION)
        p_kgg, p_fg = U(HAS_KG_GRAPH_URI), U(HAS_FRAME_GRAPH_URI)
        t_child, t_link = U(EDGE_HAS_KG_FRAME), U(EDGE_HAS_ENTITY_KG_FRAME)
        roots = list(dict.fromkeys(str(u) for u in frame_uris))
        uri_of = {U(u): u for u in roots}
        guard = guard_subject or owner_entity_uri

        async def _texts(c, uuids) -> Dict[Any, str]:
            if not uuids:
                return {}
            rows = await c.fetch(
                f"SELECT term_uuid, term_text FROM {t['term']} WHERE term_uuid = ANY($1)",
                list(uuids))
            return {r['term_uuid']: r['term_text'] for r in rows}

        # EVERY QUERY BELOW STARTS FROM THE FRAMES BEING DELETED and looks each
        # candidate edge up by SUBJECT. Written as plain joins, the planner hashed
        # every `Edge_hasKGFrame` / `Edge_hasEntityKGFrame` type row in the space
        # instead — ~570,000 on the dev wordnet space — on every delete. The
        # MATERIALIZED candidate set and the LATERAL ... LIMIT 1 type checks are
        # what hold the plan to index lookups (checked with GENERIC_PLAN on the
        # largest dev space, 2026-10-04).

        async def _children(c, frontier) -> Dict[Any, List[Any]]:
            """{frame -> its child frames}, through `Edge_hasKGFrame`."""
            rows = await c.fetch(
                f"WITH s AS MATERIALIZED ("
                f" SELECT subject_uuid, object_uuid AS parent FROM {q} "
                f" WHERE predicate_uuid = $1 AND object_uuid = ANY($2) "
                f" AND context_uuid = $6) "
                f"SELECT DISTINCT s.parent, d.object_uuid AS child FROM s "
                f"CROSS JOIN LATERAL (SELECT 1 FROM {q} vt "
                f" WHERE vt.subject_uuid = s.subject_uuid AND vt.context_uuid = $6 "
                f" AND vt.predicate_uuid = $3 AND vt.object_uuid = $4 LIMIT 1) is_child "
                f"JOIN {q} d ON d.subject_uuid = s.subject_uuid "
                f" AND d.context_uuid = $6 AND d.predicate_uuid = $5",
                p_src, list(frontier), p_vt, t_child, p_dst, g)
            out: Dict[Any, List[Any]] = {}
            for r in rows:
                out.setdefault(r['parent'], []).append(r['child'])
            return out

        async def _resolve(c):
            """(present roots, subtree) as they stand now."""
            present = {r['subject_uuid'] for r in await c.fetch(
                f"SELECT DISTINCT subject_uuid FROM {q} "
                f"WHERE subject_uuid = ANY($1) AND context_uuid = $2",
                list(uri_of), g)}
            subtree = list(present)
            if present:
                kids = await _children(c, present)
                if kids and not recursive:
                    raise DeleteRefused(
                        "Cannot delete frames with children (use recursive=true "
                        "to cascade): " + "; ".join(
                            f"{uri_of[f]} has {len(k)} child(ren)"
                            for f, k in kids.items()))
                seen = set(subtree)
                frontier = [k for ks in kids.values() for k in ks if k not in seen]
                while frontier:
                    seen.update(frontier)
                    subtree.extend(frontier)
                    nxt = await _children(c, frontier)
                    frontier = list(dict.fromkeys(
                        k for ks in nxt.values() for k in ks if k not in seen))
            return present, subtree

        async def _do(c) -> "FrameSubtreeDelete":
            if owner_entity_uri is not None:
                await lock_entities(c, [owner_entity_uri])
                present, subtree = await _resolve(c)
            else:
                # Read, lock, read again until the subtree stops growing. Locks
                # are only ever added, and `lock_entities` orders each batch.
                # The first batch carries `lock_extra` too, so a replace takes
                # every key it knows of in one ordered call.
                locked: set = set()
                extra = [U(u) for u in (lock_extra or [])]
                extra_names = {U(u): u for u in (lock_extra or [])}
                present, subtree = await _resolve(c)
                while True:
                    todo = list(dict.fromkeys(
                        [s for s in list(subtree) + extra if s not in locked]))
                    if not todo:
                        break
                    names = await _texts(c, todo)
                    await lock_entities(c, [names.get(s) or uri_of.get(s)
                                            or extra_names.get(s) or str(s)
                                            for s in todo])
                    locked.update(todo)
                    present, subtree = await _resolve(c)
            if precheck is not None:
                await precheck(c)

            absent = [u for u in roots if U(u) not in present]
            if not present and not insert_quads:
                return FrameSubtreeDelete([], absent, [])

            if owner_entity_uri is not None:
                e = U(owner_entity_uri)
                owned = await owned_by_entity(c, space_id, graph_id,
                                              owner_entity_uri, list(present))
                foreign = [uri_of[f] for f in present if f not in owned]
                if foreign:
                    raise DeleteRefused(
                        f"{len(foreign)} frame(s) do not belong to entity "
                        f"{owner_entity_uri}; nothing was deleted: "
                        + ", ".join(foreign[:5]))
            else:
                # Every frame in the subtree, not only the roots: a recursive
                # delete or replace would otherwise reach an entity's frame
                # through a standalone parent.
                names = await _texts(c, subtree)
                await refuse_entity_frames(
                    c, space_id, graph_id,
                    [names.get(f) or uri_of.get(f) for f in subtree
                     if names.get(f) or uri_of.get(f)])

            if if_unmodified_since is not None and (present or insert_quads):
                if not guard:
                    raise UnguardableWrite(roots)
                await _compare_stamp(c, space_id, graph_id, guard,
                                     if_unmodified_since)

            # The delete set. Grouped members, edges out of a subtree frame, and
            # the frame links INTO one.
            members = await c.fetch(
                f"SELECT DISTINCT subject_uuid FROM {q} "
                f"WHERE predicate_uuid = $1 AND object_uuid = ANY($2) "
                f"AND context_uuid = $3",
                p_fg, subtree, g)
            edges = await c.fetch(
                f"WITH e AS MATERIALIZED ("
                f" SELECT subject_uuid, predicate_uuid FROM {q} "
                f" WHERE context_uuid = $3 AND object_uuid = ANY($2) "
                f" AND predicate_uuid IN ($1, $4)) "
                f"SELECT DISTINCT e.subject_uuid FROM e "
                f"LEFT JOIN LATERAL (SELECT 1 AS ok FROM {q} vt "
                f" WHERE vt.subject_uuid = e.subject_uuid AND vt.context_uuid = $3 "
                f" AND vt.predicate_uuid = $5 AND vt.object_uuid = ANY($6) LIMIT 1) link "
                f" ON true "
                f"WHERE e.predicate_uuid = $1 OR link.ok IS NOT NULL",
                p_src, subtree, g, p_dst, p_vt, [t_child, t_link])
            ins = [U(u) for u in (insert_subjects or [])]
            edge_uuids = [r['subject_uuid'] for r in edges]
            if keep_outside_links and edge_uuids:
                # A link INTO the subtree from outside it: its source is not a
                # subtree frame. Kept unless the request rewrites it.
                outside = {r['subject_uuid'] for r in await c.fetch(
                    f"SELECT subject_uuid FROM {q} WHERE subject_uuid = ANY($1) "
                    f"AND predicate_uuid = $2 AND context_uuid = $3 "
                    f"AND NOT (object_uuid = ANY($4))",
                    edge_uuids, p_src, g, list(subtree))}
                keep = outside - set(ins)
                edge_uuids = [e for e in edge_uuids if e not in keep]
            _del = list(dict.fromkeys(
                list(subtree) + [r['subject_uuid'] for r in members]
                + edge_uuids + ins))
            names = await _texts(c, _del)

            deleted = 0
            if _del:
                await sync_fts_before_delete(c, space_id, _del, context_uuid=g)
                deleted, _ = await _delete_subjects_synced(c, space_id, t, _del, g)
            if insert_quads:
                await self.backend.add_rdf_quads_batch_bulk(
                    space_id, insert_quads, connection=c)
            for _s in (stamp_subjects if stamp_subjects is not None
                       else ([owner_entity_uri] if owner_entity_uri else [])):
                await _stamp_subject(c, space_id, graph_id, _s)
            self.logger.info(
                "delete_frame_subtrees: %d frame(s), %d subject(s), %d quad(s)",
                len(subtree), len(_del), deleted)
            return FrameSubtreeDelete(
                [names.get(f) or uri_of.get(f) for f in subtree], absent,
                [names[s] for s in _del if s in names])

        async with _write_conn(self.backend.db_impl.connection_pool, conn) as c:
            async with c.transaction():
                return await _do(c)

    # ------------------------------------------------------------------
    # remove_rdf_quads_batch
    # ------------------------------------------------------------------

    async def remove_rdf_quads_batch(self, space_id: str, quads: List[tuple]) -> int:
        try:
            return await self.backend.remove_rdf_quads_batch(space_id, quads)
        except Exception as e:
            self.logger.error("remove_rdf_quads_batch failed: %s", e)
            return 0

    # ------------------------------------------------------------------
    # get_objects_by_uris
    # ------------------------------------------------------------------

    async def get_objects_by_uris(self, space_id: str, uris: List[str],
                                  graph_id: Optional[str] = None) -> List[GraphObject]:
        """Retrieve multiple objects by URI list as VitalSigns GraphObjects."""
        return await self.backend.db_objects.get_objects_by_uris(space_id, uris, graph_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _triples_to_vitalsigns(self, triples: List[tuple]) -> List[GraphObject]:
        try:
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            if not triples:
                return []
            vs = VitalSigns()
            objects = await asyncio.to_thread(vs.from_triples_list, (t for t in triples))
            return cast(List[GraphObject], objects)
        except Exception as e:
            self.logger.error("_triples_to_vitalsigns failed: %s", e)
            return []


def create_backend_adapter(backend_impl) -> KGBackendInterface:
    """Return the `KGBackendInterface` adapter for a space backend.

    Dispatches on the backend's TYPE, not on a substring of its class name.
    `issues/241`: the name-substring form defaulted to the RETIRED backend's
    adapter, so an unrecognised backend was silently adapted as a store it had
    nothing to do with — and a rename of `SparqlSQLSpaceImpl` would have been
    enough to trigger it, with no import error and no failing test to say so.

    Unknown backends RAISE. There is one adapter and guessing is what the old
    default did; a caller that reaches here with something else needs to know,
    not to be handed the only adapter that happens to exist.
    """
    from ..db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl

    # IDEMPOTENT. Several callers take a `backend` parameter that is ALREADY an
    # adapter and hand it straight back in — `_get_specific_frame_graphs` is one.
    # The old name-substring dispatch matched `SparqlSQLBackendAdapter` too and
    # silently wrapped an adapter in an adapter, which happened to work because
    # the adapter delegates through `self.backend`. Rejecting it instead broke
    # those callers (`issues/243`), so this returns it unchanged: correct for
    # them, and strictly better than the double wrap it replaces.
    if isinstance(backend_impl, KGBackendInterface):
        return backend_impl

    if isinstance(backend_impl, SparqlSQLSpaceImpl):
        return SparqlSQLBackendAdapter(backend_impl)

    raise TypeError(
        f"No KG backend adapter for {type(backend_impl).__name__}. "
        f"Supported: SparqlSQLSpaceImpl, or an already-built adapter.")
