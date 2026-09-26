# 245 — Auto-sync classified every document segment as an entity, so segment vectors were skipped AND deleted

## Status: FIXED 2026-09-26, verified against a rebuilt stack: the wikipedia
## vectorization tests go from 0 vectors to 209, and the `tests/api` vectorization
## failures drop from 7 to 1. The remaining one is a DIFFERENT defect, localised
## below and not fixed here.

**Related:** `issues/219` (the auto-sync scope check this extends — the fix that
made skipping the normal outcome), `issues/244` (the other half of the same test
failures, the type-description property), `issues/220` (the vector top-K guard,
which the one remaining failure points at)

## The defect

`auto_sync._subject_scopes` maps each subject to a `(mapping_type, type_uri)` pair
so the index's mapping can be resolved for it. It could only ever return two
things:

    if   r["slot_type"]:   ("kgslot",   ...)
    elif r["entity_type"]: ("kgentity", ...)
    elif r["rdf_type"]:    ("kgentity", r["rdf_type"])   # fallback

A document segment has neither `hasKGSlotType` nor `hasKGEntityType`, so it fell
through to the fallback and was classified **`kgentity`**. The index's mapping is
registered as `kgdocument_segment` (`vector_index_setup.SEGMENTS_MAPPING_TYPE`), so
`resolve_search_mapping(..., "kgentity", ...)` returned None, and in the caller
`rule is None` means:

    # Out of scope for this index. Removing any row a previous
    # unscoped sync left behind makes the fix repair what the
    # defect wrote, rather than only stopping new damage.
    to_delete.append(subj_uuid)

So every segment was treated as out of scope for the segment index, and its vector
row was DELETED. Segment vectorization could not work at all: 206 segments, 0
vectors, for the full 120 s the test waits.

**The log said it had worked.** `segmentation_worker._do_vectorize` awaits
`schedule_sync` and then logs `"Job 1: vectorization completed for 83 subjects"` —
83 being the number of URIs it SUBMITTED, not the number stored. So three jobs
reported success, the job rows flipped to `completed`, and nothing was written.
That is `issues/242`'s shape a fourth time: a success message derived from the
request rather than the outcome.

## Why `issues/219` is the context rather than the cause

219 taught this path to SKIP subjects the mapping does not cover, which was right —
before it, everything got embedded regardless of scope, which is what cost 291,089
unwanted embeddings. But it made "skipped" the normal, expected outcome, so a
subject that is skipped because its CLASSIFICATION is wrong looks exactly like one
skipped because the mapping legitimately excludes it. The scope function was only
ever taught about slots and entities.

## The fix

`_SCOPE_SQL` now also selects `hasKGDocumentSegmentIndex` and
`hasKGDocumentType`, and the classification became:

    slot_type      -> kgslot
    entity_type    -> kgentity
    segment_index  -> kgdocument_segment     <- new
    document_type  -> kgdocument             <- new
    rdf_type       -> kgentity               (unchanged fallback)

**Segment before document, and the order is load-bearing.** Both are
`rdf:type KGDocument`; the segment index is what distinguishes them, which is the
same discriminator the segment-listing queries use. A segment also carries its
parent's document type, so testing `document_type` first would classify every
segment as a whole document — a subtler version of the bug being fixed.

Both the vector path and the FTS path call `_subject_scopes`, so this repairs both.
FTS appeared to work in the tests only because they trigger an explicit reindex
that passes `mapping_type` in by hand, bypassing the classification entirely.

## Verified

    before   [wiki_env] vec poll #55: 0 vectors -> ✗ not ready after 120s (0/206)
    after    [wiki_env] vec poll #0: 209 vectors -> ✓ vectors ready after ~0s

`tests/api` vectorization failures: **7 → 1**. `test_kgtypes_entity_integration`
5/5 (with `issues/244`), and in `test_wikipedia_document_e2e` the three
vectorization tests plus the eight that were SKIPPED behind "Vectors not ready"
now run.

## The one remaining failure is a different defect, and it is localised

`TestKGQueryVectorSearch::test_vector_search_ai_topic` — `total_count=66`,
`document_uris=[]`, `status=EMPTY`. Deterministic, reproduces in isolation.

**Its two sibling tests do not catch it**: `test_vector_search_solar_system` and
`test_vector_search_coffee` issue the SAME request shape (`search_scope="segments"`,
`include_segment_text=True`, `top_k=5`, `min_score=0.0`) and assert only
`total_count > 0`. Only the AI one asserts `len(document_uris) > 0`. So the enriched
vector-search page returns nothing for all three and two of them pass anyway —
which makes this a coverage hole as much as a defect.

What is established:

  * the count query and the page query disagree — 66 against 0 — because the count
    uses the base where clause and the page adds the enrichment and vector clauses;
  * `include_segment_text=True` adds `?entity haley:hasKGDocumentContent
    ?_seg_content` as a REQUIRED pattern while the headline beside it is OPTIONAL;
  * segments DO carry that property (`kgdocument_segmentation_processor.py:223`
    sets `kGDocumentContent`), so a missing property is NOT the explanation;
  * the plan log shows `vg_optimize: top-K detected` and `threshold pushdown` on
    `?vg_score`, so the vector top-K rewrite is active on exactly this shape.

`issues/220` is the open question about that rewrite — whether its guard
materialises the wrong side — and this is a concrete failing case to test it
against, which 220 says it lacks. NOT pursued further here.

## Not established

  * **Why the enriched page returns zero.** The interaction between the top-K
    rewrite, the threshold pushdown and the required content pattern is the
    remaining suspect; it has not been isolated by running the generated SQL by
    hand.
  * **Whether `total_count` should include the vector filter.** As it stands a
    caller is told 66 and handed nothing, which is wrong however the page query is
    fixed — the same count-vs-page disagreement as `issues/228`, on a different
    surface.
  * **Whether `_do_vectorize`'s success log should count stored vectors.** It
    reports submitted URIs and would have made this bug obvious if it reported
    stored ones. Same question as `issues/244` raises for the reindex response.
