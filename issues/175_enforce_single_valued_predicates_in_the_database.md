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

## Two failure classes, needing two different mechanisms

Everything found in issues/173 and issues/174 falls into one of two kinds, and
conflating them is why "add a lock" felt like it should be the whole answer.

**Class 1 — invariant violation.** "This predicate has two values where one is
allowed." The upsert race and the `touch_entity_modification_time` race are both
this. A lock stops each PATH from violating it; it cannot stop a path that does
not exist yet.

**Class 2 — multi-statement consistency.** The orphaned entity graph in
issues/174: a delete reads membership, an upsert adds a member, the delete acts
on a stale snapshot. Nothing about that is a uniqueness violation. It genuinely
needs the read and the write to share a transaction, and no constraint can
supply that.

## Class 1: a partial unique index makes it unbypassable

`{space}_rdf_quad`'s primary key is `(subject_uuid, predicate_uuid, object_uuid,
context_uuid)`, so two DIFFERENT values for one predicate coexist legitimately —
correct for RDF in general, wrong for a single-valued predicate.

A partial unique index on `(subject_uuid, predicate_uuid, context_uuid)`,
restricted to the single-valued predicates, makes the corruption impossible for
every writer: the upsert path, the touch, a hand-written SPARQL update, a psql
session, and any endpoint added later. That is the property a lock cannot have.

**Measured on `prod_kg` — every candidate is clean today:**

| predicate | subjects | would violate |
|---|---|---|
| `vitaltype` | 6,699,176 | 0 |
| `hasObjectCreationTime` | 81,941 | 0 |
| `hasObjectModificationDateTime` | 81,941 | 0 |
| `hasObjectStatusType` | 81,941 | 0 |
| `hasKGEntityType` | 81,941 | 0 |
| `hasName` | 81,941 | 0 |

The index definition is portable across spaces: predicate UUIDs are
deterministic UUID v5 over the URI, verified by computing them locally and
matching the production term table exactly.

### But other spaces are NOT clean, and that is the real finding here

`prod_kg` is clean only because it was just repaired. Surveying all five spaces
on the instance with `scripts/migrate_single_valued_predicate_indexes.py`:

| space | vitaltype | creation | modification | status | entityType |
|---|---|---|---|---|---|
| `prod_kg` | ok | ok | ok | ok | ok |
| `lead_data` | ok | **62** | **62** | ok | ok |
| `lead_prod` | ok | ok | **42** | ok | ok |
| `sp_kg_types` | ok | ok | ok | ok | ok |
| `testspace` | ok | ok | ok | ok | ok |

Two findings in that table.

**The corruption was never confined to the space that surfaced it.** `lead_data`
has 62 violating subjects and was never examined, because nothing there had
failed visibly. It is the same both-predicates signature as the upsert race.

**`lead_prod` corroborates the second mechanism.** 42 subjects, on
`hasObjectModificationDateTime` ONLY, with creation time clean. The upsert race
cannot produce that — it stamps both. This is the signature issues/174 item 4
inferred from just 4 subjects on `prod_kg`, now visible at ten times the scale
on a different space. `touch_entity_modification_time` is not a marginal
hypothesis; it is the dominant source of modification-time corruption on this
instance.

**The index refuses to build where the data contradicts it**, which is the
behaviour that makes the constraint worth having. It cannot be enabled on a
false premise, and it turned an unexamined space into a measured one.

### Sequence

1. Run `scripts/repair_duplicate_server_timestamps.py` per space, dry-run first.
   `lead_data` needs it; the remaining spaces need measuring.
2. Add the partial unique indexes via a migration script (schema changes here
   are made only by an explicit action, never as a side effect).
3. `CREATE UNIQUE INDEX CONCURRENTLY`, since these tables are large and live.

### The trade

A genuine race stops being silent corruption and becomes a loud unique
violation the caller must handle. That is strictly better, and the pattern
already exists — `with_deadlock_retry` retries a transaction whose body is
repeatable, which is exactly the shape a losing writer needs.

Worth stating plainly: **this would have prevented every instance of corruption
found in this session**, including the `touch_entity_modification_time` race in
issues/174 item 4, without modifying that function at all.

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

## Recommendation

**Do class 1 first, and independently.** It is a repair plus a migration, it
closes the "sneaks through a SPARQL update" hole categorically rather than path
by path, and it protects code not yet written. It also reduces the urgency of
issues/174 item 4: with the constraint in place the touch race becomes
correct-or-loud without touching that function.

**Treat class 2 as a separate, slower decision.** It is a real architecture
change, the gather hazard means it cannot be done by quietly threading a
contextvar through, and it is only needed for the read-then-write class that
constraints cannot address.

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
