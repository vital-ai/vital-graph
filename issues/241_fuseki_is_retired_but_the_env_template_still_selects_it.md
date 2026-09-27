# 241 — Fuseki is retired, but the env template still selects it and the factory still builds it

## Status: DONE — steps 0-8 all complete and verified against the code
## 2026-09-26. **`vitalgraph/` names a retired backend in ZERO places**, with no
## allow-list, gated by `tests/unit/test_retired_backends_are_gone.py` (falsified).
## `BackendType` is exactly `['sparql_sql', 'oxigraph']`. 102 files moved into
## `archive/archive_vitalgraph_old/` with history preserved.
##
## WHAT IS LEFT is outside the main package and is listed under "Remaining" at the
## end — 4 Keycloak client IDs that are EXTERNAL identifiers, one historical doc,
## one non-runnable benchmark in the dev staging area, and two provenance notes.
## Nothing that can misconfigure or mislead a caller.
##
## Two defects were introduced by this work and fixed: the adapter dispatch refused
## an already-built adapter (`issues/243`), and `case_frame_operations_reset.py`
## asserted a field that no longer exists so it failed on every operation.

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

**Stale rather than dangerous — and the scope IS decided: these are ARCHIVED, not
deleted. See "The goal" below for the file counts, the blocker and the ordering.**

  5. `vitalgraph/db/fuseki/` + `vitalgraph/db/fuseki_postgresql/` — 25 modules,
     reachable only through the factory arms in 2, EXCEPT
     `postgresql_signal_manager.py`, which the live `SPARQL_SQL` backend imports
     and which therefore has to move out first.
  6. 75 files under `test_scripts/` (incl. `kg_endpoint_fuseki/`, 5), 20 under
     `deploy/fuseki_deploy_test/`, 4 in `vitalgraph_sparql_sql_dev/`, 1 in
     `apps/fuseki/`.

The `planning/` docs are no longer in scope: all 185 tracked planning files were
untracked 2026-09-25, which removed 73 Fuseki-mentioning files from this count
without deleting anything from disk.

`issues/` keeps its 8, and `issues/archive/` its 3. Those are history and are
correctly kept — this file is not an argument for scrubbing the record.

## The enum: remove backends that do not exist — DECIDED 2026-09-26

The open question above is settled, and settling it made the scope bigger rather
than smaller. `BackendType` (`backend_config.py:19`) has five members; only two
name something a caller could use:

| member | package | |
|---|---|---|
| `POSTGRESQL` | **`vitalgraph/db/postgresql/` DOES NOT EXIST** | remove |
| `FUSEKI` | `db/fuseki/`, 6 modules — retired | remove |
| `FUSEKI_POSTGRESQL` | `db/fuseki_postgresql/`, 19 modules — retired | remove |
| `SPARQL_SQL` | `db/sparql_sql/`, 93 modules | keep |
| `OXIGRAPH` | `db/oxigraph/`, 5 modules | see below |

**`POSTGRESQL` is the case the decision reaches immediately**, and it is not part
of the Fuseki work: its package is already gone, so the enum has been advertising
a backend with NO implementation since V1 was archived. The refusal arm at
`backend_config.py:65` exists only because the member was kept. Under this rule
both go — which also removes the message that recommends `FUSEKI_POSTGRESQL`, so
step 3's "correct the V1 message" becomes "delete the V1 arm" instead.

**`OXIGRAPH` stays by the letter of the rule** — the package exists and it has a
factory arm — but it has NO arm in `create_backend_adapter`, so it cannot be used
through the KG path at all. Whether that makes it a backend that "exists" is a
separate question and is NOT decided here; flagged so nobody reads this table as
having blessed it.

**Removing members cannot break a parse.** `BackendType(<string>)` is never called
anywhere in the tree — the enum is only ever referenced by member, and the
string-to-backend dispatch is the `if/elif` chain in `impl/vitalgraph_impl.py:35`.
So the helpful diagnostic does not need a live enum member to carry it: it belongs
in that chain's `else`, naming the retired values explicitly ("'fuseki_postgresql'
was retired; use 'sparql_sql'"). That is strictly better than the status quo, where
the message exists only as a side effect of keeping a dead member.

