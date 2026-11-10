# Release deployment document: template

How to write the deployment document for a VitalGraph release, and the rules
every release's steps follow. A worked example is
[`examples/release_2026_11_issue293_query_perf.md`](examples/release_2026_11_issue293_query_perf.md).

Infrastructure is described elsewhere: [`ECS_DEPLOYMENT_GUIDE.md`](ECS_DEPLOYMENT_GUIDE.md)
for the application on ECS, [`../eks-cnpg/README.md`](../eks-cnpg/README.md) for
PostgreSQL on EKS with CloudNativePG. A release document says what THIS release
needs on top of a running deployment.

Write it with no customer or tenant identifiers. Describe spaces by role
("the largest KG space, ~6.5M edges"), and use placeholders for hosts, roles
and accounts.

---

## Deployment targets

The application always runs on ECS. Its database is one of two:

| target | database | SQL generator | how it is selected |
|---|---|---|---|
| **RDS** | managed RDS PostgreSQL | the default generator only: the `vg_planner` extension cannot be loaded on RDS | `VG_PLANNER_EXTENSION` unset or `off` |
| **EKS** | CloudNativePG on EKS (`deploy/eks-cnpg`), `vg_planner` loaded as an image volume | the planner (`qtree`) where it applies, the default generator elsewhere | `VG_PLANNER_EXTENSION=on` (or `require`) and `VG_PLANNER_FEATURES=qtree,...` on the app task |

On EKS every client, scripts included, connects through the PgBouncer pooler's
NLB (session mode), never to the primary. That is what keeps a switchover from
returning `read-only transaction` errors; see [`../eks-cnpg/README.md`](../eks-cnpg/README.md).
A release step's `--host` on EKS is the pooler's NLB.

A release document says, per change, which target it affects. Every step says
whether it applies to RDS, EKS or both. Most changes to the default generator
reach both: the planner declines to the default generator for shapes it does
not plan.

---

## Rules for every release

1. **Order relative to the rollout.** Each step is one of:
   * **pre-deploy:** must run before any new task serves (new SQL functions
     the new code calls, for example);
   * **with the rollout:** created by the new image at startup (admin tables
     via `init_tables`);
   * **post-rollout:** must run only once NO old task is left. That covers
     anything whose correctness depends on every writer running the new code:
     a derived column the new code maintains and the old code does not, or a
     flag that lets queries trust it.
   Say which, and why.
2. **Scripts run as the app role**, never the RDS master or the CNPG
   superuser: objects the master creates are unusable by the app role.
3. **Scripts lift the read-path timeouts themselves.** Production enforces a
   short `statement_timeout` and `lock_timeout` at the role or database level
   (60 s and 10 s). A script with long statements must set the maintenance
   job's fences when it connects (`maintenance_job.MAINTENANCE_*_TIMEOUT_MS`,
   15 min / 60 s) and keep each statement short (batches). A test database
   with no timeout will not show the failure. A `CREATE INDEX CONCURRENTLY`
   cut off by a timeout leaves an INVALID index that must be dropped by hand.
4. **Dry run first.** Every script defaults to a dry run and prints its
   target. Pass `--host`, `--port` and `--database` (or `--dsn`) explicitly:
   the defaults point at the local test stack.
5. **Idempotent and resumable.** A second run reports nothing to do.
6. **Rollback is written before deploy, in order.** If the new code
   maintains state the old code does not, the step that stops TRUSTING that
   state runs BEFORE the rollback starts. During a rolling rollback, old
   tasks write while the remaining new tasks still read; switching off
   afterwards is too late. Say what must be repeated before rolling forward
   again.
7. **Numbers say where they came from.** A local machine with large RAM, mostly
   warm, is not an AWS node. Give warm and cold figures where cold matters,
   and say when nothing was measured on production data.
8. **CI before building.** Record the CI result for the commit to build. If a
   job failed, say whether it was the code or the infrastructure, and
   point at the evidence.

---

## Template

```markdown
# Release <version or date>: <one-line summary>

**STATUS <date>:** pushed at `<commit>`; PyPI <version or none>; image
<built / not built>; deployed <where / nowhere>. Build from `<commit>` or later.
Contains <earlier unreleased notes, if any> (do their steps too).

**What it changes, per target.** <the user-visible effect, with numbers and where
they were measured; RDS and EKS separately when they differ>

**Verified:**
* CI on `<commit>`: <jobs and results; infrastructure failures explained>
* Test suites: <unit / integration / conformance / API counts, on what image>
* Performance tier / corpus: <before-after, rows compared, where>
* NOT run: <what was not checked, e.g. production data, cold AWS nodes>

## 1. Steps

| # | step | target | when | as |
|---|---|---|---|---|
| 1 | <pre-deploy step> | RDS + EKS | pre-deploy | app role |
| 2 | image rollout | both | rollout | (your rollout process) |
| 3 | <post-rollout migration> | ... | post-rollout | app role |

<For each step: the command(s), dry run first; what it does; how long it took and
on what size; what happens if it is skipped; what happens if it fails half-way.>

**Rollback:** <the order; what must run BEFORE the rollback starts; what must be
repeated before rolling forward again>

## 2. What is in it

| commit | what | target |
|---|---|---|

## 3. Behaviour changes a caller or operator may notice

## 4. Post-deploy checks

<SQL or API checks, per target, with the expected answer>

## 5. Open, not deploy steps
```
