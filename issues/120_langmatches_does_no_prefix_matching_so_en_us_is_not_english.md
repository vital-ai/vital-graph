# `langMatches` Does No Prefix Matching, So `en-US` Is Not English

## Status: OPEN — found 2026-08-22 while writing
## `planning/planning_sparql_features/datatypes_and_language_tags.md` §4.1

    langMatches("en-US", "en")     spec: TRUE     actual: FALSE

`FILTER(langMatches(lang(?x), "en"))` is the standard way to ask for "English,
any region". Today it returns **nothing** for `en-US`, `en-GB`, `en-AU`, and
matches only the bare tag `en`. The failure is silent: an empty result set, not
an error.

## Mechanism

`emit_expressions.py:860` emits an equality:

    if fname == "langmatches" and len(args) == 2:
        ...
        if b == "'*'":
            return f"({a} IS NOT NULL AND {a} != '')"
        return f"(LOWER({a}) = LOWER({b}))"

SPARQL 1.1 defines `langMatches` in terms of **RFC 4647 basic filtering**: a
language range matches a tag when it equals the tag, or is a prefix of it
ending at a subtag boundary. `LOWER(a) = LOWER(b)` implements only the first
half.

## Measured, end to end

Executed through the real path — sidecar, AST, generated SQL, PostgreSQL —
rather than read off the emitter:

    langMatches("en-US", "en")   FALSE   <- wrong
    langMatches("en",    "en")   TRUE
    langMatches("EN",    "en")   TRUE    <- case-insensitivity is correct
    langMatches("de",    "en")   FALSE
    langMatches("en-GB", "*")    TRUE    <- the wildcard arm is correct

So the two special cases already handled are right, and the general case is the
one that is wrong.

## Fix

Contained to the one return. A prefix test that respects the subtag boundary,
so `"en"` matches `en-US` but does not match `english`:

    LOWER(a) = LOWER(b) OR LOWER(a) LIKE LOWER(b) || '-%'

Two things to get right rather than assume:

* **The boundary matters.** A bare `LIKE b || '%'` would make `"en"` match
  `enm` (Middle English), which is a different language.
* **`b` is an expression, not always a literal.** It is emitted through
  `expr_to_sql`, so the concatenation has to work when the range comes from a
  variable, and the `'*'` arm above must keep its precedence.

## Why it matters

This is the most-used function in the datatype/language family, and the
consequence is an empty result rather than a visible failure — the category of
bug this repository has repeatedly found late. Any imported multilingual data
is affected; our own data is largely untagged, which is why it has gone
unnoticed.

## Test gap that hid it

Nothing in the suite asserts it. The DAWG `i18n` category, which covers exactly
this, exists on disk at `tests/conformance/dawg_data/sparql/sparql10/i18n` —
under `sparql10`, so the structural coverage guard in
`tests/conformance/test_dawg_coverage.py` (which walks the `sparql11` tree)
does not require it and its absence is not a failure. Wiring `i18n` would catch
this class.
