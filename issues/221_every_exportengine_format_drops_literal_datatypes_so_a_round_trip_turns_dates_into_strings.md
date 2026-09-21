# Every `ExportEngine` Format Drops Literal Datatypes, So An Export/Import Round Trip Turns Dates Into Strings

## Status: FIXED 2026-09-21 — found while trying to sort search results by an
## entity's modification datetime on an imported copy of production

The `^^<datatype>` arm now exists, via a shared `_format_literal_suffix`, and
all FOUR export queries join the space's `datatype` table. Only the OBJECT
position needs it — subject, predicate and context are never literals.

VERIFIED BY ROUND TRIP, not by reading the SQL. Exported `sp_lead_types`
(1,483,310 quads) and re-imported it into a fresh space:

    xsd:string    4,232 -> 4,232   MATCH
    xsd:decimal   3,100 -> 3,100   MATCH
    xsd:float       967 ->   967   MATCH
    xsd:integer     101 ->   101   MATCH
    xsd:boolean       2 ->     2   MATCH
    num_val       4,168 -> 4,168   MATCH

`num_val` is the line that matters: it is `GENERATED ALWAYS AS (...) STORED`
keyed on `datatype_id`, so it is non-zero only if the datatype survived.
Before the fix it would have been 0.

`xsd:dateTime` read 221 -> 207 and needed explaining rather than accepting: 21
of the source's 221 are ORPHAN terms present in `term` but in no quad, so they
are correctly not exported. Comparing the SETS rather than the counts:
**0 source values missing from the restored space.**

Two decisions, recorded here because both are easy to get wrong later:

* **`@lang` wins over `^^<dt>`.** A language-tagged literal IS
  `rdf:langString`, and `"x"@en^^<...>` is not legal N-Triples.
* **`xsd:string` is emitted explicitly** rather than left implicit. RDF 1.1
  makes a plain literal an `xsd:string` so both forms re-import identically —
  but `bulk_export._nt_term_sql` already emits it, and two exporters
  disagreeing about the same quad is precisely how this bug hid.

STILL TO DO: every space previously restored from an `ExportEngine` file
carries string-typed literals where it should have typed ones. A sweep
comparing `datatype_id` distributions against a known-good source would find
them.

The reproduction that FOUND this — `nurture_msg_prod` — was re-exported with
the fix, re-imported as `nurture_typed`, and dropped on 2026-09-21. The
corrected space is the evidence the fix holds at production scale:

    nurture_msg_prod (broken)      nurture_typed (re-exported)
    dt_val              0          dt_val            581,237   of 581,237 terms
    entity_prop_sort.value_dt  0   value_dt          174,220
    entity_slot_sort.value_dt  0   value_dt          415,426

`value_dt` is the line that matters, for the same reason `num_val` mattered in
the round trip above: it is `GENERATED ALWAYS AS (...) STORED` keyed on
`datatype_id`, so it is non-zero only if the datatype survived export, import,
AND the derived-table rebuild.

**Related:** `issues/042` (CSV import drops datatypes — the same failure, a
different door); `issues/126` (what positional datatype ids assume)

## The defect

`ExportEngine`'s term serialisers cannot emit a datatype. They take three
arguments and handle only language tags:

    data_export_impl.py:50  def _format_term_nt(text, term_type, lang)
    data_export_impl.py:65  def _format_term_nquads(text, term_type, lang)

        if lang:
            return f'"{escaped}"@{lang}'
        ...                                  # no ^^<datatype> arm at all

and every query that feeds them selects only text, type and lang — no join to
the space's `datatype` table:

    ot.term_text AS o_text, ot.term_type AS o_type, ot.lang AS o_lang

**All four export formats, not one:**

    :184  export_ntriples
    :347  export_nquads
    :478  export_jsonl_quads
    :664  export_vital_block

`vitalgraphexport` calls these, so every file the CLI writes is affected.

## It is not the case that nothing knows how to do this

`db/sparql_sql/bulk_export.py::_nt_term_sql` does it correctly — it takes a
`dt_alias`, emits `'^^<' || datatype_uri || '>'`, and its caller
`export_space_to_nquads` supplies it with a `LEFT JOIN {datatype}`.

So there are TWO N-Quads exporters in the tree, one correct and one not, and
the CLI uses the one that is not.

## Measured, production -> local round trip

Production KG space, `hasObjectModificationDateTime`:

    term_type  datatype_id  datatype_uri                   sample
    L          9            XMLSchema#dateTime             2026-08-31T01:03:04.859673+00:00

The line `vitalgraphexport -f ....nq.gz` wrote for that predicate:

    <urn:...> <...#hasObjectModificationDateTime> "2026-08-24T19:18:20.407250+00:00" <urn:...> .

No `^^<http://www.w3.org/2001/XMLSchema#dateTime>`. After importing that file,
the same 84,291 quads carry `datatype_id = 1` — `xsd:string`.

The import is NOT at fault. It stored faithfully what the file said.

## What breaks, silently

`num_val` and `dt_val` are `GENERATED ALWAYS AS (...) STORED` columns keyed on
`datatype_id` (`sparql_sql_schema.py`). A literal that arrives as `xsd:string`
therefore produces NULL in both lanes, and everything reading them goes quiet
rather than wrong-loudly:

* **Date sorting stops working.** This is how it was found:
  `entity_prop_sort.value_dt` was NULL on **all 421,456 rows** of an imported
  space, so the partial index `... WHERE value_dt IS NOT NULL` indexed ZERO
  rows. A query ordering by it returned 0 rows in 77 ms — a plausible latency
  attached to a query that did nothing, which is `issues/171` exactly.
* **Numeric and date range filters** push down against the same id sets
  (`filter_pushdown.py`), so a range over a re-imported space matches nothing.
* **`entity_slot_sort`'s dt lane** has the same shape.

None of this errors. A space restored from an export looks complete — right
quad count, right terms, right text — and silently loses every typed
comparison.

## Fix

Give the two formatters a `datatype` argument and a `^^<...>` arm, and join the
datatype table in all four queries — or better, delete them and route
`ExportEngine` through `bulk_export._nt_term_sql`, which already does this and
is the version with the escaping comment explaining the grammar.

Order matters if both are kept: `@lang` and `^^<dt>` are mutually exclusive in
the N-Triples grammar, and `rdf:langString` must serialise as the lang form.

## Then

Every space previously restored from an `ExportEngine` file has string-typed
literals where it should have typed ones, and nothing flags it. A sweep
comparing `datatype_id` distributions against a known-good source would find
them.

`nurture_msg_prod` was one such space; it has been replaced by a corrected
re-import (`nurture_typed`) and dropped. See the Status section for the
before/after figures.

One thing the repair exposed that this issue did not predict: a space restored
before the fix is not repaired by re-importing alone. The derived tables carry
the NULL `value_dt` forward until they are rebuilt, and on a 49.7M-quad space
that rebuild is a 36-minute `resync_all_auxiliary_tables`, not an incremental
catch-up — the periodic backfill moves ~17k rows per 5-minute cycle and cannot
converge. Budget for that when sweeping other affected spaces.
