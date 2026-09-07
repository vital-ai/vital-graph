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

### The default set is too narrow — slot values need it more than entities do

The set proposed above is entity-level. Working through what happens when a
SPARQL update touches a slot inside an entity graph (issues/174 item 5) showed
that is the wrong emphasis: **the corruption is worse on slot values, and they
are not covered.**

Measured on `prod_kg`, the space already repaired:

| predicate | subjects | violating | `multiple_values` |
|---|---|---|---|
| `hasTextSlotValue` | 1,852,047 | **94** | False |
| `hasDateTimeSlotValue` | 390,756 | **92** | False |
| `hasKGSlotType` | 2,821,011 | 0 | False |
| `hasObjectCreationTime` | 81,941 | 0 *(repaired)* | False |

`hasKGSlotType` being clean at 2.8M subjects while the two VALUE predicates are
corrupted is the mechanism showing through: slot types are written once at
creation, slot values are UPDATED, and updating is what races.

So the predicate set should be driven by the ontology rather than by which
properties happen to be server-managed. `multiple_values=False` is the criterion
already; the migration consults it, and the default list simply does not yet
include the slot predicates. Every one checked reports False.

**Two consequences.**

1. **The repair script needs extending.** It currently handles only the two
   entity timestamps, with keep-earliest / keep-latest rules derived from what
   those properties mean. Slot values have no such natural rule — there is no
   basis for preferring one text value over another — so the repair for them is
   a different decision, not a wider loop. Most likely: keep the value belonging
   to the most recently modified frame, or surface them for review rather than
   choosing automatically.
2. **The index cannot be added for slot predicates until they are repaired**,
   exactly as for `lead_data`. 186 subjects across the two predicates block it
   on this space alone.

### Does a unique index make sense when some properties ARE multi-valued?

Yes, and the reason is worth writing down because it is the obvious objection.

The index is **partial and per predicate** —
`... (subject_uuid, context_uuid) WHERE predicate_uuid = '<one uuid>'`. It
exists only for predicates the ontology declares single-valued. A multi-valued
property has no such index and is entirely unconstrained: on the production
space `hasMultiChoiceSlotValues` has 96 subjects, all 96 holding several values,
and none of them are affected.

**Cardinality has no class dimension**, so one decision per predicate is the
right granularity. `multiple_values` is defined on the property trait class
itself (`Property_hasName.multiple_values = False`), not on a class-property
pair, and the registry exposes no domain-specific override. A property is
therefore single- or multi-valued globally, however many classes use it — which
is exactly what a per-predicate index can express.

**And the data agrees with the model.** The check that matters is whether the
residue being called corruption might be a legitimate pattern the ontology has
simply not captured. It is not: of the 94 `hasTextSlotValue` violations, 92 sit
on one slot type, `urn:*:slot:MsgContent`, which looked like it might be
legitimately multi-valued — until the denominator:

| | count |
|---|---|
| `MsgContent` slots | 302,523 |
| holding more than one value | **92** |
| | **0.03%** |

A property that genuinely held several values would not do so 0.03% of the
time. The concentration points the other way: message content is the most
EDITED slot in the space, and updating is what races. That matches
`hasKGSlotType` — written once at creation, never updated — being clean across
2.8M subjects.

So the constraint would reject only what the model already forbids, and the
0.03% is the race showing through, not a modelling gap.

### Sequence

1. Run `scripts/repair_duplicate_server_timestamps.py` per space, dry-run first.
   `lead_data` needs it; the remaining spaces need measuring.
2. Add the partial unique indexes via a migration script (schema changes here
   are made only by an explicit action, never as a side effect).
3. `CREATE UNIQUE INDEX CONCURRENTLY`, since these tables are large and live.

### The trade — it does NOT raise, and that changes the analysis

An earlier revision of this issue said a genuine race would become "a loud
unique violation the caller must handle". **That is wrong**, and the reason
matters more than the correction.

Every path that inserts a quad does so with a TARGETLESS
`ON CONFLICT DO NOTHING`:

| path | site |
|---|---|
| bulk insert | `sparql_sql_space_impl.py:951`, `:1229` |
| bulk load | `bulk_load.py:53` |
| SPARQL update | `emit_update.py:1019` |

In PostgreSQL a targetless `ON CONFLICT DO NOTHING` applies to **every** unique
constraint and index on the table, not just the primary key. So once the partial
unique index exists, a second value for a single-valued predicate is not an
error — it is **silently suppressed**.

**What that buys.** No caller needs new error handling, no retry logic, no
transaction aborts, and no risk of a deploy turning working writes into 500s.
The invariant simply becomes unbreakable. It also covers the case locking cannot
reach at all — a WHERE-bound SPARQL update, which by construction cannot
enumerate the subjects it will touch, is nonetheless unable to produce a second
value. That is the argument for doing this at the database level rather than
path by path, stated at its strongest: **a constraint holds regardless of
whether the writer could name its subjects in advance, and the SPARQL update
path is precisely the writer that cannot.**

**What it costs, and it is the recurring theme of this whole investigation.** A
losing writer's value disappears with NO SIGNAL. Corruption becomes silent loss.
For the two timestamps that is benign — two near-identical values, either is
defensible. For a single-valued predicate whose value carries meaning, the
system would quietly keep the first writer's value and discard the second, and
nothing would say so.

There is a second, subtler case in the same mechanism. `emit_update.py:1019`
documents that its `ON CONFLICT DO NOTHING` exists to absorb duplicates the
BINDING SET produces within one statement — the DAWG Halloween-problem shape,
where a `DELETE/INSERT` maps two solutions onto one output quad. With the new
index, a legitimate update that computes two DIFFERENT values for a
single-valued predicate in one statement would also be silently reduced to one,
**arbitrarily** — the surviving row is whichever the executor reached first.
Previously it stored both, which was wrong but visible. Neither outcome is good;
silence is the better of the two and still deserves to be known about.

### Impact plan

1. **No code changes are required to adopt it.** Nothing raises, so nothing
   needs to handle a new exception. This is what makes the migration low risk.
2. **Add detection for suppression, or the fix trades one silence for another.**
   The bulk path is already positioned for this: `sparql_sql_space_impl.py:1236`
   parses the real inserted count precisely because "ON CONFLICT DO NOTHING
   means a duplicate quad row counted as written" — a suppressed row is already
   countable there. `emit_update` reports nothing comparable and would need it.
3. **Restores and imports become self-limiting.** A backup containing duplicates
   no longer reimports them; the surplus is dropped on the way in. Worth knowing
   before someone restores a pre-repair snapshot and wonders why the row counts
   differ from the source.
4. **Sequencing is unchanged and unblocked.** Repair per space, then create the
   indexes concurrently. Because nothing raises, the indexes can go on before
   the `touch_entity_modification_time` rewrite in issues/174 item 4 — that race
   degrades to "the modification time does not advance", and all three of its
   call sites already swallow failures as non-critical.

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
