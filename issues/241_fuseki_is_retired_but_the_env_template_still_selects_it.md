# 241 — Fuseki is retired, but the env template still selects it and the factory still builds it

## Status: OPEN — the DECISION is made (2026-09-25: Fuseki is RETIRED, not merely
## unused), which is what this issue was blocked on. Nothing removed yet. One
## item is a live defect rather than stale material: `.env.example` selects
## `fuseki_postgresql` and that value WINS over the correct `sparql_sql` default.

**Related:** `issues/240` (found this — a Fuseki test script was cited as evidence
about live callers, which is the failure mode this material creates),
`issues/137` (production is built from a separate deploy repo, so "nothing in
this tree uses it" is not the same as "nothing uses it")

## The decision

Fuseki is **retired**. Not "unused pending a decision", which is how the tree
currently reads — **166 tracked files** mention it, the factory constructs two
Fuseki backends, and a unit test in the live suite exercises one. Everything below
follows from the decision rather than arguing for it.

(That count was 239 earlier the same day. Untracking `planning/` removed 73 of
them without deleting anything from disk, so a reader comparing against the
survey in this session's notes is not seeing a contradiction.)

The distinction matters because it changes what each item IS. Under "unused",
`.env.example:55` is a stale default and the `tests/unit` exemption is prudent
scoping. Under "retired", the first is a defect and the second is dead weight
suppressing a guard.

## 1. The live defect: the env template selects the retired backend, and wins

    .env.example:50   VITALGRAPH_ENVIRONMENT=local
    .env.example:55   LOCAL_BACKEND_TYPE=fuseki_postgresql     <- ACTIVE
    .env.example:133  # PROD_BACKEND_TYPE=fuseki_postgresql    <- commented
    .env.example:197  # SPARQL_SQL_BACKEND_TYPE=sparql_sql     <- commented

The code default is RIGHT — `config_loader.py:147` is
`self._get_profile_env('BACKEND_TYPE', 'sparql_sql')`. The template defeats it.

`_get_profile_env` (`config_loader.py:101`) resolves in this order:

    1. {ENVIRONMENT}_{KEY}   e.g. LOCAL_BACKEND_TYPE
    2. {KEY}                 e.g. BACKEND_TYPE
    3. the default           'sparql_sql'

and `VITALGRAPH_ENVIRONMENT` defaults to `local` in BOTH the code
(`config_loader.py:69`) and the template. So `LOCAL_BACKEND_TYPE` beats the
correct default AND beats the unprefixed `BACKEND_TYPE=sparql_sql` that the
compose files set (`docker-compose.test.yml:208`).

**Copy the tracked template, run the server outside Docker, and you are on the
retired hybrid backend.** No error and no warning: `vitalgraph/db/fuseki/` and
`fuseki_postgresql/` are 25 modules and the factory imports them successfully, so
this is a wrong backend rather than a failed start.

The running stacks are NOT affected and this is why it has stayed invisible:
`vitalgraph-test-app` reports `BACKEND_TYPE=sparql_sql` and carries no `LOCAL_*`
variables at all, so the prefixed lookup misses and the unprefixed one answers.

## 2. The factory builds it, and the precedent for refusing is in the same function

`BackendFactory.create_space_backend` (`backend_config.py:55`) already does
exactly the right thing for an earlier retirement:

```python
if config.backend_type == BackendType.POSTGRESQL:
    raise ValueError(
        "The 'postgresql' (V1) backend has been archived. "
        "Use BackendType.SPARQL_SQL for pure-PostgreSQL or "
        "BackendType.FUSEKI_POSTGRESQL for the Fuseki hybrid backend."
    )
```

A retired backend raises, and the message names the replacement. `FUSEKI` and
`FUSEKI_POSTGRESQL` fall through to live `import` + construct, three and eleven
lines below.

**And that message now recommends a retired backend.** The V1 retirement points
callers at `BackendType.FUSEKI_POSTGRESQL`, so following the guidance the code
gives moves you from one retired backend to another. Fixing this issue has to fix
that string too, or the refusal added for Fuseki will be contradicted by the
refusal above it.

`BackendType` (`:19`) also carries `OXIGRAPH`, which is out of scope here and
was not investigated — noted only so the next person does not read "the enum has
four live backends" out of this file.

## 3. The live suite still exercises it, and exempts it from a guard

  * **`tests/unit/test_space_graph_filter.py`** imports
    `vitalgraph.db.fuseki.fuseki_space_impl` (`:17`, again at `:72` via
    `inspect.getsource`) and tests `space_graph_filter`. A passing unit test for a
    retired backend. Its own docstring says "the fuseki backend needs a running
    Fuseki" and that it therefore asserts on filter TEXT — so it survives only
    because it never touches the backend it is about.
  * **`tests/unit/test_connection_settings_are_required.py`** exempts Fuseki from
    its guard twice — `EXCLUDE` at `:79` skips any path under `vitalgraph/`
    containing "fuseki", and `SKIP_LINE` at `:86` skips any LINE containing it.
    The comments justify both under "unused": *"a separate backend this work does
    not touch"* and *"Fuseki's HTTP credentials share these literals but are a
    different config domain"*.

Under the decision, both exemptions are dead weight — but note the ORDER, because
it is the reverse of the obvious one: **the exemptions should go BECAUSE the code
goes, not as a separate cleanup.** `SKIP_LINE` exists because
`vitalgraph_impl.py` builds a Fuseki config from a file whose name says nothing
about Fuseki, so removing the exemption while that code stands would make the
guard FAIL. Delete the code first and both exemptions become no-ops that match
nothing.

## What the decision changes, and what it merely makes stale

**Must change — these can mislead or misconfigure today:**

  1. `.env.example:55` — stop selecting it. The `sparql_sql` profile at `:192-209`
     is already written and commented out.
  2. `backend_config.py` — refuse `FUSEKI` and `FUSEKI_POSTGRESQL` the way
     `POSTGRESQL` is refused, and correct the V1 message that recommends one of
     them.
  3. `tests/unit/test_space_graph_filter.py` — delete. It is the only place the
     live suite asserts anything about Fuseki.
  4. `tests/unit/test_connection_settings_are_required.py` — drop both exemptions,
     AFTER 5.

**Stale, not dangerous — a sweep, and a separate decision on scope:**

  5. `vitalgraph/db/fuseki/` + `vitalgraph/db/fuseki_postgresql/` — 25 modules,
     reachable only through the factory arms in 2.
  6. 75 files under `test_scripts/` (incl. `kg_endpoint_fuseki/`, 5), 20 under
     `deploy/fuseki_deploy_test/`, 4 in `vitalgraph_sparql_sql_dev/`, 1 in
     `apps/fuseki/`.

The `planning/` docs are no longer in scope: all 185 tracked planning files were
untracked 2026-09-25, which removed 73 Fuseki-mentioning files from this count
without deleting anything from disk.

`issues/` keeps its 8, and `issues/archive/` its 3. Those are history and are
correctly kept — this file is not an argument for scrubbing the record.

## DO NOT sweep the Jena sidecar — it is not Fuseki and it is load-bearing

The single most likely way to break the system while acting on this issue.
`vitalgraph-jena-sidecar` is LIVE (port 7071 on the test stack) and every SPARQL
query is parsed through it; a server that cannot reach it fails every query
silently, returning `FOUND` with `total=0`. `test_scripts/jena_sidecar/` appears
in a Fuseki grep only because 3 of its files COMPARE Fuseki against SQL.

Both are Apache Jena projects and the names are one word apart. Grep for
`fuseki` and you will hit sidecar files; act on the hit and you remove the parser.

## Not established

  * **Whether the separate deploy repo selects Fuseki.** `issues/137` records that
    production is built from a deploy repo whose history shares no commits with
    this one. Everything above is about THIS tree. Refusing the backend in the
    factory (item 2) would surface the answer loudly at startup, which is an
    argument for doing it — but it should be checked first rather than discovered
    by a failed deploy.
  * **Whether any Fuseki module is imported by non-Fuseki code.** The factory arms
    are the only entry points found; a systematic check of the 50 files under
    `vitalgraph/` that mention it was not done, and "mentions" is not "imports".
  * **Whether `apps/fuseki/init_vitalgraph_fuseki_admin.py` is referenced by any
    deployment.** 44 occurrences in one file, not traced.
  * **What a retired backend's TESTS should become.** Deleting
    `test_space_graph_filter.py` loses the record of a real defect it pins — an
    unanchored regex that over-matched a space's named graphs. Its subject is
    retired; the mistake is not.

## Reproduce

    grep -n "BACKEND_TYPE" .env.example
    grep -n "_get_profile_env\|'sparql_sql'" vitalgraph/config/config_loader.py

The template's active value is `fuseki_postgresql`; the code's default is
`sparql_sql`; the resolution order means the template wins.
