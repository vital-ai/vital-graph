# The DAWG Category Covering `langMatches` Is Not Wired, and It Is Not `i18n`

## Status: OPEN — found 2026-08-23 while fixing `issues/120`

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
