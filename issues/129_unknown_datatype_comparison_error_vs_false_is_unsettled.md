# Unknown-Datatype Comparison: Type Error or False? The Two Authorities Disagree

## Status: OPEN — semantics SETTLED and partly implemented 2026-08-24.
## Two of seven cases fixed; five remain with a diagnosed cause.

`issues/128` names `open-world` as the largest remaining sparql10 cluster.
Attempted it; got two of seven cases passing and reverted, because the change
broke eight other things and the reason is a genuine semantic conflict rather
than a coding mistake.

## What the DAWG cases demand

`open-eq-06` is `FILTER ( ?v != "a"^^t:type1 )` over `data-1.ttl`:

    :x1 :p "a"^^t:type1 .   :y1 :p "a"^^t:type2 .   :z1 :p "1"^^xsd:integer .
    :x2 :p "b"^^t:type1 .   :y2 :p "b"^^t:type2 .   :z2 :p "01"^^xsd:integer .
                                                    :z3/:z4 "2"/"02"^^integer

**Expected: 0 rows.** Eight rows in, none out. So every one is either FALSE or
an ERROR — including `"b"^^t:type1 != "a"^^t:type1`, two DIFFERENT terms of the
SAME unrecognised datatype. The only reading that gives zero is: when a
datatype's value space is unknown, we cannot know whether two lexical forms
denote the same value, so the comparison is a TYPE ERROR and the FILTER drops
the row.

`open-eq-04` (`?v != 1`, expected 2) agrees: only the integers are comparable.

## What our own tests demand — and they came from `issues/121`

`tests/integration/test_datatype_equality.py`, written 2026-08-23:

    test_two_unknown_datatypes_that_differ_are_not_equal
        "x"^^<custom> = "x"^^<other>     asserts FALSE

That follows `issues/121`, which states the spec answer for
`"x"^^<urn:myType> = "x"` is FALSE, reasoning from `RDFterm-equal`
(§17.4.1.7): two literals with different datatypes ARE different RDF terms,
and the function "returns FALSE if term1 and term2 are known to be different".

**Both readings are defensible and they contradict each other.** RDFterm-equal
says different-datatype literals are known-different, hence FALSE. The
open-world cases say an unknown value space makes the comparison
undeterminable, hence error.

## Measured cost of implementing the DAWG reading

Two cases fixed, `open-eq-06` and `open-eq-04`. Eight broken:

* five in `test_datatype_equality.py`, all asserting FALSE where the rule
  returns unbound;
* `bind/bind11`, `aggregates/SAMPLE`, `aggregates/SAMPLE DISTINCT`, which had
  been passing.

Reverted on that basis. A change that breaks eight to fix two is not a fix,
and the three conformance regressions say the blast radius reaches well past
the datatype family.

## What it would take to settle this

1. **Read §17.3's operator table, not just §17.4.1.7.** The `=` operator is
   only defined as RDFterm-equal when the operands fall OUTSIDE the supported
   datatypes; the table is what decides whether an unknown datatype makes the
   operator inapplicable (error) or falls through to term comparison (false).
2. **Check what the three regressions actually needed.** `SAMPLE` breaking
   suggests the rule reached aggregate paths that only wanted term identity —
   possibly the fix belongs at the comparison operators alone, not in a shared
   helper.
3. **Decide, then make ONE of the two test sets authoritative** and correct the
   other, rather than leaving both asserting opposite things. Right now
   `issues/121`'s premise and the DAWG corpus cannot both be right.

## Also learned, and worth keeping

`open-eq-07` — `FILTER(?v1 = ?v2)`, two variables — did NOT move under any of
the three edits, staying at 28 rows where 12 are expected. It never reached
`_cmp_sql`. The likely explanation is in the code's own comment: the builder
turns variable equality into a triple pattern (term identity) rather than a
FILTER. That is a THIRD comparison path, after the expression emitter and the
push-down, and nothing in the planning docs mentions it.


## Settled: the standard says TYPE ERROR

SPARQL 1.1 §17.3 routes `=` to a value comparison only for the datatypes it
supports. Everything else falls through to RDFterm-equal (§17.4.1.7), which
**"produces a type error if the arguments are both literal but are not the
same RDF term"**. FALSE is reserved for the case where they are NOT both
literal — a URI against a literal is well defined and unequal.

So the DAWG corpus was right and `issues/121`'s "spec: FALSE" premise was
wrong. Five tests written from that premise now assert the standard.

