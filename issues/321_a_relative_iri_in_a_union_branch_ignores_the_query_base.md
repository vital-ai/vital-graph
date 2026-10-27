# 321 — A relative IRI in a UNION branch ignores the query's BASE

## Status: FIXED 2026-10-27, on the default path. Open until the vg test stack runs the full suite on the rebuilt image.

## Defect

On the default path, which production runs:

```sparql
BASE <http://example.org/b/>
SELECT ?i WHERE { { ?s ex:p ?o BIND(IRI("x") AS ?i) } UNION { ?s ex:p ?o BIND(IRI("y") AS ?i) } }
```

This answered `<x>` and `<y>`. They should be `<http://example.org/b/x>` and `<http://example.org/b/y>`.

`EmitContext.child()`, the context a UNION branch (and other nested emission) is emitted in, did not
copy `base_uri`. So `IRI()` / `URI()` there resolved against nothing. The EXISTS body's context set it
explicitly, and the top level had it. A sub-SELECT was not affected in the shapes tested.

## How it was found

The qtree planner, once it planned queries with no pattern: its value levels are child contexts, and
W3C `iri01` (`BASE <http://example.org/> SELECT (URI("uri") AS ?uri) ...`) answered `<uri>`.

## Fix

`EmitContext.child()` passes `base_uri` on.

## Test

`tests/integration/test_base_iri_in_nested_scopes.py` covers IRI() in a UNION branch, in a sub-SELECT,
and at the top level. The UNION branch answered unresolved IRIs before the fix.
