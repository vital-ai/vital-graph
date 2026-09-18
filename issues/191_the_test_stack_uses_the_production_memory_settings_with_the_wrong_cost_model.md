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

## "Not stock" is the wrong correction, and so was the table below it

The original table compared vg-test against the RDS parameter group's **64 GB
tier** and concluded that memory MATCHED and only `random_page_cost` diverged.
Measured against the LIVE production server 2026-09-18, that is wrong twice.

Production is not on the 64 GB tier. `shared_buffers` reads 7.69 GiB, which is
25% of ~30.75 GiB, so it is the 32 GB tier. The test stack mirrors a tier
production is not running.

And comparing the settings the PLANNER actually consumes — not the ones a
README happened to list — FIVE diverge, not one:

| setting | production | vg-test | why it matters |
|---|---|---|---|
| `random_page_cost` | `1.1` | `4` | index vs seq scan; the one this issue knew about |
| `effective_cache_size` | 23 GiB | 48 GiB | how attractive a repeated index scan looks |
| `work_mem` | 32 MB | 64 MB | sort/hash costing, and where a spill begins |
| `default_statistics_target` | **500** | **100** | the quality of EVERY cardinality estimate |
| `jit` | `off` | `on` | execution, and JIT thresholds interact with cost |

`shared_buffers` is NOT on that list and its divergence (16 GiB vs 7.69) does
not matter for plan choice: PostgreSQL's planner does not read it. It changes
how fast a plan runs, not which plan is chosen, so the gate this issue exists
to protect is unaffected by it. Leaving it also keeps the 120 GB fixture set
workable, which a 7.69 GiB pool would not.

`default_statistics_target` is the one with a hidden cost. Setting it changes
nothing until the fixtures are re-ANALYZEd, and they are 120 GB — so it is
listed here and deliberately NOT bundled into the change below.

## What remains

Align the four planner inputs that take effect immediately —
`random_page_cost=1.1`, `effective_cache_size=23GB`, `work_mem=32MB`,
`jit=off` — in `docker-compose.test.yml`. **This moves plan shapes and
therefore invalidates the baselines**, so it belongs inside a re-promotion and
never as a standalone edit: sequenced any other way it lands as a wave of
phantom plan-flip failures, the same shape as the pre-ANALYZE comparison that
`76a9e1d8` was written to avoid repeating.

`default_statistics_target=500` is deliberately excluded. It is inert until
every fixture is re-ANALYZEd, that is a 120 GB operation, and doing it in the
same change would make it impossible to attribute a moved plan to either cause.
It is its own step, and it should follow this one rather than accompany it.