**What `issues/121` fixed is unaffected.** In a FILTER a type error and FALSE
both drop the row. The two differ only where the value is observed — a BIND —
and under negation, where `!error` stays an error but `!FALSE` is TRUE.

## Done

* `4fae676` — the expression path. Fixes `open-eq-06`.
* this commit — the push-down. Fixes `open-eq-04`.

Two constraints, both learned by violating them: resolve the datatype through
`_dt_sql` rather than `info.dt_col` (the latter engages where `_datatype_guard`
declines and references columns not in scope — it took out
`aggregates/SAMPLE`), and skip a pair already in one value space (the numeric
lane already yields NULL for a term outside it).

## Remaining: 5 cases, one diagnosed cause

`open-eq-07` is `FILTER(?v1 = ?v2)`: 28 rows where 12 is correct. **16 is
exactly the number of pairs among the four unknown-typed terms**, so the
same-term branch of `_term_error_cmp` is matching all of them rather than only
the four identical pairs. `open-eq-08/10/11/12` are the same shape.

**Correction to this issue's own earlier text:** it said `FILTER(?v1 = ?v2)`
never reaches `_cmp_sql`, and blamed the builder rewriting variable equality
into a triple pattern. That was inferred from a row count that did not move.
Dumping the generated SQL shows the type-error CASE is present. The path is
fine; the branch is wrong.


## The ill-typed fix was ATTEMPTED and REVERTED — comparability is PAIRWISE

Diagnosis (2026-08-24): DAWG excludes `x1/x4` against `x5`, the ill-typed
`"xyz"^^xsd:integer`. A recognised datatype carrying an unparseable lexical
form has no value, and `num_col` is NULL exactly then — so requiring
`num_col IS NOT NULL` looked like the fix.

**It made things worse.** `open-eq-08` went 42 -> 34, `open-eq-10`/`-11` went
53 -> 44. Eight pairs lost, not four gained.

The reason is structural, and it invalidates the model rather than the edit:

    x5 vs x1/x4  (ill-typed integer vs string)     DAWG EXCLUDES  -> error
    x5 vs x2/x3  (ill-typed integer vs langString) DAWG INCLUDES  -> != is TRUE
    x5 vs x7/x8  (ill-typed integer vs bnode/URI)  DAWG INCLUDES  -> != is TRUE

The SAME operand is indeterminate against one datatype and determinate against
another. **Comparability is not a property of one operand, which is what
`_comparable_sql` assumes.** Marking `x5` non-comparable removes it from all
three groups, and two of them were right.

## What the model needs to become

Pairwise determinacy, roughly:

* either side NOT a literal            -> definite (RDFterm-equal gives FALSE)
* exactly one side language-tagged     -> definite (never equal)
* both language-tagged                 -> definite (term identity over text+tag)
* both plain/typed literals            -> determinate ONLY if both datatypes are
                                          recognised AND both values parsed

That is a restructure of `_term_error_cmp`, not a patch to `_comparable_sql`.
It should be done deliberately, with the expected SRX diffed after each step —
this issue's history is five wrong theories, every one of them from reasoning
instead of diffing the expected results.

## Remaining, split by kind

NOT ours (pyoxigraph also differs from the corpus; needs hand-checking and a
recorded reason, the treatment `str-1`/`str-2` got):

    date-2      FILTER(?v != "2006-08-23"^^xsd:date)   result-set mismatch
    date-3      FILTER(?v > "2006-08-22"^^xsd:date)    expected 3, got 4
    open-eq-01  graph match, no lexical form in data   expected 2, got 0

Ours:

    open-eq-08  42 rows, correct COUNT, wrong SET      pairwise determinacy
    open-eq-10  52 vs 53, one extra row                probably the same
    open-eq-11  52 vs 53, one extra row                same shape as -10
    open-eq-12  10 vs 64                               DIFFERENT cause, below.


## `open-eq-12` — measured 2026-08-24, and my first description of it was wrong

    { ?x :p ?v1 . ?y :p ?v2 .
      OPTIONAL { ?y :p ?v3 . FILTER( ?v1 != ?v3 || ?v1 = ?v3 ) }
      FILTER (!bound(?v3)) }

I said the outer `!bound(?v3)` was not emitted, from grepping the SQL for
`IS NULL`. **It IS emitted** — as `NOT ((v5 IS NOT NULL))`, which that grep
cannot match. The filter is fine.

