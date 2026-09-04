"""Every import format must mint the SAME uuid for the same typed literal.

`issues/157` made the datatype part of term identity, and the bulk and
n-triples paths were updated to hash it. The JSONL-quads and vital-block paths
parse through `_parse_nquads_term_for_import`, which DISCARDED the datatype — so
the same `"CA"^^xsd:string` landed under one uuid when imported as n-triples and
a different one when imported as JSONL.

Nothing surfaced that. Both files import "successfully"; the rows just do not
join, and a query written against one import returns nothing for the other. This
pins the agreement instead.
"""

from __future__ import annotations

import pytest
from pyoxigraph import Literal, NamedNode

from vitalgraph.endpoint.impl.data_import_impl import (
    _classify_node, _parse_nquads_term_typed, _term_uuid)

XSD = "http://www.w3.org/2001/XMLSchema#"

# (n-quads encoding, the equivalent pyoxigraph node the BULK path sees)
SAME_TERM = [
    (f'"CA"^^<{XSD}string>', Literal("CA", datatype=NamedNode(f"{XSD}string"))),
    (f'"5"^^<{XSD}integer>', Literal("5", datatype=NamedNode(f"{XSD}integer"))),
    (f'"1.5"^^<{XSD}double>', Literal("1.5", datatype=NamedNode(f"{XSD}double"))),
    ('"hi"@en', Literal("hi", language="en")),
    ('"plain"', Literal("plain")),
    ('<http://example/x>', NamedNode("http://example/x")),
]

# A stable stand-in for the space's datatype table: the uuid only needs the two
# paths to resolve the SAME uri to the SAME id, not any particular id.
DT_IDS = {f"{XSD}string": 1, f"{XSD}integer": 2, f"{XSD}double": 3}


@pytest.mark.parametrize("nquads,node", SAME_TERM,
                         ids=[c[0] for c in SAME_TERM])
def test_the_incremental_parse_and_the_bulk_parse_agree(nquads, node):
    b_val, b_type, b_lang, b_dt = _classify_node(node)
    i_val, i_type, i_lang, i_dt = _parse_nquads_term_typed(nquads)

    assert (i_val, i_type, i_lang) == (b_val, b_type, b_lang)
    assert i_dt == b_dt, (
        f"datatype disagreement: incremental={i_dt!r} bulk={b_dt!r}")

    bulk = _term_uuid(b_val, b_type, lang=b_lang,
                      datatype_id=DT_IDS.get(b_dt))
    incr = _term_uuid(i_val, i_type, lang=i_lang,
                      datatype_id=DT_IDS.get(i_dt))
    assert bulk == incr, (
        "the same literal gets different uuids depending on the import format; "
        "rows from the two files will not join")


def test_a_typed_literal_is_not_the_same_term_as_its_plain_form():
    """The guard the agreement test cannot provide on its own.

    If both sides dropped the datatype they would still AGREE — and the whole
    point of `issues/157` would be lost silently. This fails if the datatype
    stops reaching the hash at all.
    """
    plain = _term_uuid("CA", "L", lang=None, datatype_id=None)
    typed = _term_uuid("CA", "L", lang=None, datatype_id=DT_IDS[f"{XSD}string"])
    assert plain != typed
