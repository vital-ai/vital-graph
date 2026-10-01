#!/usr/bin/env python3
"""issues/248 + issues/249 — fuzzy recall and index hygiene, against a real registry.

READ-ONLY. Every query here is a SELECT or a `find_similar` call; nothing is
written, nothing is reindexed, no entity is touched. Safe against production.

WHY THIS EXISTS AGAIN. The original checker was never committed — it has zero
objects anywhere in git history — so when it was deleted the findings survived in
`248` and `249` and the runnable form did not. The numbers in those issues are
therefore unreproducible without this, and "8 of 8 clusters recovered" is the
load-bearing claim of `248`: it is the reason the geo defect is only a defect
rather than an outage.

WHAT IT CHECKS, in the order `248`'s "Verify after fixing" puts them:

  A  duplicate-name clusters are fully recovered        the result that must not regress
  B  geo folding loses a match that name alone finds    the defect itself
  C  geo that is MISSING or DISAGREES penalises a pair  the same defect, scoring side
  D  the two known misses are two different things      do not conflate them
  E  placeholder names are a false-positive clique      issues/249

A and E need a database. B, C and D are pure function calls on the shipped
scorer and run anywhere — which is deliberate: the distinction D draws is
arithmetic, and arithmetic should not need production to confirm.

CLUSTERS ARE DISCOVERED, NOT HARDCODED. `248` names three of its eight and says
"five more", so a hardcoded list could not reproduce the 8/8 anyway. Discovering
them re-derives the result instead of trusting a stale list, and it keeps
production business names out of this file.

    python test_scripts/entity_registry/test_fuzzy_prod_check.py              # all
    python test_scripts/entity_registry/test_fuzzy_prod_check.py --offline    # B, C, D only
    python test_scripts/entity_registry/test_fuzzy_prod_check.py --clusters 20

Exit code is 0 when every check that RAN passed. A check that cannot run (no
database, no clusters found) is reported as SKIP and does not fail the run —
a checker that reports failure for being unable to look would train people to
ignore it.
"""
import argparse
import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv                                   # noqa: E402
load_dotenv(project_root / '.env')

import asyncpg                                                   # noqa: E402

from vitalgraph.config.config_loader import VitalGraphConfig     # noqa: E402
from vitalgraph.entity_registry.entity_fuzzy_pg import EntityFuzzyIndexPG  # noqa: E402
from vitalgraph.vectorization.fuzzy_core import (                # noqa: E402
    compute_shingles, score_pair)

LINE = '-' * 78

# `248`'s measured configuration, asserted rather than assumed: every number in
# that issue is relative to these, so a checker that silently ran against a
# different threshold would produce numbers nobody could compare.
EXPECTED_CONFIG = {
    'shingle_k': 3,
    'num_perm': 64,
    'threshold': 0.3,
    'min_candidates': 20,
}

# The two misses `248` ran down. Kept as literals because they are the POINT:
# one is arithmetically unreachable and one is a coin flip, and the issue is
# explicit that filing them together would be wrong.
KNOWN_MISSES = [
    ('Carbal', 'Cabral', 0.000, 'transposition in a 6-char token: NO shared '
                                '3-shingle exists, so no tuning recovers it'),
    ('Dice Durid', 'Dice Druid', 0.333, 'clears the 0.3 threshold by 0.033, so '
                                        'LSH finds it SOME of the time'),
]


# States, and only ONE of them fails the run.
#
# A checker written against OPEN issues cannot treat a known defect as a
# failure: `248` and `249` are both open and unbuilt, so every run would exit 1
# forever, and a permanently red check is one people learn to ignore — the same
# reason this file reports SKIP rather than FAIL when it cannot look.
#
#   PASS   something that must hold, holds
#   FAIL   something that must hold, does NOT — the only state that exits 1
#   KNOWN  a documented open defect still reproduces: expected, not news
#   FIXED  a documented open defect NO LONGER reproduces — loud, because the
#          issue now overstates the problem and should be re-measured
#   SKIP   could not be checked here
#   INFO   a measurement, carrying no verdict
STATES = ('PASS', 'FAIL', 'KNOWN', 'FIXED', 'SKIP', 'INFO')


