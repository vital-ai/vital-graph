# Signal Management — PostgreSQL NOTIFY/LISTEN for Cross-Instance Sync

**Date**: 2026-03-24
**Backend**: `sparql_sql` (asyncpg throughout — data pipeline + signal connections)
**Status**: Fixed — critical bugs resolved, cross-instance sync now operational

---

## 1. Problem Statement

VitalGraph deployed as N instances behind a load balancer on ECS maintains in-memory caches
(spaces, entity dedup indexes, etc.) that must stay synchronized across all instances.
When Instance A creates a space, Instance B must learn about it before it receives a
request targeting that space — otherwise it returns incorrect results (e.g. count=0).

PostgreSQL's built-in `NOTIFY`/`LISTEN` mechanism is used for this inter-process
communication. Each instance maintains dedicated PostgreSQL connections (separate from
the asyncpg data pool) for sending and receiving signals.

---

## 2. Architecture Overview

### 2.1 Component Layout

```
VitalGraphAppImpl (vitalgraphapp_impl.py)
  startup_event():
    → VitalGraphImpl.connect_database()
      → SparqlSQLDbImpl(asyncpg pool)       ← data queries
      → SignalManager(db_impl)              ← NOTIFY/LISTEN coordination
    → signal_manager.register_callback(CHANNEL_SPACE, space_manager._handle_space_signal)
    → signal_manager.register_callback(CHANNEL_ENTITY_DEDUP, entity_registry._handle_dedup_notification)
    → signal_manager.register_callback(CHANNEL_CACHE_INVALIDATE, _handle_cache_invalidate)
    → signal_manager.start_listening()      ← starts background LISTEN task
```

### 2.2 Connection Architecture

The `sparql_sql` backend uses **asyncpg throughout** — both for the data pipeline and
for signal connections:

| Purpose | Library | Connection Type | Lifecycle |
|---------|---------|----------------|-----------|
| **Data queries** (SPARQL → SQL pipeline) | `asyncpg` | Connection pool (`asyncpg.Pool`) | Managed by `SparqlSQLDbImpl` |
| **LISTEN** (receive notifications) | `asyncpg` | Dedicated `asyncpg.connect()` | Managed by `SignalManager._listen_for_notifications()` |
| **NOTIFY** (send notifications) | `asyncpg` | Dedicated `asyncpg.connect()` | Managed by `SignalManager._send_notification()` |

**Key design decisions**:
- Signal connections are **dedicated connections, not from the pool** — the LISTEN
  connection holds open registrations indefinitely; the NOTIFY connection is kept
  alive for repeated use
- **asyncpg only** — no psycopg3 dependency. The entire `sparql_sql` backend uses
  one PostgreSQL library consistently
- asyncpg runs in autocommit mode by default, so NOTIFY is sent immediately
  without explicit commit
- No pool connections are consumed or held for signaling

### 2.3 asyncpg LISTEN Pattern

asyncpg uses an event-driven listener model:

```python
# Register a callback for a channel — asyncpg handles LISTEN internally
await connection.add_listener('vitalgraph_space', notification_handler)

# The handler is called by asyncpg when a notification arrives:
def notification_handler(connection, pid, channel, payload):
    asyncio.create_task(process_notification(channel, payload))
```

The background task keeps the connection alive with `asyncio.sleep(1.0)` in a loop.
asyncpg delivers notifications to the registered handler automatically.

---

## 3. Notification Channels

All channels are prefixed with `vitalgraph_` to avoid collisions with other PostgreSQL
applications sharing the same database.

| Channel | Constant | Payload Shape | Purpose |
|---------|----------|---------------|---------|
| `vitalgraph_spaces` | `CHANNEL_SPACES` | `{"type": "created\|updated\|deleted", "timestamp": "..."}` | Broadcast: spaces list changed |
| `vitalgraph_space` | `CHANNEL_SPACE` | `{"type": "...", "space_id": "...", "timestamp": "..."}` | Specific space created/deleted/updated |
| `vitalgraph_users` | `CHANNEL_USERS` | `{"type": "...", "timestamp": "..."}` | Broadcast: users list changed |
| `vitalgraph_user` | `CHANNEL_USER` | `{"type": "...", "user_id": "...", "timestamp": "..."}` | Specific user changed |
| `vitalgraph_graphs` | `CHANNEL_GRAPHS` | `{"type": "...", "timestamp": "..."}` | Broadcast: graphs list changed |
| `vitalgraph_graph` | `CHANNEL_GRAPH` | `{"type": "...", "graph_uri": "...", "timestamp": "..."}` | Specific graph changed |
| `vitalgraph_entity_dedup` | `CHANNEL_ENTITY_DEDUP` | `{"action": "...", "entity_id": "...", ...}` | Cross-worker dedup index sync |
| `vitalgraph_process` | `CHANNEL_PROCESS` | `{"action": "started\|completed\|failed", "process_type": "...", ...}` | Job coordination (see `process_tracking_plan.md`) |
| `vitalgraph_cache_invalidate` | `CHANNEL_CACHE_INVALIDATE` | `{"cache_type": "datatype\|stats", "space_id": "...", ...}` | Cross-instance generator cache invalidation |

