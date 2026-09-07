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
"""
from __future__ import annotations

import hashlib
import struct
from typing import Iterable, List

__all__ = ["entity_lock_key", "lock_entities"]


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


async def lock_entities(conn, uris: Iterable[str]) -> List[int]:
    """Take a transaction-scoped write lock on each URI. Blocks until granted.

    SORTED, AND THAT IS NOT COSMETIC. Two requests that lock the same pair of
    entities in opposite orders deadlock; PostgreSQL detects it and kills one,
    turning a correctness fix into an error the caller has to handle. A total
    order over the keys makes that impossible, so a multi-entity write waits
    instead of failing. Sorting by KEY rather than by URI because the key is
    what PostgreSQL orders on.

    Deduplicated: re-locking a key already held by this transaction is harmless
    but is a wasted round trip, and a duplicate URI in a batch is normal.
    """
    keys = sorted({entity_lock_key(u) for u in uris})
    for key in keys:
        await conn.execute("SELECT pg_advisory_xact_lock($1)", key)
    return keys
