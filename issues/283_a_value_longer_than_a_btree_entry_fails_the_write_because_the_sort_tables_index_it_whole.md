# 283 — A value longer than a btree entry fails the write, because the sort tables index it whole

## Status: FIXED IN CODE 2026-10-19 (not yet released). Existing spaces need `scripts/migrate_sort_value_key.py`, run in two phases around the deploy (below).

**Related:** `issues/172`, which named this exact defect and its remedy and did
not build it (see "This was predicted" below). `issues/194`, which wired the
sort tables into the write paths and so moved the failure from the backfill to
the write itself. `issues/096`, which created `entity_slot_sort` and its text
index. The 63-byte identifier issues (`196`, `232`, `246`) are a different
PostgreSQL limit and are not related.

## What showed it

A consumer storing generated reports in slots saw only short reports get
through. The rest were refused with:

    index row size 3320 exceeds btree version 4 maximum 2704 for index
    "idx_<space>_ess_text"

Any slot value larger than about 2.7 KB after compression fails, in every
space, for every slot type, `KGLongTextSlot` included. The whole write is
refused, not only the slot.

## Cause

`entity_slot_sort` copies every slot's value into `value_text`, and
`idx_{space}_ess_text` is a btree over

    (context_uuid, entity_type_uuid, frame_type_path, slot_type_uuid,
     value_text COLLATE "C", entity_uuid)

A btree entry is capped at 2,704 bytes on an 8 kB page, and `value_text` has no
length limit. The slot row is derived inside the write's transaction
(`issues/194`), so the index insert fails and takes the write with it.

The canonical store was never affected. `term.term_text` is indexed by a HASH
index and a trigram GIN, neither of which stores the whole value as one entry.
The term-table btree was replaced by the hash for this same reason
(`c4dae57`, recorded in `issues/172`).

**The two prop-sort tables had the same defect,** which the report did not
reach:

| table | index | over |
|---|---|---|
| `entity_slot_sort` | `ess_text` | every slot value |
| `entity_prop_sort` | `eps_text`, `eps_any_text`, `eps_text_desc` | `hasName` |
| `frame_prop_sort` | `fps_text`, `fps_any_text`, `fps_form_text` | `hasName`, `hasKGFrameTypeDescription` |
| both prop tables | `eps_all`, `fps_all` (GIN on `value_all`) | every element |

The GIN index has a limit of the same size. Measured on the test stack (PG 18.4)
with incompressible text:

    btree   index row size 6416 exceeds btree version 4 maximum 2704
    GIN     index row size 6416 exceeds maximum 2712

So a long entity name or frame-type description failed the same way.

## This was predicted

`issues/172`, section "BUT A BOUNDED SORT KEY IS BOTH POSSIBLE AND SUFFICIENT",
2026-09:

> `{space}_entity_slot_sort.value_text` — unbounded TEXT today, indexed by
> `idx_{space}_ess_text` as a btree … IT HAS THE SAME SIZE LIMIT and works only
> because slot values happen to be short. That is convention, not construction:
> one long slot value fails the index insert … Bounding this column is a
> correctness fix as well as an enabling one.

Step 1 of that issue's plan was to bound the sort key. Its section refuting the
term-table btree said the finding "survives and is independent … a latent
correctness bug regardless of anything here". 172 was then closed by a different
fix (the sort path accepting frame criteria, `cc7cd3d`), and the bound was never
filed separately. It stayed latent until a consumer stored long text.

## Fix

**Index a bounded prefix and keep the full value.** New module
`vitalgraph/db/sparql_sql/sort_value_key.py`:

- **`value_key`**, a STORED generated column
  `left(value_text, 256)`, on all three tables. All seven text indexes now cover
  `value_key` instead of `value_text`. 256 characters is at most 1,024 bytes of
  UTF-8. Generated, like `term.dt_val`, so it cannot drift: every write path
  inserts `value_text` and gets the key with no further change.
- **`value_text` stays whole.** `slot_projection` returns it to list views, and
  cutting it would show a shortened value with nothing to say so. It is no longer
  indexed, so a large value is moved out of line by TOAST like any other column.
- **`value_all` elements are bounded** to the same 256 characters in both
  prop-sort derivations (`bounded_text_sql`).

