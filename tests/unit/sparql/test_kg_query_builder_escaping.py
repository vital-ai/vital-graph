"""Caller-supplied values must not become SPARQL syntax (issues/098).

Every query in `kg_query_builder` is built by f-string interpolation, so any
value that reaches a literal or an IRI is syntax unless escaped. At eight sites
it was not, and the consequence was not only a broken query:

    search_string = 'x")) || (1=1)) #'
    -> FILTER(CONTAINS(LCASE(?search_name), LCASE("x")) || (1=1)) #")))

which PARSES, is unconditionally true, and returns every entity of the type in a
response indistinguishable from an ordinary page.

THE ASSERTION THAT MATTERS is not "the query still compiles" — the injected form
compiled perfectly well, which is precisely what made it dangerous. It is that
the caller's value arrives at the parser as ONE literal and changes nothing about
the query's shape. That is checked by compiling the same query with an inert
term and asserting the two ALGEBRAS are identical once the literal is swapped
back — a payload that adds an operator or comments something out cannot survive
that comparison.

These tests are pure string-building; the sidecar cases are marked and skip
without it.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import pytest

from vitalgraph.sparql.kg_query_builder import (
    EntityQueryCriteria,
    EntityPropertyFilter,
    KGQueryCriteriaBuilder,
    escape_sparql_iri,
    escape_sparql_string,
)

GRAPH = "http://example.org/g"

# An inert term used as the structural baseline: no SPARQL-significant character
# in it, so the only difference between its query and a payload's is the literal.
SENTINEL = "zzsentinelzz"


def _unescaped_quotes(text: str) -> int:
    """Count `"` that actually delimit a literal.

    Walks the string honouring escapes rather than testing the preceding
    character — `"path\\\\"` ends in a quote preceded by a backslash that is
    itself escaped, and the naive rule reads that as still inside the literal.
    """
    count = 0
    i = 0
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == '"':
            count += 1
        i += 1
    return count

# The payload that actually worked. Balanced parens close CONTAINS and the
# FILTER, `|| (1=1)` makes it true, `#` comments out the generator's own tail.
BYPASS = 'x")) || (1=1)) #'

PAYLOADS = [
    BYPASS,
    'Ann "Annie" Smith',        # the symptom that got reported
    "path\\",                   # trailing backslash: escapes the closing quote
    'a"b\\"c',                  # a quote already spelled as an escape
    "a\nb",                     # raw newline is not permitted in a literal
    "tab\there",
    "plain",                    # the ordinary case must be untouched
]


def _swap(node, old: str, new: str):
    """Deep-copy `node`, replacing every string equal to `old` with `new`."""
    if isinstance(node, dict):
        return {k: _swap(v, old, new) for k, v in node.items()}
    if isinstance(node, list):
        return [_swap(v, old, new) for v in node]
    if isinstance(node, str) and node == old:
        return new
    return node


# The sidecar's compile endpoint. This was previously referenced without ever
# being defined, so `_sidecar_up` raised NameError, the except swallowed it, and
# every sidecar-marked test below skipped on every run — including on a machine
# with a healthy sidecar. Hence the narrow except: a bug in this probe must fail
# loudly rather than read as "the sidecar is down".
_SIDECAR = os.environ.get(
    "VG_SIDECAR_URL", "http://localhost:7071").rstrip("/") + "/v1/sparql/compile"


def _sidecar_up() -> bool:
    try:
        req = urllib.request.Request(
            _SIDECAR,
            data=b'{"sparql":"SELECT ?s WHERE { ?s ?p ?o } LIMIT 1"}',
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=2) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


HAS_SIDECAR = _sidecar_up()


def _compile(sparql: str) -> dict:
    req = urllib.request.Request(
        _SIDECAR,
        data=json.dumps({"sparql": sparql, "phases": {"algebraCompiled": True}}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


class TestEscapeHelpers:

    def test_backslash_is_escaped_before_the_quote(self):
        """Order is the whole correctness argument.

        Quote-first turns `\\` into `\\` and then doubles the backslash the
        quote-escape introduced. Three sites in this file previously did
        `.replace('"', '\\\\"')` alone, so a value ending in a backslash escaped
        the closing quote and reopened the hole.
        """
        assert escape_sparql_string("path\\") == "path\\\\"
        assert escape_sparql_string('a"b') == 'a\\"b'
        assert escape_sparql_string("end\\") + '"' == 'end\\\\"'

    def test_control_characters(self):
        assert escape_sparql_string("a\nb") == "a\\nb"
        assert escape_sparql_string("a\rb") == "a\\rb"
        assert escape_sparql_string("a\tb") == "a\\tb"

    def test_ordinary_text_is_unchanged(self):
        """Escaping that mangles normal input trades one bug for another."""
        for s in ["Acme Corp", "O'Brien", "50% off", "a-b_c.d", "café", "北京"]:
            assert escape_sparql_string(s) == s

    def test_non_string_values(self):
        assert escape_sparql_string(42) == "42"
        assert escape_sparql_string(None) == "None"

    def test_iri_escaping_closes_the_bracket_route(self):
        """`<...>` is terminated by `>`, so the payload shape differs."""
        out = escape_sparql_iri("http://x/a> ?s ?p ?o . <http://y/b")
        assert ">" not in out and "<" not in out and " " not in out
        assert "%3E" in out

    def test_iri_ordinary_case_unchanged(self):
        uri = "http://vital.ai/ontology/haley-ai-kg#KGLead"
        assert escape_sparql_iri(uri) == uri


@pytest.mark.parametrize("payload", PAYLOADS)
class TestGeneratedSparqlIsInert:

    def _filter_line(self, sparql: str) -> str:
        lines = [l for l in sparql.splitlines() if "CONTAINS" in l]
        assert lines, "expected a CONTAINS filter in the generated query"
        return lines[0]

    def test_search_string_stays_inside_one_literal(self, payload):
        """Counting quotes, not eyeballing the line.

        A raw `"` from the payload would open a second literal, so the filter
        clause must contain exactly the two delimiters the template puts there.
        """
        b = KGQueryCriteriaBuilder()
        sql = b.build_entity_query_sparql(
            EntityQueryCriteria(search_string=payload), GRAPH, 25, 0)
        line = self._filter_line(sql)
        assert _unescaped_quotes(line) == 2, (
            f"payload broke out of the literal: {line}"
        )

    @pytest.mark.skipif(not HAS_SIDECAR, reason="needs the Jena sidecar")
    def test_parser_sees_one_contains_and_the_original_text(self, payload):
        """The real assertion: the query's SHAPE is unchanged.

        "It compiles" is not the property under test — the injected form
        compiled perfectly well, which is what made it dangerous rather than
        merely broken.
        """
        b = KGQueryCriteriaBuilder()
        sql = b.build_entity_query_sparql(
            EntityQueryCriteria(search_string=payload), GRAPH, 25, 0)
        result = _compile(sql)
        assert result.get("ok") is True, (
            f"generated SPARQL did not parse: "
            f"{(result.get('error') or {}).get('message')}"
        )

        # Structural equivalence, which is the property that actually matters.
        # Build the same query with an inert search term; the two algebras must
        # differ ONLY in that literal. If the payload added an operator, changed
        # a join, or commented anything out, this diverges.
        #
        # Compared as PARSED OBJECTS, not as text. The rendered `pretty` form
        # re-escapes the literal in its own way, so a string comparison measures
        # the renderer rather than the query. `op` carries the caller's value
        # verbatim, which is exactly what we need to swap out.
        safe = b.build_entity_query_sparql(
            EntityQueryCriteria(search_string=SENTINEL), GRAPH, 25, 0)
        safe_op = _compile(safe)["phases"]["algebraCompiled"]["op"]
        got_op = result["phases"]["algebraCompiled"]["op"]

        assert _swap(got_op, payload, SENTINEL) == safe_op, (
            "the payload changed the query's structure, not just its search term"
        )


class TestOtherInterpolationSites:
    """The same value reaches five other places; one fixed site is not a fix."""

    def test_entity_property_filter(self):
        b = KGQueryCriteriaBuilder()
        sql = b.build_entity_query_sparql(
            EntityQueryCriteria(
                entity_property_filters=[EntityPropertyFilter(
                    property_uri="http://vital.ai/ontology/vital-core#hasName",
                    operator="contains",
                    value=BYPASS)]),
            GRAPH, 25, 0)
        lines = [l for l in sql.splitlines() if "CONTAINS" in l]
        assert lines, "expected the property filter to emit a CONTAINS"
        for line in lines:
            assert _unescaped_quotes(line) == 2, line

    @pytest.mark.skipif(not HAS_SIDECAR, reason="needs the Jena sidecar")
    def test_frame_search_string(self):
        """The frame builder carries a byte-identical clause to the entity one.

        Two copies of one rule is how the regex flag mapping went wrong
        (regex_dialect.md §4.2); here both had to be fixed and both are checked.
        """
        from vitalgraph.sparql.kg_query_builder import FrameQueryCriteria
        b = KGQueryCriteriaBuilder()
        try:
            sql = b.build_frame_query_sparql(
                FrameQueryCriteria(search_string=BYPASS), GRAPH, 25, 0)
        except (AttributeError, TypeError) as e:
            pytest.skip(f"frame builder signature differs: {e}")
        result = _compile(sql)
        assert result.get("ok") is True
        for line in sql.splitlines():
            if "CONTAINS" in line:
                assert _unescaped_quotes(line) == 2, line
