# A Servable Needle Matching Nothing Is the Slowest Text Shape

## Status: OPEN, found 2026-09-14 while writing the text bench for `issues/192`

A SIX-character needle — long enough that the trigram index can serve it — that
matches nothing is the most expensive text query measured, and it does not
finish at all on the 100k fixture.

    fixture  needle                 warm exec   rows
    10k      "LLC"      matching       56.8 ms    25
    10k      "ZQ"       UNSERVABLE    611.9 ms     0
    10k      "ZZQQXX"   servable, 0 matches  3,289.8 ms   0
    100k     "LLC"      matching       47.0 ms    25
    100k     "ZQ"       UNSERVABLE    TIMEOUT (>15 s)
    100k     "ZZQQXX"   servable, 0 matches  TIMEOUT (>15 s)

Warm figures, second pass; the first pass is slower but the ordering is
identical. `SELECT count(*) FROM sp_lead_synth_10k_term WHERE term_text ILIKE
'%ZZQQXX%'` returns 0, so there is genuinely nothing to find.

**The servable-empty needle is 5x slower than the one the index cannot serve.**
That is backwards. `MIN_TRIGRAM_NEEDLE = 3` exists precisely because short
needles cannot use the index; a long needle can, and returning nothing should be
the cheapest thing it ever does.

## This is what the failing ordering test has been reporting

`test_paging_fence_covers_every_shape::test_the_three_text_needle_regimes_stay_ordered`
fails with:

    an empty SERVABLE needle (1,475,498) cost as much as an UNSERVABLE one
    (510,486)
    assert 1475498 < 510486

It is the single hole in `coverage.json`. It was easy to read as a stale
expectation — `issues/070` did make the unservable path much cheaper (78,991 ms
exact probe -> 45 ms sampled), so "unservable is no longer worst" sounds like
the fix working. **That reading is wrong.** Unservable did not get cheap enough
to overtake; servable-empty got pathological. The buffer counts and the wall
clock agree.

## Why no bench caught it

There is none. `issues/192` lists fuzzy/text as correctness-tested with zero
bench cells, and the ordering test asserts a RELATION between the regimes
without recording their values — so a regime could degrade by orders of
magnitude while the assertion still passed, right up until it crossed another
regime. The drift was invisible until it inverted.

## What this blocks

The text bench for `issues/192` cannot be written as intended. A query-tier
bench must be fast, and two of its three regimes do not finish in 15 seconds.
Writing it with a generous timeout would be papering over this: a read-only
query taking minutes is not a tier-placement question, it is a defect.

So the bench waits on this. When it lands it should record all three regimes'
values, which is the thing that would have caught this as drift rather than as
an inversion.

## Where to look

Not yet diagnosed. The shape is `_contains_criteria` -> `comparator="contains"`
on a text slot, through `_criteria_to_gen`. `issues/070` (`MIN_TRIGRAM_NEEDLE`,
the sampled probe) and `issues/117` (the three regimes) are the relevant
history. The question to answer first is whether the servable-empty case is
reaching the trigram index at all, or falling back to a scan — a 6-character
needle that cannot use the index would explain every number above.
