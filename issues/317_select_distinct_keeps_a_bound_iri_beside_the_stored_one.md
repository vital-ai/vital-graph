# 317 — SELECT DISTINCT keeps a BIND's IRI beside the same IRI from a pattern

## Status: FIXED 2026-10-26, on the default path. Open until the vg test stack runs the full suite on the rebuilt image.

## Defect

On the default path, which production runs, `BIND(<iri> AS ?s)` carried the IRI with a NULL
`__uuid` companion. The same IRI read from a pattern carries its term's uuid. SELECT DISTINCT
compares every column, so the two rows stayed apart and one term was returned twice.

The frame fetch with its frame graph (`kgframes_endpoint`, `include_frame_graph=True`) asks
exactly this, and a frame is in its own frame graph:

```sparql
SELECT DISTINCT ?subject WHERE { GRAPH <g> {
    { BIND(<f> AS ?subject) ?subject a haley:KGFrame }
    UNION
    { ?subject haley:hasFrameGraphURI <f> } } }
ORDER BY ?subject
```

The frame's URI came back twice. On `sp_lead_synth_10k` there were 66 rows for 65 subjects.
`kg_query_builder`, `kgframe_get_endpoint_impl`, `kgrelations_endpoint` and the update impls use
the same BIND form.

## How it was found

The planner's contract check. The planner pins `BIND(<iri> AS ?s)` joined by a pattern as a
one-term VALUES, so its rows carry the uuid and it returned 65.

## Fix

`emit_extend`: a BIND of a constant IRI carries that term's uuid, registered and resolved as a
VALUES constant is (`emit_table._uuid_expr`). An IRI the term table does not hold keeps a NULL
uuid and is still returned.

Not fixed: a BIND of a literal, or of a computed value, against the same term from a pattern. Its
datatype companion can also differ (NULL against xsd:string for a plain literal).

## Test

`tests/integration/test_distinct_bind_iri_is_the_stored_term.py`: the frame-fetch shape returns
the frame once. It returned it twice before the fix. A bound IRI that is not stored is still
returned.
