# 227 — Nothing resolves an entity by identifier, so concurrent callers mint duplicates

## Status: OPEN — mechanism BUILT 2026-10-04 (`03a4afa6`, released in 0.0.45);
## NOTHING DECLARED yet. Production needs `migrate.py` BEFORE the 0.0.45 server
## deploy and the backfill after it; then business SF_ACCOUNT_ID can be the first
## declaration. Every other pair needs its duplicates merged first, by decision.
## See "As built" at the end, and the production counts there.

**Related:** `issues/173` (the same check-then-act race one layer up, in the KG
entity upsert — and the source of this repo's concurrency primitive),
`entity_registry/entity_identifier_ops.py` (the identifier write path),
`entity_registry_impl.create_entity` (already one transaction, one connection)

## The request

> Give me the entity id of an entity with identifier `fein:123`, or generate a
> new one and associate it with the FEIN. When more than one such call arrives
> at once for the same FEIN, all callers end up with the same entity id — the
> one created by whichever call was first.

There is no such call today. A caller does `lookup_by_identifier(ns, value)`,
gets a list back, and creates an entity if the list is empty. Those are two
round trips with a window between them, and the window is the whole defect.

## What is NOT the fix, because it is the obvious first guess

A blanket `UNIQUE (identifier_namespace, identifier_value)` constraint on
`entity_identifier`, applying to every namespace at once. It would reject
legitimate writes that the registry makes today by design.

(The design below *does* end in a unique index — but a partial one, scoped to a
single namespace and entity type, and only where that pairing has been
explicitly declared. The distinction is the whole issue.)

**One Salesforce record mints two entities of different types.** A `business`
and a `person`, both carrying the same identifier — 28 `SF_LEAD_PERSON_ID` and
9 `SF_CONTACT_ID` groups. Not damage; that is the import working as intended.

**Contact identifiers are many-to-one on purpose.** `EMAIL` and `PHONE` collide
across entities in 443 and 442 groups, and in nearly every one the collision is
the same `business` + `person` pair — a contact and their company share a phone.

**Placeholder values are shared by unrelated businesses.** `EIN 12-3456789` is
carried by two entities that are genuinely different companies. Four namespaces
show this shape (`EIN` 2 groups, `SF_ACCOUNT_ID` 1, `SF_OPPORTUNITY_ID` 1,
`PHONE` 1): one entity type, different names, one junk value.

The entity's identity is `entity_id` (`e_` + 10 base-36 chars). FEIN, DUNS and
`SF_LEAD_ID` are pointers *at* it. A uniqueness constraint would promote a
pointer into an identity, and the data says that is false.
`planning_entity_registry` has recorded this from the start — "identifiers are
not unique, lookup returns a list" — and it should stay true.

## The duplicates that are real, and why the server cannot see them

Measured 2026-09-22 on the dev `sparql_sql_graph` database, active rows only.
Prod is **not** measured. Every `(namespace, value)` group holding more than one
entity, split three ways:

| namespace | spans 2 entity types | one type, same name | one type, different names |
|---|---|---|---|
| `EMAIL` | 443 | 4 | 0 |
| `PHONE` | 442 | 5 | 1 |
| `SF_LEAD_PERSON_ID` | 28 | 6 | 0 |
| `SF_CONTACT_ID` | 9 | 5 | 0 |
| `SF_LEAD_ID` | 0 | **34** | 0 |
| `EIN` | 0 | **26** | 2 |
| `SF_ACCOUNT_ID` | 0 | **18** | 1 |
| `SF_OPPORTUNITY_ID` | 0 | **17** | 1 |
| `DUNS` | 0 | **2** | 0 |
| `CRM` | 0 | **1** | 0 |

Only the middle column is the defect — one business, two or three `e_` ids. The
first column is the `business` + `person` pair, by design. The third is a
shared junk value on unrelated companies.

Two things fall out of this table, and both shape the design below.

**The entity type separates the legitimate case from the defect almost
perfectly.** For the four identity-bearing namespaces — `SF_LEAD_ID`, `EIN`,
`SF_ACCOUNT_ID`, `SF_OPPORTUNITY_ID` — *every* collision is within one entity
type, so none of them is the by-design pair. Conversely `SF_LEAD_PERSON_ID` and
`SF_CONTACT_ID` are mostly the pair. That is the empirical argument for putting
`entity_type_id` in the claim key.

**Nothing in the table distinguishes columns two and three from the database's
side** — both are "one identifier, one entity type, several entities". A
constraint would have to reject both, and one of them is correct data. That is
why this needs a call deciding *before* the second entity is minted, not a rule
rejecting it afterwards.

## The design: uniqueness is DECLARED per `(namespace, entity_type)`

Not a global rule, and not a per-call convention. A pairing is declared unique,
and the declaration may only be made when the data does not already contradict
it. Everything undeclared keeps today's behaviour exactly.

**Step 1 — put the entity type on the identifier row.**

```sql
ALTER TABLE entity_identifier ADD COLUMN entity_type_id INTEGER REFERENCES entity_type(type_id);
UPDATE entity_identifier ei SET entity_type_id = e.entity_type_id FROM entity e
 WHERE e.entity_id = ei.entity_id AND ei.entity_type_id IS NULL;
```

This denormalization is safe because **an entity's type is immutable**:
`update_entity` takes `primary_name`, `description`, `country`, `status` and the
rest, but has no `type_key` parameter and never writes `entity_type_id`. There
is no update path to keep in sync.

**Step 2 — a declaration IS a partial unique index.**

```sql
-- {business_type_id} resolved from entity_type.type_key at DDL-emit time; see below
CREATE UNIQUE INDEX CONCURRENTLY uq_ident_ein_business
    ON entity_identifier (identifier_namespace, identifier_value, entity_type_id)
 WHERE identifier_namespace = 'EIN'
   AND entity_type_id = {business_type_id}
   AND status = 'active';
```

**The "may only be declared when it is true" rule enforces itself.** Postgres
refuses to build that index if any existing row contradicts it. So the
precondition is not a validation query of ours that could be subtly wrong about
statuses or soft-deletes — it is the index build failing. Undeclaring is a
`DROP INDEX`, and is always safe because it only relaxes.

**The type id has to be resolved per database, never hardcoded.** An index
predicate must be immutable, so it cannot join `entity_type` to look up a
`type_key` — a literal surrogate id is forced. But `entity_type.type_id` is a
`SERIAL` seeded with `ON CONFLICT (type_key) DO NOTHING`, so it depends on the
order that database happened to be seeded in. In dev `sparql_sql_graph`,
**`type_id` 1 is `person` and 2 is `business`** — the first draft of the example
above hardcoded `1` for "business" and would have quietly constrained the wrong
type. Declare the list as `(type_key, namespace)` pairs in
`EntityRegistrySchema` and resolve each to the local `type_id` when emitting the
DDL. Getting this wrong builds a perfectly valid index over the wrong entity
type, and nothing reports it.

**`entity_type_id` must be in the key.** Without it, a resolve against
`SF_LEAD_PERSON_ID` or `SF_CONTACT_ID` is ambiguous by construction for the 37
groups above — it would have to pick between the `person` and the `business`.
With it, `EIN`+`business` can be declared unique while `SF_CONTACT_ID` stays
open on both types, and a caller asks for the `business` behind a contact id and
gets one answer.

The surface is small: **16** `(namespace, entity_type)` pairs are in use in the
dev data, so this is a short list to curate, not an open-ended matrix.

**Why this, rather than the identity-claim table considered first.** A separate
claim table would record which entity is canonical while constraining
`entity_identifier` not at all — so a claim saying entity A owns `EIN:123` could
coexist with an identifier row pointing `EIN:123` at entity B, and `resolve` and
`lookup_by_identifier` would disagree forever. Declaring on the identifier table
itself cannot diverge from the thing it describes. It also drops a table, a
deferrable FK, and the backfill of claims.

The cost, stated plainly: **declaring becomes DDL** — one index per declared
pair, built `CONCURRENTLY`, dropped when undeclared — where the claim table
would have made it a row write.

## The race, resolved

The call: `resolve_or_create_entity(namespace, value, type_key, primary_name,
**create_kwargs) -> (entity, created: bool)`, exposed as `POST
/entities/resolve` returning `CREATED` or `FOUND`. It requires the pair to be
declared; against an undeclared pair it must refuse rather than guess, because
`lookup_by_identifier` legitimately returns a list there.

```python
# entity_id is minted in Python with secrets — no sequence, nothing to burn
try:
    async with conn.transaction():                   # SAVEPOINT
        await conn.execute("INSERT INTO entity (...) VALUES (...)", entity_id, ...)
        won = await conn.fetchval(
            "INSERT INTO entity_identifier (entity_id, identifier_namespace, "
            "identifier_value, entity_type_id) VALUES ($1,$2,$3,$4) "
            "ON CONFLICT DO NOTHING RETURNING entity_id",
            entity_id, namespace, value, type_id)
        if won is None:
            raise _LostTheRace                       # unwinds to the savepoint
except _LostTheRace:
    # our entity never existed. Read the winner's.
    owner = await conn.fetchval(
        "SELECT entity_id FROM entity_identifier WHERE identifier_namespace=$1 "
        "AND identifier_value=$2 AND entity_type_id=$3 AND status='active'",
        namespace, value, type_id)
    return await self.get_entity(owner), False

return await self.get_entity(entity_id), True
```

Ten concurrent calls for `fein:123` converge on one id with no lock and no
polling, because of how Postgres handles a conflicting insert: **the nine losers
block inside their `INSERT`** until the winner's transaction ends, and only then
return zero rows. So `won is None` already implies the winner committed, and the
following `SELECT` sees it. If the winner instead rolls back, a loser's insert
succeeds and *it* becomes the winner — no caller is left without an id.

The savepoint is what discards a loser's minted entity. Entity ids are random
10-char base-36 strings rather than a sequence, so a rolled-back attempt leaves
no gap and costs nothing. (The alternative — making
`entity_identifier.entity_id`'s FK `DEFERRABLE INITIALLY DEFERRED` so the
identifier row can be inserted first and losers do no wasted work at all — is a
migration on an existing constraint, and only worth it if the waste ever
measures.)

**Every write path gets the guarantee, not just `resolve`.** The insert above is
`_insert_identifier`, the single choke point that both `create_entity` and
`add_identifier` already call. So once a pair is declared, an ordinary
`add_identifier` that would hand a declared value to a second entity *fails*
instead of silently creating the duplicate. That failure is a domain outcome,
not a server fault: catch the unique violation and return a status naming the
entity that already holds the value, per the HTTP-200 convention these endpoints
follow.

## Why not an advisory lock, given `issues/173`

`173` fixes its race with `pg_advisory_xact_lock`, and the same shape would work
here — hash `ns:value:type`, take the lock, then check-then-create. It is the
lighter change: no new table, no backfill.

It is rejected because **an advisory lock only protects callers that take it**.
It is a convention enforced by every write path remembering to participate, and
`173` is the record of what happens when one of them does not — there, a
`getattr(..., None)` turned "this backend does not implement the locking" into
"no locking needed here" on nine call sites at once. A unique index holds
regardless of who writes, which is the property actually being asked for.

The advisory lock stays the right answer if this is ever wanted without a schema
change.

## Merge first, then declare — and nothing may bypass that

**"Zero entities" is the wrong precondition, though it is the safe instinct.**
Requiring a pairing to be empty before it can be declared means that after
merging the 26 duplicate `EIN` groups, `EIN`+`business` *still* could not be
declared — it holds ~1,300 entities and you would have to empty it first. The
weaker precondition, **"no existing row contradicts the declaration"**, is
exactly what the constraint asserts and nothing more, admits every clean
namespace immediately, and is the condition `CREATE UNIQUE INDEX` already
checks. Use that.

On today's dev data **no** identity-bearing pairing passes yet — `SF_LEAD_ID`
(34), `EIN` (28), `SF_ACCOUNT_ID` (19), `SF_OPPORTUNITY_ID` (18), `DUNS` (2) and
`CRM` (1) all hold same-type collisions. Each has to be merged through
`entity_same_as` (the `merged` entity status already exists for this) before its
index will build. That is the real work, and it is now bounded and countable
rather than open-ended: the index build tells you when you are done.

Do not let a merge pass pick `MIN(created_time)` and move on. The whole reason
this issue exists is that something already guessed.

**Do not add an internal bypass for backfills.** The proposal that internal
writes could modify values past a declaration returns the system to exactly
today's state, with one thing made worse: a constraint would then be advertising
a guarantee that is not true, and the next reader would believe it. With a real
index there is no bypass to write — the database refuses our backfill too, and
that is the property being bought. The safe shape for a bulk correction is
**drop the index, run it, rebuild it**, where the rebuild fails loudly if the
correction broke the invariant. Same freedom, no silent hole.

## What to be careful about

**It is get-or-create, not upsert.** On the found path every creation kwarg —
`primary_name`, `country`, `website` — is ignored, not merged. That has to be
loud in the docstring and the endpoint description; silently discarding a
caller's field is the predictable first bug report.

**It depends on `READ COMMITTED`.** That is the default and what asyncpg's
`conn.transaction()` inherits. Under `REPEATABLE READ` the losers get a
serialization failure instead of a clean no-op, and the convergence property
above does not hold.

**Test it under actual concurrency.** N tasks calling resolve on one key through
a real pool, asserting one distinct `entity_id`, one `entity_created` changelog
row, and N−1 `FOUND`. A single-threaded test proves nothing about the only
behaviour being requested here.

**Build declarations `CONCURRENTLY`, and expect them to fail.** A plain `CREATE
UNIQUE INDEX` takes an `ACCESS EXCLUSIVE` lock and blocks registry writes for
the build. More importantly, a failed build is the *expected* outcome on a
pairing that has not been merged yet — the declaration API has to report "these
17 values are held by more than one entity" rather than surface a raw
`unique_violation`, or the feature is unusable exactly when it is most needed.

**A declaration is schema, so it belongs with the schema.** The declared set has
to be reproducible on a fresh database, which means the index list lives in
`EntityRegistrySchema` and is applied by `apps/entity_registry/migrate.py` like
every other constraint here — not created ad hoc by whoever flips the flag.

## Out of scope, noted so it is not conflated

A `UNIQUE (entity_id, identifier_namespace, identifier_value)` constraint on
`entity_identifier` — the same identifier added twice to *one* entity — is a
separate and much smaller thing. 112 rows in `sparql_sql_graph` would
collapse, and `entity_category_map` already carries
exactly this constraint as `uq_entity_category` with an
`ON CONFLICT ... DO UPDATE SET status='active'` write path to match. It is
worth doing. It has nothing to do with duplicate entities.

## As built, 2026-10-04 (`03a4afa6`, 0.0.45)

The design above, as written, with these specifics.

- **`entity_identifier.entity_type_id`**: in the table definition, and added by
  `migrate.py` (column only). `apps/entity_registry/backfill_identifier_entity_type.py`
  fills existing rows in `identifier_id` batches — one UPDATE over the table
  would outlast production's 60 s `statement_timeout`. Written by
  `_insert_identifier` and by the JSONL importer (`entity_import_jsonl.py`), the
  only direct insert outside it.
- **Declarations**: `EntityRegistrySchema.DECLARED_UNIQUE_IDENTIFIERS`, a list of
  `(type_key, namespace)` — **EMPTY**. `declared_index_sql` emits the partial
  unique index with THIS database's `type_id`, resolved by the caller, never
  defaulted. `apps/entity_registry/declare_unique_identifiers.py`: `--report`
  (read-only, `--db PREFIX --ssl` for another database) shows per pair the rows,
  rows still untyped, and values held by more than one active entity — what
  blocks it; `--apply` builds each declared pair CONCURRENTLY, refuses while any
  row in the namespace is untyped, and on a failed build drops the invalid index
  and lists the values in the way. No force option, no bypass.
- **In force = the index exists and is VALID** (`is_identifier_declared`, from
  `pg_index.indisvalid`): a failed CONCURRENTLY build leaves an invalid index
  that enforces nothing.
- **Every write path**: a declared value held by another entity raises
  `IdentifierClaimed` from `create_entity` and `add_identifier`, answered
  ALREADY_EXISTS in a 200 naming the holder; nothing written.
- **`resolve_or_create_entity`** and `POST /entities/resolve` (CREATED / FOUND;
  INVALID_REQUEST for an undeclared pair). Client:
  `entity_registry.resolve_or_create_entity(EntityResolveRequest)` — NOT
  `resolve_entity`, which already exists for same-as resolution and silently
  shadowed the first version of this method. Marked replay-safe.
- **`create_entity` split** into `_insert_entity_rows` (the rows, rolled back with
  the transaction) and `_after_entity_created` (fuzzy index, NOTIFY, vector/FTS/
  geo sync). `create_entity` still runs both inside its transaction, as before;
  `resolve` runs the side effects only for the entity that WON, so a loser's
  rolled-back entity never reaches the fuzzy or vector indexes.

**Tests.** `tests/api/test_entity_resolve_contract.py` (6), declaring a
namespace unique for `business` by building the same index, dropped afterwards:
undeclared refused; created then found, creation fields ignored; **10 concurrent
calls converge on ONE entity, one `entity_created` row, 9 FOUND**; add_identifier
and create refused naming the holder (and the refused create leaves no entity);
a `person` may still share the value. `tests/unit/test_declared_unique_identifiers.py`.
The first API run caught a 500 of mine — `$1` used as both a VARCHAR insert
value and a comparison made PostgreSQL deduce two types — before anything
shipped.

**Measured, 2026-10-04** (`--report`, read-only; active rows; values held by >1
active entity of that type):

| pair | production rows | production dup values | dev dup values |
|---|---:|---:|---:|
| business SF_ACCOUNT_ID | 99,708 | **0 — declarable now** | 19 |
| business SF_OPPORTUNITY_ID | 123,134 | 3 | 18 |
| business SF_LEAD_ID | 632,050 | 17 | 34 |
| person SF_LEAD_PERSON_ID | 557,483 | 5 | 6 |
| person SF_CONTACT_ID | 14,013 | 63 | 6 |
| business EIN | 246,989 | **5,390** | 27 |

Production is the first measurement this issue has had; the table above it was
dev only. EIN is two orders of magnitude worse than dev, and this issue already
found placeholder EINs shared by unrelated companies, so many of the 5,390 may
be junk values, not duplicate businesses — that needs looking at before any
merge. EMAIL and PHONE collide by design (contact and company share them) and are
not candidates.

**To put it in force:** (1) `migrate.py` then `backfill_identifier_entity_type.py`
on the database; (2) merge a pair's duplicates via `entity_same_as` (decided
per group, not `MIN(created_time)`), retracting the merged entity's identifiers;
(3) add the pair to `DECLARED_UNIQUE_IDENTIFIERS`; (4) `--apply`. Business
SF_ACCOUNT_ID needs only (1), (3), (4).