**Two sites found while settling this, both in `impl/vitalgraph_impl.py`:**

  * **`:94` — the unknown-backend error recommends a retired backend.** *"Use
    'sparql_sql' or 'fuseki_postgresql' instead."* That is the SECOND instance of
    retirement guidance pointing at Fuseki, alongside `backend_config.py`'s V1
    message. Both must change together or one contradicts the other.
  * **`:30` — the default backend is the one with no package.**
    `backend_config.get('type', 'postgresql')`. **LATENT, not live**, and the
    distinction matters: `config_loader.py:147` always supplies `'type'`, so this
    fires only if the whole `backend` section is absent, and it then fails CLOSED
    with the ValueError at `:94` rather than selecting anything. So it is a wrong
    default that cannot currently mis-route a request — but it is a second,
    contradictory default in the same chain (`sparql_sql` at one end,
    `postgresql` at the other) and should be `sparql_sql`.

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

## The goal: ARCHIVE the code, the way the V1 backend was archived

Not delete. The precedent already exists in this repo and the retirement message
in `backend_config.py` names it — *"The 'postgresql' (V1) backend has been
archived"* — and the code is still there and still readable:

    archive/archive_vitalgraph_old/db_postgresql/    34 tracked files

`archive/` is TRACKED (121 files; only `archive/frontend-archive/` and
`archive/frontend-old/` are gitignored), so this is `git mv`, history preserved,
not a deletion. That distinction is load-bearing for this particular backend —
see "why it must stay readable" below.

**What moves, 81 tracked files:**

| path | tracked files |
|---|---:|
| `vitalgraph/db/fuseki/` | 6 |
| `vitalgraph/db/fuseki_postgresql/` | 19 |
| `apps/fuseki/` | 1 |
| `deploy/fuseki_deploy_test/` | 20 |
| `test_scripts/fuseki_postgresql/` | 29 |
| `test_scripts/kg_endpoint_fuseki/` | 6 |

## THE BLOCKER — the live backend's signal manager lives inside the retired package

`vitalgraph/db/fuseki_postgresql/postgresql_signal_manager.py` cannot move with
its package, because **`BackendType.SPARQL_SQL` imports it**:

    backend_config.py:188   POSTGRESQL (V1, archived)  -> .fuseki_postgresql.postgresql_signal_manager
    backend_config.py:202   FUSEKI_POSTGRESQL          -> .fuseki_postgresql.postgresql_signal_manager
    backend_config.py:209   SPARQL_SQL  (LIVE)         -> .fuseki_postgresql.postgresql_signal_manager

Archive the package as-is and the live backend loses its signal manager at
startup. It must move OUT to a neutral home FIRST — `vitalgraph/db/` or beside
`sparql_sql/` — and then the package can go.

**Its docstring makes the mislabelling explicit**, and is worth reading as the
statement of the problem rather than a nitpick:

    """PostgreSQL-based signal implementation for FUSEKI_POSTGRESQL backend."""

A module that serves the live backend, named after the retired one, documented as
belonging to the retired one.

**This trap is already one iteration old.** `backend_config.py:186` carries the
comment *"V1 postgresql backend archived — use the shared signal manager"* — so
when V1 was archived, its signal manager was NOT archived with it; it was left in
(or moved into) `fuseki_postgresql` and shared. Archiving Fuseki without moving
that module out repeats the same move one layer on, and the next retirement
inherits it again. The fix is to stop the shared module living in any retired
backend's package, not to pick a better one to park it in.

## The other live call sites, and which are already gated

  * **`fuseki_admin.FusekiPostgreSQLAdmin`** — imported at
    `admin_cmd/vitalgraphdb_admin_cmd.py:282` and `impl/vitalgraphapp_impl.py:219`.
    NOT gated at either site from what was read. These have to go or be gated
    before the move.
  * **`postgresql_schema.FusekiPostgreSQLSchema`** — imported at
    `admin_cmd/vitalgraphdb_admin_cmd.py:2140`, which sits inside
    `elif backend_type == 'fuseki_postgresql':`. Already gated, so it goes with
    the backend arm and needs no separate work.
  * **`tests/unit/test_space_graph_filter.py`** imports
    `vitalgraph.db.fuseki.fuseki_space_impl` directly — it must be deleted (or
    moved) as part of the same change, or the move breaks collection.

## Why it must stay READABLE and not be deleted

