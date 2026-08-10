# `ne` Times Out on All Five Slot Classes Because `!=` Is Not Pushable

## Status: DIAGNOSED, not fixed — 2026-08-10, `sp_lead_synth_100k`

Five cells in `issues/053`. Split out because the cause is distinct from
`issues/057`, which an earlier revision wrongly folded it into: `ne` emits a
plain `FILTER(?v != x)`, not `FILTER NOT EXISTS`.

## Chain

`eq` puts the value in the triple pattern; `ne` binds a variable and filters:

    eq   ?slot haley:hasTextSlotValue "CA"                       -> 12 triples, no FILTER
    ne   ?slot haley:hasTextSlotValue ?val . FILTER(?val != "CA") -> 13 triples, 1 FILTER

That one difference cascades:

1. `eq`'s constant materializes to a uuid, so the leaf is an index lookup on
   `(predicate_uuid, object_uuid)` — selective. `ne`'s leaf binds a variable and
   matches **every** slot value.
2. The FILTER above the join references `?val_0_0_0`, which the right BGP binds.
   `semijoin._walk` requires `not (right_private & (needed - pushable_vars))`,
   and `?val` is in `needed`, so the join is not marked. **Correctly** — dropping
   that side would drop the variable the filter needs.
3. `_emit_two_phase` gates on `_has_semijoin`, so two-phase paging declines and
   the plan reverts to a blocking `Sort` on `term_text`.
4. `ne` matches ~99.8% of entities (100,000 minus the ~176 that equal "CA"), so
   the sort processes essentially the whole space for a 25-row page.

Confirmed against `eq` on the same slot and fixture:

    eq  needs_ordered_scan=True    slice > distinct > project > order > join [SEMIJOIN] > bgp, bgp
    ne  needs_ordered_scan=False   slice > distinct > project > order > filter > join > bgp, bgp

## The escape hatch that exists but does not cover this

`pushable_vars` already exists for exactly this situation — a variable referenced
only by a FILTER that `filter_pushdown` will consume does not have to survive the
semi-join. It is how range criteria got into the gate. But
`semijoin._pushable_range_var` only recognizes `_NUMERIC_OPS` (`<`, `<=`, `>`,
`>=`), and `filter_pushdown` only consumes those plus
`contains`/`strstarts`/`strends`/`regex`. **`!=` is in neither**, at both ends,
which have to agree or the gate marks a join whose filter then fails to push.

## Two candidate fixes, and why the obvious one is unsound

**A. Push `!=` as uuid inequality** — `object_uuid <> '<uuid of "CA">'::uuid`.
Cheap and index-friendly, and **wrong for three of the five slot classes**:

| slot class | sound? | why |
|---|---|---|
| text (`xsd:string`), choice | yes, if terms are canonical | lexical form is the value |
| integer, double | **no** | `"5.0"^^xsd:double != 5` is FALSE in SPARQL; the uuids differ, so uuid inequality answers TRUE |
| boolean | **no** | `"true"` and `"1"` are the same value, different terms |

Datetime is worse still: production carries three distinct lexical forms for the
same instant (`issues/053`). So A covers 2 of 5 cells and silently corrupts the
other 3 — and `test_comparator_coverage` pins `ne` counts on text, choice and
boolean, so the boolean breakage would at least be caught.

**B. Evaluate the same expression lower, rather than rewriting it.** The BGP's
term join already exposes typed value columns (`__num`, `__bool`, `term_text`).
Applying `FILTER(?val != x)` to those columns at the leaf is semantically
identical to applying it above the join, because it is the same expression on the
same values — no datatype reasoning required, so it is sound for every class.

The cost is that it does not produce an index-usable constraint, unlike every
other push-down here, which are all of the form
`object_uuid IN (SELECT term_uuid FROM term WHERE ...)`. For this purpose that
may not matter: the goal is not a selective leaf, it is to stop `?val` being live
so the semi-join can fire and paging can early-terminate. With 99.8% of entities
matching, the first page fills almost immediately.

**B is the better direction**, but it needs `filter_pushdown` to grow a second
kind of output (a plain predicate on the BGP's own columns, not a term-table
semi-join), and `_pushable_range_var` to agree about exactly which expressions
qualify. Both ends drifting apart is how `gt` ended up uniquely slow
(`issues/054`).

## Do not fix this by removing the FILTER

`ne` could be emitted as `MINUS { ?slot ... "CA" }` or `FILTER NOT EXISTS`, which
would make it look like `issues/057`. That trades a known-correct plan for the
negation family's problems and changes multi-valued-slot semantics: with
`?val != "CA"`, an entity whose slot holds both "CA" and "NY" **matches** via the
"NY" row; under `NOT EXISTS` it does not. Those are different questions and the
current one is the one the API documents.

## Related

- `issues/053` — the sweep; these are 5 of its 17 remaining cells
- `issues/057` — the other negation family; different construct, same blocking sort
- `issues/054` — the last time the two ends of a push-down disagreed
- `two_phase_kgquery_paging_plan.md` — the gate, and D3 on match density
