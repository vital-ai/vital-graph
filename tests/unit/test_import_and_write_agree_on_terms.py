"""An imported literal and a written one must be the SAME term.

`issues/157` / `issues/158`. `_generate_term_uuid` hashes the datatype id, so
two writers that disagree about a literal's datatype mint two different terms
for one value — and a query written against either cannot see quads written
through the other. That is invisible until a space is both bulk-loaded and
incrementally written, which is the normal lifecycle.

THE CASE THAT BIT: pyoxigraph reports a plain string's datatype as `xsd:string`
explicitly. An earlier fix normalised it away to match `rdflib.Literal("CA")`,
whose datatype is None — and that was wrong. Measured on production: three
spaces, ZERO untyped literals, including one written through the CRUD path. The
KG model emits typed values, so the write path stores xsd:string too. The
importer keeps it, and these tests assert the two agree ON THAT BASIS.

Asserted as uuid EQUALITY between the two implementations rather than against a
hardcoded uuid, because the claim is that they agree — a shared constant would
still pass if both drifted together.
"""

from __future__ import annotations

import pytest
from rdflib import Literal as RdfLiteral
from rdflib.namespace import XSD

from vitalgraph.db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
from vitalgraph.endpoint.impl.data_import_impl import (
    _classify_node, _term_uuid)


class Literal:  # noqa: N801 — the NAME is load-bearing
    """The shape `_classify_node` reads from pyoxigraph.

    MUST be called `Literal`: `_classify_node` dispatches on
    `type(node).__name__`, so a double named anything else silently takes the
    IRI branch and the test compares two wrong answers. Named for the duck it
    has to be, and aliased below so the rdflib import still reads clearly.
    """

    def __init__(self, value, datatype=None, language=None):
        self.value = value
        self.language = language
        self.datatype = None if datatype is None else _OxIRI(datatype)


class _OxIRI:
    def __init__(self, value):
        self.value = value


def _import_side(node, datatype_ids):
    val, ttype, lang, dt_uri = _classify_node(node)
    return _term_uuid(val, ttype, lang=lang, datatype_id=datatype_ids.get(dt_uri))


def _write_side(lit, datatype_ids):
    dt = str(lit.datatype) if lit.datatype else None
    return _generate_term_uuid(str(lit), "L", lit.language, datatype_ids.get(dt))


class TestPlainStrings:
    """The regression. Both spellings of a bare string are one term."""

    def test_a_typed_string_agrees_with_a_typed_write(self):
        """Both sides carry xsd:string, so both resolve the same id."""
        ids = {str(XSD.string): 3}
        assert _import_side(Literal("CA", str(XSD.string)), ids) == \
               str(_write_side(RdfLiteral("CA", datatype=XSD.string), ids))

    def test_xsd_string_is_carried_not_dropped(self):
        """The revert. Dropping it would put new imports on the opposite side
        from every literal production already holds (`issues/158`)."""
        _, _, _, dt = _classify_node(Literal("CA", str(XSD.string)))
        assert dt == str(XSD.string)


class TestOtherDatatypesAreStillCarried:
    """Normalising strings must not throw the baby out — `issues/157` was the
    datatype being dropped for EVERY type, which made typed comparators match
    nothing (`MQLRating >= 65` returned 0 against a manifest count of 1,735)."""

    IDS = {str(XSD.float): 7, str(XSD.dateTime): 9, str(XSD.integer): 11}

    @pytest.mark.parametrize("dt", [XSD.float, XSD.dateTime, XSD.integer])
    def test_the_datatype_survives_and_both_sides_agree(self, dt):
        node = Literal("58.0", str(dt))
        lit = RdfLiteral("58.0", datatype=dt)
        assert _import_side(node, self.IDS) == str(_write_side(lit, self.IDS))

    def test_a_typed_literal_is_not_the_same_term_as_an_untyped_one(self):
        """The other direction: normalising must not collapse real types."""
        assert _import_side(Literal("58.0", str(XSD.float)), self.IDS) != \
               _import_side(Literal("58.0", None), self.IDS)


class TestLanguageTags:

    def test_a_language_tagged_literal_carries_no_datatype(self):
        """rdf:langString by definition — carrying both would double-key it."""
        _, _, lang, dt = _classify_node(
            Literal("colour", str(XSD.string), language="en"))
        assert lang == "en" and dt is None
