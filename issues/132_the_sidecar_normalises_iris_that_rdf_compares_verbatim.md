# The Sidecar Removes Dot-Segments From IRIs That RDF Compares Verbatim

## Status: OPEN — found 2026-08-25 finishing the sparql10 categories

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

## Options, none taken

1. **Leave it.** One conformance case; real IRIs rarely carry `/./` or `/../`.
   The cost is that a term that does carry them is unreachable by query, with
   no error.
2. **Fork Jena** to enable `strictResolver`. Correct, and a build-and-maintain
   burden for one constant.
3. **Ask upstream** whether `strictResolver` can become configurable. Cheapest
   real fix if accepted, and slowest.

## Related

- `issues/128` — the sparql10 sweep this closes out
## Related

- `issues/128` — the sparql10 sweep this closes out
