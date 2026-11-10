# Release 2026-11: long chain counts and value-ordered pages (`issues/293`)

> A worked example of [`../RELEASE_DEPLOY_TEMPLATE.md`](../RELEASE_DEPLOY_TEMPLATE.md).
> Spaces are described by role; hosts, roles and accounts are placeholders.

**STATUS:** on `main`. Build from the commit that carries the deploy-review fixes
(section 2), or later. It contains the earlier CJK full-text release
(`ae6fece8`); do its pre-deploy step too (step 1).

## What it changes, per target

Four query shapes on large lead-shaped KG spaces were slow on BOTH targets.
They timed out at 30 s on RDS and on EKS, the planner included. On the lead
100k dataset (local machine, large RAM, mostly warm), from before this
release to after:

| query shape | before | after | what fixes it | deploy step needed |
|---|---:|---:|---|---|
| value-ordered page (`ORDER BY DESC(?rating) LIMIT 25`) | 11.3 s | 0.4-0.65 s | an exact page from a sorted driver | none |
| 3-hop chain count with a range filter | 8.4 s | 1.1 s | chain sizing + covering edge indexes | step 3 for the full gain |
| 3-hop chain count with a boolean filter | timeout | 0.6 s warm, 4.5-9 s cold | edge types read off the edge table | step 4 for the full gain |
| two slot groups paired by frame, GROUP BY | 24.7 s | 2.3 s | chain sizing, per-group text lookup | none |

* **The gains are on the default generator, so RDS gets them.** For these
  shapes the planner extension is no longer the reason to move to EKS. EKS
  gets the same changes. The planner steps aside for value-ordered pages,
  whose plan it would render as sort-then-limit.
* **The numbers are local.** On a 16 GB AWS node, cold runs will be slower,
  for the same memory reasons as before. The cold figure that matters most
  is the chain count's first run: fewer pages read, but still pages.
* Rows were identical on every query of the four planner corpora (lead 100k,
  lead 10k, a frame-heavy space, and a production-shaped underwriting
  dashboard space), and nothing slowed down.

## Verified

* CI: Tests (Tier 1 + 2), Test Packaging and E2E green on the build commit.
  One E2E failure on an earlier commit was infrastructure: "Start test stack"
  timed out while an apt mirror stalled during the image build, before any
  test ran.
* Suites on the test stack, image rebuilt for the code: unit, integration,
  W3C/DAWG conformance and the full API suite, all passing.
* Performance tier, before/after on one persisted volume: no plan-shape change.
* **NOT run:** anything on production data or on an AWS node.

## 1. Steps

