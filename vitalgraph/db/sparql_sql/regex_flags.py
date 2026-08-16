"""SPARQL regex flags -> PostgreSQL, in one place so the two emitters agree.

SPARQL 1.1 §17.4.3 defines REGEX and REPLACE in terms of XPath/XQuery F&O
regular expressions. PostgreSQL's `~` and `regexp_*` are POSIX ARE. The overlap
is large — `\\d`, `\\w`, `\\s`, quantifiers, groups and backreferences all agree —
but the DEFAULTS do not:

    XPath F&O   `.` does NOT match a newline unless the `s` flag is given
    PostgreSQL  `.` DOES match a newline by default

Measured:

    'a\\nb' ~ 'a.b'                    ->  true    (POSIX default — not SPARQL)
    regexp_like('a\\nb', 'a.b', 'p')   ->  false   (SPARQL default)

So a REGEX containing `.` over multi-line text matched rows SPARQL says it must
not, with no flag involved. This store holds document bodies, so multi-line text
is the ordinary case.

THE MAPPING. PostgreSQL's newline-sensitivity options are a 2x2 and cover
XPath's `s` and `m` exactly:

    SPARQL      `.` matches \\n   `^`/`$` at line breaks   PostgreSQL
    (none)      no                no                       p
    s           yes               no                       s
    m           no                yes                      n
    s + m       yes               yes                       w

WHY ONE MODULE. There are two REGEX emitters — `emit_expressions` for a filter
evaluated above the join, and `filter_pushdown` for one pushed into the term
subquery — and they had DIFFERENT flag handling. Which runs is decided by
whether the filter was pushable, i.e. by a performance heuristic, so the same
query returned different rows depending on an optimisation. That is the worst
shape a defect can take: it stops reproducing as soon as someone simplifies the
query to investigate. Both now call this.
"""

from __future__ import annotations

# XPath F&O flags SPARQL permits. `i` is handled separately by the callers,
# which choose an operator (`~*`) rather than an embedded option.
_DOTALL = "s"          # `.` matches newline
_MULTILINE = "m"       # `^`/`$` match at line breaks
_EXTENDED = "x"        # whitespace in the pattern is ignored
_LITERAL = "q"         # the whole pattern is a literal string


def pg_embedded_options(sparql_flags: str) -> str:
    """PostgreSQL embedded-option letters for a SPARQL flags string.

    Returned WITHOUT the `(?...)` wrapper so callers can decide placement.
    Always non-empty: the SPARQL default needs `p`, so "no flags" is not "no
    options" — that equivalence is exactly the bug this replaces.
    """
    f = sparql_flags or ""
    dotall = _DOTALL in f
    multiline = _MULTILINE in f

    # The 2x2. `p` for the default is the correction; the other three were
    # either absent or contradictory before.
    if dotall and multiline:
        opts = "w"
    elif dotall:
        opts = "s"
    elif multiline:
        opts = "n"
    else:
        opts = "p"

    if _EXTENDED in f:
        opts += _EXTENDED
    if _LITERAL in f:
        # `q` makes the rest of the pattern literal, so it must come last or it
        # would swallow the options that follow it.
        opts += _LITERAL
    return opts


def apply_to_literal(pattern_text: str, sparql_flags: str) -> tuple[str, bool]:
    """Options + class translation for a pattern whose TEXT we have.

    Returns `(pattern_text, needs_unicode_ctype)`. The flag propagates from
    `regex_classes.translate_classes`: POSIX classes are ASCII-only under this
    database's `C` ctype, so a translated pattern is only correct if the operand
    is collated. Ignoring it would turn an honest error into a silently narrow
    match on non-ASCII text.
    """
    from .regex_classes import translate_classes

    body, needs_ctype = translate_classes(pattern_text)
    return f"(?{pg_embedded_options(sparql_flags)}){body}", needs_ctype


def apply_to_pattern(pattern_sql: str, sparql_flags: str) -> str:
    """Prefix a SQL *pattern literal* with the embedded options.

    `pattern_sql` is SQL text that evaluates to the pattern — usually a quoted
    literal, sometimes a column reference for a runtime pattern. The options go
    inside the pattern rather than in a flags argument so this works for `~`,
    which has no flags parameter.
    """
    opts = pg_embedded_options(sparql_flags)
    if pattern_sql.startswith("'") and pattern_sql.endswith("'"):
        # A literal: splice the options inside the quotes.
        return f"'(?{opts})' || {pattern_sql}" if "||" in pattern_sql else \
               f"'(?{opts}){pattern_sql[1:-1]}'"
    # A runtime expression: concatenate, so the options still apply.
    return f"('(?{opts})' || {pattern_sql})"


def is_case_insensitive(sparql_flags: str) -> bool:
    """Whether `i` was requested.

    Kept here so both emitters read the flag the same way, even though they act
    on it differently (`~*` versus an embedded option).
    """
    return "i" in (sparql_flags or "")
