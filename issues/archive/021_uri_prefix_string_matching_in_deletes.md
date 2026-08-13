# URI-prefix string matching drives destructive deletes (and space graph lookup)

## Status: FIXED (2026-08-04)

All four sites now identify objects by relationship or by an anchored URI
match. Audited site-by-site rather than assumed — sites 1–3 were fixed earlier
by the `segment_deletion` work; site 4 was still live.

| Site | Was | Now |
|---|---|---|
| 1 `auto_segmentation._delete_existing` | `STRSTARTS` on `{original}_parent_{method}` | `delete_segmentation(...)` — traverses `Edge_hasKGDocumentSegment`, scoped by method |
| 2 `kgdocuments_endpoint:666` | duplicate of site 1 | same helper; the duplication is gone |
| 3 `_cascade_delete_segments` | `STRSTARTS` on `_parent_` \|\| `_edge_to_` | same helper, `method_uri=None` |
| 4 `fuseki_space_impl:429,932` | `STRSTARTS(STR(?g), "…/{space_id}")` | `space_graph_filter()` — exact match on the base graph **or** base + `/` |

**The "additional bug" is also resolved.** `_cascade_delete_segments` issued
its `DELETE WHERE` through `execute_sparql_query`; it now calls
`delete_segmentation`, which uses `execute_sparql_update`. So the cascade does
run — the question the issue asked to confirm either way.

### Site 4 is on a backend nothing currently uses

Worth stating so it is not read as equal in weight to sites 1–3, which were
live data-loss paths on the active backend.

`sparql_sql` is the only backend in use — it is what `BACKEND_TYPE` selects
everywhere, and it took 41 commits in the 60 days to 2026-08-04 against 2 for
`vitalgraph/db/fuseki/` (one of which is this fix). Nothing outside
`deploy/fuseki_deploy_test/` configures Fuseki, and the backend had no test
coverage at all before this issue.

So site 4 was a *latent* bug in a dormant backend, not a live one. The fix is
cheap and correct and stays, but if this issue is used to prioritise similar
work, weight by which backend the site is on first.

### Site 4 detail

A space owns `http://vital.ai/graph/{space_id}` plus `/`-suffixed subgraphs, so
the prefix arm had to stay; what was missing was the boundary. Anchoring on
"equals the base, or starts with base + `/`" keeps subgraphs and stops space
`foo` matching space `foobar` — which mattered because one of the two callers
feeds the result straight into a graph delete.

Verified by construction rather than execution — there is no Fuseki in the test
stack. `tests/unit/test_space_graph_filter.py` asserts the emitted filter and
guards against the unanchored form returning; the guard was confirmed to fail
when the anchor is removed. Given the backend is dormant (above), that is the
proportionate level of assurance, not a gap to chase.

### Regression test

The collateral-deletion case the issue asked for exists and passes:
`tests/api/test_kgdocuments_api.py::TestSegmentDeleteScoping` creates a decoy
whose URI extends the target's prefix, deletes the target, and asserts the
decoy survives. It is what caught the whole-graph delete in issue 023.

## Summary

Four SPARQL sites identify objects by **string-matching their URI prefix**
instead of traversing the relationships that already model the association.
Three of them are `DELETE`s, so the blast radius is defined by a naming
convention rather than by the data model — any subject whose URI merely
*extends* the prefix is destroyed as collateral.

The correct relationship already exists in every case. Segment deletion, for
example, reconstructs by string surgery a link that
`vitalgraph/document/auto_segmentation.py:233-249` explicitly creates as
`Edge_hasKGDocumentSegment` edges (original → parent, parent → each segment).

Found while removing string-based *type* matching from the frame/slot queries
(see `planning/planning_sequence/frame_slot_sequence_sort_paging_plan.md`
step 7). Those were a performance problem; these are a correctness one.

## Sites

### 1. `vitalgraph/document/auto_segmentation.py:190-198` — `_delete_existing`

```sparql
DELETE WHERE {
    GRAPH <...> {
        ?s ?p ?o .
        FILTER(STRSTARTS(STR(?s), "{original_uri}_parent_{method_suffix}"))
    }
}
```

