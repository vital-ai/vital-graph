# The Sidecar Removes Dot-Segments From IRIs That RDF Compares Verbatim

## Status: FIXED 2026-08-25 (`75b0e42`, `281f181`) — found finishing the sparql10 categories

`sparql10/i18n/normalization-02` returns nothing where the corpus expects one
row, and the cause is upstream of the SQL pipeline entirely.

## Measured

    PREFIX p1: <eXAMPLE://a/./b/../b/%63/%7bfoo%7d#>
    SELECT ?S WHERE { ?S :p p1:xyz }

against

    :s1 :p <example://a/b/c/%7Bfoo%7D#xyz>.          # already normalised
    :s2 :p <eXAMPLE://a/./b/../b/%63/%7bfoo%7d#xyz>. # as written

Expected: **s2 only**. We return nothing.

| stage | IRI |
|---|---|
| Jena expands `p1:xyz` to | `eXAMPLE://a/b/%63/%7bfoo%7d#xyz` |
| pyoxigraph stores s2 as | `eXAMPLE://a/./b/../b/%63/%7bfoo%7d#xyz` |

Jena applies RFC 3986 `remove_dot_segments` — `/./b/../b/` becomes `/b/` — and
leaves the scheme case and percent-encoding case alone. The loader stores the
data IRI byte-for-byte. The two can never be equal, so the constant matches no
term and the query answers empty.

Note s1 is NOT the expected answer either. The test's whole point is that RDF
does **not** normalise: `s1` and `s2` are different IRIs and must stay so. A
normalisation that mapped both to one form would fail this test just as surely,
in the other direction.

## Why this is not a SQL-pipeline bug

By the time `generate_sql` sees the query the constant is already normalised.
Nothing downstream can recover the original characters. Term matching is
working exactly as it should — it is being handed a different IRI from the one
the query wrote.

## Scope — measured 2026-08-25, wider than first filed

This was filed as a PNAME-expansion problem, with `<...>` IRIs left unchecked.
Checked now: **every IRI in a query is affected**, and exactly one
transformation is applied.

| input | output |
|---|---|
| `<http://example/a/./b/../c>` | `http://example/a/c` — **dot-segments removed** |
| `<http://example/a/b/c>` | unchanged |
| `<eXAMPLE://a/b/c>` | unchanged — scheme case preserved |
| `<http://example/%7bfoo%7d>` | unchanged — percent-encoding case preserved |

So the blast radius is narrow but not confined to prefixes: any query IRI
containing `/./` or `/../` is rewritten before the SQL pipeline sees it, and
can never match a term stored with those segments. Everything else about the
IRI is left alone.

## Mechanism, traced

    QueryFactory.create(sparql)          no base argument
      -> QueryFactory.parse              `if (query.getBase() == null)` ->
                                         `IRIs.getSystemBase()`, which is the
                                         PROCESS WORKING DIRECTORY -- in the
                                         container, `file:///app/`
      -> QueryParserBase.resolveIRI      returns early only when the prologue
                                         base is null; it never is, because of
                                         the step above
      -> IRIx.resolve -> IRI3986.resolve

and there:

    private static final boolean strictResolver = false;
    ...
    if ( strictResolver && !other.isRelative() ) {
        // RFC 3986 section 5.2.2
        return other;        // absolute IRI returned UNCHANGED
    }

**The behaviour the corpus expects is implemented in Jena, twice, and neither
copy is reachable.** `strictResolver` is a `private static final` constant with
no setter, no system property and no context symbol. One layer down,
`AlgResolveIRI` carries the same choice:

    public static IRI3986 resolve(IRI base, IRI reference) {
        return transformReferencesNonStrict(reference, base);   // always
    }

    private static IRI3986 transformReferencesStrict(IRI reference, IRI base) {
        if ( reference.hasScheme() )
            return RFC3986.create(reference);                   // unchanged
        return transformReferencesNonStrict(reference, base);
    }

`transformReferencesStrict` is private and has exactly one occurrence in the
whole Jena tree: its own declaration. Nothing calls it.

**Why either is disabled is not recorded.** No comment, no linked issue, no
test exercising the strict path. The vendored tree here is a source drop with
no git history, so this cannot be answered from what we have -- it needs Jena's
own history or mailing list. Calling it a deliberate trade-off would be
inventing a reason.

## Why it cannot simply be switched on

The sidecar depends on the released `org.apache.jena:jena-arq:6.0.0`. The
`jena/jena-main-source` tree in this repository is reference source, not a
build input, so reading it does not mean we can patch it. Turning the flag on
would mean forking and building Jena.

Nor can the base be withheld: `QueryFactory.parse` substitutes the system base
whenever none is given, so the `getBase() == null` early return in
`resolveIRI` is unreachable through that API.

