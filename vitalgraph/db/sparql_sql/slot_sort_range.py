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
import os
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

# Only the ordering comparators. Equality is deliberately excluded HERE: it
# already reaches the term semi-join with an accurate estimate, and it is the
# shape the criterion gate is built around.
#
# That rationale holds for the shapes it was written about and NOT for the
# production Nurture shape, where an equality on a URI slot value timed out at
# 55s while the same answer driven from the slot set measured 519 ms
# (`issues/162`). Equality is served by `slot_equality_constraints` below, on
# its own lane map, so this decision is narrowed rather than overturned.
RANGE_OPS = {">=", ">", "<=", "<"}

# Lanes for EQUALITY narrowing. Separate from `VALUE_LANE` on purpose: adding
# text predicates there would also admit them to the RANGE path, where `>=` on a
# lexical form is valid SQL and almost never the intended comparison, and where
# `_is_selective` reasons in numeric terms.
#
# Text covers the URI and string-shaped slots — `entity_slot_sort.value_text`
# stores the lexical form for all of them, which is why the campaign URI matches
# `value_text = 'urn:acme:campaign:000'` exactly.
EQUALITY_LANE = dict(VALUE_LANE)
for _eq_n in ("Text", "Uri", "Choice", "Json", "Boolean", "Code", "LongText",
              "MultiChoice", "MultiTaxonomy", "Taxonomy", "Audio", "Image",
              "Video", "FileUpload", "GeoLocation", "PropertyFrameType", "Run",
              "Entity"):
    EQUALITY_LANE[f"{_H}has{_eq_n}SlotValue"] = "value_text"

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
    """`__CONST_c_N__` token -> the URI it stands for. URIs ONLY.

    Predicates are always URIs, which is what this is for. It must not be used
    to read a slot VALUE: a text slot's value is a LITERAL, `.get()` returns the
    default, and the caller silently compares against an empty string. That is
    exactly what happened — `value_text = ''` matched nothing and the
    intersection removed every row, turning a 1-row answer into 0
    (`issues/162`). Use `_const_terms` for anything that may be a literal.
    """
    return {col: text for (text, ttype, _lg, _dt), col in aliases.constants.items()
            if ttype == "U"}


def _const_terms(aliases) -> dict:
    """`__CONST_c_N__` token -> its lexical form, WHATEVER the term type.

    `entity_slot_sort.value_text` stores the lexical form for URIs and literals
    alike, so a value comparison needs the text of both. Keeping this separate
    from `_const_uris` rather than widening it: predicate lookups genuinely want
    URIs only, and a literal predicate would be a different bug.
    """
    return {col: text
            for (text, _tt, _lg, _dt), col in aliases.constants.items()}


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


# OFF BY DEFAULT — `slot_equality_constraints` RETURNS WRONG ROWS.
#
# Measured 2026-09-05 on `lead_nurture_100k`: `SFLeadId = "SYN000000000"`
# returned 0 where the correct answer is 1, in 238 ms. The narrowing is an
# INTERSECTION, so a mistake in it silently REMOVES rows — a fast, confident,
# empty result with no error, which is the worst failure mode available here and
# strictly worse than the 55s timeout it was built to fix.
#
# Kept rather than reverted (`issues/162`) so the diagnosis has something to run
# against, but a wrong answer is not a tuning problem and this must not be the
# default until the cause is found and a correctness test pins it.
EQUALITY_NARROWING_ENABLED = (
    os.getenv("VG_SLOT_SORT_EQUALITY_NARROWING", "0") == "1")


