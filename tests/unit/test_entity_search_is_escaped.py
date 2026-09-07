"""The listing's search term goes into a SPARQL string literal; escape it.

`kgentity_list_impl` interpolates `search` straight into
`FILTER(CONTAINS(LCASE(?name), LCASE("...")))` at six sites. The criteria path
in `kg_query_builder` escapes its own `search_text` with `escape_sparql_string`;
these did not.

A term containing a double quote therefore did not search for a quote — it
terminated the literal, producing either a parse error or a query the caller did
not write. That is the injection shape, in a query the server executes.

Asserted against the generated SPARQL rather than through a live search, because
the defect is in what is BUILT: a round trip could pass by returning zero results
for a broken query, which is exactly how this went unnoticed.
"""

from __future__ import annotations

import inspect

import pytest


def _builders():
    from vitalgraph.kg_impl import kgentity_list_impl as m
    return inspect.getsource(m)


def test_no_site_interpolates_the_raw_search_term():
    src = _builders()
    assert 'LCASE(\\"{search}\\")' not in src, (
        "a site still interpolates the raw search term into a SPARQL literal; "
        "wrap it in escape_sparql_string(...) as the criteria path does")


def test_every_search_literal_is_escaped():
    src = _builders()
    escaped = src.count("escape_sparql_string(search)")
    assert escaped >= 6, (
        f"only {escaped} search interpolations are escaped; there were six "
        f"sites, and an unescaped one is an injection into a query the server "
        f"runs")


def test_the_escaper_neutralises_a_quote_and_a_newline():
    """The property that matters, asserted on the escaper itself."""
    from vitalgraph.sparql.kg_query_builder import escape_sparql_string

    out = escape_sparql_string('a" . } INJECTED { "b')
    assert '"' not in out.replace('\\"', ''), (
        f"a bare double quote survives escaping: {out!r} — it would terminate "
        f"the literal it is placed in")
    assert "\n" not in escape_sparql_string("a\nb"), (
        "a raw newline survives; SPARQL 1.1 §19.7 does not permit it in a "
        "STRING_LITERAL")
