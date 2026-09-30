"""Entity-level write serialization via transaction-scoped advisory locks.

`issues/173`. Two concurrent writes to the same entity URI must not interleave:
UPSERT reads "does this exist", deletes, then inserts, and two requests that
both read "no" before either commits will both insert. On the production space
that produced 243 entities carrying two to four values for single-valued
timestamps, which blanked a whole page of the entity listing.

TRANSACTION-SCOPED, NOT SESSION-SCOPED. `pg_advisory_xact_lock` releases when
the transaction commits or rolls back, so nothing has to remember to unlock and
a crashed request cannot strand a lock. It also needs no dedicated connection
and no in-process `asyncio.Lock` beside it: session-scoped advisory locks are
reentrant on one connection, so a second acquirer sharing that connection would
be handed the lock it was supposed to wait for. Every caller here holds its own
pooled connection for the life of its transaction, so PostgreSQL serializes them
directly and that whole class of problem does not arise.

The lock is taken INSIDE the transaction that does the work, not by a caller
several layers above it. A lock acquired anywhere else can be released while the
work is still in flight, which is the same defect in a different place.

WAITING IS BOUNDED PER REQUEST, NOT PER KEY (`issues/253`). `lock_timeout` is a
per-STATEMENT setting and each key is its own statement, so N contended keys
could wait N x the timeout with nothing bounding the request as a whole. A
multi-key acquisition therefore spends one shared budget across its keys.

The single-key case, which is what a frame write does, keeps exactly the
statement it always had, because the session's own `lock_timeout` bounds it and
re-deriving the same bound per write would be pure cost. **That is true by
construction, not by assumption, and the distinction cost this issue a wrong
conclusion**: production was measured on 2026-09-30 with `lock_timeout = 0`, so
a single-key wait was bounded by nothing but `statement_timeout` at 60 s, and a
frame write doing ~0.9 s of work was seen taking 51.7 s. The REQUEST pool now
sets `lock_timeout` when it opens a connection
(`sparql_sql_db_impl._init_request_conn`), which is what makes the sentence
above hold. If that ever comes out, this file's single-key path silently becomes
unbounded again — they are one mechanism, not two.

WHICH ENTITY was never in the error. A `lock_timeout` arrives as "canceling
statement due to lock timeout" naming no URI, and above here it was flattened
into a boolean, so a failure could not be traced to a lead and nothing could be
reconciled. `EntityLockTimeout` carries the URI, the key and the wait.
"""
from __future__ import annotations

import hashlib
import logging
import os
import struct
import time
from typing import Iterable, List, Optional

from .db_provider import bounded_lock_wait

logger = logging.getLogger(__name__)

__all__ = ["EntityLockTimeout", "entity_lock_key", "lock_entities",
           "entity_lock_budget_s"]

# SQLSTATE 55P03, `lock_not_available` — what `lock_timeout` raises. Matched on
# the code rather than on an asyncpg exception class so that the classification
# is testable without a live server, and survives a driver swap.
LOCK_NOT_AVAILABLE = "55P03"

# Total seconds a multi-key acquisition may spend waiting. Matches production's
# `lock_timeout`, so locking one entity and locking twelve now cost the same
# ceiling. 0 disables the budget and restores one unbounded statement per key.
_DEFAULT_LOCK_BUDGET_S = 10.0


def entity_lock_budget_s() -> float:
    """The multi-key wait budget, from the environment."""
    raw = os.environ.get("VITALGRAPH_ENTITY_LOCK_BUDGET_S")
    if raw is None:
        return _DEFAULT_LOCK_BUDGET_S
    try:
        return max(0.0, float(raw))
    except ValueError:
        logger.warning("VITALGRAPH_ENTITY_LOCK_BUDGET_S=%r is not a number; "
                       "using %.1fs", raw, _DEFAULT_LOCK_BUDGET_S)
        return _DEFAULT_LOCK_BUDGET_S


