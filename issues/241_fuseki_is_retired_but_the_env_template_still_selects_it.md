# 241 — Fuseki is retired, but the env template still selects it and the factory still builds it

## Status: OPEN — the DECISION is made (2026-09-25: Fuseki is RETIRED, not merely
## unused), which is what this issue was blocked on. Nothing moved yet.
##
## THE GOAL IS TO ARCHIVE THE CODE, not delete it — `git mv` into
## `archive/archive_vitalgraph_old/`, where the V1 postgresql backend already
## sits, tracked. 81 tracked files. **One blocker, and it is specific:**
## `postgresql_signal_manager.py` lives in `fuseki_postgresql/` and is imported by
## the LIVE `SPARQL_SQL` backend, so it must move OUT before the package moves in.
##
## One item is a live defect rather than stale material: `.env.example` selects
## `fuseki_postgresql` and that value WINS over the correct `sparql_sql` default.
##
## ONE THING FIXED 2026-09-26: `create_backend_adapter`'s `else` no longer falls
## back to the retired adapter — it defaults to `sparql_sql`, pinned by test and
## verified by falsification. Everything else here is unstarted.
##
## THE PLAN DOES NOT REACH ZERO on its own: after the `git mv`, 31 files and 201
## `fuseki` lines remain under `vitalgraph/` — 19 files / 79 lines of them in no
## step at all, including `config_loader.py`, which still reads `FUSEKI_*` env vars
## and exposes `get_fuseki_config()`. Step 8 sweeps that and GATES it; see "Does
## the plan reach ...".
##
## DECIDED 2026-09-26: **remove backends that do not exist** from `BackendType`.
## That takes `FUSEKI`/`FUSEKI_POSTGRESQL` AND `POSTGRESQL` (whose package is
## already gone), replaces step 3's planned refusal with deletion, and leaves the
## `db/sparql_sql/` contrast comments as the ONLY deliberate residue in the tree.

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

## Order of work

0. ~~**Stop the adapter factory defaulting to Fuseki**~~ **DONE 2026-09-26** —
   `create_backend_adapter` defaults to `SparqlSQLBackendAdapter`, so archiving
   can no longer turn a silent mis-adaptation into a `NameError` on the fallback
   path. Numbered 0 because it was not in the original plan and is independent of
   everything below.
1. **Move `postgresql_signal_manager.py` out** of `fuseki_postgresql/` to a
   neutral home and repoint all three factory arms. Nothing else can proceed
   safely before this.
2. **Fix `.env.example:55`** — the one item that can misconfigure someone today,
   and independent of the move.
3. **Delete the `FUSEKI` / `FUSEKI_POSTGRESQL` arms** from both factories, and
   **delete the `POSTGRESQL` arm and enum member with them** — its package is
   already gone, so it is the same defect one retirement earlier ("The enum",
   decided 2026-09-26: remove backends that do not exist). This replaces the
   earlier plan of ADDING a refusal in the `POSTGRESQL` style.
   Then put the diagnostic where it survives the members: the `else` in
   `impl/vitalgraph_impl.py:94`, naming the retired strings explicitly — and fix
   that message, which currently recommends `'fuseki_postgresql'`, plus the
   `'postgresql'` default at `:30`. After this nothing can construct a retired
   backend and the move cannot break a running one.
4. **Remove or gate** the two `fuseki_admin` call sites; delete
   `tests/unit/test_space_graph_filter.py`.
5. **Strip the Fuseki semantics out of `kg_impl/`** — the "wider than the 81
   files" items below, which a `git mv` will NOT touch because `kg_impl/` is not
   among the 81. Delete `FusekiPostgreSQLBackendAdapter`
   (`kg_backend_utils.py:210`) and its dispatch arm, drop the `fuseki_success`
   field and the `FUSEKI_SYNC_FAILURE` log from the four write paths (33 lines),
   and remove the Fuseki cell from
   `tests/unit/test_backend_adapter_dispatch.py`. **Ordered after 3, and the
   reason is not what it first looks like:** deleting the arm while the backend can
   still be CONSTRUCTED does not leave it unadapted — the `else` hands it
   `SparqlSQLBackendAdapter`, silently. That is step 0's defect in mirror image,
   reappearing for the one backend whose name still matches. Verified by
   simulating it. Once 3 refuses construction the arm is unreachable, and from
   then on the order stops mattering — so this is a constraint on the WINDOW, not
   a permanent dependency, and the window is real only because `.env.example`
   selects Fuseki until 2 and an already-copied `.env` is not fixed by 2 either.
   **While that function is open, replace the class-NAME substring dispatch** with
   something explicit — it is the mechanism that made the bad default reachable,
   and with one arm left "substring of a class name" has no remaining excuse.
   Independent of the archive, so it can slip without blocking 6.
