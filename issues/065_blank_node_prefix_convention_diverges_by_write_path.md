# Blank Node `_:` Prefix Convention Diverges By Write Path

## Status: OPEN — identified 2026-08-10 while writing `planning/planning_sparql_features/blank_nodes.md`

A blank node is stored as an ordinary term row with `term_type = 'B'`. The
intended convention is that `term_text` holds the **bare label**, and every
serializer re-adds the `_:` prefix on the way out:

    bulk_export.py:183          WHEN 'B' THEN '_:' || {alias}.term_text
    data_export_impl.py:54,69   return f"_:{text}"

The read side is consistent with that. The write side is not — it depends on
which entry point you used.

| entry point | stores | file |
|---|---|---|
| N-Triples / N-Quads import | `b1` | `data_import_impl.py:103` — `term_str[2:]` |
| bulk / rdflib load | `b1` | `sparql_sql_space_impl.py:962` — `str(BNode)` is the bare label |
| **SPARQL UPDATE** | **`_:b1`** | `emit_update.py:169` — `return f"_:{node.label}"` |
| **string-sniffing classifier** | **`_:b1`** | `sparql_sql_space_impl.py:1849` — classifies `_:`-prefixed text as `'B'` without stripping |

`emit_update._node_text` feeds the term upsert and the term-UUID computation
directly (`emit_update.py:437, 454-456, 492-494, 804-836`), so the prefixed
string becomes both the stored text and the hash input.

## Consequences

**Export doubles the prefix.** A blank node written through SPARQL UPDATE
exports as `_:_:b1`, which is not valid N-Triples.

**The same blank node gets two different term UUIDs.** `term_uuid` is a
deterministic UUIDv5 over `(text, type, lang, datatype_id)`. `_:b1` and `b1`
hash differently, so:

    LOAD  <file with _:b1 :p :o>     → term_text 'b1',   uuid A
    DELETE DATA { _:b1 :p :o }       → looks up '_:b1',  uuid B → no match

The delete silently removes nothing. The inverse also holds: a triple inserted
via UPDATE is invisible to a delete issued through the import/REST path.

**Which convention you get is not observable from the data.** Both spellings
are legal `term_type = 'B'` rows, so a space can end up holding both encodings
of the same node with no marker distinguishing them.

## The same bug in the result path

`emit_expressions.py:848` emits `BNODE()` as `'_:b0'` / `CONCAT('_:', arg)`,
and that value is rendered as a blank-node binding by
`sql_type_binding.py:220`, which passes `value` through unchanged. The SPARQL
1.1 JSON Results format wants `{"type": "bnode", "value": "b0"}` — bare — so
the emitted result carries the prefix inside the value. Same prefix-convention
error, different layer. (The freshness half of the `BNODE()` problem is
`issues/067`; only the prefix belongs here.)

## Fix

One convention, enforced at the boundary: **`term_text` is always the bare
label; the `_:` prefix exists only in serialized RDF syntax.**

1. `emit_update._node_text` — return `node.label`, not `f"_:{node.label}"`.
   Note `_node_text` is shared with the URI/literal/var cases, so the change is
   confined to the `BNodeNode` branch at `:169`.
2. `sparql_sql_space_impl.py:1849` — strip `_:` when the sniffer classifies a
   string as `'B'`.
3. `emit_expressions.py:848` — drop the `_:` from the emitted value (coordinate
   with `issues/067`, which rewrites this expression anyway).
4. Add an assertion or a single choke-point helper so a fourth write path
   cannot reintroduce the divergence.

## Existing rows

Any space that has taken a SPARQL UPDATE containing a blank node holds
`_:`-prefixed rows. A migration is a `UPDATE ... SET term_text = substr(term_text, 3)`
on `term_type = 'B' AND term_text LIKE '\_:%'` — **but `term_uuid` is derived
from `term_text`**, so the UUID must be recomputed and every referencing quad
repointed, or the row must be re-created and the old one merged away. Check
whether any production space actually has such rows before building the
migration; given that we do not ingest blank nodes at volume, the count may
well be zero and the fix is then code-only.

## Related

- `planning/planning_sparql_features/blank_nodes.md` §4.1, §4.2.2
- `issues/067` — `BNODE()` is a constant, not fresh per solution
- `issues/076` — `INSERT DATA` blank nodes are not freshened
- `issues/069` — no blank-node fixture, which is why this survived
