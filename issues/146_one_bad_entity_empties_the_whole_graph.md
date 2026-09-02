# One Malformed Entity Empties The Whole Graph

## Status: FIXED 2026-09-02. Filed at the same time, because the fix is a
## containment change and the DATA defect underneath is still open.

## The symptom

`get_entity_graph` returns HTTP 500 about **19 times a day** on production, on
two entities that carry a list-valued value for a property the ontology declares
single-valued. Recorded in the deploy runbook as "a data defect" and left there.

It is a data defect. It is also a containment defect, and that half was ours.

## The mechanism

`_bindings_to_objects` (`kg_impl/kg_graph_retrieval_utils.py`) turns `?s ?p ?o`
bindings into GraphObjects. When a subject has two quads for the same predicate
it builds a list:

```python
if p in props:
    existing = props[p]
    if isinstance(existing, list):
        existing.append(value)
    else:
        props[p] = [existing, value]
```

That is correct and deliberate — it is the right reading of the SPARQL result,
and right for a genuinely multi-valued property. The problem is the last line of
the function:

```python
return GraphObject.from_property_maps(entries)
```

**One call, for every subject in the result.** vitalsigns rejects the list on a
single-valued property, the exception propagates, and the entire request fails —
including every well-formed entity in the same graph, and every other entity in
a batch. Two bad entities in the data take out any request that touches them.

## The fix

Fall back to per-entry construction when the bulk call fails, skipping only what
cannot be built and naming it:

    SKIPPING entity <uri> (type <type>): ValueError: ... Multi-valued properties
    on this subject: ['<predicate>']. If one of those is single-valued in the
    ontology, the data holds a duplicate quad for it and needs repair.

The bulk call stays the fast path; the retry costs nothing until something is
actually wrong. Four call sites share the helper, so all of them are covered.

## What this deliberately does NOT do

It does not guess which value is right. A duplicate quad on a single-valued
predicate is genuine ambiguity — picking one silently would turn a loud failure
into a wrong answer, which is worse. The entity is omitted and named, so the
data can be repaired.

It does not stop the entity from being missing. That is the point: the entity IS
unusable until the data is fixed. What changes is the blast radius — from "every
request touching this graph" to "this entity".

## Still open: the data

Two entities on production hold a duplicate quad on a single-valued predicate.
The log line added here names them and the offending property on the next
occurrence, which is what a repair needs. Nothing here writes to the data.

## Why this shape recurs

Third instance in this investigation of "correct handling, no containment":
`issues/140` swallowed an `UnboundLocalError` and silently disabled a plan
optimisation; `issues/144` read a statement timeout as "not a KG space" and
skipped a repair for months. Here the reverse — an exception that should have
been contained to one entity was allowed to fail everything. Both directions
come from the same omission: deciding what a failure should COST before writing
the handler.
