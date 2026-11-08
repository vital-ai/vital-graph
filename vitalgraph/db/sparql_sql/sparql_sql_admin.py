"""
Admin operations for the sparql_sql backend.

Provides init / purge / delete / info / list-spaces for the SPARQL-SQL
pure-PostgreSQL backend.  All DDL is owned by SparqlSQLSchema; this
module only orchestrates the operations.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from ..common.models import GraphData, SpaceData, UserData
from ..db_admin_inf import DbAdminInterface
from .sparql_sql_schema import SparqlSQLSchema
from .space_names import space_prefix

logger = logging.getLogger(__name__)

# DDL for deterministic UUID v5 function — mirrors Python's _generate_term_uuid()
# exactly, including \x00 separators. Requires pgcrypto extension.
_VITALGRAPH_ISO_TO_UTC_DDL = """
-- Parse a strict ISO-8601 literal to a UTC timestamp, IMMUTABLY.
--
-- The obvious `CAST(term_text AS TIMESTAMP)` cannot be used in a generated
-- column: it honours the DateStyle setting, so PostgreSQL rejects it with
-- "generation expression is not immutable". `to_timestamp` is STABLE for the
-- same reason. num_val exists only because text->numeric happens to be
-- immutable — that was luck, not a pattern that generalises (issues/053).
--
-- Assembling the value from components avoids the settings dependency
-- entirely: make_timestamp, make_interval, regexp_match and the text->int
-- casts are all immutable, so this function genuinely is too. Nothing is
-- mislabelled, which matters because an IMMUTABLE lie produces wrong answers
-- after a dump/restore rather than an error.
--
-- An explicit offset is applied to normalise to UTC, so
-- 2020-01-01T12:00:00+05:00 and 2020-01-01T07:00:00+00:00 compare equal — the
-- case lexicographic comparison on term_text gets silently backwards.
-- A literal with no offset is taken as UTC. That is a policy choice: the
-- alternative, ::timestamptz, reads it in the SESSION timezone and is
-- therefore not immutable and not reproducible.
--
-- Returns NULL for anything that is not a strict ISO date/dateTime, which is
-- what makes it safe to apply across a term table holding URIs and free text.
CREATE OR REPLACE FUNCTION vitalgraph_iso_to_utc(t text)
RETURNS timestamp
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $iso$
SELECT CASE WHEN m IS NULL THEN NULL ELSE
  make_timestamp(m[1]::int, m[2]::int, m[3]::int,
                 COALESCE(m[4], '0')::int, COALESCE(m[5], '0')::int,
                 COALESCE(m[6], '0')::double precision)
  - make_interval(
      hours => COALESCE(m[8], '0')::int * CASE WHEN m[7] = '-' THEN -1 ELSE 1 END,
      mins  => COALESCE(m[9], '0')::int * CASE WHEN m[7] = '-' THEN -1 ELSE 1 END)
END
FROM regexp_match(
  t,
  '^(\\d{4})-(\\d{2})-(\\d{2})(?:[T ](\\d{2}):(\\d{2}):(\\d{2}(?:\\.\\d+)?))?(?:([+-])(\\d{2}):(\\d{2})|Z)?$'
) AS m
$iso$;
"""


_VITALGRAPH_TERM_UUID_DDL = """
CREATE OR REPLACE FUNCTION vitalgraph_term_uuid(
    p_text text, p_type char(1),
    p_lang text DEFAULT NULL,
    p_datatype_id bigint DEFAULT NULL
) RETURNS uuid AS $$
DECLARE
    name_bytes bytea;
    ns_bytes bytea;
    hash bytea;
    raw bytea;
BEGIN
    name_bytes := convert_to(p_text, 'UTF8') || '\\x00'::bytea || convert_to(p_type, 'UTF8');
    IF p_lang IS NOT NULL THEN
        name_bytes := name_bytes || '\\x00'::bytea || convert_to('lang:' || p_lang, 'UTF8');
    END IF;
    IF p_datatype_id IS NOT NULL THEN
        name_bytes := name_bytes || '\\x00'::bytea || convert_to('datatype:' || p_datatype_id::text, 'UTF8');
    END IF;
    ns_bytes := '\\x6ba7b8109dad11d180b400c04fd430c8'::bytea;
    hash := digest(ns_bytes || name_bytes, 'sha1');
    raw := substring(hash from 1 for 16);
    raw := set_byte(raw, 6, (get_byte(raw, 6) & 15) | 80);
    raw := set_byte(raw, 8, (get_byte(raw, 8) & 63) | 128);
    RETURN encode(raw, 'hex')::uuid;
