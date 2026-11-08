"""FTS index languages: what a valid one is, and the SQL each one becomes.

ONE place turns an index's `languages` into SQL (`issues/333`). There used to
be five hand-written copies — the trigger, the batch refresh, `vg:textSearch`,
the KGQuery FTS fast path and the CLI — and they had drifted:

  * the fast path used only the FIRST language (`fast_fts_frame._resolve_index`
    took `languages[0]`), so on an `['english', 'spanish']` index a hit through
    the Spanish stemmer was found by the pipeline and missed by the fast path;
  * no copy checked the name. It was pasted unquoted into
    `to_tsvector('{lang}'::regconfig, ...)`, and the trigger DDL runs through
    `conn.execute` with no arguments — the simple-query protocol, which accepts
    several statements — so a language name was SQL injection for anyone with
    space-write access;
  * and an UNKNOWN name was accepted: PL/pgSQL does not resolve
    `'x'::regconfig` until the trigger first fires, so the index was created,
    every write into it then failed inside auto-sync (which logs a warning and
    carries on), and the subject was silently never indexed.

So the builders here refuse any name that is not a plain identifier
(`check_language_name`), and `validate_fts_languages` checks a list against
the database before anything is created or changed.

The builders' output for a valid list without `cjk` is byte-identical to what
the copies emitted, so recorded plans and baselines stay comparable.

`cjk` IS A PSEUDO-LANGUAGE, not a text search configuration: it indexes runs of
Chinese/Japanese characters as bigrams + unigrams through the
`vitalgraph_cjk_*` SQL functions (`sparql_sql_admin`, `issues/333`), because
the default parser makes an unspaced run ONE lexeme. Its arm is
`vitalgraph_cjk_tsvector(text)` on the index side and
`vitalgraph_cjk_tsquery(text)` on the query side.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence

#: A PostgreSQL text search configuration name as an index may store it: a
#: plain lowercase identifier. Every built-in configuration matches. Anything
#: else is refused before it can reach SQL.
LANGUAGE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

DEFAULT_LANGUAGES = ("english",)

#: Languages that are not `pg_ts_config` entries, each served by SQL functions.
CJK = "cjk"
PSEUDO_LANGUAGES = frozenset({CJK})

#: Named in the refusal when `cjk` is asked for on a database without them.
CJK_INSTALL_HINT = ("run scripts/install_sql_functions.py --apply on this "
                    "database (as the app role) to install them")


class InvalidFtsLanguages(ValueError):
    """An FTS index language list that must not be stored or used.

    A domain outcome, not a server fault: endpoints answer it as
    INVALID_REQUEST in an HTTP 200 body.
    """


def check_language_name(lang: object) -> str:
    """`lang`, if it is safe to put in SQL; else raise `InvalidFtsLanguages`.

    Defence in depth behind `validate_fts_languages`: the query builders read
    languages from the registry, which predates validation, so a bad name
    already stored must fail loudly here rather than be interpolated.
    """
    if not isinstance(lang, str) or not LANGUAGE_NAME.match(lang):
        raise InvalidFtsLanguages(f"invalid FTS language name {lang!r}")
    return lang


def _effective(languages: Optional[Sequence[str]]) -> List[str]:
    langs = list(languages) if languages else list(DEFAULT_LANGUAGES)
    return [check_language_name(lang) for lang in langs]


def tsvector_expr(languages: Optional[Sequence[str]], text_sql: str,
                  joiner: str = " || ") -> str:
    """`to_tsvector(lang, text) || ...` over every language.

    `text_sql` is SQL the caller owns, e.g. `COALESCE(NEW.search_text, '')`.
    An empty list means `['english']`, as it always has. `cjk` becomes
    `vitalgraph_cjk_tsvector(text)`.
    """
    return joiner.join(
        f"vitalgraph_cjk_tsvector({text_sql})" if lang == CJK
        else f"to_tsvector('{lang}'::regconfig, {text_sql})"
        for lang in _effective(languages))


def tsquery_expr(languages: Optional[Sequence[str]], text_sql: str) -> str:
    """The OR (`||`) of `websearch_to_tsquery(lang, text)` over every language.

    `text_sql` is a quoted literal the caller has already escaped, or a
    parameter such as `$1`. One language gives the bare call; several are
    parenthesised, so the result can be dropped into `tsv @@ <expr>`.

    With `cjk`, its arm is `vitalgraph_cjk_tsquery(text)`, which is NULL when
    the query has no positive CJK. `tsquery || NULL` is NULL, hence:

        others present   COALESCE(<others> || <cjk>, <others>)
        cjk alone        <cjk>        -- NULL matches nothing

    NULL is read as "no match" by every consumer: `tsv @@ NULL` is not true,
    so WHERE drops the row; a correlated score subquery then returns no row;
    the hybrid's `CASE WHEN tsv @@ q ... ELSE 0` gives 0. It was chosen over an
    empty-tsquery sentinel because every empty-tsquery constructor raises a
    NOTICE on each call, which would flood the log once per query.
    """
    langs = _effective(languages)
    parts = [f"websearch_to_tsquery('{lang}'::regconfig, {text_sql})"
             for lang in langs if lang != CJK]
    others = None
    if len(parts) == 1:
        others = parts[0]
    elif parts:
        others = "(" + " || ".join(parts) + ")"
    if CJK not in langs:
        return others
    cjk = f"vitalgraph_cjk_tsquery({text_sql})"
    if others is None:
        return cjk
    return f"COALESCE({others} || {cjk}, {others})"


def has_cjk(languages: Optional[Sequence[str]]) -> bool:
    return CJK in (languages or ())


#: Statistics target for a `cjk` index's `tsv` column. The rarity weights
#: (`fts_rarity`) come from ANALYZE's most-common-element list, and every pair
#: rarer than its floor shares one weight. At the default target the list holds
#: 1,000 elements (floor 0.86% of rows on DRCD) and hit@3 was 0.801 against
#: 0.817 with exact frequencies; at 1000 it holds 10,000 (floor 0.06%) and hit@3
#: is 0.811. ANALYZE of 19,910 rows: 286 ms.
CJK_TSV_STATISTICS = 1000


def tsv_statistics_sql(table: str, languages: Optional[Sequence[str]]) -> str:
    """`ALTER TABLE ... SET STATISTICS` for the index's `tsv` column: raised for
    a `cjk` index, the default (-1) otherwise, so removing `cjk` undoes it."""
    target = CJK_TSV_STATISTICS if has_cjk(languages) else -1
    return f"ALTER TABLE {table} ALTER COLUMN tsv SET STATISTICS {target}"


async def validate_fts_languages(conn, languages: Optional[Iterable[str]]
                                 ) -> Optional[str]:
    """None if `languages` may be stored on an FTS index, else the reason.

    Each name must be a plain identifier and either a text search
    configuration visible on this database (`pg_ts_config_is_visible`, so the
    unqualified `'name'::regconfig` the trigger uses resolves to it) or a
    pseudo-language whose SQL functions are installed. At least one name, no
    duplicates.

    The function check is what makes deploy order safe: a server whose
    database has not had the pre-deploy step REFUSES `cjk`, naming the step,
    instead of accepting it and indexing nothing.
    """
    if languages is None:
        return "languages must be a non-empty list"
    if isinstance(languages, str):
        return "languages must be a list of names, not a string"
    langs = list(languages)
    if not langs:
        return "languages must be a non-empty list"
    for lang in langs:
        if not isinstance(lang, str) or not LANGUAGE_NAME.match(lang):
            return (f"invalid language name {lang!r}: expected a PostgreSQL "
                    f"text search configuration name such as 'english'")
    dupes = sorted({lang for lang in langs if langs.count(lang) > 1})
    if dupes:
        return f"duplicate languages: {', '.join(dupes)}"
    configs = [lang for lang in langs if lang not in PSEUDO_LANGUAGES]
    if configs:
        rows = await conn.fetch(
            "SELECT cfgname FROM pg_ts_config "
            "WHERE pg_ts_config_is_visible(oid) AND cfgname = ANY($1::text[])",
            configs)
        known = {r["cfgname"] for r in rows}
        unknown = [lang for lang in configs if lang not in known]
        if unknown:
            return (f"unknown text search configuration: {', '.join(unknown)} "
                    f"(see pg_ts_config for the configurations this database "
                    f"has, or 'cjk' for Chinese/Japanese)")
    if CJK in langs:
        missing = await missing_cjk_functions(conn)
        if missing:
            return (f"'cjk' needs SQL functions this database does not have "
                    f"({', '.join(missing)}): {CJK_INSTALL_HINT}")
    return None


async def missing_cjk_functions(conn) -> List[str]:
    """The `vitalgraph_cjk_*` signatures not installed on this database."""
    from .sparql_sql_admin import CJK_FUNCTION_SIGNATURES
    rows = await conn.fetch(
        "SELECT sig FROM unnest($1::text[]) AS sig "
        "WHERE to_regprocedure(sig) IS NULL", list(CJK_FUNCTION_SIGNATURES))
    return [r["sig"] for r in rows]
