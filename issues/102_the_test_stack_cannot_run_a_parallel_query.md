# The Docker Test Stack Cannot Run a Parallel Query

## Status: DIAGNOSED, fix committed, NOT APPLIED — it needs a stack rebuild

Found 2026-08-17 while loading `sp_lead_synth_10k` onto the test stack to close
the perf baseline's coverage holes.

## The symptom

Five benches in `tests/performance/test_aggregate_growth.py` fail:

    asyncpg.exceptions.DiskFullError: could not resize shared memory segment
    "/PostgreSQL.888087048" to 16777216 bytes: No space left on device

## The cause

Docker gives a container 64 MB of `/dev/shm`, and PostgreSQL puts parallel
workers' shared memory there. `docker-compose.test.yml` never set `shm_size`, so
**any** query the planner parallelises dies on this stack. Measured directly, the
same aggregate on the same data:

    SET max_parallel_workers_per_gather = 0;   ->  1,050,896 rows, fine
    SET max_parallel_workers_per_gather = 2;   ->  DiskFullError

`max_parallel_workers_per_gather` is 2 here, so this is the default path, not an
exotic one.

## Why it was invisible

Nothing on the stack was big enough to make the planner choose a parallel plan.
The three fixtures that are — `sp_lead_synth_10k`, `sp_lead_synth_100k`,
`sp_sql_lead_dataset` — were not loaded, and the 51 benches that use them were
SKIPPING. A skipped bench is not a passing one, and this is what was hiding
behind those skips.

It also means the committed perf baseline was taken somewhere this constraint did
not apply, which is consistent with it having been recorded against the host
cluster.

## The fix, and why it is not applied

`shm_size: 1gb` on the `postgres` service, committed in
`docker-compose.test.yml`. It takes effect only when the CONTAINER is recreated —
and that service deliberately has no volumes, so PGDATA lives in the container's
writable layer:

> No volumes: PGDATA lives in the container's writable layer, so it is wiped
> when the CONTAINER is recreated — not when the image is rebuilt.

So applying it **destroys every loaded fixture**: `wordnet_frames`,
`sp_graph_synth_10k`, `sp_graph_synth_100k`, `sp_graph_skew_2k`, `sp_kg_types`,
`kg_load_test`, `sp_lead_synth_10k` and the rest. They are all reloadable — the
CSVs are on disk — but `sp_graph_synth_100k` alone is 19.6M quads and
`lead_synth_100k.csv` is 7.3 GB, so it is an hour of work, not a command.

That is a deliberate operation with a real cost, so it is left for a decision
rather than done in passing.

## What NOT to do

Set `max_parallel_workers_per_gather = 0` on the stack. It would turn the five
failures green and it would be wrong twice: it hides a real limitation, and
`perf_record.PG_SETTINGS` stamps that setting, so every run afterwards would be
incomparable with any baseline taken at 2 — which is `issues/081` again, from the
other direction.

## Order of operations, when it is done

1. `docker compose -f docker-compose.test.yml up -d --force-recreate postgres`
2. Recreate the spaces (`perf_seed_data.ensure_space` / `ensure_graph`) and
   reload from `test_data/*.csv` with `scripts/load_wordnet_csv.py`
3. `python scripts/migrate_space_schema.py --all` — freshly loaded spaces get the
   current schema, but check
4. Re-run `tests/performance` and promote the baseline. THEN the 51 skipped
   benches are measured again and a promotion does not convert them into holes

## Related

- `issues/081` — the baseline that cannot be honestly re-promoted until this is
  done; promoting now would bake 51 measured benches in as permanent holes
- `issues/055` — the port split that kept fixtures and tests on different
  clusters, which is why "not loaded here" was normal for so long