What the SQL actually shows: we return all 64 rows, so `?v3` is NEVER bound —
the OPTIONAL body produces no match at all. And the body's own FILTER emits
none of our type-error `CASE`s, so the equality rule is not reaching it.

The intended behaviour is subtle and worth writing down, because it is what
makes this case a test of the type-error rule rather than of OPTIONAL:
`?v1 != ?v3 || ?v1 = ?v3` is TRUE whenever the comparison is DETERMINATE, and
an ERROR when it is not. So the OPTIONAL matches exactly the determinate pairs,
`?v3` binds for those, and `!bound(?v3)` keeps only the INDETERMINATE ones —
the ten rows expected. It is the pairwise-determinacy question again, seen
through OPTIONAL.

So `-12` is probably NOT a separate cause after all; it is the same
determinacy model, and it will not be assessable until that lands. Whether the
OPTIONAL body binding nothing is a second, independent defect is UNKNOWN — it
has not been isolated from the equality behaviour.

## Triage DONE 2026-08-24 — and it reverses the earlier classification

I had grouped these three as "not our bug" from the `ACCEPTED` label. **That
label only means pyoxigraph ALSO differs from the `.srx`. It does not mean we
are right.** Hand-checked against data-1/data-3 and the expected SRX:

| case | corpus | us | verdict |
|---|---|---|---|
| `open-eq-01` | 0 | **0** | we are RIGHT; the oracle returns 2 |
| `date-2` | dt1,d4,d5 | dt1,d4,d5,**d2,d3** | OUR BUG |
| `date-3` | d1,d2,d3 | d1,d2,d3,**dt1** | OUR BUG |

### `open-eq-01` — oracle bug, we match the corpus

    SELECT * { ?x :p "001"^^xsd:integer }

A triple pattern, not a FILTER, so it matches by RDF TERM. `"001"^^xsd:integer`
is a distinct term from `"1"` and `"01"`; no term in the data has that lexical
form, so ZERO rows is right, and the manifest says so itself — "graph match -
no lexical form in data (assumes no value matching)". pyoxigraph returns 2,
value-matching in a graph pattern, which the manifest explicitly excludes.

### `date-2` — ours: an untimezoned xsd:date is INDETERMINATE against a
### timezoned one within 14 hours

    FILTER ( ?v != "2006-08-23"^^xsd:date )

We return `d2` (`2006-08-23Z`) and `d3` (`2006-08-23+00:00`), which the corpus
excludes. Those are the SAME DAY as the needle, differing only in carrying a
timezone. XSD gives dates a PARTIAL order: a timezoned and an untimezoned value
are comparable only when the interval between them exceeds the maximum offset
of 14 hours. Same day, so indeterminate — a type error, and the FILTER drops it.

That the corpus KEEPS `d5` (`2001-01-01Z`) against the same untimezoned needle
is the other half of the rule and the proof it is 14 hours and not "any
timezone mismatch": five years apart is determinate whatever the offset.

`datatypes_and_language_tags.md` §4.6 fixed the timezone question for
`xsd:dateTime` EQUALITY by requiring both sides to agree about having a
timezone. That is a cruder rule than XSD's and it was not applied to
`xsd:date` at all.

### `date-3` — ours: ordering an xsd:dateTime against an xsd:date is a type error

    FILTER ( ?v > "2006-08-22"^^xsd:date )

We return `dt1`, `"2006-08-23T09:00:00+01:00"^^xsd:dateTime`. `xsd:dateTime`
and `xsd:date` are different value spaces, so the ordering is a type error and
the row is dropped. We compare them anyway.

Note this is ORDERING, not equality. The type-error work so far deliberately
touched `=` and `!=` only, on the grounds that ordering has its own rule. This
is that rule, and it is missing.

### Disposition

`open-eq-01` can go in `KNOWN_FAILURES` and `XFAIL_TESTS_V2` with the reason
"oracle disagrees with the corpus; we match the corpus" — the same disposition
`str-1`/`str-2` got. `date-2` and `date-3` must NOT: they are real defects and
should stay visible.


## date-2 and date-3 are FIXED (dd97082, cca66e2)

Both now match the corpus exactly — `date-2` returns dt1, d4, d5; `date-3`
returns d1, d2, d3 — and pyoxigraph differs from the corpus on both.

Two rules, and having only one gives a wrong answer in each direction:

