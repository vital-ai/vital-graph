# Two Upstream Jena Reports, Drafted and Not Yet Filed

## Status: OPEN — drafted 2026-08-25, needs someone to post them

Both were found while fixing `issues/132`. Neither blocks us — each is worked
around in `vitalgraph-jena-sidecar` — but neither is ours to keep carrying, and
the workarounds cost real code that would come out if these land.

Affected version: **Apache Jena 6.0.0** (`org.apache.jena:jena-arq:6.0.0`),
which is what the sidecar depends on. Both were read in the matching
`jena-main-source` tree.

File at <https://github.com/apache/jena/issues>.

---

## Report 1 — `QueryTransformOps.mutateExprList` reads index 0 while writing index i

**This one is unambiguous.** No design question, no spec reading required.

### The code

`jena-arq/src/main/java/org/apache/jena/sparql/syntax/syntaxtransform/QueryTransformOps.java`

```java
// ** Mutates the List
private static void mutateExprList(List<Expr> exprList, ExprTransform exprTransform) {
    for (int i = 0; i < exprList.size(); i++) {
        Expr e1 = exprList.get(0);        // <-- get(0), every iteration
        Expr e2 = ExprTransformer.transform(exprTransform, e1);
        if (e2 == null || e2 == e1)
            continue;
        exprList.set(i, e2);              // <-- but writes at i
    }
}
```

Every element is overwritten with the transform of the first.

### Reproduction

`mutateExprList` has exactly one caller — `q2.getHavingExprs()` — so it takes a
query with more than one HAVING condition, put through any transform that
actually changes something:

```java
Query q = QueryFactory.create(
    "SELECT ?s WHERE { ?s ?p ?o } GROUP BY ?s "
    + "HAVING (COUNT(*) > 1) (COUNT(*) < 3)");

Query q2 = QueryTransformOps.transform(q, someNodeTransform);
```

- **expected** `HAVING (> (count) 1) (< (count) 3)`
- **actual** `HAVING (> (count) 1) (> (count) 1)`

The second condition stops filtering, so the query returns rows it should not.
Silent — nothing errors.

### Why it stayed hidden

Three conditions have to hold at once: more than one HAVING condition, a
transform running at all, and a transform whose result differs from its input
(the `e2 == e1` guard skips the write otherwise). We only hit it once we began
transforming every query that carried a base.

### Suggested fix

`exprList.get(i)`. Compare `mutateSortConditions` directly below it, which uses
`get(i)` correctly.

---

## Report 2 — SPARQL parsing normalises absolute IRIs, and the code that would not is unreachable

**This one has a spec argument attached, so it needs stating carefully.**

### The behaviour

```java
Query q = QueryFactory.create(
    "PREFIX p: <eXAMPLE://a/./b/../b/c#> SELECT * { ?s <http://x#p> p:xyz }");
```

- **expected** `eXAMPLE://a/./b/../b/c#xyz`
- **actual** `eXAMPLE://a/b/c#xyz` — dot-segments removed

Same for a plain `<http://example/a/./b/../c>` written directly in a pattern.

### Why this is wrong for SPARQL

SPARQL 1.1 resolves **relative** IRIs against the base using RFC 3986 §5.2,
and states that **neither Syntax-Based nor Scheme-Based Normalization is
performed**. Path-segment removal is Syntax-Based Normalization, RFC 3986
§6.2.2.3. An absolute IRI is not combined with a base at all, so nothing
licenses rewriting it.

RDF compares IRIs by character, so this is not cosmetic: a query cannot match a
term whose IRI the data holds verbatim.

The DAWG test `data-r2/i18n/normalization-02` covers exactly this, and its data
deliberately includes BOTH spellings — the already-normalised one is **not** the
expected answer, so normalising both sides fails it in the other direction.

**Note on RFC 3986 §5.2.2**: its strict/non-strict distinction is about whether
a parser may ignore a scheme identical to the base's, and under RFC strictness a
scheme-bearing reference is still transformed, dot-segments included. So the
RFC alone does not settle this — SPARQL's prohibition on syntax-based
normalization does.

### Where it comes from

Two things compound:

1. `QueryFactory.parse` substitutes `IRIs.getSystemBase()` when no base is
   given, which is the **process working directory**. So a caller who supplied
   no base still gets one, and it depends on where the JVM was started.
2. Once any base is set, `QueryParserBase.resolveIRI` sends every IRI through
   `IRIx.resolve`.

### The code that would be correct is present and unreachable

`IRI3986.resolve`:

```java
private static final boolean strictResolver = false;
...
if ( strictResolver && !other.isRelative() ) {
    return other;                       // absolute reference, unchanged
}
```

and `AlgResolveIRI`:

```java
public static IRI3986 resolve(IRI base, IRI reference) {
    return transformReferencesNonStrict(reference, base);   // always
}

private static IRI3986 transformReferencesStrict(IRI reference, IRI base) {
    if ( reference.hasScheme() )
        return RFC3986.create(reference);
    return transformReferencesNonStrict(reference, base);
}
```

`transformReferencesStrict` is private and has exactly one occurrence in the
tree: its own declaration. `strictResolver` is a `private static final false`
with no setter, no system property and no context symbol. Neither is reachable
from outside, and no comment, linked issue or test records why either is off.

### What would help

Any one of:

- make the strict path selectable (a context symbol would be enough for us);
- skip resolution for references that already carry a scheme, at least under
  SPARQL parsing;
- or, smallest and independently useful: stop substituting the working
  directory as base when the caller gave none, so that resolution only happens
  when someone asked for it.

### Our workaround

The sidecar parses via `SPARQLParser` directly, skipping the base-substituting
block, and resolves relative IRIs itself afterwards against a caller-supplied
base — applying it only to IRIs with no scheme. See `issues/132`.

---

## Related

- `issues/132` — where both were found, and how each is worked around
- `planning/planning_sparql_features/iri_resolution.md` — the design
