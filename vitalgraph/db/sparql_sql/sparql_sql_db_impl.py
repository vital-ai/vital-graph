"""
Pure-PostgreSQL database implementation for the sparql_sql backend.

Owns its own asyncpg connection pool.
The pipeline's ``db_provider.configure()`` accepts this instance and
uses ``connection_pool`` for all SQL operations.

Pattern inherited from an earlier hybrid backend, since archived
(`issues/241`), minus its second store.
"""

import asyncio
import logging
import os
from typing import Dict, List, Optional, Union, Any

import asyncpg

from ..db_inf import DbImplInterface
from ..user_management import UserManagementMixin
from ...utils.resource_manager import track_pool
from ..connection_config import require

logger = logging.getLogger(__name__)


# How long a REQUEST may wait to acquire a lock before giving up (`issues/253`).
# 0 disables the fence and restores PostgreSQL's default of waiting forever,
# which is what production was measured doing on 2026-09-30.
#
# 10 s and not lower: at the measured ~0.25 s service time that still allows a
# queue of ~40 writes to the same entity to drain, so it fences the pathological
# case without failing a busy-but-healthy one. And not higher: the caller's own
# read timeout is 30 s, so anything above that is a fence only the client ever
# reaches, which is the situation this replaces.
_DEFAULT_REQUEST_LOCK_TIMEOUT_S = 10.0


def _request_lock_timeout_s() -> float:
    raw = os.environ.get("VITALGRAPH_REQUEST_LOCK_TIMEOUT_S")
    if raw is None:
        return _DEFAULT_REQUEST_LOCK_TIMEOUT_S
    try:
        return max(0.0, float(raw))
    except ValueError:
        logger.warning(
            "VITALGRAPH_REQUEST_LOCK_TIMEOUT_S=%r is not a number; using %.1fs",
            raw, _DEFAULT_REQUEST_LOCK_TIMEOUT_S)
        return _DEFAULT_REQUEST_LOCK_TIMEOUT_S


async def _init_conn(conn):
    """Codecs every connection needs, whichever pool it belongs to."""
    import json as _json
    await conn.set_type_codec(
        'jsonb', encoder=_json.dumps, decoder=_json.loads,
        schema='pg_catalog',
    )
    await conn.set_type_codec(
        'json', encoder=_json.dumps, decoder=_json.loads,
        schema='pg_catalog',
    )


async def _init_request_conn(conn):
    """Request connections: codecs, plus a bound on WAITING for a lock.

    `issues/253`. Measured on production 2026-09-30: `lock_timeout`
    is **0** there — `source: default`, no `pg_db_role_setting`
    override — so a request waiting for a lock waited FOREVER, capped
    only by `statement_timeout` at 60 s. That is how a frame write
    whose own work is ~0.9 s took 51.7 s: 6.4 s of it was spent
    before its first statement ran, and the worst case was a
    near-minute wait behind a queue of writes to the same lead.
    `issues/231` recorded 10 s for this and that was wrong for the
    app's sessions.

    A lock wait is the one delay where waiting longer cannot improve
    the answer: the work has not started, so failing at 10 s and
    failing at 60 s lose exactly the same amount of work, and the
    first tells the caller 50 s sooner.

    SET ONCE PER CONNECTION, not per statement. `bounded_lock_wait`
    and `lock_entities` narrow it further for specific statements and
    restore what they found, so this becomes the value they restore
    TO rather than something they fight with.

    REQUEST POOL ONLY, and that is the whole reason this is a second
    init. Background work legitimately waits for locks — ANALYZE,
    VACUUM, an index build, a resync taking ACCESS EXCLUSIVE — and a
    pool-wide fence would kill it mid-way and report success, which
    is `issues/136` (the RDS `statement_timeout` killing 91% of
    VACUUMs on the big quad table) in a new costume. The INTERNAL
    pool keeps `lock_timeout = 0` deliberately.
    """
    await _init_conn(conn)
    ms = int(_request_lock_timeout_s() * 1000)
    if ms > 0:
        await conn.execute(f"SET lock_timeout = '{ms}ms'")


