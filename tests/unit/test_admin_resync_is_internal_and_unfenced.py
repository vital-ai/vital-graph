"""A full resync runs on the INTERNAL pool, with the maintenance fences raised.

Found on production 2026-09-28. One large space could not repair itself at all:

    entity_slot_sort              0 of 3,238,789 slots
    frame_slot                    empty -> the frame collapse cannot fire
    refresh_type_agreement        killed by statement timeout  x3
    edge_integrity drift probe    killed by statement timeout  x2
    entity_slot_sort backfill     ran ONCE, 84,443 entities still short

Every automatic repair path was being killed by the read path's 60s
`statement_timeout`, which is sized for user queries. `POST /api/admin/resync` is
the documented remedy — and it had the same two problems:

  1. It inherited that 60s fence, so on a space this size it would die exactly
     where the automatic paths die. Same family as `issues/136` (91% of
     production VACUUMs killed at 60s while the job reported success) and
     `issues/149` (a probe fixed while the backfill behind it was not).
  2. It acquired from the REQUEST pool, holding a request connection for the
     minutes a TRUNCATE-and-rebuild takes. `issues/231` step 1 missed it because
     the sweep audited `create_task`/`to_thread` spawn sites and this is a
     synchronous request handler.
"""

import inspect

from vitalgraph.endpoint import admin_endpoint

SRC = inspect.getsource(admin_endpoint)


def test_the_resync_uses_the_internal_pool():
    """A multi-minute rebuild must not hold a request connection."""
    assert "internal_pool_for(db_impl)" in SRC, (
        "the resync still acquires from the request pool")
    assert "pool = getattr(db_impl, 'connection_pool', None)" not in SRC, (
        "the request-pool acquire is back on the resync path")


def test_the_resync_raises_the_maintenance_fences():
    """Without this it dies at 60s on exactly the spaces that need it.

    `maintenance_timeouts` rather than a bare `SET statement_timeout`: it raises
    BOTH fences and restores them. `issues/149` raised only the statement
    timeout and the backfill then lost 43 lock races at the read path's 10s
    `lock_timeout`.
    """
    assert "maintenance_timeouts" in SRC, (
        "the resync runs on the read path's fences")
    assert "async with maintenance_timeouts(conn):" in SRC


def test_the_fences_wrap_the_resync_itself_not_just_the_acquire():
    """Ordering matters: the SET must be inside the connection and around the
    work, or it fences nothing."""
    i_conn = SRC.index("async with pool.acquire() as conn:")
    i_fence = SRC.index("async with maintenance_timeouts(conn):", i_conn)
    i_work = SRC.index("resync_all_auxiliary_tables(conn, space_id)", i_fence)
    assert i_conn < i_fence < i_work


def test_the_audit_route_still_uses_the_REQUEST_pool():
    """Not everything admin is INTERNAL. The audit log is a read a caller is
    waiting on, so it belongs on the request pool — moving it would put an
    interactive read behind whatever background work holds the 3 internal
    connections."""
    assert "getattr(self.space_manager.db_impl, 'connection_pool', None)" in SRC