The live backend documents its own behaviour by reference to this code:

    sparql_sql_space_impl.py:120   "Deterministic UUID v5 for an RDF term —
                                    matches fuseki_postgresql ..."
    sparql_sql_space_impl.py:402   "... transactions on the sparql_sql backend
                                    identically to fuseki_postgresql ..."

Term uuids are a hash over `(text, type, lang, datatype)` and a disagreement
produces a DIFFERENT TERM rather than a cosmetic difference (`issues/135`). So
`fuseki_postgresql` is the parity reference for two invariants the live backend
claims to hold. Deleting it removes the thing those comments point at; archiving
it keeps the claim checkable. If the reference is to stay useful, the comments
should be repointed at the archive path in the same change.

## Order of work — ALL DONE 2026-09-26, each verified against the code

Verified by inspection at the end, not from memory — the status line claimed these
were done for a while before this list said so.

0. ~~Stop the adapter factory defaulting to Fuseki.~~ `create_backend_adapter`
   returns `SparqlSQLBackendAdapter` and is IDEMPOTENT — an already-built adapter
   passes through. It briefly refused one instead, which broke frame-graph
   retrieval; see `issues/243`.
1. ~~Move `postgresql_signal_manager.py` out of the retired package.~~ Now
   `vitalgraph/db/postgresql_signal_manager.py`. This was the blocker: the LIVE
   backend's signal manager was inside the package being archived.
2. ~~Fix `.env.example`.~~ `LOCAL_BACKEND_TYPE=sparql_sql`, 18 `FUSEKI_*` variables
   dropped, `LOCAL_SIDECAR_URL` added because the Jena sidecar is what this backend
   actually needs.
3. ~~Delete the factory arms and the enum members.~~ `BackendType` is exactly
   `['sparql_sql', 'oxigraph']`. `POSTGRESQL` went too — its package had already
   been deleted, so the style this issue planned to COPY was itself the defect.
4. ~~Remove the `fuseki_admin` call sites; delete the retired unit test.~~ Zero
   references under `vitalgraph/`; `tests/unit/test_space_graph_filter.py` gone.
5. ~~Strip the Fuseki semantics out of `kg_impl/`.~~ `FusekiPostgreSQLBackendAdapter`
   and every `fuseki_success` are gone, and the dispatch is `isinstance` rather than
   a substring of a class name.
6. ~~`git mv` into the archive.~~ No `vitalgraph/db/fuseki*` remains;
   `archive/archive_vitalgraph_old/` holds 153 tracked files, 102 of them moved by
   this work.
7. ~~Drop both Fuseki exemptions from `test_connection_settings_are_required.py`.~~
   `EXCLUDE` and `SKIP_LINE` no longer name it; the one mention left is the comment
   recording why they went. The guard now covers every line it sees.
8. ~~Sweep the residue and gate it.~~
   `tests/unit/test_retired_backends_are_gone.py`, NO allow-list, verified by
   falsification. `vitalgraph/` is at zero.

## Wider than the 81 files: `kg_impl/` carries Fuseki SEMANTICS, not just imports

Found while copying knowledge out of the code before it is archived. These are
not imports of the Fuseki packages, so they do not appear in the move list above
and a `git mv` will not touch them — but they encode the retired backend's model
of the world. **Scheduled as step 5 of the order of work**, which exists because
"dealt with in the same pass" is not a plan: nothing here imports the Fuseki
packages, so no import error and no failing test would ever surface it.

**1. The adapter factory's DEFAULT is the retired backend.**
`kg_impl/kg_backend_utils.py:1782` dispatches on a substring of the class NAME:

```python
backend_type = type(backend_impl).__name__
if 'SparqlSQL' in backend_type:       return SparqlSQLBackendAdapter(backend_impl)
elif 'FusekiPostgreSQL' in backend_type: return FusekiPostgreSQLBackendAdapter(backend_impl)
else:
    # Default to Fuseki+PostgreSQL adapter
    return FusekiPostgreSQLBackendAdapter(backend_impl)
```

Any backend whose class name does not contain `SparqlSQL` silently gets the
Fuseki adapter. So the fallback for "I do not recognise this backend" is the one
that is retired — the same shape as `.env.example:55`, one layer up, and it would
raise `NameError` rather than fall back once the class is archived.