END;
$$ LANGUAGE plpgsql IMMUTABLE;
"""


# CJK FULL-TEXT SEARCH (`issues/333`): the `cjk` pseudo-language of an FTS index.
#
# PostgreSQL's default parser splits on spaces and punctuation, so unspaced
# Chinese/Japanese becomes ONE lexeme per run ("我夢到樓梯" is a single word)
# and only an exact-run query can match it. These functions index each run of
# CJK characters as overlapping BIGRAMS plus every character as a UNIGRAM, and
# turn a query into the same units. No dictionary and no C extension, so it runs
# unchanged wherever PostgreSQL does.
#
# By SCRIPT, not language: a run is a maximal sequence of code points in the
# class below (kana, CJK unified ideographs + Ext A, compatibility ideographs,
# Ext B-H). Everything else, Latin text and full-width punctuation included, ends
# a run and is invisible here; an index's other languages index it as before.
# Traditional and Simplified are different code points and do NOT match each
# other. Hangul is excluded: Korean is space-delimited.
#
# IMMUTABLE honestly: `normalize` (NFKC folds ｶﾀｶﾅ/ＡＢＣ and maps compatibility
# ideographs to unified ones), regexp over explicit code points (no
# locale-dependent class), substr, and to_tsvector with a constant config. The
# output depends on the Unicode tables built into PostgreSQL, so re-check `cjk`
# indexes after a PG major upgrade.
#
# CHANGING ANY BODY IS A RE-INDEX: it changes what every existing `cjk` row
# should hold. Ship it as a migration that refreshes every `cjk` index
# (`refresh-fts`), never as a silent CREATE OR REPLACE.
#
# Requires a UTF8 database (`normalize`). Measured: 38 µs per 40-character row,
# ~28x `to_tsvector('english')`; an earlier set-returning version cost 120 µs.
_CJK_CLASS = (r"぀-ヿ㐀-䶿一-鿿豈-﫿"
              r"\U00020000-\U0003134F")

_VITALGRAPH_CJK_RUNS_DDL = r"""
CREATE OR REPLACE FUNCTION vitalgraph_cjk_runs(t text) RETURNS text[]
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $f$
  SELECT array_remove(string_to_array(regexp_replace(normalize(t, NFKC),
    '[^""" + _CJK_CLASS + r"""]+', ' ', 'g'), ' '), '')
$f$;
"""

# Bigrams FIRST and in order, so their positions are consecutive and a quoted
# phrase (`'夢到' <-> '到樓' <-> '樓梯'`) matches; unigrams after, so a
# one-character query ("夢") matches a character inside a longer run without
# breaking any chain. A one-character run yields its unigram only.
_VITALGRAPH_CJK_INDEX_TEXT_DDL = r"""
CREATE OR REPLACE FUNCTION vitalgraph_cjk_index_text(t text) RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE AS $f$
DECLARE r text; n int; bi text := ''; uni text := '';
BEGIN
  FOREACH r IN ARRAY vitalgraph_cjk_runs(t) LOOP
    n := length(r);
    FOR i IN 1 .. n - 1 LOOP bi  := bi  || substr(r, i, 2) || ' '; END LOOP;
    FOR i IN 1 .. n     LOOP uni := uni || substr(r, i, 1) || ' '; END LOOP;
  END LOOP;
  RETURN bi || uni;
END $f$;
"""

_VITALGRAPH_CJK_TSVECTOR_DDL = r"""
CREATE OR REPLACE FUNCTION vitalgraph_cjk_tsvector(t text) RETURNS tsvector
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $f$
  SELECT to_tsvector('simple'::regconfig, coalesce(vitalgraph_cjk_index_text(t), ''))
