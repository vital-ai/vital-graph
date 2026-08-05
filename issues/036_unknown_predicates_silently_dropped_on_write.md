# Unknown Predicates Are Silently Dropped on Write

## Status: OPEN

## Summary

Quads whose predicate is not a valid property of the object's class are
discarded during `quads → GraphObject` conversion. No error, no warning, and the
write reports success. The caller believes the data was stored; it was not.

Reproduced against the current code:

```python
quads = [
    Quad(s="<urn:t:1>", p="<...#type>",                  o="<...haley-ai-kg#KGDocument>"),
    Quad(s="<urn:t:1>", p="<...vital-core#hasName>",     o='"Doc"'),
    Quad(s="<urn:t:1>", p="<...#hasKGDocumentFileNode>", o="<urn:file:1>"),   # an Edge CLASS, not a property
    Quad(s="<urn:t:1>", p="<...#hasTotallyMadeUpProperty>", o='"x"'),         # does not exist at all
]
objs = quad_list_to_graphobjects(quads)      # 1 object, no exception
graphobjects_to_quad_list(objs, "urn:g:1")   # → type, vitaltype, URIProp, hasName
```

**Four predicates in, two silently gone** — and the invented one is treated
exactly like the plausible-but-wrong one.

## Why it matters

This is not hypothetical. It cost real debugging time in `issues/018`:
`hasKGDocumentFileNode` is an **Edge class**
(`ai_haley_kg_domain.model.Edge_hasKGDocumentFileNode`), not a datatype property
on `KGDocument`. Writing it as a plain predicate was accepted by the API,
reported as created, and the link simply did not exist afterwards. The document
and the FileNode were both stored correctly; only the relationship vanished.
Nothing in the logs or the response indicated a problem — the only way to find
it was to query the stored object and notice a predicate missing.

The general failure mode: **a write that partially succeeds while reporting full
success**. Any client that sends a predicate the ontology does not recognise —
a typo, a renamed property, an ontology-version mismatch, or a class/property
confusion like the one above — loses that data with no signal.

## Where it happens

`quad_list_to_graphobjects` (`vitalgraph/utils/quad_format_utils.py:295`) builds
property maps and hands them to `GraphObject.from_property_maps` (VitalSigns).
That call keeps properties allowed on the resolved class and ignores the rest.
The drop is inside the library, but vitalgraph is where the information needed
to warn still exists: at `:428` the code has both `p_uri` and the subject's
`type_uri` in hand, immediately before the properties are handed over.

Note the fast path and the rdflib fallback (`_quad_list_to_graphobjects_rdflib`)
both funnel through the same place, so one fix covers both.

## Suggested fix

Warn — do not start rejecting. Rejecting would break any caller currently
relying on extra predicates being tolerated, and the failure mode here is
*silence*, not permissiveness.

1. After building each subject's property map and before
   `from_property_maps`, compare the requested predicates against what the
   resolved class accepts, and log the difference once per call:

   ```
   WARNING quad_list_to_graphobjects: 2 predicate(s) not properties of
           haley-ai-kg#KGDocument were dropped: hasKGDocumentFileNode,
           hasTotallyMadeUpProperty
   ```

2. Better, if cheap: surface the dropped predicates in the write response
   (`QuadResultsResponse`) as a `dropped_predicates` field, so an API client
   can see it without reading server logs. This fits the HTTP-200-domain-outcome
   convention — the write did succeed, just not completely.

3. Consider naming the likely cause when the predicate resolves to a known
   **class** rather than a property, since that is the trap that actually bit:
   *"`hasKGDocumentFileNode` is an Edge class — model it as an edge object with
   `hasEdgeSource`/`hasEdgeDestination`, not as a predicate."*

## Cost of not fixing

Every future ontology mismatch costs the same debugging session: notice data is
missing, disbelieve it, dump the stored quads, compare against what was sent,
then discover the predicate is not a property of the class. A single log line
turns that into a grep.

## Related

- `issues/018` — where this was found; the FileNode link is now modelled as a
  proper `Edge_hasKGDocumentFileNode`.
- `issues/022`, `issues/035` — same family of "operation reports success while
  doing nothing": a delete missing `graph_id` returning `no_op`, a cleanup using
  a parameter name the API ignores, a route form that 405s. The recurring
  lesson: **check that the thing you assume ran actually ran.**