* **`xsd:date` orders only PARTIALLY.** A timezoned value and an untimezoned
  one are comparable only when the interval exceeds the maximum offset of 14
  hours. `2006-08-23`, `2006-08-23Z` and `2006-08-23+00:00` all normalise to
  the SAME `dt_val`, so only the presence of an offset in the lexical form
  distinguishes them. 14 hours specifically and not "any timezone mismatch":
  the corpus KEEPS `2001-01-01Z` against the same untimezoned needle.
* **Confined to one value space.** `xsd:date` and `xsd:dateTime` are different
  datatypes, so their literals are different TERMS and equality is determinate
  however close the instants. Without this the window swallowed the dateTime 8
  hours from the needle, taking `date-2` from 5 rows to 2.

The asymmetry, twice confirmed by the corpus: different value spaces make
ORDERING a type error and leave EQUALITY determinate.

## NOT a harness defect — `open-eq-02` resolves a constant to the WRONG TERM

Filing the three triaged cases as xfails was tried and REVERTED, because it
broke `open-eq-02`, which had been passing:

    open-eq-02 alone                              FAILS
    open-eq-02 with open-eq-01 xfailed            FAILS
    full category, no xfails                      passes

**My first explanation was wrong.** I said `pytest.xfail()` aborts the test
body so an xfailed test never runs its DATA LOAD, and that `open-eq-02` was
relying on `open-eq-01` to load `data-1.ttl` into the shared space.

Two measurements refute it:

* `open-eq-02` has its OWN `data_file` in the manifest — `data-1.ttl`, the same
  one — so it does not depend on a neighbour to load it.
* `run_single_test_sql_v2` caches the last dataset and skips the reload when it
  matches. I REMOVED that cache so every test truncates and loads its own data,
  and `open-eq-02` STILL failed with the xfails in place. The cache is not the
  mechanism.

What IS established, and reproducible in both cache states:

    no xfails                     open-eq-02 PASSES
    open-eq-01 filed as an xfail  open-eq-02 FAILS

Neither test changed. The dependence is real; **the mechanism is unknown**, and
the reload cache — genuinely fragile, and worth removing on its own merits —
is not it.

That matters well beyond these three: `KNOWN_FAILURES` and `XFAIL_TESTS_V2`
are used throughout this file, and every entry silently removes a data load
that a later test may depend on. A category can therefore go GREEN when its
xfails are added and RED when one is removed, for reasons unrelated to the
code.

Not fixed. The dispositions were reverted, so nothing in the tree depends on
this today — `open-world` stays unwired while `open-eq-08/10/11/12` fail.

**Next step, and it is a measurement not a theory:** run `open-eq-02` in the
failing configuration and print what it actually returns and what the space
actually contains, the way `open-eq-07` was eventually cracked. Every
explanation offered so far, including both of mine, came from reasoning about
the harness rather than from looking at its output.

The reload cache should be removed regardless. A test's dataset depending on
which test ran before it is wrong even when it is not the bug in hand.


## `open-eq-02` — DIAGNOSED 2026-08-24. It is ours, and it is not about xfails

    { ?x :p "a"^^t:type1 }        expects x1

`data-1.ttl` holds two literals with the lexical form `a`:

    :x1 :p "a"^^t:type1 .
    :y1 :p "a"^^t:type2 .

**We return `y1`.** A triple-pattern constant carrying an unrecognised datatype
resolves to a term with the WRONG datatype. Measured directly: the space
contains both terms correctly, the generated SQL runs, and it returns exactly
one row — the wrong one.

That also explains the behaviour that made this look like a harness problem.
Two terms share the lexical form, so WHICH one the constant resolves to
depends on load and cache state, and therefore on which tests ran before it.
`open-eq-02` passed only when it inherited `open-eq-01`'s already-loaded data.

### Three wrong explanations, for the record

1. *"`pytest.xfail()` skips a neighbour's data load."* No — `open-eq-02` has
   its own `data_file`.
2. *"The runner's reload cache."* No — removing it entirely changed nothing.
3. *"The generator's datatype cache is stale."* No — calling
   `invalidate_datatype_cache` after every load changed nothing.

All three were reasoning about the harness. The answer came from printing the
row we actually return and comparing it against the data, which is the third
time in this issue that measurement beat inference and the third time I reached
for inference first.

### The reload cache and the missing invalidation are still worth fixing

Neither is the cause here, but both are real: `truncate_space` clears
`rdf_quad` and `term` and NOT `datatype`, and no DAWG path calls
`invalidate_datatype_cache`. A test's dataset should not depend on which test
ran before it. Separate from this bug, and lower priority than it.