## Who is right

A correction to the first draft of this issue, which called the disabled branch
"the RFC-conformant path". It is not, and the naming invites that mistake.

RFC 3986 §5.2.2's strict/non-strict distinction is about ONE thing: whether a
parser may ignore a scheme in the reference when it is identical to the base's.
Under RFC strictness a scheme-bearing reference is still transformed, and that
transform includes `remove_dot_segments`:

    if defined(R.scheme) then
       T.scheme = R.scheme;
       T.path   = remove_dot_segments(R.path);

So RFC 3986 removes dot-segments either way. Jena's "strict" branch returns the
reference untouched, which is STRONGER than RFC strictness rather than equal to
it.

What actually supports the corpus is SPARQL, not RFC 3986. SPARQL 1.1 resolves
**relative** IRIs against the base using only §5.2's basic algorithm, and states
that neither Syntax-Based nor Scheme-Based Normalization is performed --
path-segment removal being Syntax-Based Normalization, §6.2.2.3. An absolute
IRI is not combined with anything, so nothing licenses rewriting it. That is
the reading every implementation passing this test uses, and the one Jena's
unreachable branch happens to implement.

Note that `s1` in the test holds the ALREADY-NORMALISED spelling and is
deliberately **not** the expected answer. So "normalise both sides" fails this
test too, in the other direction. The corpus is asserting that the two IRIs are
distinct and must stay so, which is the RDF position: IRIs are compared by
character, not by URI equivalence.

## Fixed in the sidecar, `75b0e42`

We own the sidecar, so the fix went there rather than waiting on Jena.

`SparqlCompiler` now parses through `SPARQLParser` directly, skipping the
block in `QueryFactory.parse` that substitutes a base. `resolveIRI` returns
the string untouched when the prologue has none, so nothing is resolved that
the caller did not ask to have resolved.

| | before | after |
|---|---|---|
| `<eXAMPLE://a/./b/../b/c>` | `eXAMPLE://a/b/c` | **preserved** |
| default base | `file:///app/` | `None` |
| `FROM <data-g1.ttl>`, no BASE | `file:///app/data-g1.ttl` | stays relative |
| `FROM <data-g1.ttl>` + explicit BASE | resolved | resolved, unchanged |

A `BASE` written IN the query still behaves exactly as before. Four tests in
`SparqlCompilerTest` pin all four rows; the sidecar suite is 59 passing, and
conformance/unit/integration are clean against the rebuilt image.

The working-directory base was the more consequential half. It meant a
relative IRI in any production query resolved against wherever the service
happened to run — environment-dependent, undocumented, and nothing would have
reported it.

## Closed — `281f181`

The remaining half was our own harness. The DAWG runner prepended
`BASE <file://…>` to every query so relative graph names resolve
(`named_graph_semantics` §4.1), and a prologue is a parse-time switch: it
resolves relative IRIs, which §4.1 wanted, and normalises absolute ones, which
is this issue. The two fixes made this week worked against each other.

`CompileRequest.baseURI` replaces it. The parse stays base-less; a post-parse
pass resolves only IRIs with no scheme. An in-query `BASE` still wins, because
it applies during the parse and those IRIs are already absolute by then.

Three sites a plain `NodeTransform` does not reach, each found by a failing
test rather than by reading the code:

- **VALUES data** — `ElementTransformSubst.transform(ElementData)` renames
  variables and passes values through, short-circuiting when no variable
  changes (always, for an IRI transform).
- **The top-level VALUES clause**, which hangs off the `Query`. No test pointed
  at this one; found by asking where else bindings live after the first fix.
- **HAVING** — `QueryTransformOps.mutateExprList` reads `get(0)` while writing
  `set(i)`, so every condition becomes the transform of the first.

`sparql10/i18n/normalization-02` now passes rather than xfails, and
`XFAIL_SQL_V2_EXEC` is empty.

## Upstream: two Jena issues worth reporting

1. **`IRI3986.strictResolver` is a hardcoded `false`**, and
   `AlgResolveIRI.transformReferencesStrict` is private with no callers, so the
   behaviour SPARQL requires is unreachable. Why is not recorded anywhere. The
   argument to make is SPARQL's, not RFC 3986's: §5.2.2 removes dot-segments
   under strictness too, but SPARQL forbids syntax-based normalization outright.
2. **`QueryTransformOps.mutateExprList` has an index error.** Unambiguous, no
   design question attached.

Neither is blocking us now — (1) is worked around by withholding the base and
(2) by redoing the list — but both are real and neither is ours to keep
carrying.

## Related

- `issues/128` — the sparql10 sweep this closes out
## Related

- `issues/128` — the sparql10 sweep this closes out
