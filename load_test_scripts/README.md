# VitalGraph service load test

Asyncio load driver that hits the running VitalGraph service **through the
official `VitalGraphClient`** — measuring real p50/p95/p99 latency and throughput
under concurrent mixed read/write load. See
`planning/planning_load_test/load_test_plan.md` for the design and rationale
(why asyncio + the client, not Locust).

## One-time: data generators

The org-entity generator is **copied from the cardiff repo into the gitignored
`data_gen/`** (borrowed test data). If it's missing:

```bash
cp /path/to/cardiff-resource-rest/test_kg_endpoints/kg_test_data.py load_test_scripts/data_gen/
# plus a data_gen/organizations.py exposing ORGANIZATIONS = [...]
```

## Run

```bash
# 1. seed the space + 20 organization entities (idempotent)
python load_test_scripts/setup.py                 # --entities N, --cleanup

# 2. load test  (-u users, -t seconds, -r ramp-up seconds)
python load_test_scripts/load_test.py -u 5  -t 30 --read-only
python load_test_scripts/load_test.py -u 20 -t 120

# target the vg-test docker (:8002) instead of dev (:8001)
LOAD_TEST_ENV=test python load_test_scripts/load_test.py -u 10 -t 30
```

`setup.py` writes the created entity URIs into `load_test_data.py`;
`load_test.py` prints a per-operation latency table at the end.

## Config

`load_test_config.py` resolves the target by `LOAD_TEST_ENV` (`local`|`test`|`prod`),
overridable via `LOAD_TEST_<ENV>_VITALGRAPH_URL` / `_USERNAME` / `_PASSWORD`
(defaults: `http://localhost:8001`, `admin`/`admin`). `prod` is read-only.

## Files

| File | Purpose |
|---|---|
| `load_test.py` | asyncio driver — N `VitalGraphClient` workers, weighted ops, metrics |
| `setup.py` | seed/teardown space + entities via `VitalGraphClient` |
| `load_test_config.py` | environment/target resolution |
| `load_test_data.py` | space/graph id + entity pool (rewritten by `setup.py`) |
| `data_gen/` | **gitignored** — org-entity generator copied from cardiff |
