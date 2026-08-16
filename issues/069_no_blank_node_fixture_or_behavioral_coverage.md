# No Fixture Contains a Blank Node, So Nothing Tests Blank-Node Behavior

## Status: RESOLVED 2026-08-16 — fixture added, tests 1-12 covered

`tests/fixtures/blank_nodes.nt` (13 triples, 6 blank nodes: subject position,
object position, the same node in BOTH, two distinct labels to catch collapse,
and an `rdf:first`/`rest` collection) and `blank_nodes_collide.nt`, which reuses
the same labels so facet 2 of `issues/076` is testable.

Confirmed from the data side as well: **0 blank-node terms across 85 spaces on
two clusters**. Nothing in production exercised these paths either.

Covered so far, at unit level:
  * 3 — `VALUES` with a blank node (`test_emit_table.py`, rewritten)
  * 4, 5 — `BNODE()` freshness and result shape (`test_emit_expressions.py`,
    rewritten)
  * 6, 7 — `INSERT DATA` freshness and `DELETE DATA` rejection
    (`test_update_blank_nodes.py`)
  * 8 — cross-document collision, now that `issues/076` facet 2 is decided
    (`test_term_normalize.py`)
  * 1, 2 — write/read round-trip and load/UPDATE agreement are covered at the
    identity level (one term uuid whatever the write path), NOT yet end to end
    through a loaded space.

9, 10 and 12 are done:
  * 9, 10 — `tests/unit/sparql_sql/test_blank_node_query_paths.py` (anonymous
    variables are not projected; §15.1 term ordering, including that DESC
    reverses every component rather than only the value).
  * 12 — `tests/integration/test_derived_tables_blank_nodes.py`, which found
    the opposite of what issues/076 assumed: the edge table DOES project a
    blank-node endpoint.

1, 2 and 11 now run end to end through a real space
(`tests/integration/test_blank_node_roundtrip.py`):

  * 1 — a blank node written through the batch path is stored with a BARE
    label and reads back with its type intact.
  * 2 — the expected outcome CHANGED while this was open. The issue framed it
    as "load `_:b1`, then DELETE DATA the same triple; currently deletes
    nothing". SPARQL forbids a blank node in DELETE DATA at all, so the correct
    behaviour is refusal, not a successful delete. The test asserts refusal and
    accepts it from EITHER layer — the sidecar parser rejects the construct
    outright, and emit_update guards it as well.
  * 11 — DESCRIBE returns the subject's triple with its blank-node object (bare
    label, type `bnode`) and NOT the blank node's own triples. The documented
    forward, non-recursive CBD, pinned so changing `_describe_triples` is
    deliberate.

Writing 11 turned up an unrelated defect: the sidecar client formatted a DEBUG
log line with `data.get("input", {}).get(...)`, and on an ERROR response that
key is present with value null — so `.get(k, {})` returned the null and the log
call raised AttributeError, crashing the request and replacing the sidecar's
parse error with a traceback about NoneType. Fixed at both sites.

`issues/065`, `066`, `067` and `076` are four blank-node defects — a divergent storage
convention, a hard crash on `VALUES`, a spec-violating `BNODE()`, and merged
identities on `INSERT DATA`. Three of the four are in code that has unit tests.
All four survived because **not one test fixture in this repo contains a blank
node**, so no test ever exercises the paths end to end.

Every VitalGraph KG object has a URI, so our fixtures are URI-only by
construction. That is the right shape for testing what we actually store — and
it is exactly why the blank-node paths are the least-trodden code in the
backend while still being reachable from any SPARQL query or any third-party
import.

## What coverage exists today

| Layer | File | What it actually proves |
|---|---|---|
| Unit | `tests/unit/sparql_sql/test_construct_template.py:113,123,132` | CONSTRUCT §16.2 freshness — genuinely good, and the reason `construct.py` is the one correct blank-node implementation |
| Unit | `tests/unit/sparql_sql/test_emit_expressions.py:173,429` | a constant emits `'_:b0'`; `isBlank` → `type_col = 'B'` |
| Unit | `tests/unit/sparql_sql/test_emit_expressions.py:637,642` | **asserts the `BNODE()` bug** (`issues/067`) |
| Unit | `tests/unit/sparql_sql/test_emit_table.py:81` | **passes only by patching `.value` onto the node** (`issues/066`) |
| Integration | `tests/integration/test_construct_describe.py:99` | CONSTRUCT freshness end to end |
| API | `tests/api/test_sparql_api.py:488` | asserts subject type is `uri` **or** `bnode` — a type check, not a behavior test |
| Conformance | `tests/conformance/test_dawg_sql_v2.py`, `test_dawg_update_sql_v2.py` | the broadest real coverage; results compared up to blank-node isomorphism by `dawg_test_impl/dawg_result_comparator.py:119` |

