"""Give a slot-value range criterion something selective to drive from.

`issues/111`. A KGQuery range criterion compiles to a chain of edge and quad hops
ending in `?slot hasKGSlotType <T> . ?slot has<X>SlotValue ?v . FILTER(?v >= L)`.
The FILTER pushes down to a term semi-join on `num_val`, which is correct and
still leaves the planner nothing selective to start from: measured on
`sp_lead_synth_100k`, `MQLRating >= 99` spends half its 1.9 s in one Hash Join
and a fifth SEQUENTIALLY SCANNING all 1.66M edge rows, to return 1,017 rows.

That is the trap `emit_slice._try_selective_driven` documents from the other
side — the semi-join gate correctly declines to probe, and the set-based join it
falls back to materialises the large criterion. Neither plan fits.

`{space}_entity_slot_sort` already holds the answer. One row per
(slot, context) with the value split into `value_text`/`value_num`/`value_dt`,
and an index built for exactly this:

    idx_{space}_ess_num  btree (context_uuid, entity_type_uuid, frame_type_path,
                                slot_type_uuid, value_num, entity_uuid)
                         WHERE value_num IS NOT NULL

Measured, the same criterion:

    entity_slot_sort   Index Only Scan, 1,017 rows      1.97 ms        736 buffers
    the edge walk                                   1,877.00 ms  1,496,337 buffers

WHY THIS IS SOUND, AND WHY IT IS NOT A REWRITE

Nothing is replaced. This ADDS a constraint the chain already implies:

    <slot_alias>.<col> IN (SELECT slot_uuid FROM {space}_entity_slot_sort
                           WHERE slot_type_uuid = <T> AND value_num >= L)

`entity_slot_sort` is keyed on the SLOT — `(slot_uuid, context_uuid)` is its
primary key — and its row carries that slot's type and value. So the set above is
precisely "slots of type T whose value is >= L", which the surrounding chain
already requires of `?slot`. The constraint cannot change the answer; it can only
give PostgreSQL a small, indexed set to drive from.

That is why this anchors on the SLOT rather than the entity. Anchoring on the
entity would need `frame_type_path` matched exactly — the index is keyed on the
whole array, and a loose match admits entities reached by a different path. Sound
only if that match is perfect, and a near-miss returns WRONG ROWS. The slot
identity needs no path at all.

The leading index columns are deliberately left unconstrained. PostgreSQL 18
skip-scans them, measured above; pinning `context_uuid` would be a small further
win and is not worth the extra decline conditions until something measures it.

FRESHNESS. `entity_slot_sort` is a derived table, write-synced in five places
(and `sync_entity_slot_sort_after_edge_insert` deletes before re-deriving, so a
CHANGED value replaces its row), with drift repaired by
`maintenance_job._run_entity_slot_sort_integrity`. This is the same bargain
`rewrite_edge_table` already makes by answering traversals from `{space}_edge` —
not a new trust tier. If the table were stale this constraint could EXCLUDE a row
the chain would have returned, so `sync_entity_slot_sort` staleness becomes a
wrong-answer risk here rather than a slow-query one. That is the one real cost of
this optimisation, and it is why it declines rather than guesses whenever the
shape is not exactly what it expects.
"""

from __future__ import annotations

import logging
import re
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

SLOT_TYPE_PRED = "http://vital.ai/ontology/haley-ai-kg#hasKGSlotType"

# Value predicate -> the column `sync_entity_slot_sort` writes it to. Anything
# absent DECLINES rather than defaulting: writing a date into the numeric lane
# would silently compare the wrong column.
_H = "http://vital.ai/ontology/haley-ai-kg#"
VALUE_LANE = {
    f"{_H}hasDoubleSlotValue": "value_num",
    f"{_H}hasIntegerSlotValue": "value_num",
    f"{_H}hasLongSlotValue": "value_num",
    f"{_H}hasCurrencySlotValue": "value_num",
    f"{_H}hasDateTimeSlotValue": "value_dt",
}

# Only the ordering comparators. Equality is deliberately excluded: it already
# reaches the term semi-join with an accurate estimate, and it is the shape the
# criterion gate is built around.
RANGE_OPS = {">=", ">", "<=", "<"}

_PRED_RE = re.compile(r"(\w+)\.predicate_uuid\s*=\s*__CONST_(c_\d+)__")
_OBJ_RE = re.compile(r"(\w+)\.object_uuid\s*=\s*__CONST_(c_\d+)__")


def _uuid_of(aliases, uri: str) -> Optional[str]:
    """The resolved term uuid for a constant URI, or None if unresolved."""
    col = (aliases.constants or {}).get((uri, "U", None, None))
    return (aliases.resolved_constants or {}).get(col) if col else None


