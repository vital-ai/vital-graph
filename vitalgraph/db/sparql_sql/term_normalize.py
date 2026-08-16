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
