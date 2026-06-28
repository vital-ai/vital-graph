# PostgreSQL Advisory Locks for Entity-Level Locking

## Overview

Use PostgreSQL's built-in **session-level advisory locks** to serialize concurrent
operations on the same entity (or frame). This prevents race conditions where two
concurrent requests read-modify-write the same entity's frames simultaneously,
producing verify mismatches or lost updates.

### Why Advisory Locks?

PostgreSQL advisory locks are purpose-built for this:

- **Session-scoped**: automatically released when the connection closes or is
  returned to the pool — no stale locks from crashed processes.
- **No table bloat**: unlike row-level locks or flag columns, advisory locks live
  in shared memory only.
- **Fast**: single function call, no disk I/O.
- **Try semantics**: `pg_try_advisory_lock` returns immediately with true/false
  instead of blocking — useful for fail-fast or timeout patterns.
- **Re-entrant**: the same session can acquire the same lock multiple times
  (must unlock the same number of times).

## PostgreSQL Advisory Lock Functions

| Function | Behavior |
|---|---|
| `pg_advisory_lock(bigint)` | Block until lock acquired (session-level) |
| `pg_try_advisory_lock(bigint)` | Non-blocking, returns `true`/`false` |
| `pg_advisory_unlock(bigint)` | Release one hold on the lock |
| `pg_advisory_unlock_all()` | Release all session locks |
| `pg_advisory_xact_lock(bigint)` | Transaction-level variant (auto-released at COMMIT/ROLLBACK) |

Session-level locks persist until explicitly unlocked or the **connection closes**.
Since we use a connection pool (`asyncpg.Pool`), we must ensure locks are released
before returning connections to the pool.

## Key Design Decision: Session vs Transaction Level

**Transaction-level (`pg_advisory_xact_lock`)** is simpler — lock auto-releases at
end of transaction. But our Fuseki writes happen outside PostgreSQL transactions,
so the lock must span both the PG and Fuseki operations.

**Session-level (`pg_advisory_lock`)** is the right choice because:
- Lock must be held across async Fuseki HTTP calls (not inside a PG transaction).
- Explicit unlock after both PG + Fuseki writes complete.
- Auto-cleanup on disconnect covers crash/timeout scenarios.

## URI to Lock Key Mapping

Advisory locks take a `bigint` (64-bit integer). Entity URIs must be hashed:

```python
import hashlib
import struct

def uri_to_lock_key(uri: str) -> int:
    """Convert a URI to a stable 64-bit advisory lock key."""
    digest = hashlib.sha256(uri.encode('utf-8')).digest()
    # Unpack first 8 bytes as signed 64-bit int (PostgreSQL bigint)
    return struct.unpack('!q', digest[:8])[0]
```

Hash collisions are astronomically unlikely with SHA-256's first 64 bits
(~4 billion entities before 50% collision probability). A collision means
two unrelated entities serialize against each other — slightly slower but
not incorrect.

Optional: use the two-key variant `pg_advisory_lock(int, int)` to namespace
by space_id hash + entity_uri hash for additional collision resistance.

## Architecture

### EntityLockManager Class

A single dedicated PostgreSQL connection holds **all** advisory locks for this
service instance. Multiple locks coexist on the same connection — PostgreSQL
supports this natively. An `asyncio.Lock` serializes SQL calls on the shared
connection (required by asyncpg).

If the connection drops, **all** locks release at once — correct fail-safe
behavior for a crashed service instance.

```python
class EntityLockManager:
    """
    Manages entity-level advisory locks via a single dedicated PostgreSQL connection.
    
    All locks are held on one connection so that:
    - No pool exhaustion — one connection handles hundreds of locks.
    - Connection drop releases ALL locks (crash safety).
    - Minimal resource usage.
    """
    
    def __init__(self, postgresql_config: dict):
        self._config = postgresql_config
        self._conn: Optional[asyncpg.Connection] = None
        self._conn_lock = asyncio.Lock()  # serialize SQL on shared connection
        self._held_locks: Dict[int, str] = {}  # lock_key -> entity_uri
        self.logger = logging.getLogger(__name__)
    
    async def connect(self):
        """Establish dedicated lock connection."""
        self._conn = await asyncpg.connect(
            host=self._config.get('host', 'localhost'),
            port=self._config.get('port', 5432),
            database=self._config.get('database', 'vitalgraph'),
            user=self._config.get('username', 'vitalgraph_user'),
            password=self._config.get('password', 'vitalgraph_pass'),
        )
        self.logger.info("EntityLockManager: dedicated lock connection established")
    
    async def disconnect(self):
        """Close lock connection — releases all advisory locks."""
        if self._conn and not self._conn.is_closed():
            await self._conn.close()
        self._held_locks.clear()
        self.logger.info("EntityLockManager: disconnected, all locks released")
    
    @asynccontextmanager
    async def lock(self, entity_uri: str, timeout_seconds: float = 10.0):
        """
        Async context manager to acquire and release an entity lock.
        
        Usage:
            async with lock_manager.lock(entity_uri):
                # entity is locked for this service instance
                ...
            # lock released
        """
        lock_key = uri_to_lock_key(entity_uri)
        await self._acquire(lock_key, entity_uri, timeout_seconds)
        try:
            yield
        finally:
            await self._release(lock_key, entity_uri)
    
    async def _acquire(self, lock_key: int, entity_uri: str, timeout: float):
        """Acquire advisory lock with timeout via polling."""
        deadline = time.monotonic() + timeout
        while True:
            async with self._conn_lock:
                acquired = await self._conn.fetchval(
                    'SELECT pg_try_advisory_lock($1)', lock_key
                )
            if acquired:
                self._held_locks[lock_key] = entity_uri
                self.logger.debug(f"🔒 Lock acquired: {entity_uri} (key={lock_key})")
                return
            
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Could not acquire lock for {entity_uri} within {timeout}s"
                )
            await asyncio.sleep(0.05)  # 50ms poll interval
    
    async def _release(self, lock_key: int, entity_uri: str):
        """Release advisory lock."""
        try:
            async with self._conn_lock:
                await self._conn.fetchval(
                    'SELECT pg_advisory_unlock($1)', lock_key
                )
            self._held_locks.pop(lock_key, None)
            self.logger.debug(f"🔓 Lock released: {entity_uri} (key={lock_key})")
        except Exception as e:
            self.logger.error(f"Error releasing lock for {entity_uri}: {e}")
    
    @property
    def active_lock_count(self) -> int:
        """Number of locks currently held by this instance."""
        return len(self._held_locks)
```

