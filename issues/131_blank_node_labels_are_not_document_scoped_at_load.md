# Blank Node Labels Are Not Document-Scoped At Load

## Status: OPEN — found 2026-08-24 while landing `named_graph_semantics` §4.1

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

## Fix — not attempted here

Blank node identity has to carry its document. The obvious form is a skolem
prefix minted per load, so the stored text is unique per (document, label)
while remaining a `B` term.

Two things to settle first, which is why this is filed rather than fixed:

- **Term identity changes for every existing blank node.** Anything storing
  or comparing those UUIDs is affected, so it needs a migration story.
- **Re-loading the same document must be idempotent** where callers rely on
  that today. A per-load random prefix breaks it; a prefix derived from the
  document's identity keeps it. The second is probably right, but "the
  document's identity" needs defining for streamed and generated input.

## Related

- `named_graph_semantics` §4.1 — landed; these two are excluded from it
- `issues/130` — the harness work that made these two visible at all
