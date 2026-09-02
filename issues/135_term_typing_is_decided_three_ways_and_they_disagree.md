# Term Typing Is Decided Three Ways, and They Disagree

## Status: FIXED 2026-08-25. All three defects closed; `_infer_type` deleted.

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

### Revised 2026-08-25 after surveying the callers

The first draft proposed three changes to the string inference. Surveying who
actually calls these methods reorders the whole thing, and shrinks it.

    get_rdf_quad             ZERO callers, anywhere
    remove_rdf_quad          two tests, no production caller
    remove_rdf_quads_batch   the live path — files_impl, fuseki ops, triples
                             endpoint

And `remove_rdf_quads_batch` already does the right thing for the object:

    s_uuid = _generate_term_uuid(str(s), 'U')          # forced
    p_uuid = _generate_term_uuid(str(p), 'U')          # forced
    g_uuid = _generate_term_uuid(str(g), 'U')          # forced
    o_type = self._infer_rdflib_type(o) if hasattr(o, 'n3') else self._infer_type(o_text)

It prefers the rdflib CLASS and falls back to string inference only when the
caller had no term. That is exactly the pattern this issue was going to
propose — it is already here, applied to one position out of four.

`get_existing_quads_for_uris`, which feeds the live delete path, documents its
return as *"List of tuples (subject, predicate, object, graph) as RDFLib
Identifiers"*. So production always has terms, `hasattr(o, 'n3')` is always
true, and **`_infer_type` is never reached on any production path.**

### What that changes

**Defect 1 (the three-scheme list) is not reachable in production.** It bites
only string callers, and there are none outside tests. It is still wrong, and
the measurement below shows it cannot be made right by any regex — but it is no
longer the largest item, and it is not urgent.

**Defect 2 is the only one that bites live traffic**, and only in one place:
`s`, `p` and `g` are forced `'U'` while the object beside them is typed
properly. A blank-node subject or graph goes in as `'B'` and is looked up as
`'U'`, so it cannot be deleted. Blank node subjects are ordinary RDF.

### The revised plan

**1. Extend the object's pattern to the other three positions.** One method,
one line each, and the pattern is already in the file:

    s_type = self._infer_rdflib_type(s) if hasattr(s, 'n3') else 'U'

No API change — callers already pass terms. No migration. No lookup cost. This
is the whole production fix, and it closes `named_graph_semantics` §4.5.

**2. Delete `get_rdf_quad`.** Zero callers. Deleting it removes one of the
three mechanisms outright rather than reconciling it, and it is the only method
here whose type decision nothing depends on.

**3. Apply the same pattern to `remove_rdf_quad`.** Test-only, so it is free,
and leaving it inconsistent is how the next person learns the wrong pattern.

**4. Later, separately: the string API.** Widening `_infer_type` to a scheme
regex, and making `_ensure_term`'s `else` raise. Both are correctness work on a
surface production does not use, both are measured below as small, and the
second is breaking. Neither should hold up 1-3.

### Why this ordering is different from the first draft

The first draft led with the scheme regex because it looked like the biggest
class of broken values. It is — in the string API that nothing calls. Counting
callers before counting rows would have found that first.

### Performance implications, and whether a rewrite is the better trade

Asked directly: is it better to rewrite the data once than to pay forever?
Measured across 56 term tables on the perf cluster.

**There is no permanent cost to pay.** The proposal adds one precompiled regex
per term on the remove/get paths and nothing on the insert paths. No extra
lookups, no probing, no index change. The alternative design that WOULD cost
forever — try `'U'`, then try `'L'`, take whichever hits — is 2x the lookups on
every delete and fetch, permanently, and is the reason not to go that way.

**A rewrite would not buy anything, because the stored data is already right.**

    'U' terms                                  17,549,506
    'U' terms with no scheme (cannot be an IRI)         6

All six are `'bind projection fixture'`, in throwaway integration spaces. So
defect 3 — the `else 'U'` branch — has been reachable for as long as it has
existed and has produced six bad rows, none of them in real data. Cleaning them
is a `DELETE`, not a migration.

