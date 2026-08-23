# `langMatches` Does No Prefix Matching, So `en-US` Is Not English

## Status: RESOLVED — fixed 2026-08-23 on branch `langmatches-prefix`
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


## Resolved

One return in `emit_expressions.py`, as predicted. Both concerns in the Fix
section turned out to matter, and a third did not appear in this document.

**The boundary**, using the codebase's own prefix idiom rather than the `LIKE`
this issue proposed:

    LOWER(a) = LOWER(b) OR LEFT(LOWER(a), LENGTH(b) + 1) = LOWER(b) || '-'

`LEFT(...) = ...` matches `strstarts` (`emit_expressions.py:635`) and avoids a
hazard `LIKE` would have introduced: the range can arrive through a VARIABLE,
and `LIKE` would read a `%` or `_` in it as a metacharacter. Requiring the
`'-'` separator is what keeps `en` from matching `enm` (Middle English).

**A wildcard arriving through a variable — not in this issue.** The `*` arm
tested the EMITTED SQL for the literal `'*'`, so it only fired for a range
written in the query. `langMatches(?t, ?r)` with `?r = "*"` answered FALSE for
every tag, including tagged ones. Pre-existing, adjacent, and small enough that
leaving it would have meant shipping a still-wrong `langMatches`, so it is
fixed here: a dynamic range emits a runtime `CASE`, a static one keeps the
plain predicate so the ordinary `langMatches(lang(?v), "en")` pays nothing.

**No second path.** Checked before writing the tests rather than after:
`filter_pushdown` has no `langMatches` arm, so every case reaches
`emit_expressions`. This is the difference from `issues/121`, where the
pushdown was the only path that ran and the first fix missed it entirely.

17 tests in `tests/integration/test_lang_matches.py`, six of which failed
against the unfixed emitter. The boundary cases passed before the fix, since
equality is stricter than prefix matching — they guard the fix rather than
demonstrate the bug.

## The "test gap" section of this issue was wrong

It named `i18n` as the DAWG category covering this. `i18n` is two kanji QName
tests and three IRI/Unicode normalization tests, and covers no part of this
family. The category that holds `q-langMatches-2.rq` — literally
`FILTER langMatches(lang(?v), "en")` — is `sparql10/expr-builtin`, and it is
unreachable because `get_manifest_path` resolves only the `sparql11` tree.

Wiring it is a triage project rather than a switch: 29 of 48 tests fail, the
oracle-baseline half suggesting sparql10 data files are not loading. Filed as
`issues/125` with the measurement, rather than bolted onto this fix.
