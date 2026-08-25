# Blank Node Labels Are Not Document-Scoped At Load

## Status: FIXED 2026-08-24 — found while landing `named_graph_semantics` §4.1

Two documents that both use `_:x` produce **one** term. RDF scopes a blank
node label to the document it appears in, so those are two distinct nodes.

## Where

`generate_term_uuid` keys a term on its text and type:

    uuid5(_VITALGRAPH_NS, "_:x\x00B")

Nothing in that identity says which document the label came from, so every
`_:x` in the space is the same node. The parser hands back document-local
labels (`pyoxigraph.parse` returns `_:x` for both files below), and the loader
takes them at face value.

## How it surfaced

`sparql10/dataset/dataset-09b` and `-10b`, which are the same query:

    SELECT * FROM <data-g3-dup.ttl> FROM NAMED <data-g3.ttl>
    { ?s ?p ?o  GRAPH ?g { ?s ?q ?v } }

`data-g3.ttl` and `data-g3-dup.ttl` are byte-identical, and both say:

    _:x :p "1"^^xsd:integer .
    _:a :p "9"^^xsd:integer .

Four distinct blank nodes across the two documents, so the join on `?s` has
nothing to match: **expected 0 rows**. We return 2. The DAWG corpus is
testing exactly this — that is what the `-dup` file is FOR.

Both cases were previously registered as §4.1 failures. They are not: dataset
scoping is now correct for them, and this was the second bug behind the first.

## Why it matters beyond the corpus

This is a data-correctness bug in the loader, not a test artifact. Any two
documents ingested into one space that happen to share a label — `_:b0`,
`_:genid1`, whatever a serialiser emitted — have their blank nodes silently
merged. Nothing errors, and the result is a graph asserting identities that
were never in the source. Common serialiser outputs collide constantly.

## Fix — `skolem_label`, which already existed

The scope of this was overstated when filed, in two ways worth recording.

**The production ingest path was never affected.** It goes through rdflib,
which mints unique labels per parse — two `Graph.parse()` calls on files that
both say `_:x` produce `n3426...b1` and `na803...b1`. The claim that "any two
documents ingested into one space have their blank nodes merged" was wrong;
the exposure was the DAWG loader, which uses `pyoxigraph.parse` and takes the
document-local label verbatim.

**Both "things to settle" were already settled.** This filed a migration
question and an idempotency question as blockers. `skolem_label`
(`term_normalize.py`, from `issues/076`) had answered both: it hashes
`(scope_id, label)`, so different documents give different nodes while the
same document re-imported gives the same ones — the exact tension between RDF
scoping and idempotent reload (`issues/041`) that this issue raised as open.
It was already in use on the file-import and REST batch paths.

So the fix is one call the loader never made, with the file's own URI as
scope. Verified in both directions: same label in different documents differs,
same label in the same document is stable.

`dataset-09b` and `-10b` now pass, and `XFAIL_SQL_V2_EXEC` is empty again.

The lesson is the one this whole thread keeps producing: a defect looked novel
because nobody checked whether the codebase had already solved it. Searching
for the mechanism before designing one would have turned this from an issue
into a one-line fix.

## Related

- `named_graph_semantics` §4.1 — landed; these two are excluded from it
- `issues/130` — the harness work that made these two visible at all