Signal types: `SIGNAL_TYPE_CREATED = "created"`, `SIGNAL_TYPE_UPDATED = "updated"`, `SIGNAL_TYPE_DELETED = "deleted"`

All payloads are JSON-encoded strings.

---

## 4. SignalManager Class

**File**: `vitalgraph/signal/signal_manager.py`

### 4.1 Initialization

```python
class SignalManager:
    def __init__(self, db_impl):
        self.db_impl = db_impl              # SparqlSQLDbImpl — used for config only
        self.listen_connection = None        # dedicated asyncpg connection (LISTEN)
        self.notify_connection = None        # dedicated asyncpg connection (NOTIFY)
        self.notify_lock = asyncio.Lock()    # serialize NOTIFY calls
        self.listener_task = None            # background asyncio.Task
        self.running = False
        self.callbacks = {channel: [] for channel in ALL_CHANNELS}
        self.active_channels = set()
```

Created during `VitalGraphImpl.connect_database()` after the asyncpg pool is established:
```python
self.signal_manager = SignalManager(db_impl=self.db_impl)
self.db_impl.set_signal_manager(self.signal_manager)
```

### 4.2 LISTEN Side — `_listen_for_notifications()`

A background asyncio task that:
1. Creates a **dedicated `asyncpg.connect()`** connection (not from the pool)
2. Calls `connection.add_listener(channel, handler)` for every channel in `self.callbacks`
3. Keeps the connection alive with an `asyncio.sleep(1.0)` loop
4. asyncpg delivers notifications to the handler callback automatically
5. Handler parses JSON payload and dispatches to registered callbacks
6. On connection error, reconnects with exponential backoff (1s → 2s → 4s → ... → 30s max)

```python
# Connection created via shared helper:
db_config = self._get_db_config()  # from db_impl.config
connection = await asyncpg.connect(
    host=db_config['host'], port=db_config['port'],
    database=db_config['database'],
    user=db_config['username'], password=db_config['password'],
)
```

### 4.3 NOTIFY Side — `_send_notification()`

Sends a `NOTIFY <channel>, '<payload>'` via a **dedicated `asyncpg.connect()`** connection:
1. Lazily initializes the NOTIFY connection on first use (`_init_notify_connection()`)
2. asyncpg runs in autocommit mode by default — no explicit commit needed
3. Serialized via `asyncio.Lock` to prevent concurrent NOTIFY calls on the same connection
4. On error, closes and discards the connection; it will be recreated on next NOTIFY

### 4.4 Callback Registration

```python
signal_manager.register_callback(CHANNEL_SPACE, handler_function)
```

- Handlers are `async def handler(data: dict) -> None`
- Multiple handlers per channel are supported (executed sequentially)
- If the listener is already running, a new `LISTEN <channel>` is issued dynamically
- Default logging callbacks are registered for all channels at init time

### 4.5 Lifecycle

| Event | Action |
|-------|--------|
| App startup | `SignalManager()` created, callbacks registered, `start_listening()` called |
| App shutdown | `stop_listening()` → cancels listener task, closes both dedicated connections |
| Connection error (LISTEN) | Auto-reconnect with exponential backoff |
| Connection error (NOTIFY) | Connection reset, recreated on next NOTIFY |

---

## 5. Cross-Instance Space Cache Sync

### 5.1 The Flow

**NOTIFY side** (Instance A creates a space):

```
SpaceManager.create_space_with_tables(space_id)
  → await signal_manager.notify_spaces_changed(SIGNAL_TYPE_CREATED)
      → NOTIFY vitalgraph_spaces, '{"type":"created","timestamp":"..."}'
  → await signal_manager.notify_space_changed(space_id, SIGNAL_TYPE_CREATED)
      → NOTIFY vitalgraph_space, '{"type":"created","space_id":"...","timestamp":"..."}'
```

