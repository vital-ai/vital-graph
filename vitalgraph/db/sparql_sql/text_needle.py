"""Can the trigram index serve this text search, and what to do when it cannot.

The GIN trigram index on `term_text` serves an INFIX match only when the needle
yields a trigram that can be REQUIRED. `show_trgm('XQ')` is `{"  x"," xq","xq "}`
— every trigram PADDED — and padding only holds at a word boundary, so an infix
match that may land mid-word cannot require any of them. The index then scans
itself: `term_text ILIKE '%XQ%'` on a 10.4M-row term table returns 10,467,626
index rows and takes 12,613 ms to find nothing.

Anchored patterns keep the padding and stay fast at ANY length — `'XQ%'` 1.0 ms,
`'%XQ'` 0.03 ms — which is why this applies to unanchored matches alone, and why
the answer for a caller who wants two-character search is `STRSTARTS`, not a
faster scan.

WHAT REPLACED WHAT

The previous answer was to keep the scan and make it cheaper: emit
`(term_text || '')`, a value-preserving no-op that makes the index inapplicable
so the planner takes a sequential scan instead (12,613 ms -> 4,041 ms), and
sample the term table at generation time so PRICING that scan stayed cheap
(78,991 ms -> 45 ms of generation). Both optimised the wrong end. The sample only
decided HOW to run a query whose execution was still a full scan of every term,
and the whole point of pushing a text filter down is to be selective.

So an unservable needle is no longer pushed. The same FILTER is evaluated above
the join, over rows the query already produced — identical answers, bounded by
the result set instead of by the corpus.

WHY DECLINING IS NOT THE WHOLE FIX

Declining is semantically free but not free: when the text search is the query's
ONLY selective constraint, not pushing it means materialising the join first. So
`unbounded_scan_error` refuses that one case outright rather than trading a
4-second term scan for something worse. It fires only when the needle is
unservable AND nothing else bounds the BGP AND the term table is genuinely large,
because the same query must not error in production and pass on a fixture — the
size gate is why that risk is stated in the message rather than hidden.

WHY THE RULE IS NOT "SHORTER THAN THREE CHARACTERS"

That was tried and is wrong. It rejects legal SPARQL that the W3C corpus depends
on — `CONTAINS(?str, "a")`, `regex(?val, "a.c")`, `regex(?val, "ab*c")`, and
`CONTAINS("abc"@en, "b")`, which has no variable and never touches a term table
at all. 29 DAWG `.rq` files use these operators. Declining a PUSH-DOWN is
invisible to conformance; refusing a QUERY is not.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

MIN_TRIGRAM_NEEDLE = 3

# Below this the term scan the decline avoids is not worth erroring over: a
# sequential scan of a small term table is milliseconds, and a query that errors
# on a large space while passing on a fixture is the failure mode this gate is
# most likely to introduce. Read from `reltuples`, so it costs no scan itself.
UNBOUNDED_SCAN_TERMS = 1_000_000

_REGEX_META = set(".*+?[](){}|^$\\")
# Quantifiers that make the character before them OPTIONAL, so it cannot be part
# of a REQUIRED literal run: `ab*c` requires only 'a' and 'c'.
_OPTIONAL_QUANT = ("*", "?")


class UnindexableTextSearch(ValueError):
    """A text search that can neither be indexed nor bounded by anything else."""


def regex_is_prefix_anchored(pattern: str) -> bool:
    """Does the pattern start at the beginning of the value?

    Only `^` counts. A trailing `$` anchors the END, which pg_trgm cannot use to
    require a padded trigram the way a prefix can.
    """
    return pattern.startswith("^") and not pattern.startswith("^^")


def longest_required_literal_run(pattern: str) -> int:
    """Longest run of literal characters the pattern REQUIRES.

    Approximate and deliberately conservative — it may under-count (reporting a
    pattern unservable that pg_trgm could in fact serve), which costs a
    push-down, never an answer. Over-counting would cost 12 seconds.
    """
    best = run = 0
    i = 0
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "\\":
            # An escaped metacharacter is a literal; an escape class (\d, \w)
            # is not. Either way it consumes two characters.
            nxt = pattern[i + 1] if i + 1 < n else ""
            if nxt and nxt in _REGEX_META:
                run += 1
            else:
                best = max(best, run)
                run = 0
            i += 2
            continue
        if ch == "[":
            # A character class matches ONE character and its contents are not
            # literals. Consumed whole: counting inside it read `[abc]` as a
            # three-character run, which is the over-count this must not make.
            best = max(best, run)
            run = 0
            j = pattern.find("]", i + 1)
            i = (j + 1) if j > 0 else n
            continue
        if ch == "{":
            # A bound quantifier. Its digits are not literals either — `ab{1,2}c`
            # read as a run of three ('a','b' then '1','2' then 'c' merged) and
            # was called servable, which is exactly the over-count that costs
            # 12 seconds rather than a push-down.
            j = pattern.find("}", i + 1)
            body = pattern[i + 1:j] if j > 0 else ""
            best = max(best, run - 1 if body.startswith("0") else run)
            run = 0
            i = (j + 1) if j > 0 else n
            continue
        if ch in _REGEX_META:
            best = max(best, run)
            run = 0
            i += 1
            continue
        # A literal, unless the next character makes it optional.
        nxt = pattern[i + 1] if i + 1 < n else ""
        if nxt in _OPTIONAL_QUANT:
            best = max(best, run)
            run = 0
        else:
            run += 1
        i += 1
    return max(best, run)


def is_servable(op: str, needle: str) -> bool:
    """Can the trigram index require a trigram for this operator and needle?"""
    op = (op or "").lower()
    if op in ("strstarts", "strends", "eq"):
        # Anchored at one end, so the padding holds at any length.
        return True
    if op == "contains":
        return len(needle) >= MIN_TRIGRAM_NEEDLE
    if op == "regex":
        if regex_is_prefix_anchored(needle):
            return True
        return longest_required_literal_run(needle) >= MIN_TRIGRAM_NEEDLE
    # Unknown operator: assume servable and let the existing path decide. This
    # function must never be the reason a new operator silently stops pushing.
    return True


# A GRAPH clause binds every leaf to one context, and that arrives THREE ways
# depending on the shape — as a `leaf_terms` entry, and as
# `q0.context_uuid = __CONST_c_0__` in both `constraints` and
# `tagged_constraints`. Counting any of them as narrowing made every BGP inside
# a named graph read as bounded, so the refusal never fired: measured on
# sp_lead_synth_100k, `?s ?p ?o` with `CONTAINS(?o,"XQ")` was merely declined and
# then ran past 60 s. A graph lock says WHICH graph, not which rows.
_NOT_NARROWING = ("context_uuid",)


def _narrows(text: str) -> bool:
    """Does this constraint restrict rows within the graph it is already in?"""
    return not any(col in text for col in _NOT_NARROWING)


def bgp_is_unbounded(bgp) -> bool:
    """Does anything other than the declined text search narrow this BGP?

    A constant leaf, a numeric range, or a constraint already pushed all mean the
    join has something to drive from, so evaluating the text filter above it is
    bounded by that. With none of them the BGP is the whole graph — which is all
    a graph lock leaves it as.
    """
    if bgp is None:
        return False
    if any(col not in _NOT_NARROWING for (_alias, col) in (bgp.leaf_terms or {})):
        return False
    if bgp.range_leaves:
        return False
    if any(_narrows(sql) for (_a, sql) in (bgp.tagged_constraints or [])):
        return False
    if any(_narrows(sql) for sql in (bgp.constraints or [])):
        return False
    return True


def unbounded_scan_error(op: str, needle: str, var_name: str,
                         term_rows: Optional[int]) -> Optional[str]:
    """The refusal message, or None if this search should merely be declined.

    `term_rows` is `None` when the size was never measured — no connection, or
    no unservable needle to measure for. None means DO NOT refuse: the whole
    risk of this gate is erroring on a query that would have been fine.
    """
    if term_rows is None or term_rows < UNBOUNDED_SCAN_TERMS:
        return None
    alt = ("STRSTARTS" if (op or "").lower() == "contains"
           else "an anchored pattern ('^...')")
    return (
        f"{op.upper()}(?{var_name.lstrip('?')}, {needle!r}) cannot be served by "
        f"the text index — an unanchored needle under {MIN_TRIGRAM_NEEDLE} "
        f"characters yields only padded trigrams, which an infix match cannot "
        f"require — and nothing else in this pattern bounds the scan, so it "
        f"would read all {term_rows:,} terms in the space. Use {alt} for prefix "
        f"search, or add a constraint (a bound predicate, a type, a range) that "
        f"gives the query something to drive from.")
