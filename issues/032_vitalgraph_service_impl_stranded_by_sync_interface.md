# VitalGraphServiceImpl is stranded: it implements a sync VitalSigns interface over an async client

## Status: OPEN

*(renumbered from 027 on 2026-08-04 — the number collided with
`027_exists_loses_correlation_for_filter_only_outer_vars.md`)*

## Severity

**A whole integration surface is non-functional.** `VitalGraphServiceImpl` is
the remote/client-backed implementation of the VitalSigns `VitalGraphService`
interface — the abstraction that is supposed to let calling code work against a
local graph service or a remote VitalGraph server without caring which. The
remote half of that contract does not currently work at all.

No production code is affected today, because nothing imports it (see
"Blast radius"). The cost is the missing capability, not a live outage.

## The design intent

`VitalGraphService` (`vital_ai_vitalsigns/service/graph/graph_service.py`, an
`ABC` with 31 abstract methods) defines one interface satisfied by several
backends:

| Implementation | Where | Nature |
|---|---|---|
| `MemoryGraphService` | `vitalsigns/service/graph/memory/` | local, in-process |
| `VirtuosoService` | `vitalsigns/service/graph/virtuoso/` | local driver |
| `RDFLibSparqlImpl` | `vitalsigns/impl/rdflib/` | local driver |
| **`VitalGraphServiceImpl`** | **this repo**, `vitalgraph/service/graph/` | **remote, over `VitalGraphClient`** |

Callers such as `vitalsigns/service/vital_service.py` (23 `self.graph_service.*`
call sites) are written once against the interface. Swapping local for remote
should be a construction-time choice.

## What broke it

The interface is synchronous — 34 `def`, zero `async def`. Every other
implementor is sync-native, so that cost them nothing. `VitalGraphServiceImpl`
is the only one whose backend is asynchronous.

It was written when `VitalGraphClient` was also synchronous. Commit `2118686`
(2026-02-11) converted the client to async and updated ~10 client endpoint
modules, but did **not** touch `vitalgraph_service_impl.py`. Before that commit
the call sites were correct as written (`def execute_sparql_query` at
`a978486:vitalgraph/client/vitalgraph_client.py:587`); the conversion orphaned
them wholesale.

The result: 50 sync methods calling the async client at **26 sites** with no
`await`. Each returns an un-awaited coroutine. The two that this was noticed
through:

- `vitalgraph_service_impl.py:334,360` — `.get("boolean", …)` against a
  coroutine object. At `:335` the `except` catches only `VitalGraphClientError`,
  so the `AttributeError` reaches the caller; at `:361` a broad
  `except Exception` swallows it into `False`.

A second, older mismatch compounds it: these sites pass a raw query string where
the client signature has expected a `SPARQLQueryRequest` since before the async
conversion. So the module had already drifted from the client API.

## Blast radius

- Nothing under `vitalgraph/` imports `VitalGraphServiceImpl`.
- The only references are `test_scripts/vitalgraph_service_tests/`, which CI
  does not run.

That is why six months passed without a symptom — and also why fixing it is a
question of whether the integration is wanted, not an emergency.

## Preferred resolution: make the interface async upstream

Per the design intent, the right fix is on the **VitalSigns** side, not here.
Converting `VitalGraphService`'s 31 abstract methods to `async def` means
`VitalGraphServiceImpl` becomes correct with little more than adding `async`/
`await` — its method bodies already assume an async backend, which is precisely
the mismatch.

Source repo: `/Users/hadfield/Local/vital-git/vital-vitalsigns-python`
(version `0.1.55`). This repo now pins `vital-ai-vitalsigns>=0.1.55` in
`pyproject.toml:24,39`, raised from `>=0.1.53` so the floor matches the source
tree the interface change will be made in.

Work required upstream:

1. Convert the 31 abstract methods on `VitalGraphService` to `async def`.
2. Convert the three sync-native implementors (`MemoryGraphService`,
   `VirtuosoService`, `RDFLibSparqlImpl`) to `async def`. Mechanical — their
   bodies do no I/O awaiting, so the signature changes and the logic does not.
   They will block the loop as before; that is a separate performance question,
   not a correctness one.
3. Update `vital_service.py`'s 23 call sites to `await`, and whatever calls
   *it* in turn — this is the part to scope before committing.
4. Release, bump the pin here.

Then in this repo:

5. Mark all of `VitalGraphServiceImpl`'s methods `async`, `await` the 26 client
   calls, and wrap raw query strings in the request models the client expects
   (`SPARQLQueryRequest` and siblings).
6. Give it real coverage. It has none in `tests/api`; `test_scripts/` is not run
   by CI. Whether the interface round-trips against a live server is exactly
   what is untested.

**Sequencing caveat.** Step 3 is the unknown. Converting the interface is a
breaking change to a shared library used by other repos in this workspace; the
number of downstream `graph_service` consumers outside
`vital-vitalsigns-python` should be counted before starting, or step 1 lands and
strands a different caller the same way this one was stranded.

## Alternatives, if the upstream change is not wanted

- **Bridge locally.** Keep the sync interface and have `VitalGraphServiceImpl`
  drive the async client through its own event loop (`asyncio.run` per call, or
  a dedicated loop thread). Self-contained, but it re-blocks every call, is
  hostile to callers already inside a running loop, and preserves the shape that
  produced this bug.
- **Delete it.** If a remote `VitalGraphService` is not actually wanted, remove
  the module and `test_scripts/vitalgraph_service_tests/`. Cheapest honest
  outcome, and better than leaving code that looks supported.

Deliberately not chosen here — this is a product decision about the integration.

## Related

- `issues/024_query_form_detected_by_string_prefix_not_parser.md` — the ASK /
  `boolean` audit that surfaced this. The two boolean readers at `:334,360` are
  just where that audit intersected a module-wide problem; 024 records the
  finding and explicitly defers it here.
