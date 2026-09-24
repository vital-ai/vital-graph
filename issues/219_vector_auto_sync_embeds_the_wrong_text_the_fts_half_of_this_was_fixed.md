# Vector Auto-Sync Embeds "Every Literal Property" Instead Of The Configured Mapping

## Status: FIXED 2026-09-24 — `_sync_vectors_for_subjects` now resolves the
## index's mapping per subject and SKIPS what it does not cover, exactly as the
## FTS half does. Found 2026-09-21 while fixing that half (`issues/217`).
##
## What it cost before the fix: copying nurture actions into an archive whose
## only vector index is for DOCUMENT SEGMENTS wrote 291,089 embeddings for
## subjects that index was never meant to hold — paid for at the provider — and
## the write volume drove an autovacuum storm that took production query
## latency from 0.22s to over 50s (`issues/230`). An out-of-scope subject is now
## DELETED from the index rather than embedded, so the fix repairs what the
## defect wrote instead of only stopping it.
##
## Regression tests: `tests/unit/test_vector_sync_honours_the_mapping.py`,
## falsified against the unfixed call. geo and fuzzy are NOT audited.

**Related:** `issues/217` (the same defect in the FTS path, FIXED — read it
first; this is defect 1 of that issue, in the sibling subsystem)

## The defect

`_sync_vectors_for_subjects` (`vectorization/auto_sync.py:134`):

    text = build_search_text(props, None)

`None` is the mapping rule, and `build_search_text` documents what that means:

    rule: Optional resolved mapping rule. If None, includes all literals.

So on every write, a subject is re-embedded from **every literal property it
owns** — concatenated — regardless of what the index's `search_mapping` says to
index. `update_subject_vector` accepts `mapping_rule` and `mapping_type`
keyword arguments; auto-sync passes neither.

The bulk populator does resolve the mapping. So, exactly as in `issues/217`:

| writer | text embedded |
|---|---|
| `vector_populator` (bulk) | the configured mapping |
| `_sync_vectors_for_subjects` (every write) | **every literal property** |

A freshly populated index is correct and decays on first touch, one row at a
time.

## Why this is worse than the FTS case, not equal to it

The FTS version wrote a wrong `search_text` — inspectable, and repaired by a
re-populate that costs a `tsvector` rebuild.

An embedding is **opaque**. Nothing about the stored vector says it was built
from the slot type URI and three timestamps rather than the message. It does
not error, does not look wrong, and degrades similarity ranking in a way that
reads as "the model is mediocre". Recomputing it costs a provider call per
subject rather than a SQL expression.

It also affects `vg:hybridSearch`, which fuses this vector with the FTS score:
the lexical half is now correct (`issues/217`) and the vector half is not, so
the blend is wrong in a way neither side reports.

## Scope — checked, not assumed

    _sync_vectors_for_subjects   AFFECTED   build_search_text(props, None)
    _sync_fts_for_subjects       FIXED      issues/217
    _sync_geo_for_subjects       OK         resolves `geo_config` and passes it
    _sync_fuzzy_for_subjects     OK         calls `resolve_any_fuzzy_mapping`
                                            internally and returns False when
                                            no mapping matches

So geo and fuzzy already do the right thing, each by its own mechanism. Vector
is the only one left, and FTS is the worked example of the fix.

## The fix

The same shape as `issues/217`: resolve the mapping for the subject and pass it.
`_subject_scopes` already exists in that module and returns
`(mapping_type, type_uri)` per subject in one batched query — it was written
for the FTS path and is directly reusable.

Two things to carry over from that fix:

* **"No mapping" must mean SKIP**, not "embed everything". That is what the
  bulk populator does, and making the two agree is the point.
* **Normalise the lookup key with `str()` on both sides.** `_subject_scopes`
  keys by `uuid.UUID`; a caller holding the string form does not raise, it
  MISSES — which reads as "out of scope" and deletes the row.

## Also worth doing with it

Existing vector indexes on any space written to since its last populate already
hold embeddings built from the wrong text. Unlike the FTS case there is no cheap
repair: they need re-embedding, which is a provider cost. Worth measuring how
many rows are affected before deciding whether to re-populate or leave them.
