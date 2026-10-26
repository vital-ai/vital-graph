# 316 — A VALUES row joins a stored term by its text, not the term

## Status: FIXED 2026-10-26, on the default path. Open until the vg test stack runs the full suite on the rebuilt image.

## Defect

On the default path, which production runs, a VALUES row joined to a pattern matched terms that
share its lexical form but are different RDF terms. SPARQL joins compatible mappings, and compatible
means the same term: `"3.0"^^xsd:decimal` is not `"3.0"^^xsd:float`, the literal `"urn:x"` is not
the IRI `<urn:x>`, and `"hi"` is not `"hi"@en`. The results were silently wrong.

There were two defects, both breaking the same rule:

1. **Constant registration.** `emit_table._uuid_expr` registered a VALUES literal on (text, type)
   only, dropping its language and datatype. So `VALUES ?v { 3.0 }` was looked up as the plain
   string "3.0": it found the wrong term, or found nothing and matched nothing. The scalar fallback
   for an unresolved constant (`generator.substitute_constants`) also matched `_const` on
   (text, type) alone.

   ```sparql
   SELECT ?s WHERE { ?s ex:v ?v } VALUES (?v ?k) { (3.0 UNDEF) }   # stored "3.0"^^xsd:decimal: none found
   ```

2. **The text join.** A VALUES column holding UNDEF in any row has no term identity, so
   `emit_join` compared `CAST(a AS TEXT) = CAST(b AS TEXT)`: any stored term with the same text
   matched.

   ```sparql
   SELECT ?s WHERE { ?s ex:v ?v } VALUES (?v ?s) { (3.0 UNDEF) (UNDEF ex:zz) }  # also matched the float
   ```

## How it was found

The planner's contract check runs today's SQL beside the planner's. It disagreed on a VALUES-with-UNDEF
shape (`corpus/values_shapes/v01`): the planner joins on term uuids, today's SQL on text, and the space
stores `"3.0"^^xsd:float`.

## Fix

- `emit_table._uuid_expr` registers the literal's language and datatype as well.
- `generator.substitute_constants`: the fallback subquery matches the whole identity, through the same
  predicate (`_const_match`) the `_const` CTE uses. The CTE now also carries `lang` and `datatype_id`.
- `emit_join`: when the text join compares a VALUES constant with a stored term, it also compares the
  term's kind, language (case-blind) and datatype, reading a plain literal's datatype as NULL or
  xsd:string. The text join between other computed values is unchanged and has not been examined.

## Test

`tests/integration/test_values_undef_joins_on_the_term.py` covers decimal vs float, literal vs IRI,
plain vs tagged, and UNDEF still matching everything. It also covers a column holding UNDEF, which
needs the join fix. With either fix reverted, some of these tests fail.

Also run on the fix: the unit suite, DAWG on the default path and through the planner, and the full
integration suite.