class EntityLockTimeout(Exception):
    """A write gave up waiting for an entity's write lock.

    Carries what a reconciliation needs and the message never had: WHICH entity,
    its lock key, and how long was spent waiting.
    """

    def __init__(self, uri: Optional[str], key: int, waited_s: float,
                 cause: Optional[BaseException] = None):
        self.uri = uri
        self.key = key
        self.waited_s = waited_s
        self.cause = cause
        super().__init__(
            f"entity lock not acquired after {waited_s:.3f}s: "
            f"uri={uri!r} key={key}")


def entity_lock_key(uri: str) -> int:
    """A stable signed 64-bit advisory-lock key for an entity URI.

    PostgreSQL advisory locks are keyed by bigint, so the URI has to be reduced
    to one. SHA-256 truncated to eight bytes, read as a signed big-endian
    integer: stable across processes and releases (unlike `hash()`, which is
    randomized per process by PYTHONHASHSEED and would hand two replicas
    different keys for the same entity — locks that never collide protect
    nothing).

    A collision means two unrelated entities serialize against each other, which
    costs a little concurrency and no correctness. At 64 bits that needs ~5
    billion distinct URIs for an even chance.
    """
    return struct.unpack("!q", hashlib.sha256(uri.encode("utf-8")).digest()[:8])[0]


def _is_lock_timeout(exc: BaseException) -> bool:
    return getattr(exc, "sqlstate", None) == LOCK_NOT_AVAILABLE


async def lock_entities(conn, uris: Iterable[str],
                        budget_s: Optional[float] = None) -> List[int]:
    """Take a transaction-scoped write lock on each URI. Blocks until granted.

    SORTED, AND THAT IS NOT COSMETIC. Two requests that lock the same pair of
    entities in opposite orders deadlock; PostgreSQL detects it and kills one,
    turning a correctness fix into an error the caller has to handle. A total
    order over the keys makes that impossible, so a multi-entity write waits
    instead of failing. Sorting by KEY rather than by URI because the key is
    what PostgreSQL orders on.

    Deduplicated: re-locking a key already held by this transaction is harmless
    but is a wasted round trip, and a duplicate URI in a batch is normal.

    Raises `EntityLockTimeout` when a wait is cut short, naming the entity.
    """
    by_key = {}
    for u in uris:
        by_key.setdefault(entity_lock_key(u), u)
    keys = sorted(by_key)
    if not keys:
        return []

    budget = entity_lock_budget_s() if budget_s is None else budget_s
    started = time.monotonic()

    # One key: leave the statement exactly as it was. The session's own
    # `lock_timeout` is already a per-request bound when there is only one wait.
    if len(keys) == 1 or budget <= 0:
        for key in keys:
            await _lock_one(conn, key, by_key[key], started)
        return keys

    # Several keys: one budget between them, so the ceiling does not scale with
    # the key count. Save/restore rather than `SET LOCAL` — we are inside the
    # caller's transaction, where asyncpg nests ours as a savepoint and a
    # `SET LOCAL` would outlive its RELEASE and silently re-time the caller's
    # remaining statements (see `bounded_lock_wait`).
    for key in keys:
        remaining = budget - (time.monotonic() - started)
        # NEVER 0: PostgreSQL reads `lock_timeout = 0` as "wait forever", so a
        # spent budget rounding down to zero would remove the bound at exactly
        # the moment it is needed.
        timeout_ms = max(1, int(remaining * 1000))
        async with bounded_lock_wait(conn, timeout_ms):
            await _lock_one(conn, key, by_key[key], started)
    return keys


async def _lock_one(conn, key: int, uri: str, started: float) -> None:
    try:
        await conn.execute("SELECT pg_advisory_xact_lock($1)", key)
    except Exception as exc:
        if _is_lock_timeout(exc):
            raise EntityLockTimeout(
                uri, key, time.monotonic() - started, exc) from exc
        raise