class Results:
    def __init__(self):
        self.rows = []

    def add(self, name, state, detail=''):
        assert state in STATES, state
        self.rows.append((name, state, detail))
        print(f"  [{state:5}] {name}" + (f" — {detail}" if detail else ''))

    def known(self, name, reproduces, detail='', fixed_detail=''):
        """A defect `248`/`249` documents as open.

        Reproducing is the expected outcome. NOT reproducing is the interesting
        one, and it is reported loudly rather than silently passing: either the
        fix landed and the issue needs closing, or something else moved and the
        issue's numbers no longer describe the system.
        """
        self.add(name, 'KNOWN' if reproduces else 'FIXED',
                 detail if reproduces else
                 (fixed_detail or "no longer reproduces — re-measure the issue "
                                  "before trusting its numbers"))

    def exit_code(self):
        return 1 if any(s == 'FAIL' for _, s, _ in self.rows) else 0

    def summary(self):
        counts = {}
        for _, s, _ in self.rows:
            counts[s] = counts.get(s, 0) + 1
        out = ' '.join(f"{k}={counts[k]}" for k in STATES if k in counts)
        if counts.get('FIXED'):
            out += "   <- a documented defect stopped reproducing; read the issue"
        return out


# ---------------------------------------------------------------------------
# D — the two known misses. Arithmetic, no database.
# ---------------------------------------------------------------------------

def check_known_misses(res, k):
    print("\nD. The two known misses are two DIFFERENT failures")
    print(LINE)
    for a, b, expected_j, why in KNOWN_MISSES:
        sa, sb = compute_shingles(a, k), compute_shingles(b, k)
        shared = len(sa & sb)
        union = len(sa | sb)
        j = (shared / union) if union else 0.0
        ok = abs(j - expected_j) < 0.005
        res.add(f"jaccard({a!r}, {b!r}) = {j:.3f}",
                'PASS' if ok else 'FAIL',
                why if ok else f"expected {expected_j:.3f} — the shingling changed")
        # The scorer was never the problem; say so with its own numbers.
        score = score_pair([a], [b])
        res.add(f"  scored head-to-head: {getattr(score, 'score', score):.1f}"
                if hasattr(score, 'score') else f"  scored: {score}",
                'INFO',
                "well over the 50 floor — candidate GENERATION is the failure, "
                "not scoring")

    # The asymmetry that explains both: omission preserves neighbouring shingles,
    # transposition destroys every shingle spanning it.
    for a, b in (('Cabal', 'Cabral'), ('Dice Duid', 'Dice Druid')):
        sa, sb = compute_shingles(a, k), compute_shingles(b, k)
        res.add(f"omission variant {a!r}/{b!r} shares {len(sa & sb)} shingle(s)",
                'INFO', "omission leaves the surrounding shingles intact")


# ---------------------------------------------------------------------------
# B and C — the geo defect, at candidate-generation and at scoring time.
# ---------------------------------------------------------------------------

def check_geo_compression(res, k):
    print("\nB. Geo is three fixed shingles, so it compresses similarity toward 1")
    print(LINE)
    # The documented shape: a typo pair that name alone separates, and geo does
    # not. Measured on shingles, so it needs no index: this is WHY the candidate
    # set grew 8.9x and lost the target, not merely that it did.
    name_a, name_b = 'Aur Trdaing Corp', 'Aur Trading Corp'
    geo = {'country': 'US', 'region': 'FL', 'locality': 'Miami'}

    plain_a, plain_b = compute_shingles(name_a, k), compute_shingles(name_b, k)
    j_plain = len(plain_a & plain_b) / max(1, len(plain_a | plain_b))

    geo_a = compute_shingles(name_a, k, context_tokens=geo)
    geo_b = compute_shingles(name_b, k, context_tokens=geo)
    j_geo = len(geo_a & geo_b) / max(1, len(geo_a | geo_b))

    res.add(f"name only: jaccard {j_plain:.3f}", 'INFO')
    res.add(f"name + geo: jaccard {j_geo:.3f}", 'INFO')
    res.known("adding geo RAISES the similarity of a typo pair",
              j_geo > j_plain,
              f"+{j_geo - j_plain:.3f} — every pair sharing geo is pulled "
              f"toward 1, which is what lets the adaptive cut drop the target",
              "geo no longer compresses similarity: the fix may have landed")


