"""SPARQL regex semantics are requested, not inherited from POSIX.

SPARQL 1.1 §17.4.3 defines REGEX and REPLACE in terms of XPath/XQuery F&O
regular expressions; PostgreSQL's `~` and `regexp_*` are POSIX ARE. The overlap
is large — `\\d`, `\\w`, quantifiers, groups and backreferences all agree — but the
DEFAULTS do not:

    XPath F&O   `.` does NOT match a newline unless `s` is given
    PostgreSQL  `.` DOES match a newline by default

Measured against PostgreSQL:

    'a\\nb' ~ 'a.b'                    ->  true    (POSIX default — not SPARQL)
    'a\\nb' ~ '(?p)a.b'                ->  false   (SPARQL default)

so a REGEX containing `.` over multi-line text matched rows SPARQL says it must
not, with no flag involved. This store holds document bodies.

There were also TWO regex emitters with different flag handling, and which one
ran was decided by whether the filter was pushable — a performance heuristic. So
the same query returned different rows depending on an optimisation, and stopped
reproducing as soon as anyone simplified it to investigate.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.regex_flags import (
    apply_to_pattern, is_case_insensitive, pg_embedded_options)


class TestFlagMapping:
    """The 2x2 of XPath's `s` and `m`, verified against PostgreSQL behaviour."""

    @pytest.mark.parametrize("sparql,pg", [
        ("",   "p"),   # `.` no newline, ^$ at string ends
        ("s",  "s"),   # `.` matches newline
        ("m",  "n"),   # ^$ at line breaks
        ("sm", "w"),   # both
        ("ms", "w"),   # order must not matter
    ])
    def test_the_newline_two_by_two(self, sparql, pg):
        assert pg_embedded_options(sparql) == pg

    def test_the_default_is_not_empty(self):
        """The whole defect in one assertion.

        "No flags" is not "no options": SPARQL's default needs `p`, and emitting
        nothing gets PostgreSQL's default, which is the opposite.
        """
        assert pg_embedded_options("") == "p"

    def test_s_and_m_together_are_not_contradictory(self):
        """`filter_pushdown` emitted `s` AND `n`, which ask for opposite
        newline behaviour. The single flag that means both is `w`."""
        opts = pg_embedded_options("sm")
        assert opts == "w"
        assert not ("s" in opts and "n" in opts)

    def test_extended_and_literal_are_carried(self):
        assert "x" in pg_embedded_options("x")
        assert "q" in pg_embedded_options("q")

    def test_literal_flag_comes_last(self):
        """`q` makes the REST of the pattern literal, so any option after it
        would be swallowed as pattern text."""
        opts = pg_embedded_options("xq")
        assert opts.endswith("q")

    def test_i_is_not_an_embedded_option(self):
        """Case-insensitivity is applied by choosing `~*`, so emitting `i` here
        as well would be redundant and, for REPLACE, doubled."""
        assert "i" not in pg_embedded_options("i")
        assert is_case_insensitive("i") and not is_case_insensitive("sm")


class TestPatternApplication:

    def test_a_literal_pattern_gets_the_options_inside_the_quotes(self):
        assert apply_to_pattern("'a.b'", "") == "'(?p)a.b'"

    def test_a_runtime_pattern_is_concatenated(self):
        """A pattern that is a column reference cannot be spliced textually."""
        out = apply_to_pattern("t.v1", "")
        assert "||" in out and "(?p)" in out


class TestBothEmittersAgree:
    """§4.2: pushdown must not change semantics.

    Asserted structurally — both emitters call the shared mapper — because
    comparing generated SQL would need two full plans for one query, and the
    property that matters is that neither has its own copy of the mapping.
    """

    def test_emit_expressions_uses_the_shared_mapper(self):
        import inspect
        from vitalgraph.db.sparql_sql import emit_expressions
        src = inspect.getsource(emit_expressions)
        assert "from .regex_flags import" in src

    def test_filter_pushdown_uses_the_shared_mapper(self):
        import inspect
        from vitalgraph.db.sparql_sql import filter_pushdown
        src = inspect.getsource(filter_pushdown)
        assert "from .regex_flags import" in src

    def test_neither_emitter_maps_flags_itself(self):
        """The two disagreed because each had its own mapping. A second copy
        reappearing is the regression to catch."""
        import inspect
        from vitalgraph.db.sparql_sql import emit_expressions, filter_pushdown
        for mod in (emit_expressions, filter_pushdown):
            src = inspect.getsource(mod)
            assert 'pg_embedded += ' not in src, (
                f"{mod.__name__} has its own flag mapping again")


