# Term Typing Is Decided Three Ways, and They Disagree

## Status: OPEN — audited 2026-08-25. Three defects, all silent, all in stored data.

`term_uuid` is a UUIDv5 over `(text, type, lang, datatype)`. So a disagreement
about a term's TYPE is not a cosmetic inconsistency — it produces a **different
term**, and the write and read paths address different rows.

## The three mechanisms

| | how it decides | where |
|---|---|---|
| `_ensure_term` | by rdflib class; **`else 'U'`** | the two insert paths |
| `_infer_type(str)` | by string prefix; only `http`/`https`/`urn` are URIs | `remove_rdf_quad`, `get_rdf_quad`, `remove_rdf_quads_batch` |
| hardcoded `'U'` | unconditionally | ~20 call sites, all s/p/g positions |

Inserts type **by class**. Reads and deletes type **by string**. They agree only
where the string happens to start with `http`, `https` or `urn`.

## Measured

Computed over the term key, so no database is involved — this is arithmetic.

| value | insert | remove/get (object) | remove/get (s,p,g) | reachable |
|---|---|---|---|---|
| `URIRef http://x/a` | U | U | U | yes |
| `URIRef file:///tmp/g.ttl` | U | **L** | U | **no, as object** |
| `URIRef ftp://x/a` | U | **L** | U | **no, as object** |
| `URIRef mailto:a@b` | U | **L** | U | **no, as object** |
| `BNode b1` | B | **L** | **U** | **no, anywhere** |
| `Literal "plain text"` | L | L | — | yes |
| bare `str` `"plain text"` | **U** | L | — | **no** |

## Three defects

### 1. A URI whose scheme is not http/https/urn cannot be removed or fetched

`_infer_type` recognises exactly three schemes. Everything else falls to `'L'`.
So `file://`, `ftp://`, `mailto:`, `did:`, `tag:`, `s3://` — anything — is
inserted as a URI and looked up as a literal. `remove_rdf_quad` computes a uuid
nothing was stored under, matches no row, and **returns without complaint**.

`file://` is not hypothetical: it is the scheme the DAWG harness uses for every
graph URI.

### 2. `_infer_type`'s blank-node branch is dead code

    if value.startswith('_:'):
        return 'B'

`issues/065` settled that `term_text` holds the BARE label — a blank node is
stored `b1`, never `_:b1`, so that export does not double the prefix. And
`str(BNode("b1"))` is `'b1'`. So the branch can only fire for a caller who
hand-writes the prefix, which the convention says nobody does.

Measured: `_infer_type(str(BNode("b1")))` is `'L'`.

A blank node is therefore inserted `'B'` and looked up `'L'` in the object
position, or `'U'` in subject/graph. Unreachable either way. This is
`named_graph_semantics` §4.5, which found the graph case — the audit shows it
is every position, not just the graph.

### 3. `_ensure_term` types an unknown Python type as a URI

    if isinstance(term, URIRef):  term_type = 'U'
    elif isinstance(term, BNode): term_type = 'B'
    elif isinstance(term, Literal): term_type = 'L'
    else: term_type = 'U'          # <- a bare str lands here

A caller passing a plain Python string as an object gets a URI-typed term
holding arbitrary text. Found already, from the side:
`test_short_needle_probe_is_bounded` stored `"entity 3 (Topic)"` as a URI and
its `CONTAINS` matched it only because the push-down ignored term kind. The
fixture was fixed; the write path that permitted it was not.

`'L'` is the better default — an unknown type is far more likely to be a value
than an identifier — but changing it alters term identity for anything already
stored that way, so it needs the same migration thinking as `issues/131`.

## Why this stayed invisible

Every failure is a **silent no-op or a silent miss**. Nothing errors, nothing
logs. `remove_rdf_quad` reports success having removed nothing.

Both instances found so far were found sideways: the blank-node graph case came
out of writing a test for something the planning doc called "likely wrong, low
impact", and the bare-string case out of making `CONTAINS` respect term kind for
a conformance failure. Neither was anyone's hypothesis, and neither would have
been found by looking for it.

## What a fix has to settle

1. **One mechanism.** The read/delete paths take strings, so they cannot know
   what a caller meant. Either they take terms, or the string convention becomes
   authoritative and `_ensure_term` follows it instead.
2. **`_infer_type`'s scheme list.** A prefix test cannot be right — RFC 3986
   allows any scheme. If strings stay, the test should be for a scheme
   (`^[A-Za-z][A-Za-z0-9+.-]*:`), which is the same check the sidecar now uses
   for relative IRIs (`issues/132`).
3. **The bare-label convention vs `_:`.** `_infer_type` and `issues/065`
   disagree about what a blank node looks like in a string. One of them is
   wrong.
4. **Migration.** Any change to typing changes `term_uuid`, so existing rows
   move. Same shape as `issues/131`, and it should probably be decided with it.

## Related

- `named_graph_semantics` §4.5 — the graph-position instance, with tests
- `issues/065` — the bare-label convention `_infer_type` predates
- `issues/131` — blank node labels not document-scoped; the same migration question
- `issues/132` — where the scheme regex above already exists
