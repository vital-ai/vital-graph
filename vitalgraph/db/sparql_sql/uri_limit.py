"""An upper limit on a stored URI's length (`issues/283`).

`issues/283` bounded the VALUES the sort tables index, and left one unbounded
key column in each: `entity_uri` / `frame_uri`, the tie-break at the end of the
prop-sort indexes. A btree entry is capped at 2,704 bytes, so an entity whose
URI was long enough failed the write the same way a long value had:

    index row size ... exceeds btree version 4 maximum 2704

The limit is on every URI term, not only on entity and frame subjects. The
term table is the one place every write goes through -- a subject becomes a
sort table's tie-break only later, by derivation -- and a URI is an identifier,
not content: the longest stored in any local space is 357 bytes.

1,024 BYTES keeps the widest index tuple inside the btree limit: three UUIDs
(48), a `value_key` of 256 characters at up to 4 bytes each (1,028 with its
header), the URI (1,028) and tuple overhead -- about 2,120 of 2,704.

Two layers, because no single Python function sees every write:

* `check_uri` refuses it in the Python term builders (`_term_row`,
  `classify_term`, the SPARQL UPDATE `_term_upsert`, the import loaders), as a
  `RequestRefused` naming the URI -- before any SQL runs.
* `uri_limit_constraint_sql` is a CHECK on the term table, for the writes that
  intern terms in SQL alone (a SPARQL UPDATE's WHERE-bound values, a COPY
  load). New spaces get it from the schema; `scripts/migrate_term_uri_limit.py`
  adds it to existing ones.
"""

from __future__ import annotations

from vitalgraph.kg_impl.refusals import RequestRefused
from .space_names import space_prefix

MAX_URI_BYTES = 1024


class UriTooLong(RequestRefused):
    """A URI over `MAX_URI_BYTES`; nothing was written."""


def check_uri(text: str) -> None:
    """Raise `UriTooLong` if `text`, a URI term, is over the limit."""
    # `len` counts characters, at most 4 bytes each: under a quarter of the
    # limit, the encode is skipped -- this runs for every term of every write.
    if len(text) * 4 <= MAX_URI_BYTES:
        return
    n = len(text.encode("utf-8"))
    if n > MAX_URI_BYTES:
        raise UriTooLong(
            f"URI is {n} bytes, over the {MAX_URI_BYTES}-byte limit: {text[:80]}...")


def uri_limit_constraint_name(space_id: str) -> str:
    return f"ck_{space_prefix(space_id)}_term_uri_len"


def uri_limit_check_sql() -> str:
    """The CHECK expression, shared by the DDL and the migration."""
    return f"term_type <> 'U' OR octet_length(term_text) <= {MAX_URI_BYTES}"


def uri_limit_constraint_sql(space_id: str) -> str:
    """The table constraint clause for the term table's CREATE."""
    return (f"CONSTRAINT {uri_limit_constraint_name(space_id)} "
            f"CHECK ({uri_limit_check_sql()})")
