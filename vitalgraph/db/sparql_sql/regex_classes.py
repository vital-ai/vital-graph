"""XPath F&O character-class escapes -> POSIX ARE, for `REGEX` and `REPLACE`.

XPath/XQuery F&O — which SPARQL §17.4.3 defers to — has Unicode category escapes
(`\\p{L}`, `\\P{Nd}`) and XML name classes (`\\i`, `\\c`). POSIX ARE, which
PostgreSQL implements, has neither.

WHAT HAPPENED BEFORE. Not silence: PostgreSQL rejects them outright —

    'abc' ~ '\\p{L}'   ->  ERROR: invalid regular expression: invalid escape \\ sequence

which is a loud failure and, as failures go, the right one. This translation
replaces a loud failure with a correct answer; it is not rescuing a silent one.

THE TRAP, and why this needs the collation. POSIX classes are defined by the
LC_CTYPE in force. This database's ctype is `C`, under which they are ASCII-only:

    'é' ~ '[[:alpha:]]'                        ->  false
    ('é' COLLATE "und-x-icu") ~ '[[:alpha:]]'  ->  true

So translating `\\p{L}` to `[[:alpha:]]` and stopping there would turn a loud
error into a SILENTLY NARROW match on any non-ASCII text — strictly worse than
what it replaces, and invisible to an ASCII test suite. The operand is therefore
collated `und-x-icu` (Unicode root) whenever a class is translated, and only
then, so ordinary patterns keep their existing plans.

`und-x-icu` verified to classify `é` and `中` as alpha and Arabic-Indic `٣` as
digit.

CATEGORIES WITHOUT A FAITHFUL EQUIVALENT are deliberately NOT translated. `\\p{S}`
(symbols) has no POSIX class, and mapping it to something close would be the same
silent-narrowing mistake one level down. Those still reach PostgreSQL and still
raise, which keeps the honest failure for the cases that cannot be honestly
translated.
"""

from __future__ import annotations

import re

# The Unicode-aware collation used when a class is translated. Root locale: the
# question here is character CLASSIFICATION, not linguistic ordering, so a
# language-specific collation would add variance without adding fidelity.
CLASSIFY_COLLATION = '"und-x-icu"'

# XPath category -> POSIX class. Only entries that are faithful under an ICU
# ctype are listed; see the module docstring on why partial matches are omitted.
_CATEGORY_TO_POSIX = {
    "L": "[:alpha:]",        # any letter
    "Lu": "[:upper:]",
    "Ll": "[:lower:]",
    "Nd": "[:digit:]",
    "N": "[:digit:]",        # Nd plus Nl/No; ICU [:digit:] covers the decimal
    "P": "[:punct:]",
    "Zs": "[:space:]",
    "Z": "[:space:]",
    "C": "[:cntrl:]",
    "Cc": "[:cntrl:]",
}

# XML name classes (F&O §5.9). `\i` is a name START character, `\c` a name
# character; both are broader than ASCII, which is again why the collation
# matters.
_XML_CLASSES = {
    "i": "[:alpha:]_:",
    "c": "[:alnum:]_:.-",
}

_P_ESCAPE = re.compile(r"\\([pP])\{(\w+)\}")
_XML_ESCAPE = re.compile(r"\\([icIC])")


class UntranslatableRegexClass(ValueError):
    """An F&O class with no faithful POSIX equivalent."""


def translate_classes(pattern: str) -> tuple[str, bool]:
    """Rewrite F&O class escapes in `pattern`.

    Returns `(translated, needs_unicode_ctype)`. The flag is True when anything
    was translated, telling the caller to collate the operand — without it the
    POSIX classes are ASCII-only and the translation is wrong rather than
    merely unsupported.
    """
    changed = False

    def _cat(m: re.Match) -> str:
        nonlocal changed
        negate, name = m.group(1) == "P", m.group(2)
        posix = _CATEGORY_TO_POSIX.get(name)
        if posix is None:
            # Left alone on purpose: PostgreSQL will reject it, which is a
            # truthful failure. An approximate mapping here would be a silent
            # wrong answer, which is what this module exists to avoid.
            return m.group(0)
        changed = True
        return f"[^{posix}]" if negate else f"[{posix}]"

    def _xml(m: re.Match) -> str:
        nonlocal changed
        letter = m.group(1)
        body = _XML_CLASSES.get(letter.lower())
        if body is None:
            return m.group(0)
        changed = True
        return f"[^{body}]" if letter.isupper() else f"[{body}]"

    out = _P_ESCAPE.sub(_cat, pattern)
    out = _XML_ESCAPE.sub(_xml, out)
    return out, changed