class TestReplaceBackreferences:

    def test_backreferences_past_three_are_converted(self):
        """`$4` and beyond were left in the output as literal text."""
        import inspect
        from vitalgraph.db.sparql_sql import emit_expressions
        src = inspect.getsource(emit_expressions)
        assert "for n in range(1, 10)" in src, (
            "REPLACE no longer converts the full single-digit backreference "
            "range; a pattern with four capture groups emits a literal `$4`")


class TestCharacterClassTranslation:
    """§4.5: XPath category and XML-name escapes have no POSIX equivalent.

    Before, PostgreSQL rejected them outright —

        'abc' ~ '\\p{L}'  ->  ERROR: invalid escape \\ sequence

    which is a loud failure and, as failures go, the right one. Translating
    replaces a loud failure with a correct answer; it is not rescuing a silent
    one. (An earlier revision of the planning doc called this a silent
    pass-through. It was not; that was wrong.)
    """

    def test_unicode_categories_translate(self):
        from vitalgraph.db.sparql_sql.regex_classes import translate_classes
        assert translate_classes(r"\p{L}+")[0] == "[[:alpha:]]+"
        assert translate_classes(r"\p{Lu}")[0] == "[[:upper:]]"
        assert translate_classes(r"\p{Nd}")[0] == "[[:digit:]]"

    def test_negated_categories_translate(self):
        from vitalgraph.db.sparql_sql.regex_classes import translate_classes
        assert translate_classes(r"\P{Nd}")[0] == "[^[:digit:]]"

    def test_xml_name_classes_translate(self):
        from vitalgraph.db.sparql_sql.regex_classes import translate_classes
        assert translate_classes(r"\i")[0] == "[[:alpha:]_:]"
        assert translate_classes(r"\I")[0] == "[^[:alpha:]_:]"
        assert "[:alnum:]" in translate_classes(r"\c")[0]

    def test_a_category_with_no_faithful_equivalent_is_left_alone(self):
        """`\\p{S}` (symbols) has no POSIX class.

        Left untranslated so PostgreSQL still rejects it. Mapping it to
        something close would be the silent-narrowing mistake one level down —
        the same error as translating and forgetting the collation.
        """
        out, changed = translate_classes = __import__(
            "vitalgraph.db.sparql_sql.regex_classes", fromlist=["x"]
        ).translate_classes(r"\p{S}")
        assert out == r"\p{S}" and changed is False

    def test_an_ordinary_pattern_is_untouched(self):
        """Guard: translation must not fire on patterns that need nothing, or
        every regex would pay for the collation."""
        from vitalgraph.db.sparql_sql.regex_classes import translate_classes
        out, changed = translate_classes("a.b[0-9]+")
        assert out == "a.b[0-9]+" and changed is False

    def test_translation_signals_that_the_operand_needs_collating(self):
        """The trap this flag exists for.

        POSIX classes are ASCII-only under a `C` ctype:

            'é' ~ '[[:alpha:]]'                        -> false
            ('é' COLLATE "und-x-icu") ~ '[[:alpha:]]'  -> true

        so translating and NOT collating turns an honest error into a silently
        narrow match on non-ASCII text — worse than what it replaces, and
        invisible to an ASCII-only test suite.
        """
        from vitalgraph.db.sparql_sql.regex_classes import translate_classes
        assert translate_classes(r"\p{L}")[1] is True
        assert translate_classes("plain")[1] is False

    def test_both_emitters_collate_when_translating(self):
        import inspect
        from vitalgraph.db.sparql_sql import emit_expressions, filter_pushdown
        for mod in (emit_expressions, filter_pushdown):
            src = inspect.getsource(mod)
            assert "CLASSIFY_COLLATION" in src, (
                f"{mod.__name__} translates classes without collating the "
                f"operand, so non-ASCII text silently under-matches")
