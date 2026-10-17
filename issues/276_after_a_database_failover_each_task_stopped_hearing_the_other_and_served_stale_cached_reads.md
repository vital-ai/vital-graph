# 276 — After a database failover each task stopped hearing the other and served stale cached reads

## Status: FIXED IN CODE 2026-10-17 (not yet released). Production needs a restart until then.

**Related:** `issues/264` (single-runner jobs, the other thing a failover resets),
the 2026-10-17 RDS instance upgrade (`planning_deploy/deploy_db_r6g_2xlarge_and_gp3_440_20261017.md`).

## What production showed (2026-10-17)

The instance upgrade to db.r6g.2xlarge was done as a Multi-AZ failover; the
database restarted at 17:12:37 UTC. From then on neither VitalGraph task
received a change notice from the other:

| window (UTC) | notices sent | notices received |
|---|---|---|
| 15:00-16:00 | 289 | 578 |
| 16:00-17:00 | 426 | 876 |
| 17:00-17:12 | 50 | 100 |
| 17:14-18:00 | 1,902 | **0** |
| 18:00-19:00 | 3,431 | **0** |

(Received is twice sent before the failover: two tasks, each hearing every
notice.) At 17:12-17:13 both logged `lock connection lost, reconnecting` (the
process-lock connection) and re-created their NOTIFY connection; neither
re-established listening.

The notices are what keep each task's caches in step with writes made through
the other: the entity graph cache, the count cache, term/datatype/stats caches,
token versions, the space list. Without them, a read answered by the task that
did NOT make the write returns its cached copy — the old version, or an entity
that has been deleted. Found by the nurture-action cleanup: a delete through one
task, then a check through the other that still saw the action for 17 s and
more. It affects every reader of production — UW decision runs, explanations,
the portal, the sales agent — for any entity written since 17:12.

## Cause

`SignalManager._listen_for_notifications` (`vitalgraph/signal/signal_manager.py`)
connected, called `add_listener` for each channel, and then:

```python
# Keep connection alive — asyncpg delivers notifications via the handler
while self.running:
    await asyncio.sleep(1.0)
```

It never looked at the connection again. Its reconnect logic was in an
`except` block, so it only ran if something RAISED — and a LISTEN connection
whose server has gone does not raise anything: there is no statement in flight.
After the failover the loop slept on, for hours, on a dead connection.

The sending side does recover: `_send_notification` re-creates its connection
when it finds it closed. That asymmetry is the table above.

And recovering the connection alone is not enough: every notice sent while a
task was not listening is gone, so nothing says which of its cache entries went
stale.

## Fixed (code)

* The listener WATCHES its connection (`_wait_while_alive`): asyncpg's
  termination callback, `is_closed()`, and a `SELECT 1` probe every
  `VG_LISTEN_PROBE_INTERVAL_S` (15 s) with a `VG_LISTEN_PROBE_TIMEOUT_S` (5 s)
  timeout — the probe for a peer that vanished without the socket closing. On
  loss it logs a WARNING, reconnects (the existing back-off) and subscribes every
  channel again.
* After a REconnect (not the first connect) it runs the registered resync
  callbacks and logs a WARNING. The app registers one that clears the entity
  graph and count caches, the term, datatype and stats caches, the token-version
  cache, and reloads the space list — the caches refill on demand.
* `EntityGraphCache.clear()`, `CountCache.clear()`,
  `generator.invalidate_all_stats_caches()`, `VitalGraphAuth.clear_token_cache()`.

## Verification

`tests/unit/test_listener_survives_a_lost_connection.py` (5), with fake
connections: a terminated connection is replaced and every channel
resubscribed; a silently dead one (the probe never answers) is caught by the
probe; a closed one is replaced; resync runs after a reconnect and not on the
first connect; a failing resync callback does not stop the others; the app's
resync clears every cache named above. The four behavioural tests fail on the
previous code. Signal and cache unit tests (7 files) pass.

## Production

* **Now**: restart the VitalGraph service (`aws ecs update-service
  --force-new-deployment` on the production service) — new tasks listen again.
  Until then every cross-task read may be stale for entities written since
  17:12 UTC.
* **After release**: verify on the next failover or restart that
  `notification listener RE-connected` and `Caches cleared after the
  notification listener reconnected` appear, and that notices received per hour
  return to twice notices sent.

## Not done

* A metric or periodic check comparing notices sent with received across the
  tasks, so a deaf listener is visible without reading logs.
* The same pattern may exist in `vitalgraph/db/postgresql_signal_manager.py`
  (`asyncio.sleep(1.0)` keep-alive), which nothing imports today.