$f$;
"""

# The query, websearch-shaped. Per whitespace token (a "quoted span" counts as
# one), each CJK run becomes its bigrams, or its unigram if it is one character:
#   bare        the run's terms ORed — a whole question must still match, and
#               ts_rank_cd orders by how many pairs hit
#   "quoted"    the run as a REQUIRED phrase chain, '夢到' <-> '到樓' <-> '樓梯'
#   -negated    the chain negated AS A UNIT; negating each pair would over-exclude
#   `or`        ignored: bare terms are ORed already
# NULL when there is no positive CJK, so the arm contributes nothing; the
# builder wraps it in COALESCE (`fts_languages.tsquery_expr`). Lexemes come only
# from the CJK class — no quote, backslash or operator can occur — and are still
# passed through quote_literal, so query text never reaches tsquery syntax.
_VITALGRAPH_CJK_TSQUERY_DDL = r"""
CREATE OR REPLACE FUNCTION vitalgraph_cjk_tsquery(q text) RETURNS tsquery
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $f$
DECLARE tok text[]; neg boolean; quoted boolean; r text; n int;
        terms text[]; part tsquery; chain tsquery; bare tsquery; req tsquery;
        has_pos boolean := false;
BEGIN
  IF q IS NULL THEN RETURN NULL; END IF;
  FOR tok IN SELECT regexp_matches(q, '(-?)"([^"]*)"?|(-?)(\S+)', 'g') LOOP
    neg    := coalesce(tok[1], tok[3]) = '-';
    quoted := tok[2] IS NOT NULL;
    FOREACH r IN ARRAY coalesce(vitalgraph_cjk_runs(coalesce(tok[2], tok[4])), '{}') LOOP
      n := length(r);
      terms := CASE WHEN n = 1 THEN ARRAY[r]
                    ELSE ARRAY(SELECT substr(r, i, 2)
                               FROM generate_series(1, n - 1) i ORDER BY i) END;
      IF quoted OR neg THEN
        chain := NULL;
        FOREACH r IN ARRAY terms LOOP
          part  := quote_literal(r)::tsquery;
          chain := CASE WHEN chain IS NULL THEN part ELSE chain <-> part END;
        END LOOP;
        IF neg THEN chain := !! chain; ELSE has_pos := true; END IF;
        req := CASE WHEN req IS NULL THEN chain ELSE req && chain END;
      ELSE
        FOREACH r IN ARRAY terms LOOP
          part := quote_literal(r)::tsquery;
          bare := CASE WHEN bare IS NULL THEN part ELSE bare || part END;
        END LOOP;
        has_pos := true;
      END IF;
    END LOOP;
  END LOOP;
  IF NOT has_pos THEN RETURN NULL; END IF;
  IF bare IS NULL THEN RETURN req; END IF;
  IF req  IS NULL THEN RETURN bare; END IF;
  RETURN bare && req;
END $f$;
"""


# The POSITIVE terms of a query, deduplicated: what the rarity-weighted score
# sums over (`fts_rarity`, issues/333 D2). Same tokens and the same run rules as
# vitalgraph_cjk_tsquery, so the weights and the match see the same terms; a
# negated token's terms are left out, a quoted one's are in. Empty for a query
# with no positive CJK. Measured on DRCD (real zh-Hant, 1,000 questions):
# weighting these by rarity lifted the full-text arm from 0.682 to 0.817 hit@3
# over ts_rank_cd.
_VITALGRAPH_CJK_QUERY_TERMS_DDL = r"""
CREATE OR REPLACE FUNCTION vitalgraph_cjk_query_terms(q text) RETURNS text[]
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $f$
DECLARE tok text[]; r text; n int; out text[] := '{}';
BEGIN
  IF q IS NULL THEN RETURN out; END IF;
  FOR tok IN SELECT regexp_matches(q, '(-?)"([^"]*)"?|(-?)(\S+)', 'g') LOOP
    CONTINUE WHEN coalesce(tok[1], tok[3]) = '-';
    FOREACH r IN ARRAY coalesce(vitalgraph_cjk_runs(coalesce(tok[2], tok[4])), '{}') LOOP
      n := length(r);
      IF n = 1 THEN
        IF NOT r = ANY(out) THEN out := out || r; END IF;
      ELSE
        FOR i IN 1 .. n - 1 LOOP
          IF NOT substr(r, i, 2) = ANY(out) THEN out := out || substr(r, i, 2); END IF;
        END LOOP;
      END IF;
    END LOOP;
  END LOOP;
  RETURN out;
