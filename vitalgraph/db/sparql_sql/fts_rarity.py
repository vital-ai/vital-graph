"""Rarity-weighted scoring for the `cjk` full-text arm (`issues/333`, D2).

`ts_rank_cd` weighs every matched lexeme alike. For CJK bigrams that ranks
badly: a question shares common pairs (什麼, 我們, 那個) with half the corpus and
its one distinctive pair with the message it means. Measured on DRCD (real
Traditional Chinese, 19,910 sentences in one graph, 1,000 questions with
a known answer): weighting each matched pair by ln(N/df) lifted the full-text
arm from 0.682 to 0.817 hit@3 and from 0.517 to 0.725 hit@1. That is BM25's
rarity weighting, which is how the Lucene engines make CJK bigrams work.

THE SCORE is rarity-weighted COVERAGE:

    sum(w(p) for the query's pairs p the row contains) / sum(w(p) over all of them)

with w(p) = ln(1 / freq(p)), freq the fraction of rows containing p. It orders
rows exactly as the raw sum does for one query (the denominator is a constant),
and lies in [0, 1], which the hybrid needs: it is added to a cosine similarity,
and a raw idf sum (5-30) would swamp it.

THE FREQUENCIES are PostgreSQL's own: `pg_stats.most_common_elems` /
`most_common_elem_freqs` for the index's `tsv` column, which ANALYZE keeps.
Nothing new to maintain. A pair not in the list is rarer than every pair that
is, so it gets the list's floor frequency (the minimum it records): the
approximation sits only among rare pairs, where all weights are high. Table-wide,
not per graph: a pair's rarity is a property of the corpus.

Read ONCE per statement, before emit (`load_cjk_weights`, one round trip per
distinct (index, search text)), into `aliases.cjk_weights`; emit is pure and
reads it there. Anything missing — no statistics yet, an install without
`vitalgraph_cjk_query_terms`, a failed read — leaves no entry, and the arm keeps
`ts_rank_cd`: a ranking choice must never fail a query.
"""

from __future__ import annotations

import logging
import math
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: aliases.cjk_weights key -> [(term, weight)]
WeightKey = Tuple[str, str]

_WEIGHTS_SQL = """
WITH s AS (
    SELECT most_common_elems::text::text[] AS e, most_common_elem_freqs AS f
    FROM pg_stats
    WHERE schemaname = 'public' AND tablename = $1 AND attname = 'tsv'
    LIMIT 1
)
SELECT t.term,
       (SELECT s.f[array_position(s.e, t.term)] FROM s) AS freq,
       (SELECT s.f[array_length(s.e, 1) + 1] FROM s) AS floor
FROM unnest(vitalgraph_cjk_query_terms($2)) WITH ORDINALITY AS t(term, i)
ORDER BY t.i
"""


def _ranked_text_calls(plan, depth: int = 0):
    """Every `vg:textSearch` / `vg:hybridSearch` call in the plan: the two that
    RANK by the full-text arm (`textMatch` is boolean)."""
    from .vg_functions import VG_HYBRID_SEARCH, VG_TEXT_SEARCH
    from ..jena_sparql.jena_types import ExprFunction
    if plan is None or depth > 64:
        return

    def walk(e):
        if isinstance(e, ExprFunction):
            if getattr(e, "function_iri", None) in (VG_TEXT_SEARCH, VG_HYBRID_SEARCH):
                yield e
            for a in (e.args or []):
                yield from walk(a)

    for e in [getattr(plan, "extend_expr", None)] + list(getattr(plan, "filter_exprs", None) or []):
        if e is not None:
            yield from walk(e)
    for c in plan.children or []:
        yield from _ranked_text_calls(c, depth + 1)


def weights_from_rows(rows) -> Optional[List[Tuple[str, float]]]:
    """[(term, weight)] from the statistics read, or None to keep `ts_rank_cd`."""
    if not rows:
        return None
    out = []
    for r in rows:
        if not _CJK_TERM.match(r["term"] or ""):
            continue                 # not a term the function produces
        freq = r["freq"] if r["freq"] is not None else r["floor"]
        if freq is None:
            return None              # no statistics for the column yet
        freq = min(1.0, max(float(freq), 1e-9))
        # A pair in every row carries no information; floored above 0 so a
        # query made only of such pairs still divides by something.
        out.append((r["term"], max(math.log(1.0 / freq), 1e-6)))
    return out or None


async def load_cjk_weights(plan, ctx, conn) -> None:
    """Fill `ctx.aliases.cjk_weights` for every ranked text call on a `cjk` index."""
    from .fts_languages import CJK
    from .space_names import space_prefix
    from .vg_functions import (
        _resolve_fts_languages, _resolve_index_name, extract_text_search_args)
    store: Dict[WeightKey, List[Tuple[str, float]]] = {}
    ctx.aliases.cjk_weights = store
    if conn is None:
        return
    for expr in _ranked_text_calls(plan):
        targs = extract_text_search_args(expr)
        if targs is None:
            continue
        index = _resolve_index_name(targs.index_name, "fts", ctx)
        if CJK not in _resolve_fts_languages(index, ctx):
            continue
        key = (index, targs.search_text)
        if key in store:
            continue
        table = f"{space_prefix(ctx.space_id)}_fts_{index}"
        try:
            rows = await conn.fetch(_WEIGHTS_SQL, table, targs.search_text)
        except Exception as e:      # an install without the function, a lost connection
            logger.debug("cjk weights unavailable for %s: %s", table, e)
            continue
        w = weights_from_rows(rows)
        if w:
            store[key] = w


def cjk_weighted_coverage_sql(tsv_col: str, weights: List[Tuple[str, float]]) -> str:
    """The rarity-weighted coverage of the query's terms in `tsv_col`, in [0, 1].

    Terms are drawn from the CJK character class (no quote, backslash or
    tsquery operator can occur), and are still quoted here.
    """
    total = sum(w for _t, w in weights)
    parts = " + ".join(
        f"(CASE WHEN {tsv_col} @@ {_lexeme(t)} THEN {w:.6f} ELSE 0 END)"
        for t, w in weights)
    return f"(({parts}) / {total:.6f})"


#: The CJK class of `vitalgraph_cjk_runs`: every term the function returns is
#: drawn from it, so a term holding anything else did not come from there.
_CJK_TERM = re.compile(
    "^[\u3040-\u30FF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\U00020000-\U0003134F]{1,2}$")


def _lexeme(term: str) -> str:
    """`'<term>'::tsquery`: a bare lexeme, which a CJK term can be as it is."""
    if not _CJK_TERM.match(term):
        raise ValueError(f"not a cjk query term: {term!r}")
    return f"'{term}'::tsquery"