def _is_selective(aliases, value_pred_uri: str, op: str, literal,
                  slot_total: Optional[int]) -> bool:
    """Is this range narrow enough that driving from it wins?

    THE GATE IS THE WHOLE DIFFERENCE between a 105x speed-up and a timeout.
    Measured on sp_lead_synth_100k, the same criterion at three thresholds:

        MQLRating >= 99.9   145 matches   1,886 ms ->    18 ms
        MQLRating >= 99   1,017 matches   1,877 ms ->    70 ms
        MQLRating >= 90   9,907 matches       77 ms -> TIMED OUT (>45 s)

    The narrow end is what this exists for; the loose end already has a plan that
    works, and handing it a 9,907-row IN list destroys it. `MIN_SELECTIVITY` is
    the threshold `semijoin` already uses for the same shape of decision, with
    the same reasoning ("a criterion matching 9% of entities went to 0.77x the
    baseline while one matching 0.96% went to 889x") — 1% and 10% here straddle
    it exactly.

    UNMEASURED DECLINES. Without a count there is no way to tell the 105x case
    from the timeout, and the timeout is the one that ships.
    """
    from .semijoin import MIN_SELECTIVITY

    p_uuid = _uuid_of(aliases, value_pred_uri)
    if not p_uuid:
        return False
    stats = getattr(aliases, "range_stats", None) or {}
    # THE DENOMINATOR IS THE SLOT TYPE, not the value predicate. `pred_stats`
    # for `hasDoubleSlotValue` counts EVERY double-valued slot in the space
    # across every slot type — 3.9M rows here against MQLRating's 100,000. Read
    # that way a criterion matching 9,907 rows looks like 0.25% and sails
    # through, which is exactly what happened: the loose threshold still timed
    # out with the gate in place. Against its own slot type it is 9.9% and
    # declines, and the narrow one is 1.0% and does not.
    total = slot_total
    if not total:
        return False
    for (u, o, lit), n in stats.items():
        if u == p_uuid and o == op and str(lit) == str(literal) and n is not None:
            return n < MIN_SELECTIVITY * total
    return False


def _const_uris(aliases) -> dict:
    """`__CONST_c_N__` token -> the URI it stands for."""
    return {col: text for (text, ttype, _lg, _dt), col in aliases.constants.items()
            if ttype == "U"}


def slot_range_constraint(bgp, aliases, space_id: str, value_var: str,
                          op: str, literal, value_sql=None) -> Optional[Tuple[str, str]]:
    """`(alias, sql)` narrowing the slot to those `entity_slot_sort` agrees with.

    None whenever the shape is not exactly:

        ?slot hasKGSlotType <T> .  ?slot has<X>SlotValue ?value_var

    within THIS bgp, with `<T>` a resolved constant and `has<X>SlotValue` a
    predicate whose lane is known. Every other shape declines — a constraint
    derived from a misread chain would exclude rows the query should return.
    """
    if op not in RANGE_OPS:
        return None

    const = _const_uris(aliases)

    # predicate/object constants, by quad alias, from the BGP's own constraints.
    pred_of, obj_of, obj_token = {}, {}, {}
    for _owner, sql in (bgp.tagged_constraints or []):
        m = _PRED_RE.search(sql)
        if m:
            pred_of[m.group(1)] = const.get(m.group(2), "")
        m = _OBJ_RE.search(sql)
        if m:
            obj_of[m.group(1)] = const.get(m.group(2), "")
            obj_token[m.group(1)] = f"__CONST_{m.group(2)}__"
    for (alias, col), _t in (bgp.leaf_terms or {}).items():
        text, ttype = _t[0], _t[1]
        if col == "predicate_uuid":
            pred_of.setdefault(alias, text)
        elif col == "object_uuid" and ttype == "U":
            obj_of.setdefault(alias, text)

    # The quad carrying the value: object is `value_var`, predicate is a lane.
    slot_var = lane = None
    vslot = (bgp.var_slots or {}).get(value_var)
    if not vslot or not vslot.positions:
        return None
    for alias, col in vslot.positions:
        if col != "object_uuid":
            continue
        lane = VALUE_LANE.get(pred_of.get(alias, ""))
        if not lane:
            continue
        # Its subject variable is the slot.
        for var, slot in (bgp.var_slots or {}).items():
            if any(a == alias and c == "subject_uuid" for a, c in slot.positions):
                slot_var = var
                break
        if slot_var:
            break
    if not slot_var or not lane:
        return None
    value_pred_uri = pred_of.get(alias, "")

    # The same slot must carry a CONSTANT hasKGSlotType in this bgp.
    sslot = (bgp.var_slots or {}).get(slot_var)
    if not sslot:
        return None
    type_token = None
    for alias, col in sslot.positions:
        if col == "subject_uuid" and pred_of.get(alias) == SLOT_TYPE_PRED:
            type_token = obj_token.get(alias)
            if type_token:
                break
    if not type_token:
        return None

    # How many slots of THIS type exist — the denominator the gate needs.
    # `quad_stats` is keyed by (predicate, object) uuid pair, and
    # (hasKGSlotType, <T>) is precisely "slots of type T".
    slot_total = None
    for a, c in sslot.positions:
        if c == "subject_uuid" and pred_of.get(a) == SLOT_TYPE_PRED:
            tp = _uuid_of(aliases, SLOT_TYPE_PRED)
            to = _uuid_of(aliases, obj_of.get(a, ""))
            if tp and to:
                slot_total = (getattr(aliases, "quad_stats", None) or {}).get((tp, to))
            break

    if not _is_selective(aliases, value_pred_uri, op, literal, slot_total):
        logger.debug("slot-sort range: %s %s %s over %s slots — not selective "
                     "enough to drive", value_var, op, literal, slot_total)
        return None

    # Anchor on any position of the slot variable; subject_uuid is the natural
    # one and is what the chain joins on.
    anchor = next(((a, c) for a, c in sslot.positions if c == "subject_uuid"),
                  None)
    if anchor is None:
        return None
    alias, col = anchor

    ess = f"{space_id}_entity_slot_sort"
    sql = (f"{alias}.{col} IN (SELECT slot_uuid FROM {ess} "
           f"WHERE slot_type_uuid = {type_token} "
           f"AND {lane} {op} {value_sql if value_sql is not None else literal})")
    logger.debug("slot-sort range: %s %s %s narrowed via %s", slot_var, op,
                 literal, ess)
    return (alias, sql)
