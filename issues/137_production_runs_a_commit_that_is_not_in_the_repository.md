# Production Is Built From A Second Repository With A Disjoint History

## Status: ITEM 2 FIXED 2026-09-02 — the server now stamps `install` on startup.
## Items 1 and 3 (name the repo here; share history) remain OPEN.
## Original status: OPEN — production is built from a separate deploy repo whose history
## shares no commits with this one, and nothing here records that. The provenance
## label resolves, but only if you already know which repository to look in.
## Filed 2026-09-01, corrected the same day — see the retraction at the end.

## The facts

The running service (`vitalgraph-service`, task definition `vitalgraph-prod:48`)
uses image `vitalgraph-prod:v0.0.48-prod`, which also carries `latest`. Its OCI
config records provenance correctly — the Dockerfile's `GIT_COMMIT` plumbing
works:

    org.opencontainers.image.revision = 26b75f97492ce23c85cef63acd939a89b3a60fd6
    org.opencontainers.image.version  = v0.0.48
    org.opencontainers.image.created  = 2026-07-30T16:51:05Z

That commit is not in this repository, and `git fetch --all` does not bring it
in. It lives in a **separate deploy repository** (`acme/vital-graph-deploy`), on
branch `acme-production`, where it is a merge:

    26b75f9  Merge main into acme-production for v0.0.48-prod cutover
      parent 69d3fdc  2026-07-28 19:48  (product side)
      parent dadfac4  2026-07-30 12:47  (deploy-config side)

**Neither parent exists in this repository either.** The two histories are
disjoint — the deploy repo was populated by copying files, not by forking — so
no commit sha is shared and no `git log A..B` can span them. The product code in
production corresponds to roughly **2026-07-28**; `main` here is at 2026-08-26.

## What is actually undeployed

Because the histories are disjoint, the only way to compare is a tree diff of
the deployed `vitalgraph/` against `main`:

    changed files    129
    new in main       70
    removed            0

    sparql_sql_space_impl.py    1,227 changed lines
    maintenance_job.py            802
    kg_query_builder.py           617
    sparql_sql_schema.py          616
    kgquery_endpoint.py           265

## Verified against the deployed tree

`issues/136` was written from log behaviour before the deploy repo was known,
and graded its claims as inference. With the deployed source in hand every one
is now **checked directly**, and all five held:

| claim about production | verified |
|---|---|
| no `_checked_query` — a failed read returns `200` + `0 results` | ABSENT in deployed `kgquery_endpoint.py` |
| no `_gather_cancelling` — both twins run the full 60s | ABSENT in deployed `kgquery_endpoint.py` |
| no 55s read fence, so asyncpg's bare `TimeoutError` wins | `_apply_read_fence` ABSENT in deployed `sparql_sql_space_impl.py` |
| `add_rdf_quads_batch_bulk` returns 0 instead of raising | confirmed: deployed source is `logger.error(...)` then `return 0` |
| no `semijoin` rewrite | `semijoin.py` ABSENT from the deployed tree |

One correction in the other direction: the extended `(predicate_uuid,
object_uuid)` statistics **are** emitted by the deployed schema module —
`quad_po` is PRESENT at the deployed commit. So `stat_*_quad_po` on production
was created by the running code itself, not by anyone running
`ensure_space_indexes.py`. That strengthens `issues/136`'s conclusion rather
than weakening it: the statistic has been in place since the cutover and the
timeouts happened anyway.

The maintenance-job defect is also confirmed present in the deployed code, not
just in `main`: the deployed `maintenance_job.py` contains no reference to
`statement_timeout` at all.

## Why this is still a defect

The label resolves — but only against a repository this one never names. Nothing
in this repo records that production is built elsewhere, which repo that is, or
what point of `main` was merged in. So:

* **Diffing requires knowing the other repo exists.** Two people already spent
  effort here concluding production was unreproducible.
* **`git log` cannot span the two.** Disjoint histories mean tree diffs only —
  no bisect, no `A..B`, no blame across the boundary.
* **Three numbering schemes, none agreeing.** Image `v0.0.48`, task definition
  revision 48, `pyproject.toml` 0.0.39, newest git tag here `v0.0.39`.

## What would fix it