**Why the prefix is exact.** For a literal `v` shorter than 256 characters:

- **Equality:** a value that was cut is exactly 256 characters long, so its key
  cannot equal `v`, and neither can the full value.
- **Ordering against `v`:** the first position where the value and `v` differ is
  at most `len(v)`, which falls inside the key. If `v` is a prefix of the value,
  it is a prefix of the key as well, and the key is longer.

**Every reader declines a literal of 256 or more characters**
(`fits_value_key`), and the general pipeline answers it from `term_text`.
Declining costs latency, not correctness:

| reader | decline point |
|---|---|
| `fast_slot_filter`, and `fast_slot_sort`'s filter half | `_lane_arg` (shared through `_eq_criteria`) |
| `fast_prop_sort`, `fast_frame_prop_sort` | `_filter_terms` |
| `fast_fts_frame` | `fts_frame_decline_reason` |
| `component_intersect` | skips the narrowing for that component |

`slot_sort_range` has no text lane and is unaffected.

**The one inexact case, accepted.** Two values that agree on their first 256
characters tie on the key. A sort then orders them by its tie-break (entity
uuid or URI), not by the rest of their text. Resolving it would mean reading
`value_text` from the heap for every row, which gives up the index-only scan the
tables exist for. Nobody orders a list by text that is identical for its first
256 characters.

## Existing spaces: `scripts/migrate_sort_value_key.py`

The schema only changes new spaces. For an existing space the script:

1. adds `value_key` (this rewrites the table under ACCESS EXCLUSIVE; table sizes
   are reported first),
2. bounds any `value_all` element longer than the bound,
3. builds the seven text indexes on `value_key`, using the definitions from
   `create_space_indexes_sql`, and
4. runs ANALYZE.

Each space is migrated in one transaction. The script is idempotent and does a
dry run unless given `--apply`. No resync is needed.

**Two phases, because the deploy happens elsewhere.** The released code sorts
on `value_text`, so dropping its index before the new code is deployed would
make every text-sorted listing do a full sort until then. Instead:

    before the deploy   --apply              old index renamed <name>_pre283,
                                             new one built beside it
    after the deploy    --drop-old --apply   drops the _pre283 indexes

Until phase two, the old index still rejects long values. The write failures
stop only once it is dropped.

Code and schema may be deployed in either order without wrong answers. Old code
on a migrated space never reads `value_key`. New code on an unmigrated space
fails its fast-path query, and every reader catches that and falls back to the
general pipeline: correct, slow, and logged at WARNING.

Run the script as the owner of the tables, which on production is the app role,
not the RDS master.

## Verified

- `tests/integration/test_long_values_fit_the_sort_tables.py` (new, 3 tests).
  It writes a 6,000-character slot value, a 5,000-character name and a
  4,000-character frame description through `space_impl`, so the real sync
  modules derive the rows. It then checks the boundary on the slot paths: a
  literal one character short of the bound that is a prefix of two stored keys
  matches nothing, a long literal is declined, and the sort keeps key order. It
  also checks the text sort is still an Index Only Scan on `_ess_text`.
  **Against HEAD's schema the first test fails** with
  `index row size 6120 exceeds btree version 4 maximum 2704 for index
  "idx_inttest_…_ess_text"`, which is the reported failure. With the fix, all
  3 pass.
- `tests/unit/sparql_sql/test_sort_value_key.py` (new) covers the bound, the DDL,
  the `value_all` derivation, and the decline in every reader.
- Existing tests updated to the new column: `test_slot_value_text_is_collated`
  now also flags any emitted `value_text` equality, since that column is no
  longer indexed; also `test_slot_filter_binds_every_lane` and
  `test_slot_sort_range_gate`.
- The full `tests/unit` suite passes, and 149 of 149 tests in the 21
  sort-table integration files pass on the test stack.

## Not done

- **URIs in the tie-break columns are still unbounded.** `entity_uri` and
  `frame_uri` are key columns of the prop-sort indexes. A URI over about 1.6 KB
  would fail the same way. No such URI exists and none is plausible, so they are
  left as they are.
- Production migration: both phases, around the next deploy.