### 2. `vitalgraph/endpoint/kgdocuments_endpoint.py:661-672`

Same shape, same `parent_uri` construction — a duplicated implementation of
site 1.

### 3. `vitalgraph/endpoint/kgdocuments_endpoint.py:1285-1296` — `_cascade_delete_segments`

```sparql
DELETE WHERE {
    GRAPH <...> {
        ?s ?p ?o .
        FILTER(
            STRSTARTS(STR(?s), "{original_uri}_parent_") ||
            STRSTARTS(STR(?s), "{original_uri}_edge_to_")
        )
    }
}
```

Called from the document delete path (`kgdocuments_endpoint.py:1205`).

### 4. `vitalgraph/db/fuseki/fuseki_space_impl.py:429, 932`

```sparql
SELECT DISTINCT ?g WHERE {
    GRAPH ?g { ?s ?p ?o }
    FILTER(STRSTARTS(STR(?g), "http://vital.ai/graph/{space_id}"))
}
```

Used to enumerate a space's graphs prior to deleting them.

## Why this is wrong

**Collateral deletion.** `STRSTARTS` matches any *extension* of the prefix:

The severity differs per site, so being precise:

- **Sites 1 and 2 are clear-cut.** The prefix is
  `{original_uri}_parent_{method_suffix}` with **no trailing separator**, so
  re-segmenting with method `segmented` also deletes everything under
  `…_parent_segmented_v2` or `…_parent_segmentedXYZ` — i.e. any method whose
  suffix merely *starts with* another method's suffix. Introducing a second
  method named as an extension of an existing one silently destroys the first
  method's output.
- **Site 3** appends `_` to both prefixes, so a cross-document collision needs
  one document URI to be a prefix of another at that boundary — narrower, but
  it still inherits the method-suffix problem above and is convention-driven
  rather than relationship-driven.
- **Site 4:** space `foo` matches the graphs of space `foobar` — the pattern
  `http://vital.ai/graph/{space_id}` has no trailing boundary.

**No relationship check.** A subject is deleted because of how it is *named*,
not because it is actually a segment of that document. Rename conventions,
migrations, or a user-supplied URI that happens to share a prefix all become
data-loss vectors.

**Full scans.** Each is `?s ?p ?o` over the whole graph with a string filter —
the same shape as the type filters removed in step 7, which measured ~10s on a
5k-object fixture.

## Additional bug found at the same site

`_cascade_delete_segments` (`kgdocuments_endpoint.py:1296`) issues its
`DELETE WHERE` through **`execute_sparql_query`**, not
`execute_sparql_update` — every other delete in the file uses `_update`
(`:672`, `:683`). If the query path does not execute updates, this cascade is
silently a no-op and segments leak on document delete. Needs confirming either
way; the fix differs depending on the answer (wire it correctly, or discover it
has never run and decide whether it should).

## Suggested fix

Traverse the modelled edges instead of the URI text:

- **Segments** — follow `Edge_hasKGDocumentSegment` from the original to the
  parent copy, and from the parent to each segment; delete those subjects plus
  the edges. Optionally scope by `hasKGDocumentSegmentTypeURI`, which
  `kg_graph_retrieval_utils` already treats as the marker for managed segments.
- **Space graphs (site 4)** — enumerate graphs from the space catalog rather
  than by name pattern, or match the exact graph URIs the space manager
  created.

Sites 1 and 2 are duplicates and should collapse into one implementation.

## Regression test to add

The collateral-deletion case is the point of the fix, so the test must create
a *decoy* whose URI extends the target prefix and assert it survives:

- create `urn:doc:1` with segments, and a separate `urn:doc:1_parent_other`
  (or a second document whose URI extends the first);
- delete `urn:doc:1`;
- assert its segments and edges are gone AND the decoy is untouched.

Also assert the cascade actually deletes (guards the query/update bug above).

## Notes

Not every SPARQL string function in the codebase is wrong. User-supplied text
search — `CONTAINS(LCASE(STR(?name)), LCASE("term"))` in the frames, entities,
triples and document endpoints — is operating on literal *values*, which is
what those functions are for. This issue is specifically about matching
**identity/type by URI text** where a relationship or an explicit class already
exists.
