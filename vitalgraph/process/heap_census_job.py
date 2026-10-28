"""Count what the garbage collector scans, by type, to find what grows — issues/278.

Production's gen-2 pauses went from ~160 ms (Oct 12-16) to ~500 ms (Oct 18-19).
Every task boots near 140 ms, climbs for ~6 hours and levels off: a bounded
structure filling to its cap, not a leak. A full collection walks every object
the collector tracks, so its cost follows that count; this job says what the
count is made of, and which structure holds it.

Each pass logs, at INFO:

* TYPES — the number of tracked objects (`gc.get_objects()`, which excludes the
  set frozen at startup: exactly what a gen-2 collection walks), the most
  numerous types, and the types that grew most since the last pass;
* HOLDERS — the largest containers reachable by attribute from the `vitalgraph`
  modules, named by path (`module.attr.attr...`), with their length and growth
  since the last pass. `functools.lru_cache` functions report their size.
* KINDS — the same containers summed by holder type and attribute, so many
  small caches (one per pooled connection, one per space) show as one row.

Why two halves: a cache built at startup is FROZEN with everything else by the
startup `gc.freeze()`, and the collector's own introspection
(`gc.get_objects`, `gc.get_referrers`) does not see frozen objects — only its
entries, which arrived later. So the type count shows WHAT grows and cannot say
who holds it; the attribute walk names the holder whatever its generation.

OPT-IN. `VG_HEAP_CENSUS_INTERVAL_S` (seconds; 0, the default, registers
nothing). A pass holds the event loop for about three gen-2 collections: it
runs two (one cold, one after the walk, both timed) and visits every referent
once. Its duration is in the log line. Use 15 minutes or more, and turn it off
once the cause is known.

ONE TASK. Registered with `single_runner=True`, not because the heap is shared
— each task has its own — but so the cost lands on one task and the answer
comes from one stream. The tasks run the same code under the same traffic.
"""

from __future__ import annotations

import collections
import collections.abc
import gc
import logging
import os
import sys
import time
import types
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

HEAP_CENSUS_INTERVAL_S = float(os.getenv("VG_HEAP_CENSUS_INTERVAL_S", "0"))
HEAP_CENSUS_TOP = int(os.getenv("VG_HEAP_CENSUS_TOP", "20"))
# Containers shorter than this are not reported: the question is which
# structure holds tens of thousands of objects, not which dict holds forty.
HEAP_CENSUS_MIN_LEN = int(os.getenv("VG_HEAP_CENSUS_MIN_LEN", "500"))

# The walk descends into a container's ELEMENTS only when it is this short (a
# pool's connection list, a registry of a few jobs). A big container is
# measured and not entered: that is what keeps a pass cheap, and a cache's
# entries are what the type count already shows.
_DESCEND_MAX_LEN = 64
_MAX_DEPTH = 8
_ROOT_PREFIX = "vitalgraph"
_CONTAINERS = (dict, list, set, frozenset, tuple, collections.deque)
_SKIP = (types.FunctionType, types.BuiltinFunctionType, types.MethodType,
         types.CodeType, types.FrameType, type(len), property, staticmethod,
         classmethod, str, bytes, int, float, bool, type(None))


def _type_name(t: type) -> str:
    mod = getattr(t, "__module__", "") or ""
    qual = getattr(t, "__qualname__", getattr(t, "__name__", "?"))
    return qual if mod == "builtins" else f"{mod}.{qual}"


def count_types(objs) -> collections.Counter:
    return collections.Counter(_type_name(type(o)) for o in objs)


def fan_out(objs, top: int) -> Tuple[int, List[Tuple[str, int]]]:
    """(total referents, the `top` objects by referent count as (type, count)).

    A collection visits every referent of every object it scans, so its cost
    follows the referent total, not the object count: one dict of 600,000
    entries costs as much as 600,000 small objects and counts as one."""
    total = 0
    big: List[Tuple[int, str]] = []
    for o in objs:
        n = len(gc.get_referents(o))
        total += n
        if n >= HEAP_CENSUS_MIN_LEN:
            big.append((n, _type_name(type(o))))
    big.sort(reverse=True)
    return total, [(t, n) for n, t in big[:top]]


def _attrs(obj):
    """(name, value) for an instance's attributes: `__dict__` and `__slots__`."""
    d = getattr(obj, "__dict__", None)
    if isinstance(d, dict):
        yield from list(d.items())
    for cls in type(obj).__mro__:
        for s in getattr(cls, "__slots__", ()) or ():
            if isinstance(s, str) and s not in ("__dict__", "__weakref__"):
                try:
                    yield s, getattr(obj, s)
                except AttributeError:
                    pass


def _ours(obj) -> bool:
    mod = getattr(type(obj), "__module__", "") or ""
    return mod.startswith(_ROOT_PREFIX)


