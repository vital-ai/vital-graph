"""A `contains` needle under 3 characters is rejected, not silently served.

`issues/070`. Under 3 characters there is no usable trigram for an INFIX match,
because the trigrams of a short string are all PADDED — show_trgm('XQ') is
{"  x"," xq","xq "} — and padding only holds at a word boundary. A mid-word
match can require none of them, so the GIN index scans itself: 10,467,626 index
rows and 12,613 ms to find nothing on a 10.4M-row term table.

The emitter has a backstop that keeps such a needle away from the index, but it
only buys a sequential scan — still seconds, and O(term table) on the table
projected to grow 10x. Telling the caller is the honest answer.

Rejection is a DOMAIN OUTCOME, so it comes back 200 with a status in the body,
per the convention the rest of these endpoints follow.
"""

from __future__ import annotations

import pytest

from vitalgraph.model.kgentities_model import (
    FrameCriteria, SlotCriteria, MIN_CONTAINS_LENGTH,
    validate_contains_criteria,
)


def _frame(*slots, nested=None):
    return FrameCriteria(frame_type="urn:f", slot_criteria=list(slots),
                         frame_criteria=nested)


def _slot(value, comparator="contains"):
    return SlotCriteria(slot_type="urn:s", value=value, comparator=comparator)


class TestRejected:

    @pytest.mark.parametrize("needle", ["X", "XQ", " a ", ""])
    def test_short_needles_are_rejected(self, needle):
        err = validate_contains_criteria([_frame(_slot(needle))])
        assert err and "at least 3" in err

    def test_the_message_names_the_indexed_alternatives(self):
        """A limit without a way forward just moves the problem to the caller."""
        err = validate_contains_criteria([_frame(_slot("XQ"))])
        assert "starts_with" in err and "ends_with" in err

    def test_nested_frames_are_walked(self):
        """KGQuery expresses depth by nesting, so a check at one level is no check."""
        deep = _frame(nested=[_frame(nested=[_frame(_slot("XQ"))])])
        assert validate_contains_criteria([deep])


class TestAccepted:

    @pytest.mark.parametrize("needle", ["XQZ", "alice", "CAT"])
    def test_three_or_more_characters_pass(self, needle):
        assert validate_contains_criteria([_frame(_slot(needle))]) is None

    @pytest.mark.parametrize("comparator", ["eq", "ne", "starts_with",
                                            "ends_with", "has_any"])
    def test_only_contains_is_restricted(self, comparator):
        """Anchored matches keep the padding and stay indexed at any length.

        Measured on a 2-character needle: 'XQ%' 1.0 ms and '%XQ' 0.03 ms against
        12,613 ms for '%XQ%'. Applying this limit to them would reject queries
        the index serves perfectly well.
        """
        assert validate_contains_criteria(
            [_frame(_slot("XQ", comparator=comparator))]) is None

    def test_a_non_string_value_is_not_second_guessed(self):
        """Only a string has a length that means anything here."""
        assert validate_contains_criteria([_frame(_slot(42))]) is None

    def test_empty_criteria_are_fine(self):
        assert validate_contains_criteria(None) is None
        assert validate_contains_criteria([]) is None


def test_the_threshold_matches_what_the_index_can_serve():
    """3 is not arbitrary: it is the trigram length pg_trgm needs for an infix."""
    assert MIN_CONTAINS_LENGTH == 3
