# 288 — Document query enrichment points at unrelated objects, and hybrid search returns nothing on OpenAI embeddings

## ARCHIVED 2026-10-20 — fixed and verified locally, both follow-ups decided and fixed, in production with the current code (reported 2026-10-20); nothing remaining. Evidence: tests/api/test_kgdocument_query_enrichment_and_hybrid.py, tests/unit/test_vector_query_scored_rows_only.py, tests/unit/test_document_query_parent_context.py, tests/unit/sparql_sql/test_hybrid_search.py.

## Status: FIXED IN CODE 2026-10-20 (in production with the current code, reported 2026-10-20). Both follow-up decisions made and implemented (below).

**Related:** `issues/284`-`287` (the KG document work this exercised), `issues/280`
(OPTIONAL scoping in the engine — not the cause here; the query itself was
wrong).

## What showed it

A consumer test on the AWS test environment (release 0.0.48) uploaded four
reports from clearly different businesses, three vectorized and one not, and
queried them with paraphrases that avoid the reports' own wording. Vector, text
and hybrid-at-alpha-0 search all ranked correctly, through both the KG query
interface and the SPARQL functions, and the non-vectorized report never appeared
in a vector result. Two things were wrong:

1. **`query_documents` with `include_parent_context` / `include_original_uri`
   returned broken `document_results`.** One hit was repeated, and its "parent"
   and "original" pointed at unrelated objects in the space: a
   business-registration frame and its slots. The ranking was fine; only these
   fields were wrong.
2. **`vg:hybridSearch` at alpha 0.5 returned no rows**, while alpha 0 worked.

## Cause 1 — two sibling OPTIONALs

`_build_document_where_clause` emitted:

```
OPTIONAL { ?pe hasEdgeSource ?_parent_doc . ?pe hasEdgeDestination ?entity .
           ?_parent_doc segtype segmentation_parent . ?_parent_doc hasName ?_parent_name }
OPTIONAL { ?oe hasEdgeSource ?_original_doc . ?oe hasEdgeDestination ?_parent_doc .
           FILTER NOT EXISTS { ?_original_doc segtype ?_ot } }
```

When the first group does not match, `?_parent_doc` is unbound when the second
one runs, and the second then matches ANY edge in the graph. That is standard
SPARQL, not an engine bug. The hit comes back once per edge, with a slot as its
"parent" and the frame above that slot as its "original". The first group fails
when:

* the hit is a parent copy or an original, which have no parent above them;
* the parent copy has no `hasName`, which was required inside the group.

The repro (`tests/api/test_kgdocument_query_enrichment_and_hybrid.py`, with an
unrelated frame in the graph) returned the bakery original five times on 0.0.48.

## Cause 2 — a model-dependent cutoff on the vector arm

`hybrid_search_sql` admitted a row only if `tsv @@ q OR cosine distance < 0.6`,
which means cosine similarity above 0.4. That constant belongs to the embedding
model:

* MiniLM puts a good paraphrase near 0.6.
* OpenAI `text-embedding-3-small`, the provider of the bootstrapped
  `document_segments` index in AWS, scores good matches at 0.2-0.35. The report
  itself shows 0.196 and 0.330.

So on that index the vector arm admitted nothing. A phrase with no all-terms
lexical match (`websearch_to_tsquery` ANDs the terms) then returned no rows.
"roofing" at alpha 0 matched lexically, which is why it worked.

**A first diagnosis was wrong, and is recorded so it is not retried.** The
suspicion was `push_text_search`, which narrows a pattern to the full-text match.
It never applies to a hybrid score: it acts only on `FILTER(BOUND(?score))`, and
`_fts_index_and_query` resolves only `textSearch` / `textMatch`. The report's
query used `FILTER(?score > 0)`. The local repro with "fresh bread pastries"
passed on 0.0.48 because MiniLM scored it at 0.64.

## Fix