END $f$;
"""


# EVERY function the schema needs, in one place.
#
# There are two installers — `SparqlSQLAdmin.init_tables` (the app/admin path)
# and `scripts/perf_init_db.py` (the perf runner, which talks to a raw asyncpg
# connection rather than a db_impl). They drifted: perf_init_db installed
# `vitalgraph_term_uuid` and not `vitalgraph_iso_to_utc`, so a genuinely fresh
# perf database raised
#
#     asyncpg.exceptions.UndefinedFunctionError:
#       function vitalgraph_iso_to_utc(text) does not exist
#
# and every space-creating bench errored at setup. It went unnoticed because the
# test stack reused a data volume that already had the function, so only a truly
# clean database — which is what pinning the postgres minor forced — exposed it.
#
# Both installers now iterate this tuple. Add a function here and both paths get
# it; that is the point.
#
# Keyed by the `regprocedure` signature, so `scripts/install_sql_functions.py`
# (the pre-deploy step for databases initialised before a function existed) can
# tell which are missing. IN DEPENDENCY ORDER: a LANGUAGE sql body is checked at
# CREATE time, so a function must follow the ones it calls.
FUNCTIONS = (
    ("vitalgraph_term_uuid(text,character,text,bigint)", _VITALGRAPH_TERM_UUID_DDL),
    ("vitalgraph_iso_to_utc(text)", _VITALGRAPH_ISO_TO_UTC_DDL),
    ("vitalgraph_cjk_runs(text)", _VITALGRAPH_CJK_RUNS_DDL),
    ("vitalgraph_cjk_index_text(text)", _VITALGRAPH_CJK_INDEX_TEXT_DDL),
    ("vitalgraph_cjk_tsvector(text)", _VITALGRAPH_CJK_TSVECTOR_DDL),
    ("vitalgraph_cjk_tsquery(text)", _VITALGRAPH_CJK_TSQUERY_DDL),
    ("vitalgraph_cjk_query_terms(text)", _VITALGRAPH_CJK_QUERY_TERMS_DDL),
)
FUNCTION_DDL = tuple(ddl for _sig, ddl in FUNCTIONS)

#: What an index needs before it may name `cjk` (`fts_languages`).
CJK_FUNCTION_SIGNATURES = tuple(sig for sig, _ in FUNCTIONS if "_cjk_" in sig)


class SparqlSQLAdmin(DbAdminInterface):
    """Admin operations for the sparql_sql backend."""

    def __init__(self):
        self.schema = SparqlSQLSchema()

    # ---- check -----------------------------------------------------------

    async def check_admin_tables(self, db_impl) -> Dict[str, Any]:
        table_names = self.schema.ADMIN_TABLE_NAMES
        check_query = """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name IN ({})
        """.format(", ".join(f"'{n}'" for n in table_names))

        rows = await db_impl.execute_query(check_query)
        found = [r['table_name'] for r in rows] if rows else []
        return {
            'expected': len(table_names),
            'found': len(found),
            'tables': found,
        }

    # ---- init ------------------------------------------------------------

    async def init_tables(self, db_impl) -> bool:
        # Ensure extensions + functions (idempotent — always runs)
        await db_impl.execute_update("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        await db_impl.execute_update("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        await db_impl.execute_update("CREATE EXTENSION IF NOT EXISTS vector")
        await db_impl.execute_update("CREATE EXTENSION IF NOT EXISTS postgis")
        for _fn_ddl in FUNCTION_DDL:
            await db_impl.execute_update(_fn_ddl)

        status = await self.check_admin_tables(db_impl)

        if status['found'] == status['expected']:
            logger.info("All %d admin tables already exist", status['expected'])
            return True

        # Create tables
        for stmt in self.schema.create_admin_tables_sql():
            await db_impl.execute_update(stmt)

        # Create indexes
        for stmt in self.schema.create_admin_indexes_sql():
            await db_impl.execute_update(stmt)

        # Seed data
        for stmt in self.schema.get_admin_seed_sql():
            await db_impl.execute_update(stmt)

        logger.info("SPARQL-SQL admin tables initialized successfully")
        return True

    # ---- purge -----------------------------------------------------------

    async def purge_tables(self, db_impl) -> bool:
        # Drop all per-space tables first
        spaces = await self.list_spaces(db_impl)
        for sp in spaces:
            for stmt in self.schema.drop_space_tables_sql(sp.space_id):
                await db_impl.execute_update(stmt)
            logger.info("Dropped per-space tables for: %s", sp.space_id)

        # Truncate admin tables in reverse dependency order
        for stmt in self.schema.truncate_admin_tables_sql():
            await db_impl.execute_update(stmt)

        # Re-seed
        for stmt in self.schema.get_admin_seed_sql():
            await db_impl.execute_update(stmt)

        logger.info("SPARQL-SQL tables purged and re-seeded")
        return True

    # ---- delete ----------------------------------------------------------

    async def delete_tables(self, db_impl) -> bool:
        # Drop all per-space tables first
        spaces = await self.list_spaces(db_impl)
        for sp in spaces:
            for stmt in self.schema.drop_space_tables_sql(sp.space_id):
                await db_impl.execute_update(stmt)

        # Drop admin tables in reverse dependency order
        for stmt in self.schema.drop_admin_tables_sql():
            await db_impl.execute_update(stmt)

        logger.info("SPARQL-SQL tables deleted")
        return True

    # ---- info ------------------------------------------------------------

    async def get_info(self, db_impl, config=None) -> Dict[str, Any]:
        info: Dict[str, Any] = {
            'backend': 'SPARQL-SQL (Pure PostgreSQL)',
            'status': 'Connected',
        }

        # Config-derived info
        if config:
            sparql_sql_config = config.get_sparql_sql_config()
            info['sidecar_url'] = sparql_sql_config.get('sidecar', {}).get('url', 'N/A')
            pg_config = sparql_sql_config.get('database', {})
            info['pg_host'] = pg_config.get('host', 'N/A')
            info['pg_database'] = pg_config.get('database', 'N/A')

        # Admin table check
        status = await self.check_admin_tables(db_impl)
        info['admin_tables'] = status

        if status['found'] >= 5:
            info['init_state'] = 'initialized'

            # Space count and per-space table check
            spaces = await self.list_spaces(db_impl)
            info['space_count'] = len(spaces)
            info['spaces'] = []
            for sp in spaces:
                sid = sp.space_id
                term_tbl = f"{space_prefix(sid)}_term"
                quad_tbl = f"{space_prefix(sid)}_rdf_quad"
                tbl_check = await db_impl.execute_query(
                    "SELECT COUNT(*) as c FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name IN ($1, $2)",
                    [term_tbl, quad_tbl]
                )
                tbl_count = tbl_check[0]['c'] if tbl_check else 0
                info['spaces'].append({'space_id': sid, 'tables_ok': tbl_count == 2})

            # pg_trgm
            ext_result = await db_impl.execute_query(
                "SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
            info['pg_trgm'] = bool(ext_result)

            # User count
            user_result = await db_impl.execute_query(
                'SELECT COUNT(*) as count FROM "user"')
            info['user_count'] = user_result[0]['count'] if user_result else 0
        elif status['found'] > 0:
            info['init_state'] = 'partially_initialized'
        else:
            info['init_state'] = 'uninitialized'

        return info

    # ---- list spaces -----------------------------------------------------

    async def list_spaces(self, db_impl) -> List[SpaceData]:
        try:
            rows = await db_impl.execute_query(
                "SELECT space_id, space_name, space_description, tenant, update_time "
                "FROM space ORDER BY space_id")
            return [SpaceData.from_row(r) for r in rows] if rows else []
        except Exception:
            return []

    # ---- list graphs -----------------------------------------------------

    async def list_graphs(self, db_impl, space_id: str = None) -> List[GraphData]:
        try:
            if space_id:
                rows = await db_impl.execute_query(
                    "SELECT graph_id, space_id, graph_uri, graph_name, created_time "
                    "FROM graph WHERE space_id = $1 ORDER BY graph_id",
                    [space_id])
            else:
                rows = await db_impl.execute_query(
                    "SELECT graph_id, space_id, graph_uri, graph_name, created_time "
                    "FROM graph ORDER BY space_id, graph_id")
            return [GraphData.from_row(r) for r in rows] if rows else []
        except Exception:
            return []

    # ---- list users ------------------------------------------------------

    async def list_users(self, db_impl) -> List[UserData]:
        try:
            rows = await db_impl.execute_query(
                'SELECT user_id, username, password, email, tenant, update_time '
                'FROM "user" ORDER BY username')
            return [UserData.from_row(r) for r in rows] if rows else []
        except Exception:
            return []
