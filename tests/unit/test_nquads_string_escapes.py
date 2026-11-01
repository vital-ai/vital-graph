"""
Literal text survives the N-Quads encoding (`issues/332`).

The unescape ran as chained `replace` calls, so the second backslash of an
escaped backslash paired with the character after it, and stored text changed:
a literal backslash and `n` became a backslash and a line break. It ran on the
write path as well as the read path, so the save itself altered the value.
"""

import random

import pytest
from rdflib import Literal

from vitalgraph.endpoint.impl.data_export_impl import _format_term_nquads
from vitalgraph.endpoint.impl.data_import_impl import _parse_nquads_term_typed
from vitalgraph.endpoint.kgdocuments_endpoint import _literal_term
from vitalgraph.model.quad_model import Quad
from vitalgraph.utils.nquads_string import unescape_nquads_string
from vitalgraph.utils.quad_format_utils import (
    _escape_nquads_string,
    nquads_term_to_rdflib,
    nquads_text_to_quads,
    parse_nquads_object,
    quads_to_nquads_text,
    rdflib_term_to_nquads,
)

XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"

BACKSLASH_TEXT = [
    "a\\nb",
    "a\\rb",
    "C:\\new\\report",
    "\\newline \\rho",
    "\\d+\\n",
    '{"a":"x\\ny"}',
    "a\\\\nb",
    "a\\\nb",           # a backslash before a REAL line break
    "a\\",
    'a\\"b',
    "a\\tb",
    "a\\u00e9",
]

PLAIN_TEXT = ["a\nb", "a\rb", "a\r\nb", "a\tb", 'he said "hi"', "é😀", "it's", ""]


class TestRoundTrip:
    @pytest.mark.parametrize("value", BACKSLASH_TEXT + PLAIN_TEXT)
    def test_unescape_inverts_escape(self, value):
        assert unescape_nquads_string(_escape_nquads_string(value)) == value

    @pytest.mark.parametrize("value", BACKSLASH_TEXT + PLAIN_TEXT)
    def test_the_read_path_parser(self, value):
        assert parse_nquads_object(_literal_term(value)) == value

    @pytest.mark.parametrize("value", BACKSLASH_TEXT + PLAIN_TEXT)
    def test_the_rest_write_path_parser(self, value):
        term = nquads_term_to_rdflib(rdflib_term_to_nquads(Literal(value)))
        assert str(term) == value

    @pytest.mark.parametrize("value", BACKSLASH_TEXT + PLAIN_TEXT)
    def test_the_file_import_parser(self, value):
        assert _parse_nquads_term_typed(_literal_term(value))[0] == value

    @pytest.mark.parametrize("value", BACKSLASH_TEXT + PLAIN_TEXT)
    def test_jsonl_export_then_import(self, value):
        # The exporter writes a real tab as `\t`, which the importer has to read.
        term = _format_term_nquads(value, "L", None, XSD_STRING)
        assert _parse_nquads_term_typed(term)[0] == value

    def test_random_backslash_text(self):
        rng = random.Random(332)
        for _ in range(20000):
            value = "".join(rng.choice('\\\\\\nrtu"\n\r\t ab')
                            for _ in range(rng.randint(0, 12)))
            assert unescape_nquads_string(_escape_nquads_string(value)) == value


class TestEscapeGrammar:
    @pytest.mark.parametrize("escaped,expected", [
        ("a\\tb", "a\tb"),
        ("a\\bb", "a\bb"),
        ("a\\fb", "a\fb"),
        ("a\\'b", "a'b"),
        ("\\u00e9", "é"),
        ("\\U0001F600", "😀"),
    ])
    def test_escapes_from_other_producers(self, escaped, expected):
        assert unescape_nquads_string(escaped) == expected

    @pytest.mark.parametrize("escaped", [
        "\\x",              # not an escape
        "\\u12",            # too short
        "\\uD800",          # a surrogate: PostgreSQL could not store it
        "\\U00110000",      # past the end of Unicode
        "a\\",              # dangling
    ])
    def test_an_invalid_escape_stays_as_written(self, escaped):
        assert unescape_nquads_string(escaped) == escaped


class TestNQuadsText:
    @pytest.mark.parametrize("value", [
        "one\u2028two", "one\u2029two", "one\x0btwo", "one\x0ctwo",
        "one\x85two", "one\x1ctwo",
    ])
    def test_a_unicode_line_separator_does_not_cut_the_literal(self, value):
        quad = Quad(s="<urn:s>", p="<urn:p>",
                    o=rdflib_term_to_nquads(Literal(value)), g=None)
        parsed = nquads_text_to_quads(quads_to_nquads_text([quad]))
        assert len(parsed) == 1
        assert parse_nquads_object(parsed[0].o) == value

    @pytest.mark.parametrize("eol", ["\n", "\r\n", "\r"])
    def test_lines_still_split(self, eol):
        text = f'<urn:a> <urn:p> "1" .{eol}<urn:b> <urn:p> "2" .{eol}'
        assert [q.s for q in nquads_text_to_quads(text)] == ["<urn:a>", "<urn:b>"]