**LISTEN side** (Instance B receives the signal):

```
_listen_for_notifications() loop
  → notification on vitalgraph_space
  → _process_notification_async()
  → _execute_callbacks(CHANNEL_SPACE, data)
  → SpaceManager._handle_space_signal(data)
      → signal_type == "created" and space_id not in self._spaces
      → SpaceImpl(space_id, backend=space_backend)
      → self._spaces[space_id] = SpaceRecord(...)
      → ✅ Space now available in Instance B's cache
```

### 5.2 SpaceManager Signal Handler

**File**: `vitalgraph/space/space_manager.py`

```python
async def _handle_space_signal(self, data: dict) -> None:
    signal_type = data.get("type", "")
    space_id = data.get("space_id", "")

    if signal_type == "created":
        if space_id not in self._spaces:
            backend = self.space_backend or self.db_impl
            space_impl = SpaceImpl(space_id=space_id, backend=backend)
            self._spaces[space_id] = SpaceRecord(space_id=space_id, space_impl=space_impl)

    elif signal_type == "deleted":
        if space_id in self._spaces:
            record = self._spaces.pop(space_id, None)
            if record and hasattr(record.space_impl, "close"):
                await record.space_impl.close()
```

Registered at startup in `vitalgraphapp_impl.py`:
```python
signal_manager.register_callback(CHANNEL_SPACE, self.space_manager._handle_space_signal)
```

### 5.3 Write Paths That Send Notifications

| Operation | File | Channels Notified |
|-----------|------|-------------------|
| `create_space_with_tables()` | `space_manager.py` | `CHANNEL_SPACES` (created), `CHANNEL_SPACE` (created, space_id) |
| `delete_space_with_tables()` | `space_manager.py` | `CHANNEL_SPACES` (deleted), `CHANNEL_SPACE` (deleted, space_id) |
| `create_graph()` | `sparql_sql_space_impl.py` | `CHANNEL_GRAPHS` (created), `CHANNEL_GRAPH` (created, graph_uri) |
| `drop_graph()` | `sparql_sql_space_impl.py` | `CHANNEL_GRAPHS` (deleted), `CHANNEL_GRAPH` (deleted, graph_uri) |
| `clear_graph()` | `sparql_sql_space_impl.py` | `CHANNEL_GRAPHS` (updated), `CHANNEL_GRAPH` (updated, graph_uri) |
| `_resolve_datatype_id()` (new DT) | `sparql_sql_space_impl.py` | `CHANNEL_CACHE_INVALIDATE` (datatype, space_id) |
| `resync_all_auxiliary_tables()` | `resync_all.py` | `CHANNEL_CACHE_INVALIDATE` (stats, space_id) |

All notification calls are `await`-ed (not fire-and-forget) so errors are caught by the
surrounding try/except and logged without failing the operation.

---

## 6. Cross-Instance Entity Dedup Sync

The entity dedup system follows the same pattern (documented in `entity_dedup_plan.md`):

```
Instance A: create entity → update local dedup index → NOTIFY vitalgraph_entity_dedup
Instance B: receive NOTIFY → re-fetch entity from PostgreSQL → update local index
```

Registered at startup:
```python
signal_manager.register_callback(CHANNEL_ENTITY_DEDUP, entity_registry._handle_dedup_notification)
```

---

## 7. Startup Wiring — `vitalgraphapp_impl.py`

The complete signal setup happens in `startup_event()`, after database connection:

```python
# 1. Database connects — asyncpg pool created, SignalManager created
success = await self.vital_graph_impl.connect_database()

# 2. SpaceManager initialized from database
await self.space_manager.initialize_from_database()

# 3. Entity registry + dedup callbacks registered
signal_manager.register_callback(CHANNEL_ENTITY_DEDUP, entity_registry._handle_dedup_notification)

# 4. Space cache sync callback registered
signal_manager.register_callback(CHANNEL_SPACE, space_manager._handle_space_signal)

# 5. Cache invalidation callback registered
signal_manager.register_callback(CHANNEL_CACHE_INVALIDATE, _handle_cache_invalidate)

# 6. Start the LISTEN background task
await signal_manager.start_listening()
```

On shutdown:
```python
await signal_manager.stop_listening()  # cancel listener, close both connections
await db_impl.disconnect()             # close asyncpg pool
```

---

## 8. Bugs Found & Fixed (2026-03-24)

Three critical bugs prevented cross-instance space cache synchronization from working.