def walk_holders(min_len: int = HEAP_CENSUS_MIN_LEN,
                 roots: Optional[Dict[str, object]] = None,
                 kinds: Optional[Dict[str, List[int]]] = None,
                 exclude: Tuple[object, ...] = ()) -> Dict[str, Tuple[str, int]]:
    """{path: (container type, len)} for every container of `min_len` or more
    reachable by attribute from the roots (default: every loaded `vitalgraph`
    module). Each object is visited once, on its first path.

    `kinds`, when given, is filled with {kind: [instances, total len]} over
    EVERY container reached, whatever its size, where the kind is the holder's
    type and attribute (`asyncpg.connection.Connection._stmt_cache`). Many
    small caches — one per connection, per space — add up without any one of
    them crossing `min_len`; this is where they show.

    Entered: modules under the prefix, classes and instances defined under it,
    and short containers. Everything else is a leaf: measured if it is a
    container, otherwise ignored. An `lru_cache` function reports `currsize`.
    """
    if roots is None:
        roots = {name: m for name, m in list(sys.modules.items())
                 if m is not None and (name == _ROOT_PREFIX
                                       or name.startswith(_ROOT_PREFIX + "."))}
    found: Dict[str, Tuple[str, int]] = {}
    # `exclude`: objects never entered — the census itself, whose previous
    # pass would otherwise be reported as a growing holder.
    seen = {id(o) for o in exclude}
    stack: List[Tuple[str, object, int, str]] = [(n, m, 0, n) for n, m in roots.items()]
    while stack:
        path, obj, depth, kind = stack.pop()
        if id(obj) in seen:
            continue
        seen.add(id(obj))

        info = getattr(obj, "cache_info", None)
        if callable(info) and hasattr(obj, "cache_clear"):
            try:
                size = info().currsize
                if size >= min_len:
                    found[path] = ("lru_cache", size)
                if kinds is not None:
                    agg = kinds.setdefault(kind, [0, 0])
                    agg[0] += 1
                    agg[1] += size
            except Exception:
                pass
            continue
        if isinstance(obj, _SKIP):
            continue

        if isinstance(obj, _CONTAINERS) or isinstance(obj, collections.abc.Mapping):
            try:
                n = len(obj)
            except Exception:
                continue
            if n >= min_len:
                found[path] = (_type_name(type(obj)), n)
            if kinds is not None:
                agg = kinds.setdefault(kind, [0, 0])
                agg[0] += 1
                agg[1] += n
            if n <= _DESCEND_MAX_LEN and depth < _MAX_DEPTH:
                items = obj.items() if isinstance(obj, collections.abc.Mapping) \
                    else enumerate(obj)
                try:
                    for k, v in list(items):
                        stack.append((f"{path}[{k!r}]" if isinstance(k, (str, int))
                                      else f"{path}[...]", v, depth + 1, f"{kind}[]"))
                except Exception:
                    pass
            continue

        if depth >= _MAX_DEPTH:
            continue
        if isinstance(obj, types.ModuleType):
            if not obj.__name__.startswith(_ROOT_PREFIX):
                continue
            # A module's attributes are reached under the module's own path:
            # `from x import y` re-exports would otherwise name a holder twice.
            for k, v in list(vars(obj).items()):
                if isinstance(v, types.ModuleType) or k.startswith("__"):
                    continue
                if isinstance(v, type) and v.__module__ != obj.__name__:
                    continue
                stack.append((f"{obj.__name__}.{k}", v, depth + 1,
                              f"{obj.__name__}.{k}"))
        elif isinstance(obj, type):
            if not (obj.__module__ or "").startswith(_ROOT_PREFIX):
                continue
            for k, v in list(vars(obj).items()):
                if not k.startswith("__"):
                    stack.append((f"{path}.{k}", v, depth + 1, f"{_type_name(obj)}.{k}"))
        elif _ours(obj) or hasattr(obj, "__dict__") or getattr(type(obj), "__slots__", None):
            # An instance. A foreign one (a pool, a connection) is entered too,
            # since vitalgraph's caches are often attributes of objects it holds.
            owner = _type_name(type(obj))
            for k, v in _attrs(obj):
                stack.append((f"{path}.{k}", v, depth + 1, f"{owner}.{k}"))
    return found


