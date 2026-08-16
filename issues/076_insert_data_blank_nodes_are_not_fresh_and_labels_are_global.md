# `INSERT DATA` Blank Nodes Are Not Fresh, And Labels Are Globally Scoped

## Status: RESOLVED 2026-08-16 — all three facets; scoping decided as skolemisation

Facet 1 — `INSERT DATA` allocates fresh labels through a request-scoped map,
the mechanism `construct.py` already used for CONSTRUCT templates. Repeats of
one label within a request stay one node; nothing across requests collides. The
allocated label carries a random salt rather than a counter, because a
per-request counter restarts at 1 and would collide across requests — the bug
reintroduced by the obvious implementation, so there is a test for it.

Facet 1b — `DELETE DATA` rejects blank nodes, with an error naming
`DELETE WHERE` as the alternative.

Facet 2 — DECIDED: **option 2, skolemisation**, which RDF 1.1 Concepts §3.5
recommends directly ("SHOULD mint a new, globally unique IRI", using the
registered `genid` well-known name) rather than being one option among three.
Checked against another implementation: RDF4J's `PRESERVE_BNODE_IDS` defaults to
**false**, so fresh-per-parse is the industry default and preserving labels is
the opt-in — this store did the opposite and offered no choice.

Implemented as DETERMINISTIC skolemisation over `(document scope, label)`, which
is the part neither listed option gave alone: different documents produce
different nodes as RDF requires, AND re-importing one document reproduces its
nodes, so reload stays idempotent (`issues/041`). Random per-load allocation
satisfies the first and breaks the second.

`term_type` stays `'B'`: that is what makes `isBlank()` work, tells serializers
to emit `_:`, and lets the derived tables skip these rows. As `'U'` they would
be indistinguishable from real IRIs and would flow into the edge model.

`term_text` holds the bare LABEL, not the Skolem IRI — `BLANK_NODE_LABEL` admits
neither `:` nor `/`, so storing the IRI would export as
`_:http://.../genid/abc`, which no parser reads back. The IRI form is rendered
on demand and read back on import, so an exported blank node round-trips.

Scope is graph URI plus source basename, not the full path: the same file
imported from a different directory is the same document.

REMAINING: the JSONL importer passes a scope; other ingest paths do not yet, and
fall back to the raw label.

The derived-table question is now MEASURED, and the answer is the opposite of
what this issue assumed. `tests/integration/test_derived_tables_blank_nodes.py`:
the edge table DOES project a blank-node endpoint. Nothing in sync_edge_table
filters on term_type, and dest_node_uuid is a plain uuid column with no type
beside it. frame_entity is unaffected, as connector frames are keyed on entity
slots a blank node cannot carry.

Projecting it is defensible — an edge to a blank node is an edge, and dropping
it would make the edge table an incomplete mirror of rdf_quad, the failure mode
issues/041 exists to prevent. What it means is that a consumer treating an edge
endpoint as a dereferenceable URI can be handed a blank node. Recorded as an
assertion so changing it is deliberate.

Two facets of one root cause: **a blank node's identity in this store is its
label, forever, everywhere.**

`term_uuid` is a deterministic UUIDv5 over `(term_text, term_type, lang,
datatype_id)`. For a blank node that reduces to the label. There is no
skolemization, no per-document scope, and no allocation step — the label *is*
the key.

## Facet 1: `INSERT DATA` must allocate fresh blank nodes

SPARQL 1.1 §19.6: blank nodes in an `INSERT DATA` block are **fresh** — they
must not merge with blank nodes already in the store, and each execution of the
operation introduces new ones.

We merge. Running

    INSERT DATA { _:b1 :p 1 }

twice writes the same node both times, so the store holds one blank node with
one triple where the spec requires two blank nodes with one triple each. It
will also merge with any `_:b1` that arrived from an unrelated import.

`emit_update.py` has no label-allocation step; `_node_text` (`:169`) passes the
parsed label straight through to `_term_upsert` / `_term_uuid_subquery`.

**Fix:** allocate a fresh label per blank node per UPDATE request, before term
creation — rewrite the parsed `BNodeNode` labels through a request-scoped map
(`_:b1` → `b{request_id}_1`). This is the same mechanism `construct.py:53-61`
already implements correctly for CONSTRUCT templates; that code is the model to
follow.

## Facet 1b: `DELETE DATA` must *reject* blank nodes

The mirror rule: SPARQL 1.1 forbids blank nodes in `DELETE DATA` entirely
(there is no way to name an existing blank node in a data block). `_delete_data_sql`
(`emit_update.py:477`) does no such validation — it will build a lookup on the
label and delete whatever happens to match. Combined with `issues/065`'s prefix
divergence, what it matches is unpredictable.

**Fix:** reject `DELETE DATA` containing a blank node with a clear error at
validation time.

## Facet 2: labels are global, so cross-document loads merge

RDF scopes blank-node labels to a document. Loading two files that each use
`_:b0` should produce two distinct nodes; here it produces one, silently
merging unrelated structures. Same for two REST inserts, or an import followed
by a SPARQL UPDATE.

This has never bitten us because we do not ingest blank nodes at volume —
every VitalGraph KG object has a URI. It is nonetheless a silent
data-corruption path for any third-party RDF import, and the corruption is
unrecoverable after the fact: once merged, nothing records that the two nodes
were ever separate.

**This needs a decision, and it should be made before the first blank-node-heavy
import, not after.** Options:

1. **Per-load label mangling at parse time** — prefix each label with a load or
   document id (`{load_id}:{label}`) so scoping matches RDF semantics.
   Cheap, local to the parser, and makes labels opaque (which they already are
   to any correct consumer). Downside: labels churn across reloads, so a
   re-import of the same file produces different nodes — which is exactly what
   RDF says should happen, but breaks idempotent reload
   (cf. `issues/041`).
2. **Skolemize on ingest** — map each blank node to a `urn:` / well-known IRI at
   load, de-skolemize on export. Makes blank nodes ordinary URIs internally, so
   every downstream path (derived tables, DESCRIBE, edge model) just works.
   Bigger change, and export fidelity needs care.
3. **Document the global scoping as intended and accept the merge.** Defensible
   *only* if we commit to not importing third-party blank nodes. If chosen,
   record it in `planning/planning_sparql_features/blank_nodes.md` §4.4 and add
   a load-time warning when a label collides with an existing one.

(1) is the smaller change; (2) is the one that makes the rest of the system
stop having blank-node special cases at all — note that skolemization would
also dissolve `issues/065`, most of `issues/067`, and the derived-table
question below.

## Interaction with the derived tables

The edge and frame_entity tables model URI-based binary relations. A blank node
in a subject or object position has no representation there. Confirm that
`sync_edge_table_*` / `rewrite_edge_table` **skip** blank-node rows rather than
mis-projecting them — and note that per `issues/064` the SPARQL UPDATE path
does not maintain those tables at all, so an `INSERT DATA` with a blank node is
doubly outside the maintained world.

## Related

- `planning/planning_sparql_features/blank_nodes.md` §4.3, §4.4
- `issues/065` — prefix convention; same write path
- `issues/067` — `BNODE()` freshness, the query-side version of facet 1
- `issues/064` — SPARQL UPDATE bypasses derived-table maintenance
- `issues/041` — in-place reload leaves derived tables stale (option 1 above
  makes reload non-idempotent for blank nodes, which interacts with this)
- `issues/069` — no test would catch any of it
