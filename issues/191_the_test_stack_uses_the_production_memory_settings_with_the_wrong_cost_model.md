# The Test Stack Uses Production's Memory Settings With The Wrong Cost Model

## Status: PARTLY FIXED 2026-09-12 — the README no longer says the opposite of
## the truth. `random_page_cost` still diverges from the parameter group.

**Related:** `issues/081` (the tuning that evaporated on recreate),
`issues/190` (changing the setting requires a re-promotion),
`planning/planning_performance/rds_parameter_group_deploy.md`

## The documentation defect, now fixed

`tests/performance/README.md` claimed, in the paragraph that tells a reader how
to interpret every absolute number in the suite:

> **The vg-test PostgreSQL runs stock config** (`shared_buffers=128MB`,
> `work_mem=4MB`). Plan shapes are measured against defaults...

`docker-compose.test.yml:113-122` runs `-c shared_buffers=16GB -c
effective_cache_size=48GB -c work_mem=64MB`, and the baseline's `pg` stamp
confirms all three. The compose file's own comment explains why they are pinned
on the command line: a stack whose tuning evaporated on recreate sent four
attempts chasing a query-shape explanation for a memory setting (`issues/081`).

## "Not stock" is the wrong correction

| setting | vg-test | RDS param group, 64 GB tier | |
|---|---|---|---|
| `shared_buffers` | `16GB` | `16GB` | matches |
| `effective_cache_size` | `48GB` | `48GB` | matches |
| `random_page_cost` | **`4`** | **`1.1`** | **diverges** |

On memory the test stack MIRRORS production's small tier — presumably why those
numbers were chosen. The divergence is `random_page_cost`, still PostgreSQL's
spinning-disk default here and `1.1` in production because io2/gp3 random I/O is
roughly sequential. That is the single setting that most directly steers
index-scan versus seq-scan, which is the choice the plan-shape gate exists to
watch.

So the suite is not measuring a differently-sized server. It is measuring the
right-sized server with the wrong cost model.

## What remains

Set `random_page_cost=1.1` in `docker-compose.test.yml`. **This moves plan
shapes and therefore invalidates both baselines**, so it belongs inside the
`issues/190` re-promotion and never as a standalone edit — sequenced any other
way it lands as a wave of phantom plan-flip failures, the same shape as the
pre-ANALYZE comparison that `76a9e1d8` was written to avoid repeating.