**FIXED 2026-09-26: the default is now `SparqlSQLBackendAdapter`.** This file first
proposed making the `else` a REFUSAL; the decision was to default to the live
backend instead, which is the more consistent answer — `config_loader.py:147`
already resolves `BACKEND_TYPE` to `sparql_sql` when nothing says otherwise, so a
refusal here would have been the one place in the resolution chain that declined
to assume the only backend that exists.

Pinned by `tests/unit/test_backend_adapter_dispatch.py`, and VERIFIED BY
FALSIFICATION: with the old default restored, the two unrecognised-backend cells
fail and the rest pass, so the guard is testing the branch it claims to. Asserted
as `not FusekiPostgreSQLBackendAdapter` as well as `is SparqlSQLBackendAdapter`,
because the defect would survive a change to some third adapter. `OxigraphSpaceImpl`
is one of the two parametrised cases and is not hypothetical —
`BackendType.OXIGRAPH` is in the enum with no arm in this dispatch.

The explicit Fuseki arm is LEFT IN PLACE for now, because the package is still
here: the cell covering it pins that Fuseki's real route is the explicit arm,
which is what makes the `else` genuinely the unrecognised case. **Both the arm and
that cell are STEP 5**, not loose ends — and so is the
**substring-on-class-name dispatch**, which is still fragile and still unfixed,
but a wrong guess now lands on the live backend rather than the retired one, which
is the part that could not wait.

`FusekiPostgreSQLBackendAdapter` itself (`:210`) is a full `KGBackendInterface`
implementation living in a LIVE module, which is exactly why it needs its own step:
`kg_impl/` is not among the 81 files, so the `git mv` in step 6 will not carry it.

**2. `fuseki_success` is a result field on four write paths.** 33 lines across
`kgentity_frame_delete_impl.py` (13), `kgentity_frame_create_impl.py` (9),
`kgframe_create_impl.py` (6), `kgentity_frame_update_impl.py` (4) — a tri-state
`Optional[bool]` recording whether the Fuseki half of a dual write succeeded,
plus a `FUSEKI_SYNC_FAILURE` error log at
`kgentity_frame_delete_impl.py:486`. On a single-store backend the concept has no
referent: there is no second store to be out of sync with.

**It is NOT a public surface**, which is the one piece of good news here —
`fuseki_success` appears nowhere in `vitalgraph/model/` or
`vitalgraph/endpoint/`, so removing it is an internal refactor and not an API
change. Checked rather than assumed, because a tri-state success flag on a
response model would have made this a versioning problem.

