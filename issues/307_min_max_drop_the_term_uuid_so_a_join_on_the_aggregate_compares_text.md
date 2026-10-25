# 307 — MIN / MAX drop the term uuid, so a join on the aggregate compares text

## Status: OPEN, 2026-10-25

**Related:** `vitalgraph/db/sparql_sql/emit_group.py` (MIN/MAX companions),
`emit_join.py` (the shared-variable ON clause), `qplan._render_subq` (the planner's
render of the same shape, which joins by uuid), issue 029 (MIN/MAX term ordering),
issue 087 (the text fallback's cost).

## Found

On `latest_per_deal_by_outcome` (UW dashboards), the planner's SQL joins the outer
`?computedAt` to the sub-SELECT's `MAX(?at)` by the term's **uuid**. Today's SQL joins them by
**text**:

    ON CAST(j2.v4 AS TEXT) = CAST(j3.v14 AS TEXT) AND j2.v2__uuid = j3.v10__uuid

The cause is in `emit_group.py`. MIN/MAX pick the winning row's `__type`, `__lang` and
`__datatype` with the SPARQL ordering (`_ordered_pick`), but emit its uuid as a constant
`NULL::uuid AS <agg>__uuid` (and `__bool`, `__dt` as NULL). The aggregate then has no term
identity, so `emit_join` falls through every uuid and typed-lane case to
`CAST(a AS TEXT) = CAST(b AS TEXT)`.

## Why it is wrong

SPARQL join compatibility is RDF-term equality. MIN/MAX return one term of the group (§18.5.1),
so the joined value must be that same term. Comparing text instead:

- **joins terms that differ only in datatype or language:** `"2026-01-01T00:00:00"^^xsd:dateTime`
  joins `"2026-01-01T00:00:00"` (a plain string), or the same text `@en`. This happens whenever
  the outer side holds such a term, with no tie needed;
- **on a tie under the ordering** (same kind, same number or no number, same text, different
  datatype), the winner is arbitrary, and the text compare joins every one of the tied terms;
- **is slow:** no index or hash on term identity, and the text must be decoded on both sides
  first (issue 087 measured the same fallback at 21,790 ms vs 0.3 ms on a VALUES join).

The planner path and today's path return the same rows on the UW data (contract,
2026-10-25: 4/4 rows identical in every column) only because the data has neither case.

## Fix

1. In `emit_group.py`, pick `__uuid` with the same ordered pick as the other companions:
   `(array_agg(g.<v>__uuid ORDER BY <key>))[1] AS <agg>__uuid`. The input variable must have term
   identity (`has_term_identity()`); without it (a computed input) keep `NULL::uuid` and today's
   fallback.
2. Register the aggregate's column with uuid identity in that case, so `emit_join` takes its
   first branch (`__uuid = __uuid`).
3. Leave `__num` as it is: the guarded numeric aggregate (issue 029) is about numeric use of the
   value, not identity. Decide whether `__dt` and `__bool` should come from the pick too (today
   NULL), and check what reads them.
4. Check the other consumers of a MIN/MAX column (ORDER BY, FILTER, HAVING, projection decode)
   behave the same once `__uuid` is set. In particular, the decode must not re-join the term
   table on a uuid that was previously NULL and change the output columns.

## Tests

- A unit or DAWG-style case where the outer side has the same text as the MAX in a different
  datatype: today joins (wrong), fixed does not.
- A tie case: two terms with equal text and different datatypes in one group. Fixed joins exactly
  the picked term.
- The DAWG aggregates suite (MIN/MAX, COUNT 8b on a numeric lane) unchanged.
- `latest_per_deal_by_outcome` on the vg test stack: same rows as before, and the SQL's ON clause
  compares `__uuid`; time it before and after (the text join decodes both sides).
- Planner contract on the same query: today's and the planner's SQL agree, now by construction
  rather than by the data.
