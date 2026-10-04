#!/usr/bin/env python3
"""
Read-only production check: is the entity-registry fuzzy index actually
SERVING for the business entities in the database?

Prod moved the fuzzy index off MemoryDB/Redis onto PostgreSQL
(`PROD_ENTITY_FUZZY_BACKEND=postgresql` -> `EntityFuzzyIndexPG`). The tables
being populated is not the same claim as lookups returning the right entity,
so this exercises the SAME code path the server uses — `find_similar_by_name`
against `entity_fuzzy_band` / `entity_fuzzy_phonetic_band` — on REAL rows.

Three questions, in order:
  1. COVERAGE  — is every active business entity in the index?
  2. RECALL    — does an exact name find its own entity?
  3. FUZZY     — does a TYPO'd name still find it? (the dedup case; if this
                 fails the index is present but not doing its job)

STRICTLY READ-ONLY. It never calls add_entity / initialize / clear_index, and
connects as the app role (vitalgraph_user) so it sees exactly what the server
sees — a master-role connection can read tables the app cannot.

Usage:
    python test_scripts/entity_registry/check_fuzzy_coverage_and_recall.py [--sample N]

RECOVERED 2026-10-04. Written 2026-09-29 in the deploy repository as
`test_fuzzy_prod_check.py`; `daa3f393` here then wrote a DIFFERENT checker (the
`issues/248` / `issues/249` checks) to that same path, and syncing it overwrote
this one there too, so it existed in neither. Restored unchanged apart from this
note and its name, beside the other rather than over it.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import asyncpg

from vitalgraph.entity_registry.entity_fuzzy_pg import EntityFuzzyIndexPG

# A REPRODUCIBLE SAMPLE, THE THIRD ATTEMPT. Seeding Python's RNG did nothing
# (the draw is SQL's). `setseed` + `ORDER BY random()` did not hold either —
# measured: two runs, same seed, disjoint samples, because parallel workers
# each carry their own seed state. Hashing the id is deterministic whatever
# the plan does.
DEFAULT_SEED = 'vg-fuzzy-20260929'

# Typo recall is a RATE, not a guarantee: MinHash-LSH has a real recall
# ceiling (see the failure notes at the end). Measured 96% on prod
# 2026-09-29 over 82 real-name probes. The floor is set below that to catch a
# REGRESSION — an index that stopped being maintained, or a backend flip —
# rather than to demand perfection and cry wolf on every run.
TYPO_RECALL_FLOOR = 0.90

# A rate needs a denominator worth dividing by. `--sample 8` yields ~4 real
# names and ~8 probes, where ONE inherent LSH miss reads as 88% and trips a
# 90% floor — a false alarm produced by arithmetic, not by the index. Below
# this many probes the rate is reported and not judged.
MIN_PROBES_TO_JUDGE = 20

# NOT 10. A common name like 'Freight Solutions' has 32 candidates scoring
# >= 50 and several tied at 100, so the entity's OWN row can fall outside a
# top-10 window while being perfectly indexed. At limit=10 that reads as a
# recall failure; it is a ranking cutoff. Verified on prod: 1/2 at limit=10,
# 2/2 at limit=50, same 32 candidates.
RECALL_LIMIT = 50

# ~32.6% of active prod business entities are named 'company-<digits>' — a
# placeholder, not a business name. Character-shingle LSH has nothing to work
# with when one DIGIT moves, and no human is fuzzy-searching these. Counted
# separately so they neither flatter nor damn the real-name result.
PLACEHOLDER_PREFIX = 'company-'


def load_env(path: Path) -> dict:
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            env[k] = v.strip().strip('"').strip("'")
    return env


def typo_variants(name: str) -> list:
    """Perturbations a human actually makes: transposition and omission.

    Both are applied to the LONGEST token, not the whole string — a typo in
    'Inc' is noise the scorer should ignore anyway, and perturbing it would
    test nothing.
    """
    tokens = name.split()
    if not tokens:
        return []
    idx = max(range(len(tokens)), key=lambda i: len(tokens[i]))
    word = tokens[idx]
    out = []
    if len(word) >= 4:
        mid = len(word) // 2
        swapped = word[:mid - 1] + word[mid] + word[mid - 1] + word[mid + 1:]
        if swapped != word:
            out.append((' '.join(tokens[:idx] + [swapped] + tokens[idx + 1:]),
                        'transposition'))
        dropped = word[:mid] + word[mid + 1:]
        out.append((' '.join(tokens[:idx] + [dropped] + tokens[idx + 1:]),
                    'omission'))
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--sample', type=int, default=25)
    ap.add_argument('--type-key', default='business')
    ap.add_argument('--seed', default=DEFAULT_SEED,
                    help='same seed = same sample')
    args = ap.parse_args()

    env_path = project_root / '.env'
    if not env_path.exists():
        print(f"no {env_path} — needs NEW_PROD_DB_* and VITALGRAPH_DB_* to reach prod")
        return 2
    env = load_env(env_path)
    # The fuzzy index reads ENTITY_FUZZY_* through get_scoped_env; prod sets
    # neither NUM_PERM nor THRESHOLD, so the defaults it uses (64 / 0.3) are
    # the ones the server logged at boot. Left unset here on purpose.
    os.environ.setdefault('VITALGRAPH_ENVIRONMENT', 'prod')

    pool = await asyncpg.create_pool(
        host=env['NEW_PROD_DB_HOST'], port=int(env['NEW_PROD_DB_PORT']),
        database=env['NEW_PROD_DB_NAME'], user=env['VITALGRAPH_DB_USERNAME'],
        password=env['VITALGRAPH_DB_PASSWORD'], ssl='require',
        min_size=1, max_size=4, command_timeout=120,
    )

    print(f"connected: {env['NEW_PROD_DB_HOST']} as {env['VITALGRAPH_DB_USERNAME']}")

    async with pool.acquire() as c:
        total = await c.fetchval(
            "SELECT COUNT(*) FROM entity e JOIN entity_type et ON et.type_id=e.entity_type_id "
            "WHERE e.status='active' AND et.type_key=$1", args.type_key)
        indexed = await c.fetchval(
            "SELECT COUNT(*) FROM entity e JOIN entity_type et ON et.type_id=e.entity_type_id "
            "JOIN entity_fuzzy_hash h ON h.entity_id=e.entity_id "
            "WHERE e.status='active' AND et.type_key=$1", args.type_key)

    print("\n=== 1. COVERAGE ===")
    print(f"  active {args.type_key} entities : {total:,}")
    print(f"  with a row in fuzzy_hash    : {indexed:,}")
    gap = total - indexed
    print(f"  gap                         : {gap:,} "
          f"({'OK' if gap == 0 else 'MISSING FROM INDEX'})")

    fuzzy = EntityFuzzyIndexPG.from_env(pool)

    async with pool.acquire() as c:
        rows = await c.fetch(
            "SELECT e.entity_id, e.primary_name, e.country, e.region, e.locality "
            "FROM entity e JOIN entity_type et ON et.type_id=e.entity_type_id "
            "WHERE e.status='active' AND et.type_key=$1 "
            "AND length(e.primary_name) >= 6 "
            "ORDER BY md5(e.entity_id || $2) LIMIT $3",
            args.type_key, args.seed, args.sample)

    # [real, placeholder] tallies, kept apart on purpose (see PLACEHOLDER_PREFIX)
    exact = {'real': [0, 0], 'ph': [0, 0]}
    typo = {'real': [0, 0], 'ph': [0, 0]}
    failures = []

    def bucket(name):
        return 'ph' if name.startswith(PLACEHOLDER_PREFIX) else 'real'

    print(f"\n=== 2. EXACT RECALL — {len(rows)} sampled {args.type_key} entities ===")
    for r in rows:
        eid, name = r['entity_id'], r['primary_name']
        res = await fuzzy.find_similar_by_name(
            name, country=r['country'], region=r['region'],
            locality=r['locality'], type_key=args.type_key, limit=RECALL_LIMIT)
        b = bucket(name)
        exact[b][1] += 1
        self_hit = next((x for x in res if x['entity_id'] == eid), None)
        if self_hit:
            exact[b][0] += 1
            mark = f"OK   score={self_hit['score']:5.1f} ({self_hit['match_level']})"
        else:
            mark = f"MISS ({len(res)} other candidates)"
            failures.append(('exact', name, eid, [x['primary_name'] for x in res[:3]]))
        print(f"  {mark}  {name[:58]!r}")

    print(f"\n=== 3. FUZZY / TYPO RECALL (the dedup case) ===")
    for r in rows:
        eid, name = r['entity_id'], r['primary_name']
        for variant, kind in typo_variants(name):
            b = bucket(name)
            typo[b][1] += 1
            res = await fuzzy.find_similar_by_name(
                variant, country=r['country'], region=r['region'],
                locality=r['locality'], type_key=args.type_key, limit=RECALL_LIMIT)
            self_hit = next((x for x in res if x['entity_id'] == eid), None)
            if self_hit:
                typo[b][0] += 1
                print(f"  OK   {kind:<14} score={self_hit['score']:5.1f}  "
                      f"{variant[:40]!r} -> {name[:40]!r}")
            else:
                failures.append(('typo', variant, eid, [x['primary_name'] for x in res[:3]]))
                print(f"  MISS {kind:<14}              {variant[:40]!r} -> "
                      f"expected {name[:40]!r}")

    def rate(pair):
        hit, tot = pair
        return f"{hit}/{tot}" + (f" ({100.0 * hit / tot:.0f}%)" if tot else "")

    print("\n=== SUMMARY ===")
    if total:
        print(f"  coverage             : {indexed:,}/{total:,} "
              f"({100.0 * indexed / total:.2f}%)")
    print(f"  exact recall (real)  : {rate(exact['real'])}")
    print(f"  typo  recall (real)  : {rate(typo['real'])}   <- the dedup claim "
          f"(floor {TYPO_RECALL_FLOOR:.0%})")
    print(f"  exact recall (placeholder '{PLACEHOLDER_PREFIX}*') : {rate(exact['ph'])}")
    print(f"  typo  recall (placeholder '{PLACEHOLDER_PREFIX}*') : {rate(typo['ph'])}")

    await pool.close()

    # The verdict is about REAL names. Placeholders are reported, not judged.
    probes = typo['real'][1]
    typo_rate = (typo['real'][0] / probes) if probes else 1.0
    judged = probes >= MIN_PROBES_TO_JUDGE
    ok = (gap == 0
          and exact['real'][0] == exact['real'][1]
          and (typo_rate >= TYPO_RECALL_FLOOR or not judged))
    print(f"\n  VERDICT: {'PASS' if ok else 'ATTENTION — see MISS lines above'}")
    if not judged:
        print(f"    (typo rate over {probes} real-name probe(s) — under "
              f"{MIN_PROBES_TO_JUDGE}, so reported but not judged; "
              f"raise --sample to test it)")
    for kind, queried, eid, top in failures:
        print(f"    {kind:<5} {queried[:44]!r} (want {eid}) — top candidates: "
              + ", ".join(repr(t[:28]) for t in top))
    if failures:
        # Two mechanisms seen on prod, both inherent to MinHash-LSH rather than
        # to the PostgreSQL backend, and worth telling apart before filing a bug:
        #   * the target was never PROPOSED — check get_candidate_ids() directly;
        #     a transposition inside a short token does this ('Carbal'/'Cabral',
        #     which still scores 83.3 when compared head to head).
        #   * geo DILUTION — country/region/locality are shingled into the query
        #     as well as the index, and on some names that widens the candidate
        #     set and loses the target ('Aur Trdaing Corp': found rank 1 score
        #     100 on name alone, absent once geo is passed, 120 -> 1071 cands).
        print(f"  {len(failures)} failure(s) — re-check with get_candidate_ids() "
              f"and with geo omitted before calling it a regression")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