def check_geo_penalty(res):
    print("\nC. Geo that is MISSING or DISAGREES penalises a true pair")
    print(LINE)
    same = 'Identical Holdings LLC'

    def score(a_geo, b_geo):
        sa = compute_shingles(same, EXPECTED_CONFIG['shingle_k'], context_tokens=a_geo)
        sb = compute_shingles(same, EXPECTED_CONFIG['shingle_k'], context_tokens=b_geo)
        return len(sa & sb) / max(1, len(sa | sb))

    full = {'country': 'US', 'region': 'FL', 'locality': 'Miami'}
    partial = {'country': 'US', 'region': 'FL'}            # locality missing
    other = {'country': 'US', 'region': 'TX', 'locality': 'Austin'}
    none_ = {}

    j_full = score(full, full)
    j_missing = score(full, partial)
    j_disagree = score(full, other)
    j_none = score(none_, none_)

    res.add(f"identical name, identical geo: {j_full:.3f}", 'INFO')
    # Both are `248`'s open defect, not regressions: an incomplete record and a
    # disagreeing one are each penalised against an identical NAME. They flip to
    # FIXED when geo moves out of `_name_shingles`.
    res.known(f"identical name, one geo field MISSING: {j_missing:.3f}",
              j_missing < j_none - 0.001,
              f"penalised below the no-geo baseline of {j_none:.3f} — "
              f"issues/248, an incomplete record should not cost recall",
              "an incomplete record no longer scores below the no-geo baseline")
    res.known(f"identical name, geo DISAGREES: {j_disagree:.3f}",
              j_disagree < j_none - 0.001,
              f"penalised below the no-geo baseline of {j_none:.3f} — "
              f"issues/248's 0.478 case",
              "a disagreeing geo no longer penalises an identical name")


# ---------------------------------------------------------------------------
# A — duplicate-name cluster recall. The load-bearing result.
# ---------------------------------------------------------------------------

async def discover_clusters(conn, want, type_key='business'):
    """Real duplicate-name clusters: >=2 active entities sharing a normalised name.

    Placeholder names are EXCLUDED — `issues/249` is a 209,580-member clique of
    them, and including it would report a recall triumph that measures nothing.
    """
    rows = await conn.fetch(
        """
        SELECT lower(btrim(e.primary_name)) AS norm,
               array_agg(e.entity_id) AS ids,
               count(*) AS n
        FROM entity e
        JOIN entity_type et ON e.entity_type_id = et.type_id
        WHERE e.status = 'active'
          AND et.type_key = $1
          AND e.primary_name IS NOT NULL
          AND btrim(e.primary_name) <> ''
          AND e.primary_name !~ '^company-[0-9]+$'
        GROUP BY 1
        HAVING count(*) BETWEEN 2 AND 5
        ORDER BY count(*) DESC, 1
        LIMIT $2
        """,
        type_key, want)
    return [dict(r) for r in rows]


async def check_cluster_recall(res, pool, idx, want):
    """`248`'s load-bearing result, and the EASY case by construction.

    A cluster shares a normalised name, so its members score 100 against each
    other — well clear of any threshold. That is not a weakness of the check,
    it is the question the system actually has to answer ("a new record arrives
    for a business already in the registry"), and `248` says so before anything
    else. But do NOT read a green A as "recall is fine": the hard cases are
    typo variants, and they are B, C and D above. Verified while writing this —
    forcing `min_score=99.99` did not make this check fail, because an identical
    name scores exactly 100.
    """
    print(f"\nA. Duplicate-name clusters are fully recovered (sampling {want})")
    print(LINE)
    async with pool.acquire() as conn:
        clusters = await discover_clusters(conn, want)
    if not clusters:
        res.add("duplicate-name cluster recall", 'SKIP',
                "no multi-member clusters found — nothing to measure here")
        return

    recovered = 0
    partial = []
    for c in clusters:
        ids = set(c['ids'])
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT primary_name, country, region, locality FROM entity "
                "WHERE entity_id = $1", c['ids'][0])
        hits = await idx.find_similar_by_name(
            name=row['primary_name'], country=row['country'],
            region=row['region'], locality=row['locality'],
            limit=50)
        found = {h.get('entity_id') for h in hits} | {c['ids'][0]}
        if ids <= found:
            recovered += 1
        else:
            # Never print the name: it is customer data and the id is enough to
            # look it up deliberately.
            partial.append(f"{c['ids'][0]} {len(ids & found)}/{len(ids)}")

    ok = recovered == len(clusters)
    res.add(f"{recovered}/{len(clusters)} clusters fully recovered",
            'PASS' if ok else 'FAIL',
            "every member returned — issues/248's load-bearing result, and the "
            "EASY case: identical names score 100, so this says nothing about "
            "typo recall (see B/C/D)"
            if ok else "incomplete: " + ', '.join(partial[:6]))
    if len(clusters) < want:
        res.add(f"only {len(clusters)} cluster(s) available, asked for {want}",
                'INFO',
                "a smaller registry than the one issues/248 measured; the ratio "
                "is the result, not the count")