Two of these tests encode the defects rather than catching them. That is worse
than no coverage: it makes the fix look like a regression.

Everything above is query-side. **There is no test anywhere that writes a blank
node and reads it back** — which is precisely where `065`, `066`, and `076`
live.

## Sample data to add

A single small fixture unblocks most of the missing tests. Proposed
`tests/fixtures/blank_nodes.nt` (or the N-Quads equivalent if named-graph
coverage is wanted):

- a subject blank node with two triples — proves within-node consistency;
- an object blank node reachable from a URI subject — the DESCRIBE case;
- a blank node appearing in **both** subject and object position — proves the
  two positions resolve to one term row;
- two blank nodes with distinct labels, to catch collapse;
- an RDF collection (`( :a :b :c )`), which desugars to an `rdf:first`/`rdf:rest`
  chain of blank nodes — this doubles as the seed fixture for the RDF-lists
  entry in `planning/planning_sparql_features/README.md` §2;
- **a second file reusing the same labels** (`blank_nodes_collide.nt`), which is
  the only way to test the label-scoping decision in `issues/076` facet 2.

Keep it tiny — a dozen triples. The point is reaching the code paths, not
volume. Cross-reference
`issues/050_fixtures_cannot_express_the_dominant_production_shape.md`: that
issue is about fixtures not matching production; this one is the complement —
fixtures not covering what production *doesn't* contain but the API still
accepts.

## Tests to write

Ordered so that each one would have caught a specific open issue.

1. **Write/read round-trip** — `INSERT DATA { _:b1 :p :o }`, query it back,
   export it. Asserts `term_text` has no `_:` and the export has exactly one.
   → catches `issues/065`.
2. **Load/UPDATE agreement** — load `_:b1` from N-Triples, then `DELETE DATA`
   the same triple through SPARQL UPDATE. Currently deletes nothing.
   → `issues/065`.
3. **`VALUES` with a blank node** — `SELECT ?x WHERE { VALUES ?x { _:b0 } }`
   must generate SQL rather than raise. Rewrite the existing unit test to build
   a plain `BNodeNode(label="b0")` with no attribute patching.
   → `issues/066`.
4. **`BNODE()` freshness** — over ≥2 rows, ≥2 distinct labels; and
   `BNODE("x")` twice in one solution agrees.
   → `issues/067`.
5. **`BNODE()` result shape** — no binding value begins with `_:`.
   → `issues/067`.
6. **`INSERT DATA` freshness** — run the same insert twice; expect two blank
   nodes, not one.
   → `issues/076`.
7. **`DELETE DATA` with a blank node** — expect a clear rejection.
   → `issues/076`.
8. **Cross-file label collision** — load both fixture files; assert whatever
   `issues/076` facet 2 decides. Write this test *after* the decision, and let
   it encode the decision.
   → `issues/076`.
9. **Anonymous blank nodes in patterns** — `SELECT ?s WHERE { ?s :p [] }` and
   the `DISTINCT` variant must not leak the anonymous variable into results.
   The projection-injection logic at `generator.py:556-582` has no direct test,
   and its `DISTINCT` handling (project *under* the dedup) is subtle enough to
   deserve one.
10. **Term ordering** — `ORDER BY` over a mix of unbound, blank node, IRI, and
    literal must follow the order asserted at `emit_group.py:238`.
11. **DESCRIBE with a blank-node object** — pin the documented
    forward-non-recursive-CBD behavior (a dangling stub) so that changing
    `_describe_triples` is a deliberate act.
    → `planning/planning_sparql_features/blank_nodes.md` §4.5.
12. **Derived tables skip blank nodes** — after loading the fixture, the edge
    and frame_entity tables must contain no blank-node-derived rows.
    → `issues/076`, `issues/064`.

Tests 1–8 need the fixture; 9–10 are pure unit tests and can be written
immediately.

## Note on the two bug-asserting tests

`test_emit_expressions.py:637,642` and `test_emit_table.py:81` must be rewritten
as part of `issues/067` and `issues/066` respectively — not adjusted to the new
output. Both currently describe the implementation; the replacements should
describe the spec, so they keep their value when the implementation changes
again.

## Related

- `planning/planning_sparql_features/blank_nodes.md` §5, §6
- `issues/065`, `066`, `067`, `068` — the defects this gap concealed
- `issues/050` — the complementary fixture problem
