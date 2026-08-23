# A Literal With an Unknown Datatype Equals a Plain String

## Status: RESOLVED — fixed 2026-08-23 on branch `datatype-equality`
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


## Resolved — the full fix, both emitters

Done as the **full fix**, not the narrower unknown-datatype-only form sketched
above. The narrow form would have left the pushdown path wrong, and the
pushdown path is the one that runs against stored data.

**Expression path** (`emit_expressions.py`). `_cmp_pair` still chooses a lane
and still returns a pair; a new `_cmp_sql` composes it with the operator and
conjoins a datatype guard when neither side is provably in one value space.
The three rules above hold:

* numeric and datetime lanes compare by value, unguarded — `_in_one_value_space`
  returns True for them, so `"1"^^xsd:integer = 1.0` stays TRUE;
* plain and `xsd:string` stay equal, via `COALESCE(dt, xsd:string)` on both
  sides — a plain literal stores `datatype_id` NULL, not the xsd:string id;
* everything else compares only when the datatypes match.

`!=` is NOT the negation of the guarded `=`. It composes as
`(a != b) OR NOT guard`: two terms with different datatypes ARE unequal, so
the guard failing makes `!=` true, where it makes `=` false.

**Pushdown path** (`filter_pushdown.py`) — and this is where the issue's own
closing paragraph turned out to be right. The two emitters did disagree, and
the expression-path fix alone changed nothing for stored data, because a
stored-data `FILTER(?v = "x")` never reaches it. Two sites matched lexically:

* `_try_text_filter`'s `eq` arm emitted a bare `term_text = 'x'`. It now pins
  the datatype for a plain/`xsd:string` needle and DECLINES a typed one,
  deferring to the expression path.
* `_ne_equality_cond`'s plain/`xsd:string` arm carried a comment saying it
  matched "without pinning the datatype id". Correct that plain and
  `xsd:string` are one value; wrong that nothing else could collide.

Both now use `_plain_string_datatype_guard()`, so they cannot drift apart.

## What the original measurement missed

The 11 tests in `tests/integration/test_datatype_equality.py` split into eight
comparing literals written IN THE QUERY and three that STORE the three terms
first. The eight passed against the expression-path fix alone. Only the stored
ones caught the pushdown, and they only exist because the exposure query in
this issue — `datatype_id > 40` — prompted checking what the three terms
actually look like on disk:

    "x"                  datatype_id NULL    (plain)
    "x"^^xsd:string      datatype_id 1
    "x"^^<urn:custom>    datatype_id 41      (a row added on store)

That NULL is the detail the fix turns on, and it is not visible from a query
that never stores anything. Answering "does the schema change?" — no DDL
change; the per-space `datatype` table simply gains a row.

## Exposure question still open

The production count above was never run; no access from here. The fix is
correct either way, but whether this was a live defect or a latent one is
still unanswered.
