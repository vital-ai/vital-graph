# A Literal With an Unknown Datatype Equals a Plain String

## Status: OPEN — found 2026-08-22 while writing
## `planning/planning_sparql_features/datatypes_and_language_tags.md` §4.2

    "x"^^<urn:myType> = "x"        spec: FALSE     actual: TRUE

Two literals with different datatypes are not value-equal unless both lie in
comparable value spaces. `urn:myType` is not a datatype we know, so the
comparison falls back to RDF term equality, which requires the datatypes to
match. We answer TRUE.

## What this actually is

The README of `planning_sparql_features` asks, under datatype edge cases,
whether unknown datatypes "compare as strings, and does the numeric lane
silently swallow them". Measured: **not the numeric lane — the text lane.**
Comparison is on `term_text`, so every literal whose datatype we do not model
collapses into the string lane and compares equal to a plain literal with the
same lexical form.

The term itself is stored correctly. `term_uuid` is a UUIDv5 over
`(text, type, lang, datatype)`, so `"x"^^<urn:myType>` and `"x"` are distinct
terms with distinct uuids, and a round-trip preserves both. It is only the
comparison that loses the distinction.

## Measured

    "x"^^<urn:myType> = "x"^^<urn:myType>    TRUE    correct
    "x"^^<urn:myType> = "x"                  TRUE    WRONG, should be FALSE

## Why it is worse than it looks

* **It is a silently wrong answer, not an error.** A query that should return
  nothing returns rows.
* **It cuts both ways.** `FILTER(?v = "x")` over data carrying a custom
  datatype now matches, and a query intended to distinguish typed from untyped
  values cannot.
* **Custom datatypes are exactly what imported third-party RDF carries.** Our
  own data uses the standard 40 in `STANDARD_DATATYPES`, which is why this has
  not surfaced.

## Fix — needs a decision, not just an edit

Unlike `issues/120` this is not one expression. Correct equality means carrying
`datatype_id` into the comparison whenever neither side is in a known
comparable value space, which touches the value lanes rather than a single
emitter arm:

* the numeric and datetime lanes already compare by VALUE and must keep doing
  so — `"1"^^xsd:integer = 1.0` is TRUE and correct today;
* `xsd:string` and a plain literal must stay equal, since RDF 1.1 makes them
  the same thing;
* everything else should compare only when the datatypes match.

The third rule is the new one. The risk is doing it in a way that also breaks
the first, which is the mistake `issues/049` made in the other direction —
booleans were compared in the text lane when they should not have been.

Worth checking before implementing: whether the pushdown path
(`filter_pushdown.py`) and the expression path agree on this, since
`issues/070` and the regex work both found the two emitters disagreeing about
semantics, which turns a pushdown into a behaviour change.