| # | step | target | when | as |
|---|---|---|---|---|
| 1 | `install_sql_functions.py --apply` (the CJK release's step) | RDS + EKS | pre-deploy | app role |
| 2 | image rollout | both | rollout | your rollout process |
| 3 | covering edge endpoint indexes | RDS + EKS | any time | app role |
| 4 | mark edge types maintained, then set the flag | RDS + EKS | **post-rollout, no old task left** | app role |

**Hosts.** On RDS, `<host>` is the instance endpoint. On EKS it is the
PgBouncer pooler's internal NLB, never the primary (`deploy/eks-cnpg/README.md`).
The scripts' session settings (the lifted timeouts) hold through it, because
the pooler runs in session mode.

**Step 2.** Startup creates two admin tables, `edge_type_maintained` and
`edge_type_maintenance_enabled`. On EKS, keep the app's `VG_PLANNER_EXTENSION`
and `VG_PLANNER_FEATURES` as they are; nothing in this release needs them
changed.

**Step 3: covering edge indexes.**

    python scripts/migrate_edge_endpoint_covering.py --dsn "postgresql://<app role>@<host>:5432/<db>" --dry-run
    python scripts/migrate_edge_endpoint_covering.py --dsn "postgresql://<app role>@<host>:5432/<db>"

* Rebuilds `idx_{space}_edge_dst_src` / `_src_dst` with `INCLUDE (context_uuid,
  edge_uuid, edge_type_uuid)`: CONCURRENTLY, under a temporary name, then drop
  and rename. It does not block writes. The script lifts the read-path
  timeouts at connect, so a long build is not cut off half-way. If an earlier
  run was cut off, the script reports the INVALID index to drop first.
* Disk: each index grows ~320 -> ~525 MB per 5.3M edges, and both copies exist
  briefly during the swap.
* A partitioned edge table is skipped (CONCURRENTLY cannot build on a
  partitioned parent) and reported.
* If skipped, nothing breaks. Edge walks re-read edge heap pages: 15-20 s
  steady state against 4.5 s covered, on lead 100k on the default generator.

**Step 4: edge types.** AFTER THE ROLLOUT HAS FINISHED AND NO OLD TASK IS LEFT
(staging: keep any old-image service on the same database at 0 tasks):

    python scripts/migrate_edge_types_maintained.py --all --host <host> --port 5432 --database <db> --user <app role>
    python scripts/migrate_edge_types_maintained.py --all --host <host> --port 5432 --database <db> --user <app role> --apply

* **What it does, the first time:** clears every mark (any mark written
  while old and new tasks overlapped is untrustworthy). It reconciles each
  space's `edge.edge_type_uuid` against the vitaltype quads, in batches of
  50,000 edges, each its own REPEATABLE READ transaction, so a concurrent
  retype is never overwritten. It marks each space, and only then sets the
  database-wide flag that lets queries read edge types off the column. If
  any space was written during its reconcile, the flag is not set and the
  script exits 1: re-run it.
* **Duration:** lead 100k, 5.3M edges: 107 s warm, 218 s cold. Budget by the
  largest space's edge count (the largest KG space is ~6.5M edges). The
  script lifts the read-path timeouts at connect, and each statement is a
  short batch.
* **Why after the rollout:** old tasks neither keep the column in step nor
  unmark a space. Until the flag is set, no query reads the column.
* **If skipped or failed:** nothing breaks, and queries stay correct. The
  3-hop count with a boolean filter does not get its gain.

**Rollback**, in this order:

1. **BEFORE the rollback starts**, while only new tasks serve:

       python scripts/migrate_edge_types_maintained.py --disable --host … --port … --database … --user <app role> --apply

   This drops the flag and every mark, and new tasks stop reading the column
   at once (each query re-checks the flag in its own snapshot). Run after the
   rollback has started, it is too late: old tasks would already be writing
   while the remaining new tasks still trusted the marks.
2. Roll back the image. The old image ignores the new tables, the covering
   indexes and the new SQL; nothing else needs undoing.
3. **Before rolling forward again,** repeat step 4 in full, once the new
   rollout has finished.

## 2. What is in it

| commit | what | target |
|---|---|---|
| `54604629` | Value-ordered pages from a sorted driver, exact, with a fallback to the unchanged page; covering edge endpoint indexes (schema + migration). | both |
| `814faceb` | Chain walks sized and driven by their value filters; a literal value constant counts as a filter; an end's filter tables are hoisted; per-group text lookup after COUNT GROUP BY. | both |
| `527a7cbb` | Hop-wise SQL is the same in every process (table order no longer follows Python's per-process string hashing). | both |
| `fb1543f0` | Hop-wise type checks as hashed set membership, with a per-statement `work_mem` raise; edge vitaltype checks read off a maintained `edge.edge_type_uuid`, re-checked by the executor in the query's snapshot. | both |
| `11fa1229` | Edge-type marks are read only after the migration sets a database-wide flag. | both |
| deploy-review fixes | The sorted-driver page restricts candidate (holder, value) pairs, not holders: a holder with two values could return its worse value ahead of another holder's better one. Graph drops, clears, import replace and truncate, and subject removal delete the edge rows with the quads, in one transaction. SPARQL updates keep the edge table for the subjects they name inside their transaction, so only WHERE-bound vitaltype changes unmark a space. The reconcile is batched under REPEATABLE READ. Both migration scripts lift the read-path timeouts. | both |

## 3. Behaviour changes a caller or operator may notice

* No change in results: every change is exact and was compared row for row.
* **Memory:** a large, unpaged chain query that checks type sets as hashed
  sets raises its own `work_mem` for its transaction, to at most 37.5 MB.
  It never lowers it. RDS parameters are unchanged.
* **Writes:** an existing edge row now takes the edge's current vitaltype on
  conflict. A SPARQL update keeps the edge table for its named subjects
  inside its transaction. Graph drop and clear remove the graph's edge rows
  in the same transaction as its quads. A WHERE-bound SPARQL update that
  may change a vitaltype bumps a per-space counter row.
* **Maintenance job:** a new phase reconciles spaces such an update unmarked.

## 4. Post-deploy checks

* After step 2: `SELECT to_regclass('edge_type_maintained'),
  to_regclass('edge_type_maintenance_enabled')`, both not null.
* After step 3: `SELECT indexname FROM pg_indexes WHERE indexname LIKE
  '%edge_dst_src' AND indexdef NOT LIKE '%INCLUDE%'` returns nothing.
* After step 4: `SELECT * FROM edge_type_maintenance_enabled` returns one row,
  and `SELECT count(*) FILTER (WHERE dirty_gen = clean_gen), count(*) FROM
  edge_type_maintained` shows every space marked. A re-run of the script
  reports "0 space(s) to mark".
* Latency: the underwriting dashboard should be at parity (it did not move
  locally). The gains show on the chain counts and value-ordered pages of
  large lead-shaped spaces. Measure cold and warm on the AWS node.

## 5. Open, not deploy steps

* On the default generator, a long chain walk's cold cost is now mostly index
  pages read in walk order; the planner's set-wise plan reads fewer.
* The paged range benches sit at their deterministic order. Choosing the
  in-hop order on cost is a follow-up.
