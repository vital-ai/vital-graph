"""A search needle under three characters is refused by the BACKEND.

`issues/070`. An infix `ILIKE '%xq%'` cannot use the trigram index: the trigrams
of a two-character string are all PADDED, padding only holds at a word boundary,
and an infix match may land mid-word — so none can be required and the GIN index
degenerates into scanning itself. Measured on `sp_lead_synth_100k`, 10.4M terms:

    term_text ILIKE '%XQ%'    10,274 ms
    term_text ILIKE '%XQZ%'        5.6 ms

`MIN_CONTAINS_LENGTH = 3` has guarded the KGQuery criteria path since
2026-08-11. It guarded nothing else, and the list endpoints take a free-text
`search` box that compiles to the same shape. End to end on the same fixture,
through the frames list:

    search "XQ"    generation 5,487 ms + execution 7,917 ms
    search "XQZ"   generation    40 ms + execution 3,503 ms

BOTH halves are charged — the estimate scans the term table to prove absence,
then the query scans it again.

The rule is now enforced at every entry point that accepts free text, which is
what makes it a rule rather than a convention: a validator called from one place
is a property of that place.

An EMPTY or ABSENT search stays legal. It means "no filter", not "match
everything short", and rejecting it would break every unfiltered list.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from vitalgraph.model.kgentities_model import MIN_CONTAINS_LENGTH, validate_search_text

REPO = Path(__file__).resolve().parents[2]

# Every handler that takes free text and compiles it to a CONTAINS.
GUARDED = {
    "vitalgraph/endpoint/kgframes_endpoint.py": 2,
    "vitalgraph/endpoint/kgentities_endpoint.py": 3,
    "vitalgraph/endpoint/kgdocuments_endpoint.py": 1,
    "vitalgraph/endpoint/triples_endpoint.py": 1,
    "vitalgraph/endpoint/kgquery_endpoint.py": 1,   # via validate_contains_criteria
    # Found by the shape sweep below, not by inspection — which is the argument
    # for keying on the shape: two endpoints taking a search box were missed
    # when the guarded set was written out by hand.
    "vitalgraph/endpoint/kgtypes_endpoint.py": 1,
    "vitalgraph/endpoint/objects_endpoint.py": 1,
}


class TestTheValidator:

    @pytest.mark.parametrize("needle", ["x", "xq", " xq ", "\tab"])
    def test_a_short_needle_is_refused(self, needle):
        err = validate_search_text(needle)
        assert err and str(MIN_CONTAINS_LENGTH) in err

    @pytest.mark.parametrize("needle", ["xqz", "hello", "  abc  "])
    def test_a_long_enough_needle_passes(self, needle):
        assert validate_search_text(needle) is None

    @pytest.mark.parametrize("needle", [None, "", "   "])
    def test_no_search_is_not_a_short_search(self, needle):
        """Rejecting this would break every unfiltered list page."""
        assert validate_search_text(needle) is None

    def test_the_message_names_an_alternative(self):
        """A refusal that does not say what to do instead is a dead end."""
        err = validate_search_text("xq")
        assert "index" in err.lower()


class TestEveryEntryPointEnforcesIt:
    """The point of the change: one guarded endpoint is not a rule.

    Keyed on the CALL, not on a list of known-good files, so a new endpoint that
    takes a search box and forgets this is caught by the count going stale.
    """

    @pytest.mark.parametrize("path,expected", sorted(GUARDED.items()))
    def test_the_guard_is_called(self, path, expected):
        src = (REPO / path).read_text()
        calls = src.count("validate_search_text(") + src.count("validate_contains_criteria(")
        # the import line counts as one occurrence per call site here
        assert calls >= expected, (
            f"{path} calls a search-length guard {calls} time(s), expected at "
            f"least {expected} — a handler taking free text is unguarded")

    def test_the_guarded_files_still_exist(self):
        for path in GUARDED:
            assert (REPO / path).is_file(), f"{path} moved; update this sweep"

    def test_no_handler_takes_search_without_the_guard(self):
        """Sweep for the shape rather than the filenames above."""
        offenders = []
        for path in sorted((REPO / "vitalgraph/endpoint").glob("*.py")):
            src = path.read_text()
            takes_search = 'search: Optional[str] = Query(' in src
            if takes_search and "validate_search_text" not in src:
                offenders.append(path.relative_to(REPO).as_posix())
        assert not offenders, (
            "these accept a free-text search and never check its length: "
            + ", ".join(offenders))