**3. Interface docstrings name Fuseki as a live example** —
`db/space_backend_interface.py:5` and `:444` ("Fuseki: HTTP webhooks or
polling"), `db/db_inf.py:10`, `db/db_admin_inf.py:4`, `space/space_impl.py:14`,
`space/space_manager.py:79`. Documentation only, but it is what a reader uses to
decide what the interface is FOR, and it currently says the answer is a backend
that no longer exists.

## Knowledge copied out of the Fuseki code before archiving, 2026-09-25

The parity references in `sparql_sql_space_impl.py` are no longer pointers into
code that is about to move. Each now states the fact instead:

  * **`_generate_term_uuid`** carries the wire format in full — namespace,
    component order, the `\x00` separator, and which fields are omitted rather
    than empty — because it is a compatibility contract and every stored
    `term_uuid` is its output. Three things recorded that were only discoverable
    from the archived code:
    **(a)** the namespace is `uuid.NAMESPACE_DNS`, the standard RFC 4122
    constant, not a VitalGraph-specific one — the archived comment called it "a
    consistent namespace UUID for VitalGraph terms", which invites someone to
    "fix" it and reassign every term uuid in every space;
    **(b)** `datatype_id` is a per-space `BIGSERIAL`, so a typed literal's
    identity depends on a LOCAL id, stable across spaces only because
    `STANDARD_DATATYPES` is seeded in list order — reordering that list changes
    every typed-literal uuid in every space created afterwards
    (`filter_pushdown.py:890` leans on the same invariant);
    **(c)** the archived batch write path hardcoded `datatype_id = None` for
    every term under a standing TODO, so typed literals it wrote were hashed with
    the datatype OMITTED. Their uuids are not what this function produces for the
    same triple — which is a mechanism behind the datatype-loss family
    (`issues/157`, `221`, `234`) and part of why those end "existing spaces still
    need reloading".
    The stated format is asserted against the implementation, five cases
    including the blank-node divergence, so the docstring cannot drift silently.
  * **`_SparqlSQLCoreAdapter`** states the transaction contract callers rely on,
    and records TWO things the archived version did that it does not: it called
    `track_connection()` (`utils/resource_manager.py:212` — still live, and used
    by `sparql_sql_db_impl.py`, just not on this path), and it RELEASED THE
    CONNECTION IF STARTING THE TRANSACTION RAISED. Here, a failure in
    `tr.start()` after a successful `acquire()` leaks the connection for the life
    of the process. **Recorded, deliberately not fixed** — it is pool behaviour
    and belongs with `issues/231`; on a 30-connection pool with no bulkhead it is
    1/30th of the box per occurrence, and `issues/229` is what exhaustion looks
    like from outside (fewer results, HTTP 200, no error).
  * **Graph auto-registration** states the rule — inserting a quad into a graph
    URI implicitly creates that graph's catalog row — rather than citing
    `DualWriteCoordinator` for it, with `issues/116` for what happens when only
    some write paths honour it.
  * **`_VITALGRAPH_NS`** and **`_SparqlSQLDbOpsAdapter`** no longer describe
    themselves by reference to the archived names.

Three references were left pointing at the archived code deliberately, because
they are about the ARCHIVED behaviour rather than this backend's:
`sparql_sql_db_impl.py:8`, `sparql_sql_db_objects.py:5`/`:74`, and
`sparql_sql_schema.py:11`/`:1623` ("unlike fuseki_postgresql, which relies on
Fuseki for query execution"). Those should be repointed at the archive path in
step 6 rather than rewritten.

## Remaining — the whole tracked tree, 2026-09-26

Every tracked occurrence outside `archive/` and `issues/`, counted rather than
estimated. `vitalgraph/` is absent from this list, which is the point.

    .env.example                                     5   Keycloak CLIENT IDs
    tests/unit/test_retired_backends_are_gone.py      6   the gate itself
    tests/unit/test_connection_settings_are_required  3   why the exemptions went
    test_scripts/jena_sidecar/data_profile.md        11   historical comparison
    test_scripts/test_script_kg_impl/kgentity_test_data.py  2  provenance note
    vitalgraph_sparql_sql_dev/scripts/benchmark_fuseki_vs_sql.py  54
    vitalgraph_sparql_sql_dev/data/load_wordnet_frames.py  1   historical note
    .gitignore                                       1   archived TDB path
    deploy/deploy_docs/ECS_DEPLOYMENT_GUIDE.md        1   the env-var table
    vitalhome/.../vitalsigns_config.yaml.template     1   VitalSigns vocabulary
    tests/unit/test_frame_delete_reports_failure.py   1   issues/242 history

None of these can misconfigure anything or tell a caller a backend exists:

  * **The 4 Keycloak client IDs** (`fuseki-client`, `fuseki-graphdb`) name clients
    registered in a Keycloak realm. Changing them breaks auth rather than tidying
    it — they are external identifiers that happen to contain the word.
  * **The two test files and the two provenance notes** exist to say why something
    was removed. Deleting them would delete the reason.
  * **`data_profile.md`** is a historical Fuseki-vs-SQL literal comparison, headed as
    such. Its datatype findings are what `issues/221`/`234` turned out to be about,
    and the Jena SIDECAR it sits beside is live and unrelated.
  * **`benchmark_fuseki_vs_sql.py`** cannot run. LEFT IN PLACE: that package is a
    deliberate staging area for experiments and is not swept.
  * **`vitalsigns_config.yaml.template`** — `database_type: "fuseki"` in an example
    service block. That is VitalSigns' config vocabulary, not this project's
    backend registry, so it is not ours to change.
  * **The deploy guide and `.gitignore`** are one line each and cosmetic; the
    gitignore pattern now points at the archived path so an old checkout stays
    clean.

The gate is scoped to `vitalgraph/` ONLY, deliberately: a guard that fails on
pre-existing hits elsewhere gets disabled rather than fixed (`issues/188`). Widening
it would mean deciding each of the above, and each has a reason to stay.
