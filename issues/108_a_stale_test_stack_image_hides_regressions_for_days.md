# A Stale Test-Stack Image Hides Regressions for Days

## Status: OPEN — the mechanism is understood; the fix is a decision, not a patch

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

* The image takes ~8 minutes to build, so nobody rebuilds casually.
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