# ---------------------------------------------------------------------------
# Transaction wrapper
# ---------------------------------------------------------------------------

class SparqlSQLTransaction:
    """Transaction wrapper with async context manager support."""

    def __init__(self, connection, transaction, pool):
        self.connection = connection
        self.transaction = transaction
        self.pool = pool
        self._committed = False
        self._rolled_back = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None and not self._committed and not self._rolled_back:
            await self.commit()
        elif not self._rolled_back:
            await self.rollback()

        # Always release connection back to pool
        await self.pool.release(self.connection)

    async def commit(self):
        """Commit the transaction."""
        if not self._committed and not self._rolled_back:
            await self.transaction.commit()
            self._committed = True

    async def rollback(self):
        """Rollback the transaction."""
        if not self._committed and not self._rolled_back:
            await self.transaction.rollback()
            self._rolled_back = True

    def get_connection(self):
        """Get the underlying connection for direct database operations."""
        return self.connection


# ---------------------------------------------------------------------------
# DbImplInterface implementation
# ---------------------------------------------------------------------------

class SparqlSQLDbImpl(UserManagementMixin, DbImplInterface):
    """
    Pure-PostgreSQL database implementation for the sparql_sql backend.

    Manages an asyncpg connection pool used by:
    - The V2 SPARQL-to-SQL pipeline (via ``db_provider.configure(self)``)
    - The service layer (via ``DbImplInterface`` methods)
    - ``SparqlSQLSpaceImpl`` (shared pool)

    Args:
        postgresql_config: Dict with keys: host, port, database, username, password.
            Optional keys: min_pool_size (default 2), max_pool_size (default 10),
            command_timeout (default 60).
    """

    def __init__(self, postgresql_config: dict):
        self.config = postgresql_config
        self.connection_pool: Optional[asyncpg.Pool] = None
        # Separate INTERNAL pool (`issues/231`). None until connect().
        self.internal_pool: Optional[asyncpg.Pool] = None
        # Whether `internal_pool` is None ON PURPOSE (internal_pool_size=0).
        # Without this flag, "disabled by the operator" and "missing because
        # something went wrong" are indistinguishable, and background work
        # silently returns to the request pool in both cases — see
        # `pool.internal_pool_for`.
        self.internal_pool_disabled: bool = False
        self.connected = False
        self._signal_manager = None

        logger.info("SparqlSQLDbImpl initialized")

    @property
    def _pool(self) -> asyncpg.Pool:
        """Return connection_pool, raising if not connected."""
        if self.connection_pool is None:
            raise RuntimeError("SparqlSQLDbImpl not connected — call connect() first")
        return self.connection_pool

    @property
    def _internal_pool(self) -> asyncpg.Pool:
        """The pool for DEFERRABLE background work — ANALYZE, VACUUM, backfill,
        auto-sync (`issues/231`).

        Every background job must acquire here rather than on `_pool`, or the
        separation is cosmetic. On 2026-09-24 six stacked `ANALYZE` held six
        request connections and production stopped answering; the statements
        were legitimate, the pool they took was not.

        Delegates to `pool.internal_pool_for`, which distinguishes a pool that
        is absent ON PURPOSE (`internal_pool_size=0`) from one that is missing
        because something went wrong. The second case is reported at ERROR
        rather than papered over: silently running background work on the
        request pool is the 2026-09-24 outage configuration.
        """
        from vitalgraph.db.pool import internal_pool_for
        return internal_pool_for(self) or self._pool

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Create the asyncpg connection pool and verify connectivity."""
        try:
            logger.debug("Connecting to PostgreSQL for sparql_sql backend...")

            from vitalgraph.db.pool import (
                create_pool, register_pool, PoolClass, DEFAULT_ACQUIRE_TIMEOUT,
            )
            # The INTERNAL pool's client-side fence must match the maintenance
            # budget, not the read path's. See its `command_timeout` below.
            from vitalgraph.process.maintenance_job import (
                MAINTENANCE_STATEMENT_TIMEOUT_MS,
            )

            min_size = self.config.get('min_pool_size', 10)
            max_size = self.config.get('max_pool_size', 30)
            acquire_timeout = self.config.get('acquire_timeout', DEFAULT_ACQUIRE_TIMEOUT)

            # `max_pool_size` IS THE WHOLE BUDGET for this task, across both
            # classes (decided 2026-09-25). The internal pool is CARVED OUT of
            # it, not added to it:
            #
            #     request pool = max_pool_size - internal_pool_size
            #     internal pool = internal_pool_size
            #     total         = max_pool_size
            #
            # Measured 2026-09-25: adding the internal pool on top was the only
            # effect of the bulkhead this workload could detect. At equal TOTAL
            # capacity the split made no latency difference; unmatched, it looked
            # like a 3x win that was purely the extra connections. So charging
            # them to the budget both removes a false win and keeps the one
            # number that matters — the sum the database actually sees —
            # honest. The database sees the sum across every task and class, and
            # per-task pools multiply while the server's useful concurrency does
            # not (`issues/231` step 4).
            internal_max = self.config.get('internal_pool_size', 3)
            if internal_max > 0:
                if internal_max >= max_size:
                    # Leave at least one connection for serving requests. An
                    # internal pool that consumes the entire budget is not a
                    # bulkhead, it is an outage with extra steps.
                    logger.warning(
                        "internal_pool_size=%s does not fit inside "
                        "max_pool_size=%s; reducing internal to %s so request "
                        "serving keeps at least one connection",
                        internal_max, max_size, max(0, max_size - 1),
                    )
                    internal_max = max(0, max_size - 1)
                request_max = max_size - internal_max
            else:
                request_max = max_size

            # CLAMP, do not fail. `min_pool_size` is a warm-connection floor and
            # `max_pool_size` is a hard ceiling; lowering only the ceiling is an
            # unambiguous request for a smaller pool, and asyncpg answers it with
            # "min_size is greater than max_size" at connect() time.
            #
            # That error then arrives as `'NoneType' object has no attribute
            # 'execute_update'` from startup, because the backend is left unset —
            # the real cause is one line earlier in the log and the visible
            # failure names neither pool nor size. Reducing the global budget is
            # step 4 of `issues/231`, so operators WILL lower max_size, and they
            # should not have to know to lower min_size with it.
            #
            # Compared against `request_max`, NOT `max_size`: the carve-out above
            # means the request pool is smaller than the budget, so a min that
            # fits the budget can still exceed the pool it is applied to.
            if min_size > request_max:
                logger.warning(
                    "min_pool_size=%s exceeds the request pool (%s of a %s "
                    "budget, %s reserved for internal); clamping min to %s",
                    min_size, request_max, max_size, internal_max, request_max,
                )
                min_size = request_max
            # INTERNAL gets its own small pool (`issues/231`). Background work —
            # ANALYZE, VACUUM, backfill, segmentation, auto-sync — is always
            # deferrable and nothing waits on it interactively, so it is capped
            # low and, critically, CANNOT consume the connections request
            # serving needs. On 2026-09-24 six stacked ANALYZE held six of
            # thirty request connections and production stopped answering.
            #
            # SET IT TO 0 TO DISABLE the split: background work then runs on the
            # request pool, exactly as it did before this existed. That is a
            # rollback switch — this changes where every background job gets its
            # connection, and a change that broad needs one — and it is also the
            # CONTROL arm for measuring the bulkhead, since a test cannot show
            # isolation without the un-isolated run to compare against.
            internal_max = self.config.get('internal_pool_size', 3)

            self.connection_pool = await create_pool(
                host=require(self.config, 'host'),
                port=require(self.config, 'port'),
                database=require(self.config, 'database'),
                user=require(self.config, 'username'),
                password=require(self.config, 'password'),
                min_size=min_size,
                max_size=request_max,
                max_inactive_connection_lifetime=120.0,
                command_timeout=self.config.get('command_timeout', 60),
                acquire_timeout=acquire_timeout,
                init=_init_request_conn,
            )
            # REQUEST, not QUERY: this pool still serves reads AND writes.
            # Calling it QUERY would file every mutation wait as a query wait,
            # and "are readers being starved" is exactly the question the wait
            # records exist to answer. Becomes QUERY when step 3 splits them.
            register_pool(self.connection_pool, PoolClass.REQUEST)
            logger.info(
                "asyncpg REQUEST pool created: min_size=%s max_size=%s "
                "(of a %s budget, %s carved out for INTERNAL) acquire_timeout=%ss",
                min_size, request_max, max_size, internal_max, acquire_timeout,
            )

            if internal_max > 0:
                # Separate pool, not a share of the first one. A share would still
                # let INTERNAL exhaust what QUERY needs, which is the whole defect.
                self.internal_pool = await create_pool(
                    host=require(self.config, 'host'),
                    port=require(self.config, 'port'),
                    database=require(self.config, 'database'),
                    user=require(self.config, 'username'),
                    password=require(self.config, 'password'),
                    min_size=1,
                    max_size=internal_max,
                    max_inactive_connection_lifetime=120.0,
                    # MAINTENANCE BUDGET, not the request path's 60s.
                    #
                    # `command_timeout` is asyncpg's CLIENT-SIDE limit and is a
                    # SEPARATE fence from the server's `statement_timeout`.
                    # `maintenance_timeouts()` raises the server one; it cannot
                    # touch this. So a repair that correctly cleared the server
                    # fence was still killed here at 60s, raising
                    # `asyncio.TimeoutError` — whose `str()` is EMPTY, which is
                    # why it surfaced as `Resync failed: ` with no reason.
                    #
                    # Measured on production 2026-09-28: a full resync of a
                    # 3.2M-slot space died four times at ~60-70s each (the client
                    # retried), having raised the server fence to 15 minutes.
                    # `issues/231` listed this interaction as unestablished —
                    # "two 60s limits on the same statement, from different
                    # layers". It is established now.
                    #
                    # This pool exists only for deferrable background work, so
                    # the maintenance budget belongs at BOTH layers here. The
                    # REQUEST pool keeps 60s.
                    command_timeout=self.config.get(
                        'internal_command_timeout',
                        MAINTENANCE_STATEMENT_TIMEOUT_MS / 1000.0),
                    acquire_timeout=acquire_timeout,
                    init=_init_conn,
                )
                register_pool(self.internal_pool, PoolClass.INTERNAL)
                logger.info(
                "asyncpg INTERNAL pool created: max_size=%s "
                "(total across both pools: %s)", internal_max, max_size)
            else:
                # Left as None deliberately. `_internal_pool` and the background
                # call sites fall back to the request pool, so this is the
                # pre-split behaviour rather than a broken half-state. Logged at
                # WARNING because it is not a configuration anyone should be in
                # without having chosen it.
                self.internal_pool = None
                self.internal_pool_disabled = True
                logger.warning(
                    "INTERNAL pool DISABLED (internal_pool_size=0) — background "
                    "work will run on the request pool, which is the behaviour "
                    "that caused the 2026-09-24 outage. Intended only for "
                    "rollback or for the control arm of a bulkhead measurement."
                )

            # Per-process pool-occupancy monitor. Quiet (DEBUG) at steady state,
            # WARNING near capacity. Not routed through ProcessScheduler: that
            # advisory-locks a job to one instance, but every task has its own pool.
            from vitalgraph.db.pool import start_pool_monitor
            self._pool_monitor = start_pool_monitor(self.connection_pool)

            # Track pool for service-level cleanup
            track_pool(self.connection_pool)

            # Verify the pool works
            async with self._pool.acquire() as conn:
                result = await conn.fetchval('SELECT 1')
                if result == 1:
                    self.connected = True
                    logger.debug("sparql_sql PostgreSQL pool established")
                    return True
                else:
                    logger.error("sparql_sql PostgreSQL connection test failed")
                    return False

        except ValueError:
            # A missing connection setting is a MISCONFIGURATION, not a
            # connectivity failure. `return False` is the right answer to "the
            # database is unreachable" — callers retry or degrade. It is the
            # wrong answer to "this config cannot name a database", which no
            # amount of retrying fixes, so that one propagates.
            self.connected = False
            raise
        except Exception as e:
            logger.error(f"Failed to connect sparql_sql PostgreSQL: {e}")
            self.connected = False
            return False

    async def disconnect(self) -> bool:
        """Close the asyncpg connection pool."""
        try:
            monitor = getattr(self, '_pool_monitor', None)
            if monitor is not None:
                monitor.cancel()
                try:
                    await monitor
                except asyncio.CancelledError:
                    pass
                self._pool_monitor = None

            if self.connection_pool:
                logger.debug("Closing sparql_sql PostgreSQL pool...")

                try:
                    await asyncio.wait_for(
                        self.connection_pool.close(), timeout=3.0
                    )
                    logger.debug("sparql_sql pool closed gracefully")
                except asyncio.TimeoutError:
                    logger.warning("Pool close timed out, terminating...")
                    self.connection_pool.terminate()

                self.connection_pool = None

            # Closed the same way and just as unconditionally. An INTERNAL pool
            # left open holds connections that no longer belong to anyone, and
            # the leak is invisible because nothing serves traffic from it.
            internal = getattr(self, 'internal_pool', None)
            if internal is not None:
                try:
                    await asyncio.wait_for(internal.close(), timeout=3.0)
                except asyncio.TimeoutError:
                    logger.warning("INTERNAL pool close timed out, terminating...")
                    internal.terminate()
                self.internal_pool = None

            self.connected = False
            return True

        except Exception as e:
            logger.error(f"Error closing sparql_sql pool: {e}")
            return False

    async def is_connected(self) -> bool:
        """Check if the connection pool is alive."""
        if not self.connected or not self.connection_pool:
            return False

        try:
            async with self._pool.acquire() as conn:
                await conn.fetchval('SELECT 1')
            return True
        except Exception:
            self.connected = False
            return False

    # ------------------------------------------------------------------
    # Query execution
    # ------------------------------------------------------------------

    async def execute_query(
        self,
        query: str,
        params: Optional[Union[Dict, List]] = None,
    ) -> List[Dict[str, Any]]:
        """Execute a SQL query and return rows as list of dicts."""
        if not self.connected:
            raise RuntimeError("sparql_sql backend not connected")

        try:
            async with self._pool.acquire() as conn:
                if params:
                    if isinstance(params, dict):
                        param_values = list(params.values())
                    else:
                        param_values = params
                    rows = await conn.fetch(query, *param_values)
                else:
                    rows = await conn.fetch(query)

                return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"sparql_sql execute_query error: {e}")
            raise

    async def execute_update(
        self,
        query: str,
        params: Optional[Union[Dict, List]] = None,
    ) -> bool:
        """Execute a SQL update/insert/delete operation."""
        if not self.connected:
            raise RuntimeError("sparql_sql backend not connected")

        try:
            async with self._pool.acquire() as conn:
                if params:
                    if isinstance(params, dict):
                        param_values = list(params.values())
                    else:
                        param_values = params
                    await conn.execute(query, *param_values)
                else:
                    await conn.execute(query)
                return True

        except Exception as e:
            logger.error(f"sparql_sql execute_update error: {e}")
            return False

    # ------------------------------------------------------------------
    # Transactions
    # ------------------------------------------------------------------

    async def create_transaction(self) -> SparqlSQLTransaction:
        """Create a transaction with async context manager support."""
        return await self.begin_transaction()

    async def begin_transaction(self) -> SparqlSQLTransaction:
        """Begin a transaction: acquire connection, start txn, return wrapper."""
        if not self.connected:
            raise RuntimeError("sparql_sql backend not connected")

        connection = None
        try:
            connection = await self._pool.acquire()

            from ...utils.resource_manager import track_connection
            track_connection(connection)

            transaction = connection.transaction()
            await transaction.start()

            return SparqlSQLTransaction(connection, transaction, self._pool)

        except Exception as e:
            logger.error(f"sparql_sql begin_transaction error: {e}")
            if connection is not None:
                await self._pool.release(connection)
            raise

    async def commit_transaction(self, transaction: SparqlSQLTransaction) -> bool:
        """Commit a transaction and release its connection."""
        try:
            await transaction.commit()
            await transaction.pool.release(transaction.connection)
            return True
        except Exception as e:
            logger.error(f"sparql_sql commit_transaction error: {e}")
            try:
                await transaction.pool.release(transaction.connection)
            except Exception:
                pass
            return False

    async def rollback_transaction(self, transaction: SparqlSQLTransaction) -> bool:
        """Rollback a transaction and release its connection."""
        try:
            await transaction.rollback()
            await transaction.pool.release(transaction.connection)
            return True
        except Exception as e:
            logger.error(f"sparql_sql rollback_transaction error: {e}")
            try:
                await transaction.pool.release(transaction.connection)
            except Exception:
                pass
            return False

    # ------------------------------------------------------------------
    # Connection info & signal manager
    # ------------------------------------------------------------------

    def get_connection_info(self) -> Dict[str, Any]:
        """Get connection information for diagnostics."""
        return {
            'type': 'postgresql',
            'backend': 'sparql_sql',
            # '?' rather than a plausible default: this is a DIAGNOSTIC, and
            # printing localhost:5432/vitalgraph for a config that never said so
            # is how a misconfiguration reads as normal.
            'host': self.config.get('host', '?'),
            'port': self.config.get('port', '?'),
            'database': self.config.get('database', '?'),
            'connected': self.connected,
            'pool_size': self.connection_pool.get_size() if self.connection_pool else 0,
            'pool_max_size': self.connection_pool.get_max_size() if self.connection_pool else 0,
        }

    def set_signal_manager(self, signal_manager):
        """Set the signal manager for this database implementation."""
        self._signal_manager = signal_manager
        logger.debug("Signal manager set on SparqlSQLDbImpl")

    def get_signal_manager(self):
        """Get the signal manager for this database implementation."""
        return self._signal_manager

    # ------------------------------------------------------------------
    # Schema helpers
    # ------------------------------------------------------------------

    async def initialize_schema(self) -> bool:
        """Verify admin tables exist (created during service initialization)."""
        try:
            check_query = """
            SELECT COUNT(*) as table_count
            FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_name IN ('install', 'space', 'graph', 'user', 'process',
                              'agent_type', 'agent', 'agent_endpoint', 'agent_function', 'agent_change_log')
            """
            result = await self.execute_query(check_query)
            table_count = result[0]['table_count'] if result else 0

            if table_count == 10:
                logger.debug("sparql_sql admin tables verified (10/10)")
                return True
            else:
                logger.error(
                    "sparql_sql admin tables missing (%d/10 found)", table_count
                )
                return False

        except Exception as e:
            logger.error(f"Error verifying sparql_sql schema: {e}")
            return False

    async def space_data_tables_exist(self, space_id: str) -> bool:
        """Check if term and rdf_quad tables exist for a space."""
        try:
            check_query = """
            SELECT COUNT(*) as table_count
            FROM information_schema.tables
            WHERE table_name IN ($1, $2)
            AND table_schema = 'public'
            """
            results = await self.execute_query(
                check_query,
                [f'{space_id}_term', f'{space_id}_rdf_quad'],
            )

            if results and len(results) > 0:
                return results[0]['table_count'] == 2
            return False

        except Exception as e:
            logger.error(f"Error checking data tables for space {space_id}: {e}")
            return False