class HeapCensusJob:
    """One pass: tracked objects by type, and the largest holders by path,
    each diffed with the previous pass."""

    def __init__(self, roots: Optional[Dict[str, object]] = None,
                 top: int = HEAP_CENSUS_TOP, min_len: int = HEAP_CENSUS_MIN_LEN):
        # Extra roots beside the `vitalgraph` modules — the app instance, whose
        # caches no module global may reach. Paths start with the root's key.
        self._roots = dict(roots or {})
        self._top = top
        self._min_len = min_len
        self._prev_types: Optional[collections.Counter] = None
        self._prev_holders: Optional[Dict[str, Tuple[str, int]]] = None
        self._prev_kinds: Optional[Dict[str, List[int]]] = None
        self._passes = 0

    async def run(self) -> Dict:
        # A full collection before the walk touches anything: the cost of the
        # automatic ones, which find the heap as the requests left it.
        t_cold = time.monotonic()
        gc.collect(2)
        cold_ms = (time.monotonic() - t_cold) * 1000
        t0 = time.monotonic()
        objs = gc.get_objects()
        try:
            counts = count_types(objs)
            tracked = len(objs)
            referents, widest = fan_out(objs, self._top)
        finally:
            del objs
        t_types = time.monotonic() - t0
        # And again with the heap just walked: the scan alone.
        t_gc = time.monotonic()
        gc.collect(2)
        gc_ms = (time.monotonic() - t_gc) * 1000
        roots = {name: m for name, m in list(sys.modules.items())
                 if m is not None and (name == _ROOT_PREFIX
                                       or name.startswith(_ROOT_PREFIX + "."))}
        roots.update(self._roots)
        kinds: Dict[str, List[int]] = {}
        holders = walk_holders(self._min_len, roots, kinds, exclude=(self,))
        seconds = time.monotonic() - t0

        prev_t, self._prev_types = self._prev_types, counts
        prev_h, self._prev_holders = self._prev_holders, holders
        prev_k, self._prev_kinds = self._prev_kinds, kinds
        self._passes += 1
        n = self._passes

        top = counts.most_common(self._top)
        type_growth: List[Tuple[str, int]] = []
        if prev_t is not None:
            delta = counts.copy()
            delta.subtract(prev_t)
            type_growth = [(t, d) for t, d in delta.most_common(self._top) if d > 0]
        biggest = sorted(holders.items(), key=lambda kv: kv[1][1], reverse=True)[:self._top]
        holder_growth: List[Tuple[str, int]] = []
        if prev_h is not None:
            holder_growth = sorted(
                ((p, ln - prev_h.get(p, ("", 0))[1]) for p, (_, ln) in holders.items()),
                key=lambda pd: pd[1], reverse=True)
            holder_growth = [(p, d) for p, d in holder_growth[:self._top] if d > 0]
        # A kind is reported when its instances TOGETHER reach `min_len`.
        kind_rows = sorted(((k, c, t) for k, (c, t) in kinds.items()
                            if c > 1 and t >= self._min_len),
                           key=lambda r: r[2], reverse=True)[:self._top]
        kind_growth: List[Tuple[str, int]] = []
        if prev_k is not None:
            kind_growth = sorted(((k, t - prev_k.get(k, [0, 0])[1])
                                  for k, (_c, t) in kinds.items()),
                                 key=lambda kd: kd[1], reverse=True)
            kind_growth = [(k, d) for k, d in kind_growth[:self._top] if d > 0]

        logger.info(
            "heap census #%d: %d tracked objects (+%d frozen at startup), "
            "%.2fs (types %.2fs). Most numerous: %s", n, tracked,
            gc.get_freeze_count(), seconds, t_types,
            ", ".join(f"{t}={c}" for t, c in top))
        logger.info("heap census #%d full collection %.0f ms cold, %.0f ms warm, over "
                    "%d referents; widest objects: %s", n, cold_ms, gc_ms, referents,
                    ", ".join(f"{t}={c}" for t, c in widest) or "none")
        logger.info("heap census #%d largest holders: %s", n,
                    "; ".join(f"{p} {t} len={ln}" for p, (t, ln) in biggest) or "none")
        logger.info("heap census #%d holders by kind (instances, total len): %s", n,
                    "; ".join(f"{k} x{c} len={t}" for k, c, t in kind_rows) or "none")
        if prev_t is not None:
            logger.info("heap census #%d growth since the last pass — types: %s | "
                        "holders: %s | kinds: %s", n,
                        ", ".join(f"{t}+{d}" for t, d in type_growth) or "none",
                        ", ".join(f"{p}+{d}" for p, d in holder_growth) or "none",
                        ", ".join(f"{k}+{d}" for k, d in kind_growth) or "none")
        return {"pass": n, "tracked": tracked, "frozen": gc.get_freeze_count(),
                "referents": referents, "widest": widest, "gc_ms": round(gc_ms, 1), "gc_cold_ms": round(cold_ms, 1),
                "top": top, "type_growth": type_growth, "holders": biggest,
                "holder_growth": holder_growth, "kinds": kind_rows,
                "kind_growth": kind_growth, "seconds": round(seconds, 3)}
