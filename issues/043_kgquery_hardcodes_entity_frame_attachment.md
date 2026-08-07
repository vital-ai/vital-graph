# KGQuery Hardcodes How Entities Attach to Frames

## Status: OPEN — whole datasets are unqueryable, silently

`KGQueryCriteriaBuilder` assumes exactly one shape for the entity→frame
relationship. A KG that models the connection any other way cannot be queried
through KGQuery at all, at any scale, and gets **zero rows with no error** rather
than a "this criteria shape is not supported" response.

## What is hardcoded

`vitalgraph/sparql/kg_query_builder.py` offers two modes, selected by
`EntityQueryCriteria.use_edge_pattern`:

| hop | `use_edge_pattern=True` | `use_edge_pattern=False` |
|---|---|---|
| entity → frame | `Edge_hasEntityKGFrame` (:657) | `vg-direct:hasEntityFrame` (:713) |
| frame → child frame | `Edge_hasKGFrame` (:1197) | `vg-direct:hasFrame` (:1202) |
| frame → slot | `Edge_hasKGSlot` (:732) | `vg-direct:hasSlot` (:739) |

Both are the *same topology* — a direct containment link from entity to frame —
differing only in whether it is reified as an edge node or expressed as a direct
property. There is no third option, and no way to supply one.

## The case that does not fit

`wordnet_frames` (8.58M quads, 109,745 `KGEntity`, 285,348 `KGFrame`) attaches
entities the other way round — through the slot value:

```
KGFrame --Edge_hasKGSlot--> KGEntitySlot --hasEntitySlotValue--> KGEntity
```

Its only edge kind is `Edge_hasKGSlot`; there is no `Edge_hasEntityKGFrame` and
no `vg-direct:hasEntityFrame` anywhere in the space. Frames reference entities
rather than entities referencing frames — a perfectly ordinary way to model a
relation (here, WordNet relations as frames with source/destination entity
slots), and one the KG model itself clearly permits, since this data was
produced by the standard tooling.

Consequence: **no KGQuery entity criteria can be expressed over wordnet.** Not a
scale limitation, not a criteria-authoring problem — the builder cannot emit a
pattern that matches the data.

This was found while selecting a fixture for the paging work
(`planning/planning_performance/kgquery_o_page_paging_generator_plan.md`). The
fixture survey initially recorded the missing edge as a "topology caveat"
requiring new criteria; it in fact rules the dataset out entirely.

## Why it is dangerous rather than merely limiting

The failure is a zero-row result, indistinguishable from "nothing matched".
Nothing logs, nothing raises. A bench, a test, or a UI panel driven by such a
query looks like it is working on an empty result set. This is the same failure
class as `issues/041` and `issues/042`, both found in the same session:

- a KGQuery bench asserting *upper* bounds passes trivially on zero rows
- a caller cannot distinguish "unsupported topology" from "no data"

## Secondary defect — `use_edge_pattern` is ignored for standalone slot criteria

Within the same file, the **standalone** `criteria.slot_criteria` path (slot
criteria not nested under a `frame_criteria`) hardcodes `Edge_hasEntityKGFrame`
in all three of its branches — `not_exists`, `is_empty`, and the normal
value path — with no `use_edge_pattern` check at all (~:745, :760, :774).

So `use_edge_pattern=False` is honoured for `frame_criteria` and silently
disregarded for `slot_criteria`. A caller selecting direct-property mode gets
edge-pattern SQL for part of its query, and therefore zero rows in a
direct-property KG. Independent of the main issue and cheaper to fix.

## What is needed

KGQuery needs to express entity→frame attachment as something other than a fixed
pair of hardcoded predicates. Rough options, not yet evaluated:

1. **A third mode** — e.g. `attachment="via_slot_value"`, emitting
   `?frame --Edge_hasKGSlot--> ?slot --hasEntitySlotValue--> ?entity`. Smallest
   change, covers the known case, but the enum grows once per new topology.
2. **Configurable attachment path per space** — declare how entities reach
   frames (predicate chain and direction) in space or KG-type configuration, and
   have the builder read it. Handles unknown topologies; needs somewhere
   trustworthy to store it and a migration for existing spaces.
3. **Infer from the data** — probe which attachment predicates exist in the space
   and pick. No caller changes, but adds a lookup to the query path and picks
   silently, which is how this class of bug arises in the first place.

Whatever the mechanism, **an unsatisfiable criteria shape should be reported, not
returned as an empty result.** If the builder emits a pattern whose predicates do
not occur in the space at all, that is knowable at generation time and is far
more useful raised than swallowed.

## Reproduce

```python
# Any KGQuery frame criteria against wordnet_frames returns 0 rows.
# Confirm the required predicate is simply absent:
```

```sql
SELECT count(*) FROM wordnet_frames_term
WHERE term_text = 'http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame';
-- 0

SELECT t.term_text, count(*) FROM wordnet_frames_rdf_quad q
JOIN wordnet_frames_term p ON p.term_uuid = q.predicate_uuid
 AND p.term_text = 'http://vital.ai/ontology/vital-core#vitaltype'
JOIN wordnet_frames_term t ON t.term_uuid = q.object_uuid
WHERE t.term_text LIKE '%Edge%' GROUP BY 1;
-- Edge_hasKGSlot | 570696      (the only edge kind in the space)
```

## Related

- `planning/planning_performance/kgquery_o_page_paging_generator_plan.md` — where
  this surfaced; the growth-curve bench had to move to `sp_lead_synth` because of it
- `tests/performance/test_kgquery_growth_curve.py` — documents the constraint in
  its module docstring so the fixture choice is not "corrected" back later
- `issues/041`, `issues/042` — the other two silent-failure defects in this area
