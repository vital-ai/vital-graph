"""CSV and TSV result-file parsing for the DAWG conformance corpus.

These run against the REAL corpus files rather than hand-built strings, because
the interesting cases are the ones the DAWG authors chose deliberately — a
comma inside a quoted literal, a custom datatype, a double whose lexical form is
not its canonical form. Inventing fixtures here would mean inventing the edge
cases too, and I would have invented easier ones.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vitalgraph_sparql_sql_dev.dawg_test_impl.dawg_srx_parser import (
    ResultParseError,
    SparqlBinding,
    UnsupportedResultFormat,
    parse_result_file,
)
from vitalgraph_sparql_sql_dev.dawg_test_impl.dawg_result_comparator import (
    SparqlResults,
    compare_results,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
CSV_TSV = (
    _PROJECT_ROOT
    / "tests" / "conformance" / "dawg_data" / "sparql" / "sparql11" / "csv-tsv-res"
)

XSD = "http://www.w3.org/2001/XMLSchema#"

pytestmark = pytest.mark.skipif(
    not CSV_TSV.exists(), reason="DAWG corpus not present"
)


def _objects(results) -> list:
    return [row.get("o") for row in results.rows]


class TestTSVParsing:
    """TSV carries full term syntax, so it is compared strictly."""

    def test_term_types_are_recovered(self):
        r = parse_result_file(CSV_TSV / "csvtsv01.tsv")
        assert r.variables == ["s", "p", "o"]
        kinds = [o.type for o in _objects(r)]
        assert kinds == ["uri", "literal", "literal", "literal", "literal", "bnode"], (
            "TSV distinguishes <uri>, \"literal\" and _:bnode; losing that "
            "distinction would make every comparison against a TSV vacuous"
        )

    def test_datatypes_including_a_custom_one(self):
        r = parse_result_file(CSV_TSV / "csvtsv03.tsv")
        by_dt = [(o.value, o.datatype) for o in _objects(r)]
        assert ("5,5", "http://example.org/myCustomDatatype") in by_dt, (
            "a user-defined datatype IRI must survive parsing"
        )
        assert ("-3", f"{XSD}negativeInteger") in by_dt, (
            "the narrow XSD type is what the file says; widening it to "
            "xsd:integer here would hide a backend that widened it too"
        )

    def test_a_comma_inside_a_quoted_literal(self):
        """The case that separates TSV from CSV.

        `"4,4"` is ONE value. A CSV reader pointed at the TSV, or a naive split
        on commas, yields two — and the row count would still look right.
        """
        r = parse_result_file(CSV_TSV / "csvtsv03.tsv")
        assert "4,4" in [o.value for o in _objects(r)]
        assert len(r.rows) == 7

    def test_bare_numerics_get_their_implied_datatype(self):
        r = parse_result_file(CSV_TSV / "csvtsv03.tsv")
        dts = {o.value: o.datatype for o in _objects(r)}
        assert dts["2.2"] == f"{XSD}decimal"
        assert dts["1.0e6"] == f"{XSD}double"

    def test_lexical_form_is_preserved_not_canonicalised(self):
        """`1.0e6` stays `1.0e6`.

        RDF 1.1 makes the lexical form part of a literal's identity, so
        `"1.0e6"^^xsd:double` and `"1000000"^^xsd:double` are different terms.
        A parser that canonicalised here would silently agree with any engine
        that also canonicalised, which is the disagreement this corpus exists
        to expose.
        """
        r = parse_result_file(CSV_TSV / "csvtsv03.tsv")
        assert "1.0e6" in [o.value for o in _objects(r)]

    def test_unbound_is_absent_not_empty(self):
        """csvtsv02 comes from a query with OPTIONAL, so some cells are empty."""
        r = parse_result_file(CSV_TSV / "csvtsv02.tsv")
        unbound = [row for row in r.rows if "o2" not in row]
        assert unbound, "expected rows where the OPTIONAL did not match"
        for row in unbound:
            assert "o2" not in row, (
                "an unbound variable must be ABSENT; binding it to an empty "
                "literal would make OPTIONAL indistinguishable from a match"
            )


class TestCSVParsing:
    """CSV is lossy by specification — the parser must say so, not paper over it."""

    def test_it_declares_itself_lossy(self):
        assert parse_result_file(CSV_TSV / "csvtsv01.csv").lossy_types is True
        assert parse_result_file(CSV_TSV / "csvtsv01.tsv").lossy_types is False

    def test_uris_are_not_guessed_back(self):
        """A bare `http://...` in CSV could have been a URI or a string.

        Guessing on the `http` prefix would be right for this file and wrong for
        a literal that happens to look like a URI — and the failure would only
        appear on data nobody has.
        """
        r = parse_result_file(CSV_TSV / "csvtsv01.csv")
        assert all(o.type in ("literal", "bnode") for o in _objects(r))

    def test_blank_nodes_survive_because_csv_does_write_them(self):
        r = parse_result_file(CSV_TSV / "csvtsv01.csv")
        assert any(o.type == "bnode" for o in _objects(r)), (
            "CSV writes `_:label`, so this is the one distinction it keeps"
        )

    def test_quoted_comma_is_one_field(self):
        r = parse_result_file(CSV_TSV / "csvtsv03.csv")
        assert len(r.variables) == 3
        assert "4,4" in [o.value for o in _objects(r)]


class TestLossyComparison:
    """The comparator degrades only when a lossy file is involved."""

    def _results(self, bindings, lossy=False):
        return SparqlResults(
            variables=["o"],
            rows=[{"o": b} for b in bindings],
            lossy_types=lossy,
        )

    def test_types_are_ignored_against_a_lossy_expectation(self):
        typed = self._results([SparqlBinding(type="uri", value="http://example.org/x")])
        lossy = self._results(
            [SparqlBinding(type="literal", value="http://example.org/x")], lossy=True
        )
        assert compare_results(typed, lossy).match

    def test_types_still_matter_when_neither_side_is_lossy(self):
        """The guard that keeps this from weakening every other comparison."""
        as_uri = self._results([SparqlBinding(type="uri", value="http://example.org/x")])
        as_literal = self._results(
            [SparqlBinding(type="literal", value="http://example.org/x")]
        )
        assert not compare_results(as_uri, as_literal).match, (
            "a URI and a string that spell the same characters are different "
            "terms; lossy mode must not leak into ordinary comparisons"
        )

    def test_values_still_matter_in_lossy_mode(self):
        """Lossy is not 'compares nothing'."""
        a = self._results([SparqlBinding(type="literal", value="foo")], lossy=True)
        b = self._results([SparqlBinding(type="literal", value="bar")], lossy=True)
        assert not compare_results(a, b).match


class TestUnreadableExpectationsRaise:
    """An expectation we cannot read must not be able to become a skip.

    This is the mechanism behind three separate coverage holes, not a
    hypothetical: `parse_result_file` returned None on failure, every caller
    turned None into a skip, and a skip counts as green. Six `sparql10/dataset`
    result files were unreadable for as long as that category had been wired,
    and the category reported clean the whole time (issues/130).

    So these tests are about the FAILURE MODE, not about parsing. They assert
    that the bad news is raised where callers cannot quietly discard it.
    """

    def test_unparseable_file_raises_rather_than_returning_none(self, tmp_path):
        bad = tmp_path / "broken.srx"
        bad.write_text("<sparql><head><this is not xml at all")
        with pytest.raises(ResultParseError):
            parse_result_file(bad)

    def test_malformed_turtle_raises(self, tmp_path):
        bad = tmp_path / "broken.ttl"
        bad.write_text("@prefix : <http://example/> .\n:s :p [ unclosed .")
        with pytest.raises(ResultParseError):
            parse_result_file(bad)

    def test_relative_iri_in_turtle_is_readable(self, tmp_path):
        """The issues/130 case itself: a bare `<data-g1.ttl>` must resolve.

        Kept as a test because the fix is a base IRI derived from the file's
        own location, which is easy to drop in a refactor and whose absence
        shows up as a skip rather than a failure.
        """
        f = tmp_path / "r.ttl"
        f.write_text(
            '@prefix rs: <http://www.w3.org/2001/sw/DataAccess/tests/result-set#> .\n'
            '[] rs:resultVariable "g" ; rs:solution [ rs:binding '
            '[ rs:value <data-g1.ttl> ; rs:variable "g" ] ] .\n'
        )
        r = parse_result_file(f)
        assert len(r.rows) == 1
        assert r.rows[0]["g"].value.endswith("/data-g1.ttl")

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(ResultParseError):
            parse_result_file(tmp_path / "absent.srx")

    def test_unknown_format_is_a_distinct_type(self, tmp_path):
        """Skipping on a format we have no parser for is defensible.

        It gets its own type so a call site has to opt into that, rather than
        inheriting it from the same bare None that meant "corrupt".
        """
        f = tmp_path / "results.parquet"
        f.write_text("x")
        with pytest.raises(UnsupportedResultFormat):
            parse_result_file(f)
        assert issubclass(UnsupportedResultFormat, ResultParseError)