### Next

Find where a triple-pattern object constant is resolved to a `term_uuid` and
check what datatype it uses. `term_uuid` is a UUIDv5 over
`(text, type, lang, datatype)`, so resolving `"a"^^t:type1` to `y1`'s term
means the datatype going into that computation — or into the lookup that
replaces it — is not `t:type1`.


## ROOT CAUSE — a constant term is resolved by (text, type) ALONE

`AliasGenerator.register_constant` (`ir.py:62`) keys on a 2-TUPLE:

    def register_constant(self, term_text: str, term_type: str) -> str:
        key = (term_text, term_type)

and `build_constants_cte` (`generator.py:101`) looks the term up with exactly
that:

    WHERE term_text = 'a' AND term_type = 'L'

**`term_uuid` is a UUIDv5 over `(text, type, lang, datatype)`.** So the lookup
is missing two of the four components that define the term. Where more than one
term shares a lexical form, it returns whichever row comes back first.

Measured in the DAWG space:

    8dc3a916-06d2-54ba-a253-8f213eb07232   text=a   dt=t#type1
    5fb8b014-ea39-5979-9221-760afc2a64bb   text=a   dt=t#type2

The emitted SQL for `{ ?x :p "a"^^t:type1 }` contained
`object_uuid = '5fb8b014...'` — the **type2** term — and so returned `y1`
instead of `x1`.

`collect.py:248` is the registration site for a literal object in a triple
pattern, and it passes `val.value` only, discarding the datatype and the
language tag the node carries.

## This is far wider than the DAWG case

ANY triple pattern with a typed or language-tagged literal constant is exposed
whenever another term shares its lexical form:

    { ?x :p "5"^^xsd:integer }     may match "5"^^xsd:double or plain "5"
    { ?x :label "cat"@en }         may match "cat"@fr or plain "cat"

It has not bitten our own data because a given predicate there tends to carry
one datatype, so lexical forms rarely collide across types. Imported RDF has no
such guarantee — the same condition that made `issues/121` invisible.

Note this is TERM matching in a graph pattern, not FILTER evaluation, so none
of the equality work in this issue touches it. It is a fourth comparison path,
after the expression emitter, the push-down, and the semi-join gate.

## The fix, and why it is not a one-liner

`register_constant` must key on `(text, type, lang, datatype)` and
`build_constants_cte` must emit all four in its `WHERE`. That means:

* six call sites of `register_constant` (`collect.py` x3,
  `filter_pushdown.py` x2, `emit_table.py`), each needing the lang/datatype it
  currently drops;
* every reader of `aliases.constants[(text, type)]` — `semijoin.py:88`,
  `slot_sort_range.py`, `emit_bgp` — since the key shape changes;
* the CTE's multi-pair `IN ((text, type), ...)` form becomes a 4-column
  comparison, and `datatype` is an ID on the term table but a URI on the node,
  so the lookup has to join or resolve.

Worth doing carefully with the expected SRX diffed after each step. It should
fix `open-eq-02` and may well move `open-eq-03`/`-05`/`-09`, which are the same
graph-match-on-a-typed-literal shape.


## FIXED on branch `constant-term-identity` — and the fix carries a
## prerequisite: generation must stop swallowing exceptions

Three commits, all five gates green:

    bb9d605  resolve a constant term by its full identity
    334fe73  resolve the datatype by id, no join, plain == xsd:string
    a2b623a  the widened key silently disabled three optimisations

Perf went 48 -> 15 -> 2 -> 0 across them.

### The three plan regressions, and why they are one shape

Widening `constants` from `(text, type)` to `(text, type, lang, datatype)` did
not break loudly anywhere. It broke as lookups returning None, and every
consumer reads None as "unmeasured — decline the optimisation". Rows stayed
CORRECT; plans collapsed.

| site | symptom |
|---|---|
| `_dt_predicate` demanding `datatype_uri IS NULL` | 0 rows for every string criterion |
| `_term_uuid(aliases, *pred)`, FIVE splat sites | swallowed TypeError -> `range_stats` empty -> 4115x buffers |
| `_all_values_resolved` keying on a 2-tuple | VALUES fast path abandoned, 7,342 ms against 0.4 ms |

Four suites passed with all three present. Only perf caught them, and only
where a benchmark asserts buffers or milliseconds rather than rows.

### THE PREREQUISITE: a swallowed exception is not an implementation detail

