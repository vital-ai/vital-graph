# 306 — The vg test stack keeps every space on one 133 GB volume

## Status: OPEN (proposal), 2026-10-24

**Related:** `docker-compose.test.persist.yml` (the volume, `VGTEST_PGDATA` in `.env`),
the planner stack's `docker-compose.planner.persist.yml` (`VGPLANNER_PGDATA`), the memory
pressure that hung the Docker VM on 2026-10-24.

## Found

The vg test stack's PostgreSQL data is ONE volume: an anonymous, hash-named volume
(`VGTEST_PGDATA` in `.env`), **133.6 GB**, holding every test and performance space
together. A performance run against one large space starts a cluster that carries all of
them, and every run competes with the rest for the same buffers, WAL, autovacuum and
`ANALYZE`. A measurement on one space is taken alongside whatever the others are doing,
and on this machine (64 GB RAM, Docker VM 32 GB, host PostgreSQL alongside) the stack
cannot share memory with anything else.

The planner stack was built the other way: a fresh volume per dataset, switched by
`VGPLANNER_PGDATA=<volume>` and a restart (`test_scripts_internal/planner_ext/stack_volume.sh`).
Loading is the slow part (lead 10k, 7.4M quads: 163 s; wordnet_frames, 10.3M quads: 239 s;
uw_prodshape2, 14.4M quads: 840 s); switching is a restart.

## Proposal

1. **A correctness volume:** every SMALL test space (the fixtures the integration and API
   suites create and delete, the DAWG/conformance data, the small lead fixtures), as the
   default `VGTEST_PGDATA`. Correctness tests need breadth; one volume with all of them is
   still right there.
2. **One volume per large performance space:** the production-shaped spaces (the main KG
   space at prod scale, `sp_lead_synth_100k`, the UW prod-shaped space, wordnet, the graph
   synth fixtures), each loaded once into its own named volume and selected per run with
   `VGTEST_PGDATA=<volume>`. A performance run then measures one space on a cluster that
   holds only it.
3. **Reuse across the two stacks where the engine matches.** Both images are PostgreSQL 18.4
   (Debian PGDG) with PostGIS and pgvector; the planner image adds `vg_planner`. A volume
   loaded once can then be mounted by either stack, one at a time:
   - a planner-stack volume in vg test: the `vg_planner` extension is in the catalog but its
     library is absent. Harmless unless something calls its functions (`planner_ext.detect`
     does only with `VG_PLANNER_EXTENSION` on, and catches the error);
   - a vg-test volume in the planner stack: works as is; `CREATE EXTENSION vg_planner` once.
   - Never both stacks on one volume at the same time.
   - Settings are not in the volume (both stacks pass `-c` flags), so each stack keeps its own
     `shared_buffers`.
4. A small switch helper for vg test, like the planner's `stack_volume.sh` (show / switch,
   never `down -v`).

## Before doing it

- List what is on the 133.6 GB volume (space, quads, size) and decide which spaces are
  "large". Several may be stale and need not move.
- Splitting means reloading each large space into its own volume from its loader (or a
  `pg_dump` of that space's tables). The current volume stays until every split volume is
  verified (row counts, stats, a perf baseline matching the old one).
- Tests and scripts that assume one cluster with every space (cross-space tests, the perf
  suite's fixture discovery) need to name the volume they require, or skip with a clear
  message when the space is absent.