### Usage in Frame Update Path

```python
async def _update_entity_frames(self, entity_uri, frame_objects, ...):
    lock_manager = self.get_entity_lock_manager()
    
    async with lock_manager.lock(entity_uri):
        # All reads + writes for this entity are now serialized.
        # No other request can modify this entity's frames concurrently.
        
        frames = await self.discover_entity_frames(...)
        result = await self.update_processor.update_frames(...)
        return result
```

## Connection Design

Advisory locks are tied to the **connection**, not the transaction.

The `EntityLockManager` uses a **single dedicated connection** (outside the
main connection pool) to hold all advisory locks:

1. **One connection, many locks**: PostgreSQL allows hundreds of advisory locks
   on a single connection. No pool exhaustion concern.

2. **Independent of main pool**: the lock connection is separate from the
   `asyncpg.Pool` used for normal CRUD operations. Locking never competes
   with data queries for pool connections.

3. **Crash safety**: if the process dies or the connection drops, PostgreSQL
   releases all advisory locks held by that connection automatically.

4. **Serialized SQL access**: `asyncio.Lock` (`_conn_lock`) ensures only one
   coroutine issues a SQL command on the shared connection at a time
   (required by asyncpg's single-command-per-connection rule).

5. **Reconnection**: if the lock connection drops unexpectedly, the manager
   should detect and re-establish it. All previously held locks are lost
   (correct behavior — the operations using them will fail and retry).

## Monitoring

Current advisory locks can be inspected:

```sql
SELECT * FROM pg_locks WHERE locktype = 'advisory';
```

This shows which connections hold which advisory lock keys. Useful for
debugging lock contention.

## Constraints Summary

| Constraint | How it's met |
|---|---|
| Lock by entity URI | URI hashed to bigint advisory lock key |
| Release on disconnect | Session-level advisory locks auto-release |
| No stale locks | Connection close = lock release (PostgreSQL built-in) |
| Timeout support | `pg_try_advisory_lock` + polling with deadline |
| Multi-instance safe | All instances share the same PostgreSQL, same lock namespace |
| Minimal overhead | No table, no disk I/O — shared memory only |
| Works with existing stack | Uses same `asyncpg.Pool` already in `postgresql_db_impl.py` |
| Works with NOTIFY/LISTEN | Independent of signaling — both use PostgreSQL but different features |

## Implementation Steps

1. **Create `EntityLockManager`** in `vitalgraph/db/fuseki_postgresql/entity_lock_manager.py`
   - `uri_to_lock_key()` hash function
   - `EntityLockManager` with `acquire()`, `try_acquire()`
   - `LockHandle` with async context manager

2. **Wire into `FusekiPostgreSQLSpaceImpl`**
   - Initialize `EntityLockManager` with the existing connection pool
   - Expose via `get_entity_lock_manager()` on the space impl

3. **Wrap entity mutation endpoints**
   - `_update_entity_frames` — acquire lock on entity_uri before any reads/writes
   - `_create_or_update_frames` — same
   - `_delete_entity_frames` — same
   - Entity delete — same

4. **Consider pool sizing**
   - Evaluate whether to increase `max_size` or use a separate lock pool

5. **Add logging**
   - Log lock acquire/release with timing for observability
   - Log contention (when `try_acquire` fails or timeout approaches)

6. **Test**
   - Concurrent updates to the same entity → serialized, no verify mismatch
   - Concurrent updates to different entities → fully parallel
   - Lock timeout handling
   - Connection drop → lock auto-released