1. **Name the deploy repo here** — a line in `README.md` or `PACKAGING.md`
   saying production is built from it and which branch. Cheapest, fixes the
   worst symptom.

   **BLOCKED, and not by effort.** The deploy repository's name contains the
   client name, and this repo's standing rule is that the client name does not
   appear in tracked files — `8e12e25` exists to remove it. `README.md` and
   `PACKAGING.md` are both tracked, so writing the repo's real name into either
   trades one problem for a worse one.

   Item 2's stamp is the better answer anyway, and is done: the deployed
   database now says what is running without anyone needing the repo name. What
   is still missing is the mapping from a product sha to the deploy-repo sha
   that built it, and that wants a home OUTSIDE this repository — the deploy
   repo's own README, or the same place the deploy credentials live. Not here.
2. **Record the mapping per deploy** — image tag -> deploy-repo sha -> product
   sha -> task definition revision, so "what is running" is answerable without
   pulling OCI labels out of a registry.

   **The place to put it already exists and is empty.** Found 2026-09-02: the
   `install` admin table on production already carries the three columns
   `apps/migrate_install_version.py` adds —

       id | active | vitalgraph_version | git_commit | deployed_datetime
        1 | t      |                    |            |

   — and all three are NULL. Nothing in `main` writes them; `db/common/models.py`
   types them `Optional[str] = None` and says they "stay None until a server
   stamps them". No server does.

   The values are already in the container as environment variables, set by the
   Dockerfile from the same build args as the OCI labels:

       VITALGRAPH_GIT_COMMIT=26b75f97492ce23c85cef63acd939a89b3a60fd6
       VITALGRAPH_BUILD_VERSION=v0.0.48
       VITALGRAPH_BUILD_TIME=2026-07-30T16:51:05Z

   So the fix is a stamp on startup, next to `_auto_init_auth_tables`, writing
   those three into `install`. That turns "what is running?" into one SQL query
   against the database the app is already connected to — no registry access, no
   knowledge of which repo built it. The schema half of this was done and then
   left unwired.
   **DONE 2026-09-02.** `vitalgraph/build_info.py` resolves version, commit and
   build time; `VitalGraphAppImpl._stamp_build_provenance()` writes the first
   two plus `now()` into the active `install` row on every startup.

   Two details this section had wrong, both of which would have made the fix a
   no-op in the environment it exists for:

   * **`apps/` is not copied into the image.** The Dockerfile copies
     `vitalgraph/` only, so detection could not live beside the migration.
     `apps/migrate_install_version.py` now re-exports from the package instead,
     so there is one copy rather than two that can drift.
   * **"next to `_auto_init_auth_tables`" would never have run.** That path is
     gated on `VG_AUTO_INIT=true`, which is test environments. The stamp is
     placed after it and OUTSIDE that branch; a test asserts the indentation, so
     a later edit cannot quietly move it back inside.

   `deployed_datetime` is stamped at START time rather than build time: the
   column is named "deployed", a restart legitimately updates "since when has
   this code been running", and the build moment is still recoverable from the
   version and commit. Build time is logged beside it.

   Answering "what is running?" is now:

       SELECT vitalgraph_version, git_commit, deployed_datetime
         FROM install WHERE active;

3. **Share history instead of copying.** A real fork or a subtree/submodule
   makes `git log A..B` work again. Larger change; the first two are worth doing
   regardless.

Not worth doing: the build-time check this file originally proposed (fail if
`GIT_COMMIT` is not an ancestor of a pushed branch). The sha *is* pushed — in
the other repo — so that check would pass and teach nothing.

## Retraction — what this file first claimed, 2026-09-01

Originally filed as "Production Runs A Commit That Is Not In The Repository",
concluding the sha "may not exist anywhere" and that the image might be
unreproducible. **Wrong.** It exists, is pushed, and the image is reproducible;
it is in a second repository nobody had mentioned. The evidence at the time —
the sha absent here, absent on origin after `git fetch --all`, and a version
string matching no tag — is equally consistent with both readings, and the
alarming one was picked without asking whether another repo existed.

The lesson worth keeping: "not in this repo" is a statement about this repo, not
about the world. The retracted conclusion also produced a proposed fix (the
ancestry check) that would not have worked.

## Related

- `issues/136` — the maintenance VACUUM defect from the same investigation. Its
  claims are now verified against the deployed tree rather than inferred.
- `issues/108` — a stale test-stack image hiding regressions for days. Same
  family: what is running is not what is being reasoned about.
