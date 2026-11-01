"""
N-Quads string unescaping.

The one implementation, for the quad wire format and the file importers alike.
It lives apart from `quad_format_utils` because `data_import_impl` runs it for
every term of an import and does not otherwise load that module's VitalSigns
and rdflib imports.
"""

import re

_ESCAPE = re.compile(r'\\(?:u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8}|.)', re.DOTALL)

_ECHAR = {
    '\\t': '\t',
    '\\b': '\b',
    '\\n': '\n',
    '\\r': '\r',
    '\\f': '\f',
    '\\"': '"',
    "\\'": "'",
    '\\\\': '\\',
}


def _decode_escape(match: 're.Match') -> str:
    token = match.group(0)
    if token[1] not in 'uU' or len(token) == 2:
        return _ECHAR.get(token, token)

    codepoint = int(token[2:], 16)
    # Not scalar values, so the grammar forbids them and PostgreSQL could not
    # store them. They stay as written, like any other invalid escape.
    if codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
        return token
    return chr(codepoint)


def unescape_nquads_string(s: str) -> str:
    """Unescape the N-Quads string escapes: ECHAR, \\uXXXX and \\UXXXXXXXX.

    ONE PASS, LEFT TO RIGHT. Each escape has to be read from where the previous
    one ended, or the second backslash of an escaped backslash pairs with the
    character after it. Chained `replace` calls did exactly that: a stored
    `C:\\new`, written `C:\\\\new`, came back as `C:\\`, a line break and `ew`
    (`issues/332`). No ordering of those calls is correct: backslashes first
    turns the same text into `C:` and a line break.
    """
    return _ESCAPE.sub(_decode_escape, s)