The information that is missing is missing at the API BOUNDARY, not in storage.
`remove_rdf_quad(space, s, p, o, g)` takes strings; RDF terms are not strings.
Rewriting rows cannot add a distinction the caller never expressed.

**What the measurement did change: step 1 is smaller than it looked, and the
string API is worse than this issue said.**

    'L' terms                                   3,421,707
    already unreachable by string lookup today    138,871   (text starts http/https/urn)
    NEWLY unreachable under a scheme regex             46

So the scheme regex costs 46 rows to fix every non-http URI scheme — a good
trade, and 0.03% of the literals already affected. But look at what those 46
are:

    'arrowworms: a group of small active transparent...'
    'shorebirds: plovers; sandpipers; avocets; phalaropes'
    'flatfishes: halibut; sole; flounder; plaice; turbot'

`^[A-Za-z][A-Za-z0-9+.-]*:` matches `arrowworms:`. A word followed by a colon
is a valid scheme *by the grammar* — RFC 3986 §3.1 defines the SYNTAX of a
scheme, not which schemes exist.

**Corrected twice, and the second correction retires the first.**

The IANA registry beats a syntax regex — membership rejects `arrowworms:` and
accepts `file:`, `ftp:`, `did:`. But asking which scheme test to use is the
wrong question, because every OTHER layer in this system recognises a URI from
an EXPLICIT MARKER and never guesses:

| layer | how it knows | ambiguous? |
|---|---|---|
| N-Quads / N-Triples text (`quad_format_utils`) | `<...>`, `_:`, `"..."` delimiters | no |
| SPARQL text (the sidecar, Jena's parser) | the same delimiters | no |
| sidecar JSON -> `jena_ast_mapper` | `"type": "uri" \| "literal" \| "bnode"` | no |
| rdflib terms | the Python class | no |
| **bare strings (`_infer_type`)** | **nothing — it guesses** | **yes** |

Four layers carry the answer; one throws it away and reconstructs it from the
characters. No scheme test repairs that, because the ambiguity is not in the
rule — it is in accepting a string with no marker.

### So: what to implement on the string surface

**Nothing new. `nquads_term_to_rdflib` already does this**, correctly, and is
already used by the REST batch endpoints:

    <http://...>              -> URIRef
    "value"                   -> Literal
    "value"^^<http://...>     -> Literal with datatype
    "value"@lang              -> Literal with language tag
    _:label                   -> BNode

It carries the marker, so there is nothing to infer. It also already handles
`bnode_scope` (`issues/076`), which `_infer_type` has no concept of.

The decision:

1. **Delete `get_rdf_quad`** — zero callers.
2. **`remove_rdf_quad` takes terms**, or N-Quads-encoded strings through
   `nquads_term_to_rdflib`. Test-only, so free.
3. **`remove_rdf_quads_batch` prefers the rdflib class in all four positions.**
   The object already does; `s`, `p` and `g` are forced `'U'`. Any string
   fallback goes through `nquads_term_to_rdflib`, not `_infer_type`.
4. **Delete `_infer_type`.**

**The IANA registry is not needed and should not be added.** It was the best
answer to "how do we guess better", and the answer is that we stop guessing. A
caller who writes `<http://x>` has said URI; one who writes `"http://x"` has
said literal; the 138,871 literals whose text looks like a URL are no longer a
problem, because nothing is looking at their text to decide.

### The two scheme tests must NOT be unified

There are now two places asking something scheme-shaped, and they answer
DIFFERENT questions:

    sidecar   HAS_SCHEME = ^[A-Za-z][A-Za-z0-9+.-]*:
              "is this IRI reference absolute, or relative and in need of
               resolution?"  (issues/132)

    _infer_type
              "is this string a URI or a literal?"

The sidecar's must stay a SYNTAX test. RFC 3986 §5.2.2 keys resolution on
whether the reference carries a scheme, not on whether that scheme is
registered — `<arrowworms:foo>` is an absolute reference and must be left
alone. Swapping in the IANA registry there would resolve it against the base
and silently change the IRI.

They look like the same check and are not. Anyone tidying two scheme tests into
one shared helper would break IRI resolution to improve term typing. That is
the note this section exists to leave.

### What this leaves

`_infer_type`'s 138,871 mis-inferred literals stop mattering the moment nothing
inspects their text to decide a type. They were never bad DATA — they are
correctly stored `'L'` terms that a guessing lookup could not find.

### Performance implications, and whether a rewrite is the better trade

Asked directly: is it better to rewrite the data once than to pay forever?
Measured across 56 term tables on the perf cluster.

**There is no permanent cost to pay.** The proposal adds one precompiled regex
per term on the remove/get paths and nothing on the insert paths. No extra
lookups, no probing, no index change. The alternative design that WOULD cost
forever — try `'U'`, then try `'L'`, take whichever hits — is 2x the lookups on
every delete and fetch, permanently, and is the reason not to go that way.

**A rewrite would not buy anything, because the stored data is already right.**

    'U' terms                                  17,549,506
    'U' terms with no scheme (cannot be an IRI)         6

All six are `'bind projection fixture'`, in throwaway integration spaces. So
defect 3 — the `else 'U'` branch — has been reachable for as long as it has
existed and has produced six bad rows, none of them in real data. Cleaning them
is a `DELETE`, not a migration.

The information that is missing is missing at the API BOUNDARY, not in storage.
`remove_rdf_quad(space, s, p, o, g)` takes strings; RDF terms are not strings.
Rewriting rows cannot add a distinction the caller never expressed.

**What the measurement did change: step 1 is smaller than it looked, and the
string API is worse than this issue said.**

    'L' terms                                   3,421,707
    already unreachable by string lookup today    138,871   (text starts http/https/urn)
    NEWLY unreachable under a scheme regex             46

So the scheme regex costs 46 rows to fix every non-http URI scheme — a good
trade, and 0.03% of the literals already affected. But look at what those 46
are:

    'arrowworms: a group of small active transparent...'
    'shorebirds: plovers; sandpipers; avocets; phalaropes'
    'flatfishes: halibut; sole; flounder; plaice; turbot'

`^[A-Za-z][A-Za-z0-9+.-]*:` matches `arrowworms:`. A word followed by a colon
is a valid scheme *by the grammar* — RFC 3986 §3.1 defines the SYNTAX of a
scheme, not which schemes exist.

**Corrected: the right test is the registry, not a regex.** IANA maintains the
authoritative list of registered URI schemes, and it is FINITE — a few hundred
entries. `arrowworms` is not in it. `file`, `ftp`, `mailto`, `did`, `tag`,
`s3`, `data` are. So checking membership rather than shape:

    rejects  arrowworms:, shorebirds:, flatfishes:   (the 46 false positives)
    accepts  file:, ftp:, mailto:, did:, tag:        (the class defect 1 is about)

which is what both other options get wrong in opposite directions — the
three-prefix list is too narrow, the syntax regex too broad.

Two residuals, both smaller than what they replace:

- **Unregistered private schemes** are legal in RDF and would be rejected. A
  vocabulary coining `vital:` would not round-trip. That is a narrower failure
  than today's list, which rejects every scheme but three.
- **The registry changes**, so it needs a refresh path. It moves slowly, and a
  vendored copy with a dated comment is enough.

It still does not make string inference CORRECT — a literal whose text is
`"http://example.com"` is a literal, and no registry can know that. The 138,871
rows already lost stay lost. So the API change remains the real fix, and the
registry is the right rule for the string surface that will still exist behind
it.

**Where a rewrite IS the right call, and it is not here.** `issues/131` —
blank node labels not scoped to their document — cannot be fixed without moving
term identity, so it needs exactly the one-time rewrite this question is about.
These two should still not be bundled: this one needs none, and bundling would
put a no-migration fix behind a migration decision.

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


---

## Fixed 2026-08-25

One mechanism, `_term_type_of(term)`, for subject, predicate, object and graph
alike in every path. `_infer_type` is deleted rather than widened.

| defect | closed by |
|---|---|
| 1. non-http schemes unreachable | types come from the term, so no scheme rule is consulted at all |
| 2. blank nodes unreachable | same — s/p/g stop being hardcoded `'U'` |
| 3. unknown type guessed as `'U'` | raises `TypeError` naming `nquads_term_to_rdflib` |

### Three things the implementation found that the audit had not

**A third spelling.** `remove_rdf_quads_batch_bulk` carried its own inlined
`isinstance` chain — a fourth decision point beside the three this issue named.
Found by grep after fixing the first batch path; reading the issue alone would
have missed it.

**`get_rdf_quad` is contract, not dead code.** This issue recorded "zero
callers" and proposed deleting it. It is `@abstractmethod` on
`SpaceBackendInterface` and the fuseki backends implement it, so removing it
left `SparqlSQLSpaceImpl` with an unimplemented abstract method and
uninstantiable. *No direct callers* is not *unused*.

**Raising into a swallowing `except` achieves nothing.** Both `remove_rdf_quad`
and `get_rdf_quad` wrap everything in `except Exception -> log -> return
False`, so the new `TypeError` became a logged failure and a `False` — which
reads exactly like "the quad was not there". The typing now happens OUTSIDE the
try: a DB error is worth swallowing there, a caller error is not.

### The sweep that made defect 3 safe

Instrumented the `else` branch and ran conformance, unit and integration:
**nine** bare strings reached it, every one from a test. No production path
passes one — consistent with `get_existing_quads_for_uris` returning rdflib
Identifiers. Three test call sites were updated to pass terms.

### Verification

22 unit tests over the term key; an integration test that removes a quad from a
blank-node graph, which is the case production takes. The string-passing test
beside it now expects `TypeError` rather than a silent no-op.

Conformance, unit and integration: 0 failures.
---

## Appended 2026-09-01 — a lead from `issues/138`, checked and NOT a defect

`issues/138` fixed two sites that truncated a `leaf_terms` identity from the
4-tuple `(text, type, lang, datatype)` to `(text, type)`, silently missing every
typed literal. `traversal_chain._as_uuid_pair` looked like a third instance — it
does the same truncation:

    p_text, p_type = pred[0], pred[1]
    o_text, o_type = obj[0], obj[1]
    ...
    return (_generate_term_uuid(p_text, p_type),
            _generate_term_uuid(o_text, o_type))

**It is not a defect.** Two lines above the call there is an explicit guard:

    if p_type != "U" or o_type != "U":
        return None

so nothing but a plain URI ever reaches `_generate_term_uuid`, and a plain URI
has no lang or datatype to lose. The two-argument form is correct for whatever
survives the guard. Recorded here so the next person who greps for this pattern
does not re-open it.

### What IS wrong there is the reasoning, and it is this issue's subject

Both comments at that site assert something false about `leaf_terms` — the
docstring says it "records constants as `(term_text, term_type)`", and the
inline comment says a typed or language-tagged object's lang/datatype are not
carried "here".

`leaf_terms` DOES carry them, and has since `a2b623a` widened the key. Verified
directly on a production query:

    leaf_terms[q9,object_uuid] = ('00QUg00000mPfkIMAS', 'L', None,
                                  'http://www.w3.org/2001/XMLSchema#string')

That belief — "leaf_terms is a 2-tuple" — is exactly what produced `issues/138`,
in two other files, at a measured cost of 2.7 ms -> 54,949 ms. It survives here
as a comment justifying a restriction it does not actually justify.

### The consequence is a missed optimisation, not a bug

Because the identity IS available, the `p_type != "U"` bail is now self-imposed.
`_as_uuid_pair` exists so `rdf_stats` can price a constrained end and the
traversal direction can be chosen. Today a chain constrained by a typed LITERAL
— the shape the production hot path uses, `hasTextSlotValue` on an `SFLeadId` —
prices as unknown, so the direction goes unchosen.

Lifting it means passing the full identity through and letting
`_generate_term_uuid` hash lang/datatype as the writer does. Not attempted here:
it changes which traversals get a direction, which is a plan change wanting its
own measurement, and `issues/090` is where that argument belongs.

**Not started. The stale comments are worth correcting regardless of whether the
restriction is lifted** — they are the false belief, written down, sitting in the
file that would otherwise be the next place it causes a defect.