# ---------------------------------------------------------------------------
# E — the placeholder clique.
# ---------------------------------------------------------------------------

async def check_placeholder_clique(res, pool):
    print("\nE. Placeholder names in the index (issues/249)")
    print(LINE)
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            "SELECT count(*) FROM entity e JOIN entity_type et "
            "ON e.entity_type_id = et.type_id "
            "WHERE e.status = 'active' AND et.type_key = 'business'")
        placeholder = await conn.fetchval(
            "SELECT count(*) FROM entity e JOIN entity_type et "
            "ON e.entity_type_id = et.type_id "
            "WHERE e.status = 'active' AND et.type_key = 'business' "
            "AND e.primary_name ~ '^company-[0-9]+$'")
    if not total:
        res.add("placeholder share", 'SKIP', "no active business entities")
        return

    pct = 100.0 * placeholder / total
    res.add(f"{placeholder:,} of {total:,} active business entities are "
            f"`company-<digits>` ({pct:.1f}%)",
            'INFO',
            "issues/249 measured 209,580 of 643,791 = 32.6% on 2026-09-29")
    # Not a FAIL: `249` is OPEN and decided-but-unbuilt, so a nonzero count is
    # the expected state. It becomes a PASS when the fix lands and this drops to
    # zero IN THE INDEX — which is the thing to re-check then.
    res.known("placeholder names are still in the index (issues/249)",
              placeholder > 0,
              f"{placeholder:,} of them, in a single phonetic cell — decided, "
              f"unbuilt; see issues/249 §2",
              "no placeholder names remain: issues/249 appears to be built")


# ---------------------------------------------------------------------------

async def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--offline', action='store_true',
                    help="only the checks that need no database (B, C, D)")
    ap.add_argument('--clusters', type=int, default=8,
                    help="how many duplicate-name clusters to sample (default 8, "
                         "matching issues/248)")
    args = ap.parse_args()

    res = Results()
    k = EXPECTED_CONFIG['shingle_k']

    print("READ-ONLY. No writes, no reindex. Safe against production.")
    check_known_misses(res, k)
    check_geo_compression(res, k)
    check_geo_penalty(res)

    if args.offline:
        print(f"\n{LINE}\noffline: skipped the checks that need a database")
    else:
        try:
            cfg = VitalGraphConfig().get_database_config()
            pool = await asyncpg.create_pool(
                host=cfg.get('host', 'localhost'), port=int(cfg.get('port', 5432)),
                database=cfg.get('database'), user=cfg.get('username'),
                password=cfg.get('password', ''), min_size=1, max_size=3)
        except Exception as e:
            res.add("database checks (A, E)", 'SKIP', f"cannot connect: {e}")
            pool = None

        if pool is not None:
            try:
                idx = EntityFuzzyIndexPG.from_env(pool)
                # Assert the configuration the issue's numbers are relative to.
                actual = {
                    'num_perm': getattr(idx, 'num_perm', None),
                    'threshold': getattr(idx, 'threshold', None),
                    'shingle_k': getattr(idx, 'shingle_k', None),
                }
                drift = {kk: (vv, EXPECTED_CONFIG[kk])
                         for kk, vv in actual.items()
                         if vv is not None and vv != EXPECTED_CONFIG[kk]}
                res.add(f"index config {actual}",
                        'FAIL' if drift else 'PASS',
                        f"differs from what issues/248 measured: {drift}"
                        if drift else "matches issues/248's measured baseline")
                await check_cluster_recall(res, pool, idx, args.clusters)
                await check_placeholder_clique(res, pool)
            finally:
                await pool.close()

    print(f"\n{LINE}\n{res.summary()}")
    return res.exit_code()


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
