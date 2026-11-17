# 347 — The test and planner images run PostgreSQL 18.7, not the pinned 18.4

## Status: FIXED 2026-11-16 in `f842e74e` (both Dockerfiles). Both images report 18.4 (Debian 18.4-1.pgdg13+1) and fail to build on any other minor. Baseline re-record on 18.4 in progress (`query`, `query_lead100k`). NOT a production change: production is 18.4 already.

## Found

During the PG 19 evaluation (`planning_pg19`, E2/E7), the 18 arm built from the vg test
stack's image reported `server_version` **18.7**. So does the running vg test stack:

    $ docker exec vitalgraph-test-pg postgres --version
    postgres (PostgreSQL) 18.7 (Debian 18.7-1.pgdg13+2)

`docker/test-pg/Dockerfile` says `FROM postgres:18.4` and explains why the minor must be
pinned ("THE MINOR IS PINNED, NOT JUST THE MAJOR … a performance baseline is a claim about a
specific engine"). Production (RDS) runs 18.4.

The committed baselines already disagree with each other:

    tests/performance/baselines/query.json   "server_version": "18.7 (Debian 18.7-1.pgdg13+2)"
    tests/performance/baselines/load.json    "server_version": "18.4 (Debian 18.4-1.pgdg13+1)"

## Cause

The image installs PostGIS and pgvector from PGDG without versions:

    apt-get install -y --no-install-recommends postgresql-18-postgis-3 postgresql-18-pgvector

The current pgvector build declares `Depends: postgresql-18 (>> 18.7)` (`0.8.7-1.pgdg13+2`,
rebuilt for 18.7), so apt upgrades the server inside the image: `postgresql-18`,
`postgresql-client-18`, `postgresql-18-jit` and `libpq5` all go 18.4 → 18.7, and PostGIS
comes in at 3.7.0. Verified with `apt-get install -s` on `postgres:18.4`. The `FROM` pin
holds only until the first extension rebuild after a minor release.

**`docker/planner-pg/Dockerfile` has the same flaw twice.** The runtime stage upgrades the
server the same way, and the build stage installs `postgresql-server-dev-18` unpinned. But
`vg_planner`'s `src/pg18_joinsearch.c` is a verbatim copy of `REL_18_4`'s join search, and
`planning_planner` D1 rests on the plugin stack running *the same planner as production*.
An 18.4-copied join search inside an 18.7 server is exactly the drift D1 rules out.
(`deploy/eks-cnpg/images/vg-planner/Dockerfile` is correct: it pins the dev package to the
server's own version and asserts `pg_config --version`.)

## Fix (applied in `f842e74e`, approved by Marc)

Hold the server packages at the base image's version and pin the extension builds that do
not demand a newer server:

    apt-mark hold postgresql-18 postgresql-client-18 libpq5 postgresql-18-jit
    apt-get install -y --no-install-recommends \
        postgresql-18-pgvector=0.8.7-1.pgdg13+1 \
        postgresql-18-postgis-3=3.6.4+dfsg-2.pgdg13+1 \
        postgresql-18-postgis-3-scripts=3.6.4+dfsg-2.pgdg13+1

`apt-get install -s` on `postgres:18.4` installs only those three and leaves the server at
18.4. PostGIS 3.6.4 is the version the CloudNativePG profile pins. The planner image's build
stage needs `postgresql-server-dev-18=<the server's package version>`, as the CNPG
Dockerfile does. Add the same `pg_config --version` assertion to both images, so a future
drift fails the build instead of passing silently.

**Consequence**: perf baselines recorded on the 18.7 image (`query.json`, re-promoted
2026-11-16) are refused against an 18.4 run (`perf_compare` checks `server_version`), so
they must be re-recorded on the fixed image. Whether to go to 18.4 (production's version)
or deliberately re-pin to 18.7 is the decision. 18.4 keeps parity with RDS. The pinned
package versions above will disappear from the repository eventually; a long-term fix may
need a local mirror or a minor bump made deliberately, as the Dockerfile's comment intends.

**Applied as above, plus one thing the dry run did not reach.** The planner image's build stage
also needs `libpq-dev` pinned to the server's version: with the server held,
`postgresql-server-dev-18=18.4-1.pgdg13+1` depends on `libpq-dev`, whose newest build wants
`libpq5` 18.7, so apt refused ("held broken packages"). Both images now install pgvector
0.8.7-1.pgdg13+1 and PostGIS 3.6.4, `vg_planner`'s regression suite passes 3/3 in the
build, and both assert `pg_config --version` = 18.4.

Existing volumes (`vgtest_core`, `vgdata_corpus1`, `vgdata_uw_prodshape2`) hold PostGIS
3.6.4 and vector 0.8.6/0.8.7 in their catalogs, so they load on the pinned libraries.

## Not done

- The `query` and `query_lead100k` baselines are being re-recorded on 18.4 at HEAD (in
  progress, by another session).
- The pinned package builds will leave the PGDG repository eventually; when they do, the
  build fails loudly (by design), and the minor has to be moved deliberately.
