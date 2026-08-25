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

THE MAPPING. PostgreSQL's newline-sensitivity options look like a 2x2 over
XPath's `s` and `m`, and that is how they were first read here:

    SPARQL      `.` matches \\n   `^`/`$` at line breaks   PostgreSQL
    (none)      no                no                       p
    s           yes               no                       s
    m           no                yes                      n
    s + m       yes               yes                       w

There is a THIRD axis, and no PostgreSQL option covers it. Every one of those
letters ties BRACKET NEGATION to `.`:

    p, n        `.` and `[^x]` both EXCLUDE the newline
    s, w        `.` and `[^x]` both ADMIT it

XPath does not tie them. `.` excludes the newline unless `s`; `[^x]` is a set
complement and ALWAYS admits it. So what SPARQL asks for by default -- dot
excludes, bracket admits -- is none of the four. Measured:

    'a\\nc' ~ '(?p)a[^b]c'   ->  false   (PostgreSQL `p`)
    'a\\nc' ~ '(?s)a[^b]c'   ->  true    (XPath, and what sparql10/regex wants)

So the dot is expressed in the PATTERN instead: `dot_to_non_newline` rewrites
each unescaped `.` outside a bracket to `[^\\n]`, and the option then only has
to place the anchors -- `s` normally, `w` for `m`. That gives all four XPath
combinations exactly.

A pattern arriving at RUN TIME has no text to rewrite, so `apply_to_pattern`
keeps the older `p`/`n`: `.` right, bracket negation wrong. There is no third
option there, and `.` is the commoner case.

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


def pg_embedded_options(sparql_flags: str,
                        dot_rewritten: bool = False) -> str:
    """PostgreSQL embedded-option letters for a SPARQL flags string.

    Returned WITHOUT the `(?...)` wrapper so callers can decide placement.
    Always non-empty: the SPARQL default needs `p`, so "no flags" is not "no
    options" — that equivalence is exactly the bug this replaces.
    """
    f = sparql_flags or ""
    dotall = _DOTALL in f
    multiline = _MULTILINE in f

    # PostgreSQL ties `.` and bracket negation together; XPath does not. See
    # the third-axis note in the module docstring. When the caller has already
    # rewritten `.` in the pattern text, the option only has to get the ANCHORS
    # right, and it should leave bracket negation matching newline as XPath
    # requires -- `s` and `w` do that. Without the rewrite we keep the older
    # `p`/`n`, which get `.` right and bracket negation wrong; for a pattern
    # that arrives at run time there is no text to rewrite and no third option.
    if dot_rewritten:
        opts = "w" if multiline else "s"
    elif dotall and multiline:
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


def dot_to_non_newline(pattern: str) -> str:
    """Rewrite every unescaped `.` outside a bracket expression to `[^\\n]`.

    XPath's `.` excludes the newline; PostgreSQL has no mode that excludes it
    from `.` while still admitting it in `[^x]`, so the dot is expressed
    directly and the option is left to handle the anchors. Escaped dots, and
    dots inside `[...]` (including POSIX `[: :]` names, where a `]` does not
    close the bracket), are literal already and are left alone.
    """
    out, i, n, in_bracket = [], 0, len(pattern), False
    while i < n:
        c = pattern[i]
        if c == "\\" and i + 1 < n:
            out.append(pattern[i:i + 2]); i += 2; continue
        if in_bracket:
            if c == "[" and i + 1 < n and pattern[i + 1] == ":":
                end = pattern.find(":]", i)
                if end != -1:
                    out.append(pattern[i:end + 2]); i = end + 2; continue
            if c == "]":
                in_bracket = False
            out.append(c); i += 1; continue
        if c == "[":
            in_bracket = True
            out.append(c); i += 1
            # A leading `^` and/or `]` are literal members, not a close.
            if i < n and pattern[i] == "^":
                out.append(pattern[i]); i += 1
            if i < n and pattern[i] == "]":
                out.append(pattern[i]); i += 1
            continue
        out.append("[^\\n]" if c == "." else c); i += 1
    return "".join(out)


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
    # `q` makes the whole pattern literal, so there is no metacharacter to
    # rewrite and doing so would corrupt it.
    rewrite = _DOTALL not in (sparql_flags or "") and _LITERAL not in (sparql_flags or "")
    if rewrite:
        body = dot_to_non_newline(body)
    opts = pg_embedded_options(sparql_flags, dot_rewritten=rewrite)
    return f"(?{opts}){body}", needs_ctype


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