* **Enrichment** (`kg_query_builder.py`): the original lookup is NESTED inside
  the parent group, both hops are typed `Edge_hasKGDocumentSegment` (as
  `segment_deletion` traverses them), and the parent's name is its own
  OPTIONAL. A hit with no parent above it (a parent copy, or an original) now
  gets an empty parent and original instead of a stranger's. The grouped
  (`group_by_document`) query shares the clause.
* **Hybrid** (`vg_functions.hybrid_search_sql`):
  * no distance cutoff, so every subject in the FTS index gets the fused score,
    and ranking plus the caller's own FILTER decide what is kept;
  * the vector table is LEFT JOINed with `COALESCE(cosine, 0)`, so a document
    with vectorization off (`issues/285`) is still found through the lexical
    arm.

## Verified (local vg test stack)

* `tests/api/test_kgdocument_query_enrichment_and_hybrid.py`: 4 tests. On 0.0.48
  the enrichment case with managed objects excluded returned the same hit five
  times, and hybrid at alpha 0.5 returned nothing for "somewhere to buy
  something sweet for a party". That query has no lexical match and scores 0.35
  against the bakery text on the local model, under the old cutoff, as OpenAI's
  good matches are. With the fix all 4 pass: the bakery ranks first, and alpha 0
  stays pure lexical.
* `tests/unit/test_document_query_parent_context.py` pins the nesting, the edge
  types and the optional name; all 3 fail on 0.0.48.
  `tests/unit/sparql_sql/test_hybrid_search.py` pins the absence of the cutoff,
  the LEFT JOIN, the alpha weights, and that the text narrowing never applies to
  a hybrid score.

## Workaround until released

Map a hit back to its report through the segment itself, for example
`list_segments` from the original, or the segment URI's parent edge, not through
`include_parent_context`. Use `vg:vectorSimilarity` instead of
`vg:hybridSearch` on OpenAI-backed indexes.

## Follow-ups, decided 2026-10-20

* **Parent copies in results: documented, not dropped.** The hidden
  segmentation copy holds the whole text, sits under the same
  `kgdocument_segment` mapping, and is a legitimate whole-document match for
  other callers. It stays in results by default. To search segments only, pass
  `search_scope="segments"`. That scope keeps rows with a segment index above
  0, and the parent copy's is 0. The client's `query_documents` docstring now
  says so.
* **An explicit `search_scope` of `segments` or `summaries` overrides the
  default `exclude_managed_segments=True`.** The two contradicted each other:
  the scope asks for exactly the managed objects the default excludes. Until
  `paragraph` joined the managed list, a segment search under the default
  returned only the pieces of oversized markdown sections; with
  `text_chunk` segments it returned nothing. Found when the Wikipedia e2e,
  which relied on that leak, returned 0 rows after `paragraph` was added.
* **A vector query returns only scored rows.** Under the default
  `exclude_managed_segments=True`, a vector query over a segment-only index
  returned the originals, which have no vector, with `score=None` in arbitrary
  order. The single-vector clause now carries `FILTER(BOUND(?score))`, as the
  multi-vector form already did.
  * That filter sits between the ORDER and the score's EXTEND, where the
    vector top-K rewrite refuses on any restriction (`issues/220`). It is
    EXEMPT (`vg_optimize._is_bound_of`), because the rewrite's join yields only
    rows with a vector.
  * The multi-vector form's existing `BOUND` filter had been costing it the
    rewrite all along; the exemption fixes that too.
* **`exclude_managed_segments` missed `paragraph` segments.** The builder had
  its own copy of the managed-type list without `urn:segtype:paragraph`, which
  is what the markdown splitter gives the pieces of an oversized section. There
  were three other copies, all complete. All four now read one
  `segment_config.MANAGED_SEGMENT_TYPES`.

Tests: `tests/unit/test_vector_query_scored_rows_only.py` covers the top-K
exemption, a real filter still refusing, `BOUND` emitted, and `paragraph`
excluded; three of its five fail on the previous code. In the API test
(`TestSegmentScope`, and the managed case of `TestEnrichment`), managed objects
excluded now returns nothing rather than unscored originals.
