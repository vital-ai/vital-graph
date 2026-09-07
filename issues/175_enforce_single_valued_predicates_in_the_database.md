# 175 — Enforce single-valued predicates in the database, not per write path

**Status:** open
**Raised:** 2026-09-07
**Related:** issues/173 (the upsert race), issues/174 (the remaining unlocked
paths), `scripts/repair_duplicate_server_timestamps.py`

## The question this answers

Locking the entity and frame paths still leaves a raw SPARQL update — or an
endpoint nobody has written yet — free to reintroduce the same corruption. An
application lock is opt-in per path. Something that cannot be opted out of is
needed for the invariant.

## RETRACTED — class 1 cannot be enforced in the store

**The proposal below to enforce single-valued predicates with unique indexes is
withdrawn.** It rested on a premise that is false for this system.

VitalGraph is a **general quad store**. Any predicate may be used single-valued
or multi-valued, by any subject, at any time. `multiple_values` on a VitalSigns
property trait describes what a MODEL expects of objects it manages — it is not
a contract the store makes about every quad written through it. A space holds
whatever RDF is loaded into it, and the same predicate that is single-valued for
a KGEntity may legitimately carry several values for something else in the same
space.

**A unique index would therefore be wrong, and would fail silently.** Every quad
insert uses a targetless `ON CONFLICT DO NOTHING` (`sparql_sql_space_impl.py:951`
and `:1229`, `bulk_load.py:53`, `emit_update.py:1019`), which applies to every
unique index on the table. So the index would not reject legitimate
multi-valued data — it would **discard the second value with no error at all**.
Loading ordinary RDF into a space would quietly lose triples. That is a worse
failure than the corruption it was meant to prevent, and harder to notice.

The per-predicate shape has a second problem that follows from the same premise:
predicates are determined dynamically, so the index set can never be complete.
22 single-valued predicates × 5 spaces is 110 indexes today, every one requiring
DDL, and any new ontology or import adds more that nobody has created. The
guarantee would apply to whatever someone last remembered to migrate — which is
the silent-absence failure this effort keeps finding, rebuilt deliberately.

### What survives the retraction

The measurements stand, and they are why this issue was worth writing:

- **186 subjects on the repaired space still hold duplicate slot values** — 94
  `hasTextSlotValue`, 92 `hasDateTimeSlotValue` — and 92 of the 94 sit on
  `MsgContent`, 0.03% of 302,523 such slots. Concentrated in the most-edited
  slot, which is the update race showing through.
- **`hasKGSlotType` is clean across 2.8M subjects**, because it is written once
  at creation and never updated. The contrast identifies the mechanism.
- **Other spaces are affected too** — `lead_data` 62 subjects on both entity
  timestamps, `lead_prod` 42 on modification time only, the latter being the
  `touch_entity_modification_time` signature.
- **A whole-table sweep finds all of it with no predicate list**, which is the
  one approach that IS naturally dynamic.

### Where enforcement actually belongs

The invariant "a KGEntity has one creation time" is an **application-level**
statement about KG objects, not a store-level statement about quads. So it has
to be enforced where that meaning exists:

1. **In the write paths** — issues/174. Locking is the mechanism that does not
   assume anything about predicate cardinality, because it serialises writers
   rather than constraining values. This is now the primary line of defence, not
   a complement to a constraint.
2. **In detection and repair, run periodically** — the sweep needs no predicate
   list, scales with whatever predicates exist, and reports rather than
   suppresses. For KG-managed predicates a violation is a genuine defect worth
   alarming on; for arbitrary loaded RDF it is not, so the report needs to be
   scoped by what the KG layer manages rather than by the raw quad table.
3. **NOT in the quad table.** Whatever it gains for KG objects, it takes from
   the store's general contract.

**Consequence for issues/174 — smaller than first thought.** The retraction was
argued to leave the WHERE-bound SPARQL update with no backstop. It does not: the
emitted SQL materialises its change set into a temp table before writing
anything, so those updates can take the same locks as every other path, with the
lock step placed after materialisation. The claim that they "cannot be
enumerated" came from a static AST helper and does not describe runtime. See
issues/174 item 5.

So withdrawing the constraint costs less than it appeared to. Locking covers
every path, including the one this issue existed to backstop.

## Class 2: a write scope, and the hazard that shapes it

The appealing design is an ambient connection in a `contextvar`: a caller opens
a write scope, and everything beneath it — including `execute_sparql_update` —
silently joins that transaction, with no viral `conn=` parameter across 48 call
sites. It would cover the SPARQL path automatically, which is what makes it
attractive.

**The hazard is concrete in this codebase.** An asyncpg `Connection` is not safe
for concurrent use, and there are **28 `asyncio.gather` sites**, several running
two database operations at once — `kgentity_list_impl.py:208` gathers
`objs_task` and `count_task`, both of which hit the database. Handing those a
single ambient connection produces intermittent `InterfaceError` under load.

So an ambient scope MUST detect concurrent use — an in-use flag that raises a
descriptive error naming the fan-out, turning a rare protocol corruption into a
first-run developer error. Without that guard, ambient is worse than viral,
because the failure is rare, load-dependent, and reads as a database problem.

Also unavoidable under any scheme: `execute_sparql_update` opens three
transactions on the connection it acquires (issues/174 records which and why),
and asyncpg turns a nested `conn.transaction()` into a `SAVEPOINT`. Those three
blocks need their nested semantics decided deliberately, not inherited.

## Recommendation, after the retraction

**Locking is now the primary defence, not a complement to a constraint.**
issues/174 was scoped on the assumption that a constraint would backstop the
paths locking could not reach. It will not, so the paths that were deprioritised
on that basis need re-weighing — particularly the WHERE-bound SPARQL update,
which now has no backstop at all.

**Detection and repair become the safety net**, and must stay detection. A
whole-table sweep needs no predicate list, so it scales with a store whose
predicates are open-ended, and it reports rather than suppressing — which is the
only safe posture when the same predicate may be legitimate multi-value for one
subject and a defect for another. It needs scoping to what the KG layer manages,
or it will alarm on ordinary RDF.

**Repair the known corruption regardless.** 186 subjects on the repaired space,
62 on `lead_data`, 42 on `lead_prod`. That is real damage to KG-managed objects
and is worth fixing whether or not anything enforces it afterwards — though the
slot-value repair still needs a keep-rule, and unlike the timestamps there is no
natural one.

**Class 2 is unchanged** — a real architecture change, gated on the gather
hazard, and now the only structural answer available rather than one of two.

## Open questions

- ~~Which predicates are genuinely single-valued?~~ **Answered.** VitalSigns
  property trait classes carry `multiple_values`, and the migration consults it:
  it refuses to index any predicate the ontology declares multi-valued, so a
  hand-passed `--predicates` cannot create a constraint the model disagrees
  with. Verified: the five default predicates report `multiple_values=False`
  and `hasKGActionTypeList` reports `True`. `vitaltype` is structural rather
  than a VitalSigns property and is listed explicitly, with that noted in the
  code.
- **How wide should the default set be?** Indexing every single-valued
  predicate would be the stronger guarantee, but each index is write
  amplification on a hot table. The default is the server-managed set — the
  ones the system writes itself, and therefore the ones a race can corrupt with
  no client involved.
- **Per-graph or per-subject?** The proposed index keys on
  `(subject, predicate, context)`, so the same subject may hold different values
  in different graphs. That matches how the rest of the system scopes by
  context, but it is a decision, not an obvious default.
- **The remaining two spaces** on the instance have not been measured.
