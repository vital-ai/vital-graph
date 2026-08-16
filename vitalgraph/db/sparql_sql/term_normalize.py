"""One place that decides how a term's text is stored.

THE CONVENTION: `term_text` always holds the BARE value. For a blank node that
is the label without `_:`. The prefix belongs to serialized RDF syntax and is
re-added by the serializers on the way out (`bulk_export.py`,
`data_export_impl.py`).

The read side always agreed on that. The write side did not, and which
convention you got depended on the entry point (issues/065):

    N-Triples / N-Quads import    b1      data_import_impl strips `_:`
    bulk / rdflib load            b1      str(BNode) is already bare
    SPARQL UPDATE                 _:b1    emit_update._node_text added it back
    string-sniffing classifier    _:b1    typed as 'B' without stripping

Both spellings are legal `term_type = 'B'` rows, so nothing in the data marks
which one a space holds.

WHY IT IS NOT COSMETIC. `term_uuid` is a deterministic UUIDv5 over
`(term_text, term_type, lang, datatype_id)`, so the two spellings are two
different terms:

    LOAD  <file with _:b1 :p :o>     -> term_text 'b1',  uuid A
    DELETE DATA { _:b1 :p :o }       -> looks up '_:b1', uuid B  -> no match

The delete removes nothing and reports success. The inverse holds too: a triple
written through SPARQL UPDATE is invisible to a delete issued through the import
path. And an exported blank node written via UPDATE comes out `_:_:b1`, which
is not valid N-Triples.

Applied at term-identity computation rather than only at the call sites, so a
fifth write path cannot reintroduce the divergence by forgetting to strip.
"""

from __future__ import annotations

BLANK = "B"
_PREFIX = "_:"


def normalize_term_text(term_text: str, term_type: str) -> str:
    """The canonical stored text for a term.

    Idempotent, so applying it twice is harmless — which matters because it is
    applied both where text is stored and where the UUID is computed, and those
    are not always the same call.
    """
    if term_type == BLANK and isinstance(term_text, str) \
            and term_text.startswith(_PREFIX):
        return term_text[len(_PREFIX):]
    return term_text


def serialize_term_text(term_text: str, term_type: str) -> str:
    """The RDF-syntax form: the stored text with `_:` re-added for a blank node.

    The inverse of `normalize_term_text`, here so the pairing is visible in one
    file. Serializers that already inline this are correct; new ones should call
    it rather than add a fifth copy of the convention.
    """
    if term_type == BLANK and isinstance(term_text, str) \
            and not term_text.startswith(_PREFIX):
        return _PREFIX + term_text
    return term_text


# ---------------------------------------------------------------------------
# Skolemisation
# ---------------------------------------------------------------------------

# The fixed namespace every skolemised blank node belongs to.
#
# RDF 1.1 Concepts §3.5: a system replacing blank nodes with IRIs "SHOULD mint a
# new, globally unique IRI (a Skolem IRI) for each blank node so replaced", and
# one that wants them recognisable outside its boundaries "SHOULD use a
# well-known IRI with the registered name `genid`". So the shape is registered,
# not invented here.
SKOLEM_BASE = "http://vital.ai/.well-known/genid/"

# Label prefix, carried in `term_text`. Short, and a letter first because
# N-Triples BLANK_NODE_LABEL must begin with PN_CHARS_U or a digit.
_SKOLEM_LABEL_PREFIX = "vg"


def skolem_label(scope_id: str, label: str) -> str:
    """The stored label for blank node `label` appearing in scope `scope_id`.

    DETERMINISTIC in both arguments, which is the whole point of the design:

      * different documents, same label -> different nodes, because `scope_id`
        differs. That is RDF's rule — blank node identifiers are "locally
        scoped to the file or RDF store, and are *not* persistent or portable"
        — and it is what a global label registry got wrong: two files each
        using `_:b0` silently merged into one node, unrecoverably.
      * the SAME document re-imported -> the SAME nodes, because neither
        argument changed. A random allocation per load would satisfy RDF and
        break idempotent reload (issues/041); deriving from the scope gives
        both, which neither per-load mangling nor random skolemisation gives
        alone.

    Returns a BARE label, not an IRI. `term_text` for a 'B' row holds the bare
    value (see normalize_term_text), and N-Triples BLANK_NODE_LABEL admits
    neither `:` nor `/` — so storing the full Skolem IRI would export as
    `_:http://.../genid/abc`, which no parser reads back. The IRI form is
    rendered by `skolem_iri` when it is actually wanted.
    """
    import hashlib

    digest = hashlib.sha256(
        f"{scope_id}\x00{label}".encode("utf-8")).hexdigest()[:32]
    return f"{_SKOLEM_LABEL_PREFIX}{digest}"


def skolem_iri(term_text: str) -> str:
    """The Skolem IRI form of a stored blank-node label."""
    return SKOLEM_BASE + normalize_term_text(term_text, BLANK)


def is_skolem_label(term_text: str) -> bool:
    """Whether a stored label was minted by `skolem_label`.

    Labels that predate skolemisation, or arrive from a path that does not
    skolemise, stay readable — this is how they are told apart rather than
    assumed.
    """
    bare = normalize_term_text(term_text, BLANK)
    return (bare.startswith(_SKOLEM_LABEL_PREFIX)
            and len(bare) == len(_SKOLEM_LABEL_PREFIX) + 32
            and all(c in "0123456789abcdef"
                    for c in bare[len(_SKOLEM_LABEL_PREFIX):]))


def deskolemize_iri(iri: str) -> str | None:
    """The blank-node label inside a Skolem IRI, or None if it is not one.

    Used on import: a document containing our own exported Skolem IRIs should
    read them back as the blank nodes they were, rather than as ordinary IRIs.
    """
    if isinstance(iri, str) and iri.startswith(SKOLEM_BASE):
        return iri[len(SKOLEM_BASE):]
    return None
