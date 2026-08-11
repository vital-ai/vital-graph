# KGQuery Hardcodes How Entities Attach to Frames

## Status: OPEN — whole datasets are unqueryable THROUGH KGQUERY, silently

Scope corrected 2026-08-11. An earlier revision of this line said "unqueryable"
without qualification, which overstates it: **raw SPARQL queries this data
fine**, because it goes to the quads and carries none of the topology
assumptions below. `tests/performance/test_wordnet_query_bench.py::
test_wordnet_frame_union` asserts `rows > 0` for a frame UNION over the very
space this issue calls unqueryable, and it passes.

That changes the severity but not the defect. The data is reachable and nothing
is lost; what is missing is the CRITERIA API over it — the path the UI and
clients use — and its failure mode is still the bad one: zero rows, no error.
So this is an API-surface gap with a SPARQL workaround, not an inaccessible
dataset.

**Consolidated with `issues/048` on 2026-08-08.** That issue approached the same
defect from the connection side and found the missing half. Together they show
three query paths, each assuming a different entity-to-frame topology, and no
agreement between them.

Edge kinds actually present, measured:

| | wordnet_frames | sp_lead_synth_10k |
|---|---|---|
| `Edge_hasEntityKGFrame` (entity contains frame) | **0** | 40,000 |
| `Edge_hasKGSlot` (frame contains slot) | 1,141,392 | 775,400 |
| `Edge_hasKGRelation` (direct entity-to-entity) | **0** | **0** |

And the three paths:

| path | requires | works on |
|---|---|---|
| `build_entity_query_sparql` | `Edge_hasEntityKGFrame` | lead only — this issue |
| `build_relation_query` | `Edge_hasKGRelation` | **nothing**, in any space here — `issues/048` |
| `rewrite_frame_entity_table` | frame → slot → entity | matches wordnet's data, but is emitted by **no builder** |

So wordnet-shaped data — frames referencing entities through slot values — is
queryable by **no** KGQuery path at all, while `{space}_frame_entity` maintains
285,348 rows indexing precisely that topology, for a rewrite nothing reaches.
The materialised index for the unsupported shape is the one that exists; the
supported shape's copy of that table is empty.

`Edge_hasKGRelation` appears zero times in wordnet, both lead fixtures, and the
restored production copy. Whatever the relation query was written against is not
represented in any data available here.

That makes this a modelling decision rather than three separate bugs: which
entity-to-frame topologies are supported, and which of the derived tables and
rewrites should exist to serve them.

`KGQueryCriteriaBuilder` assumes exactly one shape for the entity→frame
relationship. A KG that models the connection any other way cannot be queried
through KGQuery at all, at any scale, and gets **zero rows with no error** rather
than a "this criteria shape is not supported" response.

## Why SPARQL is not simply the answer

Worth stating so the workaround is not mistaken for a fix:

* The criteria API is what the frontend and the typed clients call. "Write
  SPARQL instead" is not available to them without rebuilding what
  `KGQueryCriteriaBuilder` exists to provide.
* The optimisation work in `issues/053` (two-phase paging, the semi-join gate,
  push-down, candidate-driven negation) reaches the SPARQL that KGQuery
  GENERATES. A hand-written SPARQL query for this topology gets none of it by
  default, so the workaround is also the slower path.
* The silence is the real defect either way. A caller who supplies criteria for
  an unsupported topology cannot distinguish "no matches" from "this shape is
  not supported", which is what makes it survivable-looking in production.

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