### 8.1 Bug: `start_listening()` Never Called

**Root cause**: `SignalManager.start_listening()` was never called during app startup.
The background listener task was never created, so no instance ever received NOTIFY
messages from other instances.

**Fix**: Added `await signal_manager.start_listening()` in `vitalgraphapp_impl.py`
`startup_event()` after callback registration (line 367).

### 8.2 Bug: NOTIFY Silently Failed — asyncpg Connection Without `await`

**Root cause**: `_send_notification()` acquired a connection from the **asyncpg pool**
(`db_impl.connection_pool.acquire()`). asyncpg's `.execute()` is async and returns a
coroutine. The code called `self.notify_connection.execute(notify_sql)` **without
`await`**, so the coroutine was created but never executed. The NOTIFY SQL never ran.

Additionally, `_commit_connection()` called `.commit()` which doesn't exist on asyncpg
connections, failing silently.

**Fix**: Replaced the pool-based connection with a **dedicated `asyncpg.connect()`**
connection (not from the pool). The execute is now properly `await`-ed. asyncpg runs
in autocommit mode by default, so NOTIFY is sent immediately.

**Files changed**: `_init_notify_connection()`, `_close_notify_connection()`,
`_send_notification()` in `vitalgraph/signal/signal_manager.py`.

### 8.4 Additional: Converted LISTEN from psycopg3 to asyncpg

**Root cause**: The LISTEN side used psycopg3 (`psycopg.AsyncConnection`) while the
rest of the `sparql_sql` backend uses asyncpg. This introduced an unnecessary second
PostgreSQL driver dependency.

**Fix**: Rewrote `_listen_for_notifications()` to use asyncpg's `add_listener()` API
instead of psycopg3's `notifies()` generator. Both LISTEN and NOTIFY now use dedicated
`asyncpg.connect()` connections via the shared `_create_dedicated_connection()` helper.
Removed the `psycopg` import entirely from `signal_manager.py`.

### 8.3 Bug: Fire-and-Forget Notifications Lost Errors

**Root cause**: `SpaceManager.create_space_with_tables()` and `delete_space_with_tables()`
used `asyncio.create_task(signal_manager.notify_space_changed(...))` — fire-and-forget.
If the notification task failed (which it always did due to Bug 8.2), the error was
silently lost.

**Fix**: Changed to direct `await` calls so errors are caught by the existing try/except:
```python
# Before (broken):
asyncio.create_task(signal_manager.notify_space_changed(space_id, SIGNAL_TYPE_CREATED))

# After (fixed):
await signal_manager.notify_space_changed(space_id, SIGNAL_TYPE_CREATED)
```

**Files changed**: `vitalgraph/space/space_manager.py` — both `create_space_with_tables()`
and `delete_space_with_tables()`.

---

## 9. Files

| File | Purpose |
|------|---------|
| `vitalgraph/signal/signal_manager.py` | `SignalManager` class — NOTIFY/LISTEN coordination, callback dispatch |
| `vitalgraph/signal/notification_bridge.py` | Bridge between PostgreSQL NOTIFY and WebSocket (UI push) |
| `vitalgraph/impl/vitalgraphapp_impl.py` | Startup wiring — registers callbacks, starts listener |
| `vitalgraph/impl/vitalgraph_impl.py` | Creates `SignalManager` during `connect_database()` |
| `vitalgraph/space/space_manager.py` | `_handle_space_signal()` callback + sends notifications on space CRUD |
| `vitalgraph/entity_registry/entity_registry_impl.py` | `_handle_dedup_notification()` callback |
| `vitalgraph/db/sparql_sql/generator.py` | Module-level caches (`_term_cache`, `_datatype_cache`, `_stats_cache`) + invalidation functions |
| `vitalgraph/db/sparql_sql/resync_all.py` | Sends `CHANNEL_CACHE_INVALIDATE` (stats) after resync |
| `vitalgraph/db/sparql_sql/compile_cache.py` | `SparqlCompileCache` — per-instance, no cross-instance sync needed |
| `vitalgraph/db/fuseki_postgresql/fuseki_postgresql_space_graphs.py` | Graph CRUD with `await`-ed notifications |

---

## 10. Operational Notes

### 10.1 Latency

PostgreSQL NOTIFY latency is typically sub-millisecond within the same database.
Cross-instance sync is near-instantaneous for co-located ECS tasks sharing the same
RDS instance.

### 10.2 Failure Modes

