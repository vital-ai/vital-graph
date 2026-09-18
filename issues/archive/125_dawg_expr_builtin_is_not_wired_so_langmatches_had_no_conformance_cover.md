# The DAWG Category Covering `langMatches` Is Not Wired, and It Is Not `i18n`

## Status: RESOLVED 2026-08-23 — wired, and it found two real bugs the
## same day. Original report follows.

`issues/120` shipped a `langMatches` that did no prefix matching. Its "test gap
that hid it" section named the wrong category:

> The DAWG `i18n` category, which covers exactly this, exists on disk at
> `tests/conformance/dawg_data/sparql/sparql10/i18n`

**`i18n` does not cover `langMatches`.** It holds five cases — two kanji QName
tests and three IRI/Unicode normalization tests. Wiring it would not have
caught `issues/120` and will not catch anything in this family.

The category that DOES cover it is **`sparql10/expr-builtin`**, which contains
the exact failing query:

    q-langMatches-2.rq:  { :x ?p ?v . FILTER langMatches(lang(?v), "en") . }

along with `LangMatches-1`, `-3`, `-4`, `-basic`, and a `de-latn-de` case that
pins the subtag boundary from the other side.

## Why it never ran

`get_manifest_path` (`dawg_manifest_parser.py:264`) resolves one tree:

    return dawg_root / "sparql" / "sparql11" / category / "manifest.ttl"

Every entry in `P0_CATEGORIES` is therefore a `sparql11` category, and no
`sparql10` category is reachable by any spelling. The manifest has been on disk
the whole time. This is the same shape as the 2026-08-16 finding recorded in
`test_dawg_sql_v2.py` — "19 of 34 DAWG categories were wired in, so a green run
meant green on the categories someone remembered to add" — except that here the
category could not be added at all.

## What wiring it costs — measured, not estimated

Making `get_manifest_path` treat a slashed name as a path relative to
`sparql/` is three lines and backward compatible. Adding
`"sparql10/expr-builtin"` then collects 24 cases (48 tests across
`test_sql_v2` and `test_oracle_baseline`).

**29 of the 48 fail.** That is why this is filed rather than done: it is a
triage project, not a switch. Measured on branch `langmatches-prefix` with the
`issues/120` fix in place, so the LangMatches `test_sql_v2` cases are NOT the
bulk of it.

Two distinct kinds, and they need separating before anything is concluded:

* **`test_oracle_baseline` failures**, e.g. `LangMatches-1` reporting
  `expected 10, got 1`. The ORACLE is pyoxigraph, so a failure there is not our
  backend being wrong. A count that far off suggests the manifest's data files
  are not all being loaded for this tree — likely `_resolve_path` against
  sparql10 layout, which nothing has ever exercised. **Check this first**; if
  the data loads wrong, every downstream failure in the category is noise.
* **`test_sql_v2` failures**, some already flagged `[pyoxigraph also differs
  from .srx]` (`str-1`: expected 7, got 4). Those are the pre-existing
  oracle-disagreement class the file already tracks.

## Why it is worth doing

`expr-builtin` covers `str`, `lang`, `datatype`, `isIRI`, `isLiteral`,
`isBlank`, `sameTerm` and `langMatches` — the core term-inspection functions.
`issues/120` and `issues/121` were both in this family, both silently wrong,
and both found by writing a targeted test rather than by the suite. There is a
manifest on disk that would have found one of them.

Do not wire it and add 29 xfails. Diagnose the oracle/data-loading half first;
the honest failure count is not known until that is separated out.


## Resolved

`get_manifest_path` now treats a slashed category as a path relative to
`sparql/`, and `sparql10/expr-builtin` is in `P0_CATEGORIES`.

## The 29-of-48 estimate in this document was wrong

It said "a triage project, not a switch" and told the next reader to diagnose
the oracle half first. That instinct was right and the SIZE was not: the
failures were mostly **one missing parser**.

`sparql10` predates SRX and encodes expected results as RDF —
`rs:ResultSet` / `rs:solution` / `rs:binding` — so every `.ttl` result was
read as a CONSTRUCT graph and compared as triples. `LangMatches-1` reporting
`expected 10, got 1` was 10 TRIPLES IN THE FILE, not ten rows of anything.
That is why the oracle "failed" cases it should trivially pass, and it is why
this looked structural.

    29 failures  ->  13   after adding the rs:ResultSet parser
                 ->  11   after fixing lang() on non-literals
                 ->  10   after propagating the type error through langMatches "*"

**The lesson worth keeping is about the estimate, not the parser.** The
measurement in this document was accurate — 29 of 48 — and the inference from
it was not. A failure count says nothing about how many CAUSES there are, and
"the oracle also fails" pointed at a shared comparator rather than at 29
independent problems. One hour of reading beat the estimate by a wide margin.

## What it caught immediately, both ours

* **`lang()` of a non-literal returned `''`** instead of a type error, so a URI
  looked like an untagged literal — `lang-1`, `lang-2` and `LangMatches-4`,
  three cases with one cause. The same `term_type = 'L'` gate `datatype()`
  needed the same day.
* **The `langMatches` `*` arm turned NULL into FALSE.** Invisible positively
  and wrong under negation, since `!FALSE` is TRUE while `!error` is an error.
  A bug in code written hours earlier, caught by the net being switched on.

## The ten that remain are two different things

* `sameTerm-eq`, `sameTerm-not-eq`, `sameTerm-simple` — a REAL gap, diagnosed
  and filed as `issues/127`: `?v1 = ?v2` between two VARIABLES compares
  `term_text`. `sameTerm` itself is correct.
* `str-1`, `str-2` — the corpus disagrees with BOTH engines; hand-reading
  `data-builtin-1.ttl` agrees with us.

Recorded in `KNOWN_FAILURES` and `XFAIL_TESTS_V2` separately. `sameTerm-*`
needs an entry in both, for different reasons; deleting either hides half.

## Still unwired

`sparql10` has other categories, and `sparql12`, `rdf11`, `rdf12` remain
unreachable-by-default in the same way — the mechanism is fixed, the wiring is
per-category. `dawg_conformance_coverage.md` §2 now records that.
