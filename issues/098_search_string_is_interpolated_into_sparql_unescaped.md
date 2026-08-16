# Search Input Is Interpolated Into SPARQL Unescaped — Confirmed Filter Bypass

## Status: OPEN — found 2026-08-16 while reviewing the portal query work

`KGQueryCriteriaBuilder` builds its filters by f-string interpolation, so a
caller-supplied search string lands inside a SPARQL string literal with no
escaping:

    kg_query_builder.py:552   FILTER(CONTAINS(LCASE(?search_name), LCASE("{criteria.search_string}")))
    kg_query_builder.py:1001  (the same clause in the frame builder)
    kg_query_builder.py:575   FILTER(CONTAINS(LCASE(STR(?{filter_var})), LCASE("{filter_criterion.value}")))
    kg_query_builder.py:601   (entity property filters)
    kg_query_builder.py:1590  `contains` comparator in _build_property_filter

The portal plan already carried this as *"a `"` in the box currently breaks the
query"*. It is more than that.

## Confirmed, not theorised

A plain quote does break the query — the generated SPARQL fails to parse:

    search_string = 'Ann "Annie" Smith'
    -> FILTER(CONTAINS(LCASE(?search_name), LCASE("Ann "Annie" Smith")))
    -> Lexical error at line 21, column 55

But a balanced payload compiles and **disables the filter**:

    search_string = 'x")) || (1=1)) #'
    -> FILTER(CONTAINS(LCASE(?search_name), LCASE("x")) || (1=1)) #")))
    -> compiles; the FILTER is unconditionally true

The `#` comments out the remainder of the line, so the attacker also controls
where that clause ends. Verified against the sidecar (our production parse path)
on 2026-08-16.

Effect: the search filter is bypassed and the caller receives every entity of
the type rather than the ones matching their term. Since the same pattern is
used for property filters, the same bypass applies to those.

## Scope of the exposure

The values reaching these sites come from API request bodies —
`search_string`, and `value` on entity property filters. Any caller who can
issue a list/query request can reach them.

What it does NOT appear to reach: this builder emits SELECT, executed through
`execute_sparql_query`, so this is a read-side filter bypass rather than a write
primitive. That is a limit on impact and not a reason to leave it — the same
untrusted string reaches five interpolation sites, and the next one added may
not be a SELECT.

## Why the existing note understated it

The plan's line was written from the observed symptom: someone typed a quote and
the query failed. A failure is loud and gets described as a bug. The bypass is
silent — it returns a plausible-looking page of results — so it was never the
thing anyone noticed.

## The fix

Escape at the point of interpolation, for the five sites above and any future
one: at minimum `\\` and `"`, plus the characters SPARQL 1.1 §19.7 requires in a
STRING_LITERAL (`\n`, `\r`, `\t`, `\b`, `\f`). A single helper, used everywhere a
caller-supplied value becomes a literal, is the shape that survives — the same
lesson as the regex flag mapper in `regex_dialect.md` §4.2, where two copies of
one rule let a performance heuristic change semantics.

Note `_build_vector_criteria` (`:1735`, `:1737`) ALREADY escapes quotes:

    escaped_val = v.vector.replace('"', '\\"')

so the convention exists in this very file and was applied at one site out of
six.

## Not fixed here, deliberately

`kg_query_builder.py` currently has ~215 uncommitted lines of in-flight sort
work in the tree (`issues/096`). Adding an escaping change on top would tangle
two unrelated changes in one file. Worth doing as its own commit once that
settles, or immediately if this is judged urgent enough to interleave.

## Related

- `issues/043` — the other `kg_query_builder.py` defect; that file is worth a
  sweep rather than point fixes
- `test_scripts_internal/kg_portal_queries/PORTAL_QUERY_PLAN.md` — carries the
  client-facing version of this as *"a `"` in the box currently breaks the
  query"*. That understates it, and is worth correcting when someone next
  updates that document — the bypass matters more to a caller than the breakage,
  because the breakage is visible and the bypass is not
