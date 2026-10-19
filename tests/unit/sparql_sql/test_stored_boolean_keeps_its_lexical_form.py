"""A stored xsd:boolean is returned with its own lexical form — issues/280.

`_binding_from_companions` rewrote "0"→"false" and "1"→"true" for every
xsd:boolean it rendered, so `"0"^^xsd:boolean` read back as a different term:
in RDF 1.1 a literal's identity includes its lexical form. Every DAWG `cast/*`
case failed on that stored row, and passed only because pyoxigraph canonicalised
too. A computed boolean is canonical already, so it is unaffected.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.sql_type_binding import XSD_BOOLEAN, _binding_from_companions


@pytest.mark.parametrize("lexical", ["0", "1", "true", "false"])
def test_a_stored_boolean_keeps_its_text(lexical):
    b = _binding_from_companions(lexical, "L", None, XSD_BOOLEAN)
    assert (b.type, b.value, b.datatype) == ("literal", lexical, XSD_BOOLEAN)