def slot_equality_constraints(bgp, aliases, space_id: str) -> list:
    """`[(alias, sql)]` narrowing each slot fixed to a CONSTANT value.

    DISABLED by default — see `EQUALITY_NARROWING_ENABLED`. It returns wrong
    rows on at least one measured shape.

    The equality twin of `slot_range_constraint`, and sound for the same reason:
    it ADDS a constraint the chain already implies, anchored on the SLOT.

        ?slot hasKGSlotType <T> . ?slot has<X>SlotValue <V>

    already requires `?slot` to be a slot of type T whose value is V, and
    `entity_slot_sort` is keyed on `(slot_uuid, context_uuid)` with that slot's
    type and value on the row. So

        <slot>.<col> IN (SELECT slot_uuid FROM {space}_entity_slot_sort
                         WHERE slot_type_uuid = <T> AND value_text = '<V>')

    cannot change the answer; it can only hand PostgreSQL a small indexed set to
    drive from. Nothing is replaced and no var_slot is dropped.

    WHY THIS RATHER THAN A REWRITE. Collapsing the walk onto `entity_slot_sort`
    outright would have to re-home the edge variables (`?frame_edge_0` binds
    `edge_uuid`, which this table does not have), translate a term-uuid constant
    into the TEXT the value column stores, and match `frame_type_path` exactly —
    where a near-miss returns WRONG ROWS. Anchoring on the slot needs none of
    that: the slot identity carries no path.

    WHY THE VALUE IS A LITERAL AND NOT A `__CONST__` TOKEN. Those tokens resolve
    to TERM UUIDS; `value_text` holds the lexical form. Comparing the two matches
    nothing and would return a confident empty result — the worst failure
    available here — so the text is taken from the constant map and quoted.

    Measured on `lead_nurture_100k` (53M quads), the shape this exists for:
    the edge walk timed out at 55s; the same answer driven from the slot set is
    519 ms by hand (`issues/161`).
    """
    if not EQUALITY_NARROWING_ENABLED:
        return []

    const = _const_uris(aliases)        # predicates: URIs
    terms = _const_terms(aliases)       # values: URI or literal
    if not const:
        return []

    pred_of, obj_of, obj_token = {}, {}, {}
    for _owner, sql in (bgp.tagged_constraints or []):
        m = _PRED_RE.search(sql)
        if m:
            pred_of[m.group(1)] = const.get(m.group(2), "")
        m = _OBJ_RE.search(sql)
        if m:
            # From `terms`, not `const`: a literal is not in the URI map and
            # would read as "" — see `_const_uris`.
            if m.group(2) in terms:
                obj_of[m.group(1)] = terms[m.group(2)]
                obj_token[m.group(1)] = f"__CONST_{m.group(2)}__"
    for (alias, col), _t in (bgp.leaf_terms or {}).items():
        text, ttype = _t[0], _t[1]
        if col == "predicate_uuid":
            pred_of.setdefault(alias, text)
        elif col == "object_uuid":
            obj_of.setdefault(alias, text)

    out = []
    seen = set()
    for alias, pred_uri in pred_of.items():
        lane = EQUALITY_LANE.get(pred_uri)
        if not lane:
            continue
        # The value must be a CONSTANT here — that is what makes it an equality
        # rather than the FILTER shape `slot_range_constraint` serves.
        value_text = obj_of.get(alias)
        if not value_text or obj_token.get(alias) is None:
            # An EMPTY value is the signature of a constant that could not be
            # resolved. Emitting `value_text = ''` would match nothing and, in
            # an intersection, delete every row.
            continue

        # Its subject is the slot; that slot must also carry a constant type.
        slot_var = None
        for var, vslot in (bgp.var_slots or {}).items():
            if any(a == alias and c == "subject_uuid"
                   for a, c in (vslot.positions or [])):
                slot_var = var
                break
        if not slot_var:
            continue
        sslot = (bgp.var_slots or {}).get(slot_var)
        type_token = None
        for a, c in (sslot.positions or []):
            if c == "subject_uuid" and pred_of.get(a) == SLOT_TYPE_PRED:
                type_token = obj_token.get(a)
                if type_token:
                    break
        if not type_token:
            continue

        anchor = next(((a, c) for a, c in (sslot.positions or [])
                       if c == "subject_uuid"), None)
        if anchor is None:
            continue

        if lane != "value_text":
            # Numeric/datetime equality needs the literal in that column's type
            # and a quoted lexical form would not compare. Deferred, not
            # rejected — `issues/162` records it as unmeasured.
            continue

        ess = f"{space_id}_entity_slot_sort"
        lit = str(value_text).replace("'", "''")
        sql = (f"{anchor[0]}.{anchor[1]} IN (SELECT slot_uuid FROM {ess} "
               f"WHERE slot_type_uuid = {type_token} "
               f"AND value_text = '{lit}')")
        key = (anchor[0], sql)
        if key not in seen:
            seen.add(key)
            out.append(key)
            logger.debug("slot-sort equality: %s = %s narrowed via %s",
                         slot_var, value_text, ess)
    return out