`_generate_sql` catches broadly and returns `GenerateResult(ok=False, error=...)`,
or lets a partially-degraded plan through. So a `TypeError` in an OPTIONAL path
— a statistics lookup, a gate, a rewrite — never reaches a stack trace. It
becomes a missing optimisation, and the query still answers correctly.

That is what made the 4115x regression invisible. It is also what made
`open-eq-02`'s `too many values to unpack` cost two wrong diagnoses earlier in
this same issue: the message surfaced with no location, and finding it needed a
hand-written probe that re-raised.

**This belongs to the fix, not to a separate ticket.** The constants key is
touched by a dozen call sites across nine modules; the next person to widen or
narrow it will hit exactly this again, and will get the same silence.

Minimum viable change: log the traceback at ERROR whenever generation catches,
including for the paths that recover. A degraded plan that logs nothing is
indistinguishable from a correct one until somebody benchmarks it.

Worth considering beyond that: make the OPTIONAL paths — stats collection,
selectivity gates, table rewrites — fail LOUDLY under test and quietly in
production, so a shape change like this one turns a suite red instead of
turning a benchmark slow. Every one of these three defects would have been
caught at the first `pytest tests/unit` had that been true.

## Pairwise determinacy IMPLEMENTED 2026-08-24 — and `open-eq-12` is a
## DIFFERENT bug

`_determinate_sql` replaces the per-operand `_comparable_sql`. It short-circuits
in the order the spec reasons: either side not a literal -> decidable; either
side language-tagged -> decidable; otherwise both need a usable VALUE, where
"usable" means a recognised datatype AND, for a numeric one, `num_col`
non-NULL (an ill-typed `"xyz"^^xsd:integer` is a valid term with no value).

`open-eq-08`, `-10` and `-11` pass. `open-eq-10` matches the corpus exactly —
52 of 52, nothing extra, nothing missing.

The measured diff is what made the rule obvious, and it is worth keeping
because it shows why per-operand CANNOT work:

    EXTRA    x5 (ill-typed integer) against strings  -> we said unequal,
                                                        corpus says error
    MISSING  x2/x3 (@en, @EN) against y6 (^^unknown) -> corpus says unequal,
                                                        we excluded

The SAME operand, `x5`, is indeterminate against a string and determinate
against a tagged literal. A per-operand verdict removes it from both.

### `open-eq-12` is NOT this rule — the OPTIONAL's variables are unresolved

    OPTIONAL { ?y :p ?v3 . FILTER( ?v1 != ?v3 || ?v1 = ?v3 ) }
    FILTER (!bound(?v3))

Expected 10, we return 64. I assumed the determinacy rule was not reaching
inside the OPTIONAL body. It is worse than that. The emitted LEFT JOIN reads:

    ON j0.v2__uuid = j1.v4__uuid
       AND ((NULL /* vg:unresolved-var ?v1 */ != NULL /* vg:unresolved-var ?v3 */)
         OR (NULL /* vg:unresolved-var ?v1 */ =  NULL /* vg:unresolved-var ?v3 */))

**Both variables emit as `vg:unresolved-var`.** `?v1` is bound on the LEFT side
and `?v3` on the right, and both should be in scope for a join condition. The
condition is therefore NULL, the LEFT JOIN matches nothing, `?v3` never binds,
and `!bound(?v3)` keeps every row — 64 of them.

That is a SCOPE defect in join-condition emission, not a semantics one. It
explains the missing type-error `CASE` as a symptom rather than a cause:
`_cmp_sql` never receives resolvable variables.

`issues/028` established a policy for unresolved variables — `_check_unresolved_vars`
raises when one was in scope and still failed to resolve. This case slips past
it, emitting a comment-annotated NULL into a JOIN CONDITION, where the effect
is not an error but a join that silently matches nothing.

**FIXED.** The ON clause now emits against a `ctx.child()` whose type registry
maps each variable to its OPERAND-qualified column — `j0.<sql_name>` for the
left side, `j1.<sql_name>` for the right. `open-eq-12` returns 10, matching the
corpus.

Two details that made this non-obvious:

* The output variables ARE registered on `ctx` — but further down, after the ON
  clause is built, and they name the join's OUTPUT columns. An ON clause has to
  reference the OPERANDS. Registering earlier would not have fixed it.
* A NULL join condition is not an error. It is a join that matches nothing, so
  `issues/028`'s unresolved-variable policy never fires. That is the same
  failure shape as the swallowed exception above: a defect that degrades the
  answer instead of raising.
