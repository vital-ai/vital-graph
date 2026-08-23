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

## Exposure is UNKNOWN — and the local measurement does not bound it

Zero spaces carry a literal with a datatype outside the standard 40 — checked
across all 54 spaces on the docker test stack and all 99 on the local host
cluster.

**That says nothing about production.** Both of those are development
environments. Custom datatypes arrive with imported third-party RDF, and what
has been imported into a served space is not visible from here. If any of it
carries one, callers are getting wrong answers today and have been.

An earlier revision of this section read "nothing we serve today can be
returning a wrong answer because of this". That was an overreach from two dev
databases to production, and it is exactly the inference this repository keeps
getting caught by — `issues/081` and `issues/118` are both a measurement
generalised past what it measured.

What the local result DOES establish: the change can be developed and tested
here without a fixture that exercises it, so one has to be built.

**Answering the exposure question takes one query against a production space**,
and it is cheap for anyone with access:

    SELECT count(*) FROM <space>_datatype WHERE datatype_id > 40;

Non-zero anywhere means this is a live defect with a known blast radius rather
than a latent one, and it should be prioritised accordingly.

## Fix — needs a decision, not just an edit

The mechanism is written up in
`planning/planning_sparql_features/datatypes_and_language_tags.md` §4b:
`_cmp_pair` (`emit_expressions.py:342`) is the lane chooser, it returns a
PAIR that six callers compose with an operator, and correct term equality
is a CONJUNCTION — so the full fix changes that contract and all six
comparators, every one of which works today.

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

**A narrower form avoids most of that risk.** Rather than reworking how
equality chooses a lane, require datatype equality ONLY when a datatype is
outside the standard set — leaving every currently-correct path untouched.
Unknown datatypes are exactly the broken case, and they are also the case with
no data behind them, so the blast radius of getting it wrong is confined to
the thing that is already wrong.

Worth checking before implementing: whether the pushdown path
(`filter_pushdown.py`) and the expression path agree on this, since
`issues/070` and the regex work both found the two emitters disagreeing about
semantics, which turns a pushdown into a behaviour change.
