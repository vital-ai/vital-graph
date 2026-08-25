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

### 2. A blank node is reachable only in the object position, and only if the caller spells it `_:b1`

**Corrected 2026-08-25** — the first draft of this issue called
`_infer_type`'s `_:` branch dead code. It is not. `_generate_term_uuid`
normalises internally (`issues/065`), so `U("_:b1", "B") == U("b1", "B")`, and
a caller who writes the prefix does reach the stored term.

Measured, against the term the insert path writes:

| caller writes | object position | subject / predicate / graph |
|---|---|---|
| `_:b1` | infers `'B'` — **reaches it** | forced `'U'` — misses |
| `b1` | infers `'L'` — misses | forced `'U'` — misses |

So there are two separate problems, not one:

- **The bare spelling misses.** `str(BNode("b1"))` is `'b1'`, so any caller
  passing an rdflib blank node through `str()` — the obvious thing to do —
  silently misses. That is what `named_graph_semantics` §4.5's test does.
- **s/p/g cannot reach a blank node at all.** Those positions are hardcoded
  `'U'`, so no spelling works. Blank nodes are legal RDF subjects and N-Quads
  graph names, so this is a real hole rather than a rejected input.

The object position is the only one that works, and only for one of the two
spellings a caller might reasonably use.

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

## Proposed solution

### The shape of it

**One decision point, and it takes a TERM rather than a string.**

The read/delete paths cannot type a bare string correctly, because a bare
string is genuinely ambiguous — `"b1"` is a blank node label or a literal, and
nothing in the characters says which. No amount of inference fixes that; it is
missing information, not a wrong rule. So the fix is to stop inferring where
the caller already knows.

    def term_key(term) -> tuple[str, str, str | None, int | None]:
        '''(text, type, lang, datatype_id) for an rdflib term. The ONLY place
        a term's type is decided.'''

`_ensure_term`, `remove_rdf_quad`, `get_rdf_quad` and
`remove_rdf_quads_batch` all route through it. `_infer_type` becomes a
string-to-term PARSER used only at the API boundary, where a caller has
supplied text and something must interpret it.

### Three changes, in dependency order

**1. `_infer_type` tests for a scheme, not for three of them.** RFC 3986 allows
any scheme, and the check already exists in the sidecar for exactly this
purpose (`issues/132`):

    ^[A-Za-z][A-Za-z0-9+.-]*:

This alone closes defect 1 — `file://`, `ftp://`, `mailto:`, `did:` and every
other scheme start round-tripping. It is the smallest change with real value
and it needs no migration: nothing currently stores those as `'L'`, because the
insert path always typed them `'U'`. **Do this first and separately.**

Note it changes what a literal whose text merely looks like a URI infers to.
That is the ambiguity above, and it is why this must not be the whole fix.

**2. s/p/g stop being hardcoded `'U'`.** They take the parsed type like the
object position does. Blank nodes are legal RDF subjects and N-Quads graph
names; today no spelling reaches one. Closes defect 2 and
`named_graph_semantics` §4.5.

**3. `_ensure_term`'s `else` branch becomes an error, not `'U'`.** An unknown
Python type is a caller mistake, and guessing "URI" is the worst available
guess — it silently stores arbitrary text as an identifier, which is how
`test_short_needle_probe_is_bounded` came to hold `"entity 3 (Topic)"` as a
URI. Raising turns a silent data defect into a stack trace at the call site.

`'L'` is the tempting alternative and is wrong for the same reason `'U'` is:
it guesses. The difference is only that it guesses better.

### What this does NOT change

**Nothing already stored moves.** That is the point of the ordering. Steps 1
and 2 only make previously-unreachable terms reachable — they change what a
LOOKUP computes, never what an INSERT writes, so no existing `term_uuid`
changes and no migration is needed.

Step 3 changes nothing stored either; it rejects a call that currently
succeeds. That is a breaking API change for any caller passing bare strings,
and the audit cannot say how many there are — worth a sweep before it lands.

This is deliberately unlike `issues/131`, which cannot avoid moving term
identity. These two should NOT be bundled: bundling them would put a
no-migration fix behind a migration decision.

### Ordering, and why

| step | closes | migration | breaking |
|---|---|---|---|
| 1. scheme regex | defect 1 | none | no |
| 2. s/p/g take the parsed type | defect 2, §4.5 | none | no |
| 3. `else` raises | defect 3 | none | **yes** |

Steps 1 and 2 are safe and independently valuable. Step 3 needs a caller sweep
first. Doing 1 alone would already retire the largest class — every URI scheme
outside three.

### How to know it worked

`tests/unit/sparql_sql/test_term_typing_agreement.py` records the current
disagreements as passing assertions, each carrying a message to update this
issue. **They are meant to fail when this is fixed** — a failure there is the
signal that a mechanism was reconciled, not a regression.

## Related

- `named_graph_semantics` §4.5 — the graph-position instance, with tests
- `issues/065` — the bare-label convention `_infer_type` predates
- `issues/131` — blank node labels not document-scoped; the same migration question
- `issues/132` — where the scheme regex above already exists
