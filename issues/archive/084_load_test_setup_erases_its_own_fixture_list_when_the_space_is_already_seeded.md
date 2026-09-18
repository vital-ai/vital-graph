# Load-Test Setup Erases Its Own Fixture List When The Space Is Already Seeded

## Status: FIXED 2026-08-16

`load_test_scripts/setup.py` generates entities and then WRITES the URIs it
created into `load_test_scripts/load_test_data.py`, which the driver reads to
pick random entities.

Run it against a space that is already seeded and it creates 0 new entities —
then writes that empty result over the file:

    SETUP COMPLETE — 0 entities ready

    load_test_data.py | 83 +-------------------------------
    1 file changed, 1 insertion(+), 82 deletions(-)

The driver then refuses to run:

    No entity URIs — run setup.py first.

So the advertised fix for the failure is the command that caused it, and running
it again does not help — the space is still seeded, so it still creates nothing
and still writes nothing. Recovering needs `git checkout` of a tracked file,
which is not obvious from the message.

## Why it matters more than the inconvenience

* **It is a destructive write on a TRACKED file**, performed as a side effect of
  a setup command. Any local edits to that fixture list are gone.
* **The failure mode is silent at the point of damage.** `0 entities ready` is
  printed as a SUCCESS line. Nothing says "I just emptied the file the driver
  depends on".
* **It makes the seeded-space case the broken one.** Re-running setup is the
  normal thing to do before a load run, and it is exactly what breaks it.

## Fix

1. Do not write the fixture list when the run created nothing — or better, write
   the URIs the space ACTUALLY contains rather than only the ones this run
   created. The driver wants entities that exist, not entities that are new.
2. If the space is already populated, say so and exit non-zero, rather than
   reporting completion with a count of zero.
3. Consider not writing to a tracked source file at all. A generated fixture
   list belongs beside the run output, not in the repo — the current design
   means every seeding run dirties the working tree.

## Fixed

All three, plus the driver message that sent people back into the failure.

**1. It records what the space CONTAINS.** `_entities_in_space` reads the space
back after seeding and writes that, so a second run against a seeded space still
produces a usable list instead of an empty one. The driver wants entities that
exist, not entities that are new.

**2. An empty or unknown result is never written.** Two cases, kept apart
because they mean different things:

* the listing FAILED — no answer. The existing file is left untouched rather
  than replaced with a lie.
* the space is genuinely empty after seeding — refuses to write, and says the
  created/failed counts.

Either way `main()` exits **1** with `SETUP FAILED`. It used to print
`SETUP COMPLETE — 0 entities ready` and return 0 while destroying the list.

**3. The generated list is no longer a tracked source file.** It is
`load_test_entities.json`, gitignored; `load_test_data.py` stays tracked and
reads it. A seeding run no longer shows up in `git status` at all — verified by
writing the file and checking `git status --untracked-files=all` is clean for
that path.

**4. The driver names the actual state.** It said "run setup.py first", which
was the command that had emptied the list, and re-running it did the same thing
again. It now distinguishes "the file is missing" from "the file exists and
lists nothing", and does not prescribe the command that caused the second case.

`cleanup` removes the generated file rather than writing an empty one: absent
and empty are different states, and absent is the honest one after a teardown.

## Tests

`tests/unit/test_load_test_fixture_list.py` — 14 cases. The behavioural half
(absent vs empty vs corrupt vs a JSON object where a list belongs) runs against
the module; the setup half is asserted at source level, because reproducing it
needs a live server AND an already-seeded space, which is precisely the
combination that let this sit unnoticed.

Includes a check that `load_test_entities.json` is gitignored — without it the
third fix silently regresses to the old symptom.

## Found

While verifying the paging fix end-to-end (`issues/078`): re-seeded the test
stack, then the driver would not start. Restored with
`git checkout HEAD -- load_test_scripts/load_test_data.py`.
