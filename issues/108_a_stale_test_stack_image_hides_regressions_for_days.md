# A Stale Test-Stack Image Hides Regressions for Days

## Status: options 1 and 2 DONE (2026-08-19, 2026-08-22) — the suite refuses,
## and now rebuilds once first. Options 3 and 4 DECLINED, with reasons.

`tests/shared/image_freshness.py`, called from `tests/api/conftest.py` at
`pytest_sessionstart`. It compares `vitalgraph/**/*.py` in the working tree
against the same files in the container and exits with the differing paths.

**It caught its own author, the same day.** The text-needle change
(`issues/070`) was reported as "unit, integration, api and performance all
pass". The container was missing `text_needle.py` entirely and still carried the
`(term_text || '')` hack the change removed:

    CHANGED (5):  db/sparql_sql/filter_pushdown.py, generator.py, ir.py,
                  semijoin.py, model/kgentities_model.py
    ONLY IN TREE — never built (1):  db/sparql_sql/text_needle.py

Rebuilding then exposed a second defect the API had been hiding: a REFUSED
generation returned an ordinary empty result set, because only `cr.ok` was
checked and never `gen.ok`. See the commit "report a refused generation instead
of answering empty" — a refusal indistinguishable from "no matches", found only
because the code was finally executed through the API.

Four decisions in the implementation, each guarding a way it could have become
noise:

* the hash algorithm is SENT as a `python -c` literal, never imported from the
  image — an imported hasher is the stale copy, and changing it would report a
  mismatch that is not staleness;
* per-file rather than one tree hash, so the failure separates "rebuild" from
  "you edited something the image does not contain";
* it FAILS, it does not skip — a skip in a suite read as coverage is this same
  defect, and this repo has shipped that twice;
* the absent-container path fails when the target is localhost. "Docker is not
  here, so pass" makes the guard a no-op exactly where nobody is looking. A
  non-local target is exempt, because a remote stack builds from the commit
  under test. `VG_ALLOW_STALE_IMAGE=1` escapes and still prints what it skips.

It cannot rebuild for you. Options 2-4 below remain a decision.

Two correctness regressions shipped on 2026-08-17 and were found on 2026-08-18,
both by the same accident: someone rebuilt the container.

    f3068d8   a BIND-projected variable returned nothing
    9d9b071   a FILTER over text stopped generating at all

Between them they broke `_frame_exists_in_backend` — so every frame looked
absent, DELETE answered "Frame not found", and **14 API tests failed** — and made
the frames list answer `total_count: 3, objects: []`, a search box reporting
three results above an empty table.

Neither was caught for a day. `vitalgraph-test-app` was **43 hours old**, so no
request had ever executed the new code. `tests/api` and the Playwright suite both
run against `:8002`, which serves that image.

## Why this is not "remember to rebuild"

**A green `tests/api` says nothing about code the running image does not
contain**, and nothing distinguishes the two. The suite passes identically
whether it is testing today's code or Tuesday's, which makes it worse than no
signal: it is a signal that is read as coverage.

The same day, the reverse also happened — a rebuild surfaced `issues/107`
(`column j2._seg_idx does not exist`), which had been latent because the semi-join
gate that exposes it fires on statistics, not on code.

## What makes it likely rather than unlucky

* ~~The image takes ~8 minutes to build, so nobody rebuilds casually.~~
  **WRONG, and it shaped a whole day's behaviour.** Measured 2026-08-20 across
  six consecutive rebuilds: **21-24 seconds**. Docker layer caching means only
  the source COPY and the layers after it are redone. The ~8 minutes is a COLD
  build. Believing the stale figure is why changes got batched to avoid
  rebuilding — the opposite of what this issue asks for.
* `docker compose up -d` does NOT rebuild on source changes; it recreates only
  when the compose config or image changes.
* The generator is the most-changed component in this repo and is entirely
  inside the image.
* PGDATA lives in the app-adjacent postgres container's writable layer
  (`issues/102`), which trains everyone to avoid recreating containers.

## Options, none of them free

1. **Fail the API suite when the image is older than HEAD.** A conftest check
   comparing the container's `vitalgraph` source hash to the working tree, and
   skipping loudly — or failing — on a mismatch. Cheap, and it converts a silent
   false pass into a stated one. It cannot rebuild for you.
2. **Rebuild in the API suite's session fixture.** Correct and slow: 8 minutes
   on every run of `tests/api`, which will get worked around.
3. **Bind-mount the source into the container for the test stack.** Removes the
   staleness entirely for pure-Python changes; diverges from how the image is
   built in CI, which is its own class of "works here" bug.
4. **Run `tests/api` only in CI**, where the image is always built from the
   commit under test. Honest, and gives up the local signal.

Option 1 is the smallest thing that makes the failure loud, and does not
substitute for a decision about 2-4.

## Evidence this is a pattern, not an incident

* `issues/102` — the test stack could not run a parallel query for weeks, hidden
  because the fixtures that would provoke one were not loaded.
* `issues/041` — a derived table can be a faithful copy of the PREVIOUS contents,
  and every count check passes.
* `issues/088` — an optimisation reverted twice with every suite green.

The common shape: **a check that reports success while measuring something other
than what it names.**

## Related

- `issues/100` — the two days of wrong hypotheses that a stale image contributed to
- `issues/107` — found by the rebuild, latent before it
- `issues/102` — PGDATA in the writable layer, the reason recreating is avoided

## Option 2 landed 2026-08-22 (`c21d89d`), and the objection to it was wrong

This file rejected rebuilding automatically as "correct and slow: 8 minutes on
every run of `tests/api`, which will get worked around". That number was a COLD
build. Measured on a machine with the warm layer cache it normally has:

    no-op build (nothing changed)          1.7 s
    rebuild after a real source change    24.1 s
    container recreate and health         13 s

**0.4 s when the image is current**, about 40 s when it is not. The estimate
was out by two orders of magnitude for the case that happens on almost every
run, and the decision rested on it for three days.

On a mismatch the guard now rebuilds once, recreates the app container, waits
for `/health`, and re-checks. Still stale afterwards and it fails as before,
saying a rebuild was already attempted so the cause is not staleness.

Scoped to the app service with `--no-deps`, because this stack's postgres keeps
PGDATA in its writable layer (`issues/102`) and recreating it would destroy the
fixtures. Verified untouched across a self-heal: 54 spaces, 50,570,000 quads.

`VG_NO_IMAGE_REBUILD=1` keeps the check without the side effect.

### Why 3 and 4 are declined

**3, bind-mount the source.** It would remove staleness for pure-Python changes
and introduce a different class of "works here": the tested artefact stops
being the built image, so anything the Dockerfile does — dependency pinning,
compiled extensions, file layout — is no longer exercised locally. Option 2
gets the same result while keeping the image the thing under test.

**4, run `tests/api` only in CI.** This gives up the local signal to protect
it, and the local signal is where the two regressions in this file were found.
With option 2 the local run is now self-correcting, which is what made 4 look
attractive in the first place.

### A footnote worth keeping

The module logged through an undefined `logger` — a `NameError` waiting to fire
exactly when a rebuild failed, replacing the diagnosis with a traceback at the
one moment it mattered. Found while wiring option 2, not by the tests.