6. **`git mv` the 81 files** into `archive/archive_vitalgraph_old/`, and repoint
   the parity comments in `sparql_sql_space_impl.py`, `sparql_sql_db_impl.py`,
   `sparql_sql_db_objects.py` and `sparql_sql_schema.py` at the new path.
7. **Drop both Fuseki exemptions** from
   `tests/unit/test_connection_settings_are_required.py` — last, because they can
   only become no-ops once the code is gone, and dropping them earlier makes the
   guard fail on `vitalgraph_impl.py`.
8. **Sweep the residue and GATE it.** Steps 1-7 do NOT reach zero — see the
   accounting below. Clear the 19 files that no other step touches, then add a
   guard asserting `fuseki` appears nowhere under `vitalgraph/` except a short,
   justified allow-list. Without the guard "nothing Fuseki in the main packages"
   is a claim that decays on the first merge; with it, it is an invariant.

Steps 2 and 3 are the ones that stop the bleeding; 1 is the one that makes 6
possible; 6 is the goal; 8 is what makes the goal CHECKABLE. 5 is the step that is
easiest to forget, because nothing in `kg_impl/` imports the Fuseki packages — so
no import error, no failing test and no `git mv` will remind anyone it is
outstanding.

## Does the plan reach "nothing Fuseki outside the archive"? NOT AS WRITTEN

Asked directly, and worth answering with a count rather than a yes. After step 6
moves the two packages, **31 files and 201 `fuseki` lines remain under
`vitalgraph/`**. They fall into three groups, and only the first two are
intentional:

**Deliberate, and should stay:**

  * `db/sparql_sql/` — 17 lines across `sparql_sql_space_impl.py` (9),
    `sparql_sql_db_objects.py` (3), `sparql_sql_db_impl.py` (3),
    `sparql_sql_schema.py` (2). Step 6 repoints these AT the archive path; they
    describe the archived behaviour by contrast ("unlike fuseki_postgresql, which
    relies on Fuseki for query execution") and rewriting them loses the contrast.
  * `db/backend_config.py` — **nothing, as it turns out.** This row originally
    reserved the step-3 refusal as deliberate residue. The decision to REMOVE
    backends that do not exist (see "The enum") deletes the arms and the members
    instead of adding a refusal, and moves the diagnostic to
    `impl/vitalgraph_impl.py`'s `else` — which names retired backends in a STRING,
    not as enum members. So `backend_config.py` should reach zero `fuseki` lines,
    and the only deliberate residue left in the whole tree is the
    `db/sparql_sql/` contrast comments above.

**Partially covered — the step handles the CODE but not the prose:**

  * `kg_impl/` — step 5 removes the adapter and the 33 `fuseki_success` lines, but
    `kg_backend_utils.py:5`/`:189`, `kgentity_delete_impl.py:28`/`:145`,
    `kgslot_delete_impl.py:26`, `kgentity_update_impl.py:6`/`:38`,
    `kgslot_update_impl.py`, `kgtypes_update_impl.py` and
    `kg_graph_retrieval_utils.py` describe dual-write-to-Fuseki in docstrings that
    survive it.
  * `impl/vitalgraphapp_impl.py` (10) and `admin_cmd/vitalgraphdb_admin_cmd.py`
    (9) — step 4 takes the `fuseki_admin` call sites; the dataset auto-register
    block and the `get_fuseki_postgresql_config()` call are not in any step.

**No step touches these at all — 19 files, 79 lines:**

    config/config_loader.py                 27   FUSEKI_URL/DATASET/USERNAME/...,
                                                 get_fuseki_config(),
                                                 get_fuseki_postgresql_config()
    impl/vitalgraph_impl.py                 20   builds the Fuseki backend config
    ops/database_op.py, graph_import_op.py   5
    endpoint/kgentities, kgdocuments, kgframes 6
    space/space_manager.py, space_impl.py    4
    db/db_inf.py, db_admin_inf.py,
      space_backend_interface.py             4   interface docstrings offering
                                                 Fuseki as a live example
    kg_impl/ docstrings (7 files)            9
    entity_registry/entity_registry_impl.py  2

`config_loader.py` is the one that matters beyond tidiness: it still READS
`FUSEKI_*` environment variables and exposes `get_fuseki_config()`, so the
configuration surface keeps offering a backend that refuses to construct. That is
the same class of thing as `.env.example:55` — a live surface for a dead option.

**So the answer is no, and step 8 exists to make it yes.** The guard is the part
that matters: `issues/214` reached "zero occurrences in tracked files" for the
client name and it held because a rule enforced it, not because a sweep was
thorough. The analogue here is a test over `vitalgraph/` with an allow-list
holding only the `db/sparql_sql/` contrast comments and whatever step 3's refusal
needs. Note the irony to avoid: step 7 DELETES Fuseki exemptions from one guard,
and step 8 adds a new guard that needs its own — keep it short and make every
entry state why, or it becomes the thing `issues/188` describes, a rule that
passes by exempting what it cannot check.

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