| Failure | Behavior |
|---------|----------|
| LISTEN connection drops | Auto-reconnect with exponential backoff (1s–30s) |
| NOTIFY connection drops | Reset on error, recreated lazily on next NOTIFY |
| NOTIFY fails for a space create | Space is still created locally; other instances miss the signal until next restart or manual refresh |
| Instance restarts | Full space list reloaded from database on startup (`initialize_from_database()`) |

### 10.3 Self-Notification

An instance that sends a NOTIFY also receives it on its own LISTEN connection.
The `_handle_space_signal` handler is idempotent — if the space already exists in the
local registry (`space_id in self._spaces`), the signal is ignored.

### 10.4 AWS RDS Compatibility

- `NOTIFY`/`LISTEN` work normally on RDS PostgreSQL
- Advisory locks (used by `ProcessLockManager`) also work normally on RDS
- No superuser permissions required

---

## 11. In-Memory Cache Inventory

Complete inventory of in-memory state that could go stale in an N-instance deployment.

### 11.1 Synced Caches (covered by NOTIFY/LISTEN)

| Cache | Location | Signal Channel | Callback |
|-------|----------|---------------|----------|
| `SpaceManager._spaces` | `space_manager.py` | `CHANNEL_SPACE` | `_handle_space_signal` — adds/removes SpaceRecord |
| `EntityDedupIndex` (LSH + `_entity_cache`) | `entity_dedup.py` | `CHANNEL_ENTITY_DEDUP` | `_handle_dedup_notification` — add/remove/reload |
| `generator._datatype_cache` | `generator.py` | `CHANNEL_CACHE_INVALIDATE` | `invalidate_datatype_cache(space_id)` |
| `generator._stats_cache` | `generator.py` | `CHANNEL_CACHE_INVALIDATE` | `invalidate_stats_cache(space_id)` |

### 11.2 Safe Without Sync

| Cache | Location | Why Safe |
|-------|----------|----------|
| `generator._term_cache` | `generator.py` | Read-through cache of **immutable data** — `(term_text, term_type) → uuid` never changes once created. Cache misses fall through to DB. No stale negative caching. Unbounded growth is the only concern (consider LRU cap for very large datasets). |
| `SparqlCompileCache` | `compile_cache.py` | Keyed by SPARQL query hash. Compiled algebra is deterministic for a given SPARQL string. Each instance builds its own cache independently. LRU-capped at 512 entries. |
| `auto_analyze._change_counts` | `auto_analyze.py` | Local heuristic counters for triggering ANALYZE. Each instance tracking its own write volume is correct behavior. |
| `ProcessScheduler._jobs` | `process_scheduler.py` | Registered at startup, static thereafter. Advisory locks handle leader election across instances. |

### 11.3 Not Yet DB-Backed (no sync needed today)

| State | Location | Notes |
|-------|----------|-------|
| `VitalGraphAuth.users_db` | `vitalgraph_auth.py` | Hardcoded dict. If/when auth moves to PostgreSQL, will need `CHANNEL_USER` sync wiring. |

### 11.4 Cache Invalidation Signal Flow

The `CHANNEL_CACHE_INVALIDATE` channel carries a `cache_type` field that dispatches to
the correct invalidation function:

```
Instance A: insert new datatype
  → invalidate_datatype_cache(space_id)         ← local
  → NOTIFY vitalgraph_cache_invalidate,
      '{"cache_type":"datatype","space_id":"..."}'

Instance B: receive NOTIFY
  → _handle_cache_invalidate(data)
  → cache_type == "datatype"
  → invalidate_datatype_cache(space_id)         ← remote
  → next query reloads from DB
```

Same pattern for `stats` after `resync_all_auxiliary_tables()`.

Datatype invalidation is rare in practice — standard XSD datatypes are loaded at space
creation, and custom datatypes are uncommon. The signal exists as a correctness safety
net rather than a high-frequency path.

### 11.5 Graph Change Notifications

Both backends now send graph change notifications:

| Backend | File | Pattern |
|---------|------|--------|
| `fuseki_postgresql` | `fuseki_postgresql_space_graphs.py` | `await sm.notify_graph_changed(...)` |
| `sparql_sql` | `sparql_sql_space_impl.py` | `await sm.notify_graph_changed(...)` |

Graph records are **not cached in memory** — they are queried from the `graph` table on
each request. The notifications serve the `NotificationBridge` (WebSocket push to
frontend) so the UI updates when graphs change on another instance.

Both backends use `await` (not fire-and-forget) so errors are caught and logged.
