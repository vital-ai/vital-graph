# Load-Test Setup Erases Its Own Fixture List When The Space Is Already Seeded

## Status: OPEN — found 2026-08-12

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

## Found

While verifying the paging fix end-to-end (`issues/078`): re-seeded the test
stack, then the driver would not start. Restored with
`git checkout HEAD -- load_test_scripts/load_test_data.py`.
