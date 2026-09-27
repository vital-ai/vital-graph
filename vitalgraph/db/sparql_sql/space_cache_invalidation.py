"""Quiesce a space and drop every process-local cache keyed by its id.

`issues/232` step 4. The rename is a catalogue operation and takes effect the
instant it commits — but the process has been caching against the OLD id, and
none of those caches notice. Left alone they are not merely stale: a term-uuid
cache keyed `(space_id, text, type)` answers for a space that no longer exists,
and the answers look perfectly normal.

WHY A COORDINATOR RATHER THAN A CALL AT EACH SITE. Nine caches, in eight modules,
with four different invalidation shapes — `invalidate_space(id)`,
`invalidate_x_cache(id)`, a bare dict, and one that had no per-space entry point
at all. The chance of a future cache being added and this list not being updated
is the whole risk, so `CACHE_INVALIDATORS` is a declared list and a test asserts
it covers every per-space cache it can find in the tree.

QUIESCE FIRST, AND WHY THE LOCKS MATTER. `process_lock_key` is a sha256 over
`{type}:{space_id}`, so a job holding the lock for the OLD id does NOT exclude a
job that starts under the NEW one. Two maintenance passes over the same physical
tables, neither aware of the other, is the failure this ordering avoids — and it
is why a rename must not be run against a space that is actively being served.
This module cancels what it can reach and REPORTS what it cannot, rather than
implying it made the space quiet.

WHAT IT CANNOT DO. Every cache here is PROCESS-LOCAL. In a multi-process or
multi-task deployment this clears one process, and the others keep their stale
entries until they are restarted or their own entries expire. That is a real
limitation of doing this in-process, stated here because the alternative — a
notification other processes act on — is a larger piece of work and `issues/232`
lists "a NEW signal carrying BOTH ids" as part of this step that is not built.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _generator_caches(space_id: str) -> int:
    from .generator import (
        invalidate_datatype_cache, invalidate_stats_cache,
        invalidate_term_cache, invalidate_value_stats_cache)
    invalidate_term_cache(space_id)
    invalidate_datatype_cache(space_id)
    invalidate_stats_cache(space_id)
    invalidate_value_stats_cache(space_id)
    return 4


def _count_cache(space_id: str) -> int:
    from vitalgraph.cache.count_cache import _count_cache
    _count_cache.invalidate_space(space_id)
    return 1


def _entity_graph_cache(space_id: str) -> int:
    from vitalgraph.cache.entity_graph_cache import _entity_graph_cache as cache
    cache.invalidate_space(space_id)
    return 1


def _provider_cache(space_id: str) -> int:
    from vitalgraph.vectorization.registry import invalidate_space
    return invalidate_space(space_id)


def _edge_fanout_slot(space_id: str) -> int:
    from vitalgraph.process import maintenance_job
    return 1 if maintenance_job._edge_fanout_slot.pop(space_id, None) is not None else 0


def _ownership_cache(space_id: str) -> int:
    from vitalgraph.kg_impl.kgentity_frame_update_impl import KGEntityFrameUpdateProcessor as P
    stale = [k for k in P._ownership_cache if k[0] == space_id]
    for k in stale:
        del P._ownership_cache[k]
    return len(stale)


def _pop(module_path: str, attr: str) -> Callable[[str], int]:
    """An invalidator for a plain `{space_id: …}` module-level dict.

    Most of these have no invalidation entry point of their own — they are bare
    dicts — so rather than adding six near-identical functions to six modules,
    the key is popped here. Generated from a path so a rename of the MODULE
    fails loudly at import rather than silently clearing nothing.
    """
    def _fn(space_id: str) -> int:
        import importlib
        mod = importlib.import_module(module_path)
        cache = getattr(mod, attr)
        return 1 if cache.pop(space_id, None) is not None else 0
    return _fn


#: (name, callable) for every process-local cache keyed by space id.
#:
#: SIX OF THESE WERE NOT IN `issues/232`'s LIST. The issue named the caches
#: someone remembered; the derived test in
#: `tests/unit/test_space_cache_invalidation.py` scans for dicts the code INDEXES
#: BY `space_id` and found six more — four of them readiness flags
#: (`_frame_slot_ready`, `_frame_slot_present`, `_prop_sort_present`,
#: `_frame_prop_sort_present`), which are the dangerous shape: a cached "this
#: table is present" for a space id whose tables have moved is a false positive
#: that selects a fast path over objects that are not there.
#:
#: DELIBERATELY ABSENT, each for a stated reason:
#:   `compile_cache`            keyed by SPARQL hash, not by space
#:   `_instance_by_signature`   keyed by (provider, config) — see registry
#:   `_IN_FLIGHT`               handled by `quiesce_space`, which CANCELS the
#:                              tasks rather than forgetting them; dropping the
#:                              dict would leak running work
#:   Redis metric keys          TTL'd, self-healing
CACHE_INVALIDATORS: List[Tuple[str, Callable[[str], int]]] = [
    ("generator.term/datatype/stats/value_stats", _generator_caches),
    ("count_cache", _count_cache),
    ("entity_graph_cache", _entity_graph_cache),
    ("vectorization.registry._provider_cache", _provider_cache),
    ("maintenance_job._edge_fanout_slot", _edge_fanout_slot),
    ("kgentity_frame_update._ownership_cache", _ownership_cache),
    # Found by the derived test, not by the issue's list.
    ("auto_analyze._change_counts",
     _pop("vitalgraph.db.sparql_sql.auto_analyze", "_change_counts")),
    ("auto_analyze._last_analyze_time",
     _pop("vitalgraph.db.sparql_sql.auto_analyze", "_last_analyze_time")),
    ("maintenance_job._recompute_slot",
     _pop("vitalgraph.process.maintenance_job", "_recompute_slot")),
    ("ensure_frame_slot_table._frame_slot_ready",
     _pop("vitalgraph.db.sparql_sql.ensure_frame_slot_table", "_frame_slot_ready")),
    ("sync_frame_slot_table._frame_slot_present",
     _pop("vitalgraph.db.sparql_sql.sync_frame_slot_table", "_frame_slot_present")),
    ("fast_prop_sort._prop_sort_present",
     _pop("vitalgraph.db.sparql_sql.fast_prop_sort", "_prop_sort_present")),
    ("fast_frame_prop_sort._frame_prop_sort_present",
     _pop("vitalgraph.db.sparql_sql.fast_frame_prop_sort",
          "_frame_prop_sort_present")),
]


async def quiesce_space(space_id: str, conn=None) -> Dict[str, Any]:
    """Stop what can be stopped, and report what cannot.

    Returns `{cancelled, locks_held}`. `locks_held` naming anything is a reason
    NOT to proceed with a rename: the lock key is derived from the space id, so
    the holder will not exclude work that starts under the new name.
    """
    report: Dict[str, Any] = {"cancelled": 0, "locks_held": []}

    try:
        from vitalgraph.vectorization.auto_sync import cancel_space_syncs
        report["cancelled"] = await cancel_space_syncs(space_id)
    except Exception as e:
        # Reported, not raised: an un-cancellable sync is a reason for the CALLER
        # to stop, and swallowing it silently is how a rename races a job.
        logger.warning("quiesce(%s): could not cancel syncs: %s", space_id, e)
        report["cancel_error"] = str(e)

    if conn is not None:
        from vitalgraph.process.process_lock_manager import process_lock_key
        for job in ("analyze", "vacuum", "maintenance", "backfill", "analytics"):
            key = process_lock_key(job, space_id)
            try:
                got = await conn.fetchval("SELECT pg_try_advisory_lock($1)", key)
            except Exception:
                continue
            if got:
                await conn.fetchval("SELECT pg_advisory_unlock($1)", key)
            else:
                report["locks_held"].append(job)
    return report


def invalidate_space_caches(space_id: str, *,
                            space_manager: Optional[Any] = None) -> Dict[str, int]:
    """Drop every process-local cache entry keyed by *space_id*.

    Never raises: a cache that cannot be cleared is reported as an error entry
    rather than aborting the rest. Half the caches cleared is strictly better
    than none, and the caller has already committed the rename by this point —
    failing here would leave the process in a worse state than continuing.
    """
    dropped: Dict[str, int] = {}
    for name, fn in CACHE_INVALIDATORS:
        try:
            dropped[name] = fn(space_id)
        except Exception as e:
            logger.warning("invalidate(%s): %s failed: %s", space_id, name, e)
            dropped[name] = -1
    # The SpaceManager's record is DROPPED rather than repointed: it carries a
    # live backend bound to the old id, and reconstructing that correctly is
    # `get_space_or_load`'s job on the next request. Optional because most
    # callers of this module do not hold one.
    if space_manager is not None:
        try:
            spaces = getattr(space_manager, "_spaces", None)
            if spaces is not None and space_id in spaces:
                del spaces[space_id]
                dropped["SpaceManager._spaces"] = 1
            else:
                dropped["SpaceManager._spaces"] = 0
        except Exception as e:
            logger.warning("invalidate(%s): SpaceManager failed: %s", space_id, e)
            dropped["SpaceManager._spaces"] = -1
    return dropped
