"""The bounded text key the three sort tables index (`issues/283`).

`entity_slot_sort`, `entity_prop_sort` and `frame_prop_sort` copy a value's
text into `value_text`, and every text index on them was a btree over that
column. A btree entry is capped at 2,704 bytes and a GIN entry at 2,712, while
`term_text` is unbounded, so one long value -- a report in a `KGLongTextSlot`,
a long frame-type description -- failed the index insert and with it the whole
write:

    index row size 3320 exceeds btree version 4 maximum 2704 for index
    "idx_<space>_ess_text"

`issues/172` named this as a latent bug and the remedy as a bounded prefix; it
was never built, and it stayed latent only while every value happened to be
short.

THE FIX IS A PREFIX, AND IT IS EXACT FOR EVERY LITERAL SHORTER THAN IT. The
indexes now cover `value_key = left(value_text, VALUE_KEY_CHARS)`, and the
readers compare against `value_key`. For a literal `v` with
`len(v) < VALUE_KEY_CHARS`:

  * EQUALITY is exact. A value that was cut is exactly `VALUE_KEY_CHARS` long,
    so its key cannot equal a shorter literal -- and neither can the full value.
  * ORDERING against `v` is exact. The first position where the full value and
    `v` differ is at most `len(v)`, which is inside the key, so the key compares
    the same way the value does. If `v` is a prefix of the value, it is a
    prefix of the key too, and the key is longer.

A literal of `VALUE_KEY_CHARS` or more cannot be answered from the key, so the
fast paths DECLINE it (`fits_value_key`) and the general pipeline answers from
`term_text`, whose hash index has no size limit. Declining costs latency, not
correctness.

THE ONE PLACE THE KEY IS NOT EXACT IS A SORT. Two values that agree on their
first `VALUE_KEY_CHARS` characters tie on the key and are ordered by the
tie-break (the entity uuid or URI) rather than by the rest of their text.
Resolving it would mean reading `value_text` from the heap for every row, which
gives up the index-only scan these tables exist for. Accepted: ordering a list
by text that is identical for its first 256 characters is not a sort anyone
asks for.

`value_text` STAYS WHOLE. `slot_projection` returns it to list views, and cutting
it would show a shortened value with nothing to say so. It is simply no longer
indexed, so its size is now TOAST's problem and not the btree's.

256 CHARACTERS IS AT MOST 1,024 BYTES of UTF-8, which leaves room in the 2,704
for the uuid columns and `frame_type_path` beside it, at any depth a real frame
path reaches.
"""

from __future__ import annotations

from typing import Any

VALUE_KEY_COLUMN = "value_key"

#: Characters, not bytes: PostgreSQL's `left()` counts characters, and so does
#: Python's `len()` on a str, so the guard and the column agree by construction.
VALUE_KEY_CHARS = 256


def value_key_column_sql() -> str:
    """The column definition, for `CREATE TABLE` and the migration alike.

    GENERATED, for the reason `dt_val` on the term table is: it cannot drift
    from `value_text`. Every write path -- the three sync modules, their
    backfills and resyncs -- inserts `value_text` and gets the key for free, so
    there is no fourth place to forget.
    """
    return (f"{VALUE_KEY_COLUMN} TEXT GENERATED ALWAYS AS "
            f"(left(value_text, {VALUE_KEY_CHARS})) STORED")


def bounded_text_sql(expr: str) -> str:
    """`expr` cut to the key length -- for `value_all`, which is aggregated
    rather than generated, so the sync modules apply this themselves."""
    return f"left({expr}, {VALUE_KEY_CHARS})"


def fits_value_key(value: Any) -> bool:
    """Whether the key answers a comparison against `value` exactly.

    False for any literal of `VALUE_KEY_CHARS` characters or more, and for a
    list holding one. The caller declines the whole query on False: dropping
    the one criterion instead would return a superset, which is a wrong answer
    rather than a slow one.
    """
    if value is None:
        return True
    if isinstance(value, (list, tuple, set, frozenset)):
        return all(fits_value_key(v) for v in value)
    return len(str(value)) < VALUE_KEY_CHARS
