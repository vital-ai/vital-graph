#!/usr/bin/env python3
"""
Direct Fuseki WordNet Query Test — Comparison Benchmark

Runs the exact same SPARQL queries used by test_sparql_wordnet.py
(basic queries + happy_words_v2.py queries) directly against a
Fuseki endpoint, for timing comparison with the sparql_sql backend.

Usage:
    python vitalgraph_client_test/test_fuseki_wordnet_query.py
    python vitalgraph_client_test/test_fuseki_wordnet_query.py --fuseki-url http://localhost:3030
    python vitalgraph_client_test/test_fuseki_wordnet_query.py --dataset wordnet_frames
"""

import os
import sys
import time
import logging
import argparse
import requests
from typing import Optional, Dict, Any, List
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# ── Ontology constants (same as test cases) ──────────────────────────────
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
VITAL_NAME = "http://vital.ai/ontology/vital-core#hasName"
VITAL_EDGE_SRC = "http://vital.ai/ontology/vital-core#hasEdgeSource"
VITAL_EDGE_DST = "http://vital.ai/ontology/vital-core#hasEdgeDestination"
HALEY_KG_ENTITY = "http://vital.ai/ontology/haley-ai-kg#KGEntity"
HALEY_KG_FRAME = "http://vital.ai/ontology/haley-ai-kg#KGFrame"
HALEY_FRAME_TYPE_DESC = "http://vital.ai/ontology/haley-ai-kg#hasKGFrameTypeDescription"
HALEY_KG_DESC = "http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription"
HALEY_SLOT_TYPE = "http://vital.ai/ontology/haley-ai-kg#hasKGSlotType"
HALEY_SLOT_VALUE = "http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue"


# ═══════════════════════════════════════════════════════════════════════════
# SPARQL Queries — identical to case_wordnet_basic_queries.py
# ═══════════════════════════════════════════════════════════════════════════

TRIPLE_COUNT_SPARQL = "SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o }"

TYPE_COUNTS_SPARQL = f"""
SELECT ?type (COUNT(?s) AS ?count) WHERE {{
    ?s <{RDF_TYPE}> ?type .
}}
GROUP BY ?type
ORDER BY DESC(?count)
LIMIT 10
"""

FIND_HAPPY_SPARQL = f"""
SELECT ?entity ?name WHERE {{
    ?entity <{RDF_TYPE}> <{HALEY_KG_ENTITY}> .
    ?entity <{VITAL_NAME}> ?name .
    FILTER(CONTAINS(?name, "happy"))
}}
LIMIT 20
"""

PREDICATE_INVENTORY_SPARQL = """
SELECT ?p (COUNT(*) AS ?count) WHERE {
    ?s ?p ?o .
}
GROUP BY ?p
ORDER BY DESC(?count)
LIMIT 15
"""

LIMIT_OFFSET_P1_SPARQL = f"""
SELECT ?entity ?name WHERE {{
    ?entity <{RDF_TYPE}> <{HALEY_KG_ENTITY}> .
    ?entity <{VITAL_NAME}> ?name .
}}
ORDER BY ?name
LIMIT 5 OFFSET 0
"""

LIMIT_OFFSET_P2_SPARQL = f"""
SELECT ?entity ?name WHERE {{
    ?entity <{RDF_TYPE}> <{HALEY_KG_ENTITY}> .
    ?entity <{VITAL_NAME}> ?name .
}}
ORDER BY ?name
LIMIT 5 OFFSET 5
"""

# ═══════════════════════════════════════════════════════════════════════════
# SPARQL Queries — identical to case_wordnet_relationship_queries.py
# (from happy_words_v2.py)
# ═══════════════════════════════════════════════════════════════════════════

RELATIONSHIPS_SPARQL = f"""
SELECT ?srcName ?relationType ?dstName WHERE {{
    ?srcEntity <{RDF_TYPE}> <{HALEY_KG_ENTITY}> .
    ?srcEntity <{VITAL_NAME}> ?srcName .
    FILTER(CONTAINS(?srcName, "happy"))

    ?frame <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
    ?frame <{HALEY_FRAME_TYPE_DESC}> ?relationType .

    ?srcSlot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
    ?srcSlot <{HALEY_SLOT_VALUE}> ?srcEntity .
    ?srcEdge <{VITAL_EDGE_SRC}> ?frame .
    ?srcEdge <{VITAL_EDGE_DST}> ?srcSlot .

    ?dstSlot <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
    ?dstSlot <{HALEY_SLOT_VALUE}> ?dstEntity .
    ?dstEdge <{VITAL_EDGE_SRC}> ?frame .
    ?dstEdge <{VITAL_EDGE_DST}> ?dstSlot .

    ?dstEntity <{VITAL_NAME}> ?dstName .
}}
"""

FRAME_UNION_SPARQL = f"""
SELECT ?entity ?frame ?srcEntity ?dstEntity WHERE {{
    {{
        ?srcEntity <{HALEY_KG_DESC}> ?srcDesc .
        FILTER(CONTAINS(?srcDesc, "happy"))
        FILTER(?srcEntity != ?dstEntity)

        ?srcSlot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
        ?srcSlot <{HALEY_SLOT_VALUE}> ?srcEntity .
        ?srcEdge <{VITAL_EDGE_SRC}> ?frame .
        ?srcEdge <{VITAL_EDGE_DST}> ?srcSlot .
        ?dstSlot <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
        ?dstSlot <{HALEY_SLOT_VALUE}> ?dstEntity .
        ?dstEdge <{VITAL_EDGE_SRC}> ?frame .
        ?dstEdge <{VITAL_EDGE_DST}> ?dstSlot .
        BIND(?srcEntity AS ?entity)
    }}
    UNION
    {{
        ?dstEntity <{HALEY_KG_DESC}> ?dstDesc .
        FILTER(CONTAINS(?dstDesc, "happy"))
        FILTER(?srcEntity != ?dstEntity)

        ?srcSlot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
        ?srcSlot <{HALEY_SLOT_VALUE}> ?srcEntity .
        ?srcEdge <{VITAL_EDGE_SRC}> ?frame .
        ?srcEdge <{VITAL_EDGE_DST}> ?srcSlot .
        ?dstSlot <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
        ?dstSlot <{HALEY_SLOT_VALUE}> ?dstEntity .
        ?dstEdge <{VITAL_EDGE_SRC}> ?frame .
        ?dstEdge <{VITAL_EDGE_DST}> ?dstSlot .
        BIND(?dstEntity AS ?entity)
    }}
}}
ORDER BY ?entity
"""


class FusekiWordNetQueryTester:
    """Run WordNet SPARQL queries directly against Fuseki for benchmarking."""

    def __init__(self, fuseki_url: str, dataset: str):
        self.fuseki_url = fuseki_url.rstrip('/')
        self.dataset = dataset
        self.query_url = f"{self.fuseki_url}/{self.dataset}/query"
        self.timings: List[Dict[str, Any]] = []

    def query(self, sparql: str, description: str, timeout: int = 120) -> Optional[Dict]:
        """Execute a SPARQL query and return results with timing."""
        headers = {'Accept': 'application/sparql-results+json'}
        params = {'query': sparql}

        t0 = time.monotonic()
        try:
            resp = requests.get(
                self.query_url, params=params, headers=headers, timeout=timeout
            )
            dt = time.monotonic() - t0

            if resp.status_code == 200:
                try:
                    results = resp.json()
                except ValueError:
                    logger.error(f"   ❌ Non-JSON response ({len(resp.text)} chars)")
                    self.timings.append({
                        'query': description, 'time_s': dt, 'rows': 0,
                        'status': 'non-JSON response',
                    })
                    return None
                bindings = results.get('results', {}).get('bindings', [])
                self.timings.append({
                    'query': description,
                    'time_s': dt,
                    'rows': len(bindings),
                    'status': 'ok',
                })
                return results
            else:
                self.timings.append({
                    'query': description,
                    'time_s': dt,
                    'rows': 0,
                    'status': f'HTTP {resp.status_code}',
                })
                logger.error(f"   ❌ HTTP {resp.status_code}: {resp.text[:200]}")
                return None
        except requests.exceptions.RequestException as e:
            dt = time.monotonic() - t0
            self.timings.append({
                'query': description,
                'time_s': dt,
                'rows': 0,
                'status': f'error: {e}',
            })
            logger.error(f"   ❌ {e}")
            return None

    # ── Basic Queries ─────────────────────────────────────────────────

    def test_triple_count(self) -> bool:
        r = self.query(TRIPLE_COUNT_SPARQL, "Triple Count")
        if not r:
            return False
        bindings = r['results']['bindings']
        count = int(bindings[0].get('count', {}).get('value', 0)) if bindings else 0
        dt = self.timings[-1]['time_s']
        logger.info(f"    Total triples: {count:,}  ({dt:.3f}s)")
        return count > 0

    def test_type_counts(self) -> bool:
        r = self.query(TYPE_COUNTS_SPARQL, "Entity Type Counts")
        if not r:
            return False
        bindings = r['results']['bindings']
        dt = self.timings[-1]['time_s']
        logger.info(f"    Top types ({dt:.3f}s):")
        for b in bindings[:5]:
            t = b.get('type', {}).get('value', '?')
            c = b.get('count', {}).get('value', '0')
            short = t.rsplit('#', 1)[-1] if '#' in t else t.rsplit('/', 1)[-1]
            logger.info(f"      {short}: {int(c):,}")
        return len(bindings) > 0

    def test_find_happy(self) -> bool:
        r = self.query(FIND_HAPPY_SPARQL, "Find Happy Entities")
        if not r:
            return False
        bindings = r['results']['bindings']
        dt = self.timings[-1]['time_s']
        logger.info(f"    Found {len(bindings)} 'happy' entities ({dt:.3f}s)")
        for b in bindings[:5]:
            name = b.get('name', {}).get('value', '?')
            logger.info(f"      - {name}")
        return len(bindings) > 0

    def test_predicate_inventory(self) -> bool:
        r = self.query(PREDICATE_INVENTORY_SPARQL, "Predicate Inventory")
        if not r:
            return False
        bindings = r['results']['bindings']
        dt = self.timings[-1]['time_s']
        logger.info(f"    {len(bindings)} predicates ({dt:.3f}s):")
        for b in bindings[:8]:
            p = b.get('p', {}).get('value', '?')
            c = b.get('count', {}).get('value', '0')
            short = p.rsplit('#', 1)[-1] if '#' in p else p.rsplit('/', 1)[-1]
            logger.info(f"      {short}: {int(c):,}")
        return len(bindings) > 0

    def test_limit_offset(self) -> bool:
        r1 = self.query(LIMIT_OFFSET_P1_SPARQL, "LIMIT OFFSET p1")
        r2 = self.query(LIMIT_OFFSET_P2_SPARQL, "LIMIT OFFSET p2")
        if not r1 or not r2:
            return False
        b1 = r1['results']['bindings']
        b2 = r2['results']['bindings']
        names1 = {b.get('name', {}).get('value') for b in b1}
        names2 = {b.get('name', {}).get('value') for b in b2}
        overlap = names1 & names2
        # Combine the two timing entries
        t1 = self.timings[-2]['time_s']
        t2 = self.timings[-1]['time_s']
        logger.info(f"    Page 1: {len(b1)} results, Page 2: {len(b2)} results, overlap: {len(overlap)}  ({t1:.3f}s + {t2:.3f}s)")
        return len(overlap) == 0

    # ── Happy Words Queries ───────────────────────────────────────────

    def test_relationships(self) -> bool:
        r = self.query(RELATIONSHIPS_SPARQL, "Relationships (REGEX 'happy')")
        if not r:
            return False
        bindings = r['results']['bindings']
        dt = self.timings[-1]['time_s']
        logger.info(f"    {len(bindings)} relationships ({dt:.3f}s)")

        by_rel: dict = {}
        for b in bindings:
            src = b.get('srcName', {}).get('value', '?')
            rel = b.get('relationType', {}).get('value', '?')
            dst = b.get('dstName', {}).get('value', '?')
            rel_short = rel
            if rel_short.startswith('Edge_Wordnet'):
                rel_short = rel_short[len('Edge_Wordnet'):]
            elif rel_short.startswith('Edge_'):
                rel_short = rel_short[len('Edge_'):]
            by_rel.setdefault(rel_short, []).append((src, dst))

        for rel_type in sorted(by_rel.keys()):
            pairs = by_rel[rel_type]
            logger.info(f"    {rel_type} ({len(pairs)}):")
            for src, dst in sorted(pairs)[:3]:
                logger.info(f"      {src} ---{rel_type}---> {dst}")
            if len(pairs) > 3:
                logger.info(f"      ... and {len(pairs) - 3} more")

        return len(bindings) > 0

    def test_frame_union(self) -> bool:
        r = self.query(FRAME_UNION_SPARQL, "Frame UNION (REGEX 'happy')")
        if not r:
            return False
        bindings = r['results']['bindings']
        dt = self.timings[-1]['time_s']

        entity_uris = set()
        frame_uris = set()
        for b in bindings:
            for key in ('entity', 'srcEntity', 'dstEntity'):
                uri = b.get(key, {}).get('value')
                if uri:
                    entity_uris.add(uri)
            f = b.get('frame', {}).get('value')
            if f:
                frame_uris.add(f)

        logger.info(f"    {len(bindings)} rows ({dt:.3f}s)")
        logger.info(f"    Unique entities: {len(entity_uris)}, unique frames: {len(frame_uris)}")
        return True

    # ── Run all ───────────────────────────────────────────────────────

    def run_all(self) -> bool:
        logger.info(f"Fuseki endpoint: {self.query_url}\n")

        all_passed = True

        # Basic Queries
        logger.info("=" * 60)
        logger.info("  Basic Queries  (Fuseki direct)")
        logger.info("=" * 60)

        basic_tests = [
            ("Triple Count", self.test_triple_count),
            ("Entity Type Counts", self.test_type_counts),
            ("Find Happy Entities", self.test_find_happy),
            ("Predicate Inventory", self.test_predicate_inventory),
            ("LIMIT and OFFSET", self.test_limit_offset),
        ]
        basic_passed = 0
        for name, fn in basic_tests:
            try:
                if fn():
                    basic_passed += 1
                    logger.info(f"  ✅ {name}")
                else:
                    all_passed = False
                    logger.info(f"  ❌ {name}")
            except Exception as e:
                all_passed = False
                logger.info(f"  ❌ {name}: {e}")

        # Happy Words Queries
        logger.info("")
        logger.info("=" * 60)
        logger.info("  Happy Words Queries  (Fuseki direct)")
        logger.info("=" * 60)

        happy_tests = [
            ("Relationships Query (happy_words_v2.py L138-158)", self.test_relationships),
            ("Frame UNION Query (happy_words_v2.py L162-196)", self.test_frame_union),
        ]
        happy_passed = 0
        for name, fn in happy_tests:
            try:
                if fn():
                    happy_passed += 1
                    logger.info(f"  ✅ {name}")
                else:
                    all_passed = False
                    logger.info(f"  ❌ {name}")
            except Exception as e:
                all_passed = False
                logger.info(f"  ❌ {name}: {e}")

        # Summary
        total = len(basic_tests) + len(happy_tests)
        passed = basic_passed + happy_passed
        logger.info("")
        logger.info("=" * 60)
        logger.info("📊 TEST SUMMARY  (Fuseki direct)")
        logger.info("=" * 60)
        status = "✅" if basic_passed == len(basic_tests) else "❌"
        logger.info(f"  {status} Basic Queries: {basic_passed}/{len(basic_tests)} passed")
        status = "✅" if happy_passed == len(happy_tests) else "❌"
        logger.info(f"  {status} Happy Words Queries: {happy_passed}/{len(happy_tests)} passed")
        logger.info(f"\nOverall: {passed}/{total} tests passed")

        # Timing table
        logger.info("")
        logger.info("=" * 60)
        logger.info("⏱️  TIMING COMPARISON TABLE")
        logger.info("=" * 60)
        logger.info(f"  {'Query':<45} {'Time':>8} {'Rows':>8}")
        logger.info(f"  {'─' * 45} {'─' * 8} {'─' * 8}")
        for t in self.timings:
            time_str = f"{t['time_s']:.3f}s"
            logger.info(f"  {t['query']:<45} {time_str:>8} {t['rows']:>8}")

        if all_passed:
            logger.info("\n🎉 All queries passed!")
        return all_passed


def main():
    parser = argparse.ArgumentParser(
        description="Run WordNet SPARQL queries directly against Fuseki for comparison"
    )
    parser.add_argument(
        '--fuseki-url', default='http://localhost:3030',
        help='Fuseki server URL (default: http://localhost:3030)'
    )
    parser.add_argument(
        '--dataset', default='wordnet_frames',
        help='Fuseki dataset name (default: wordnet_frames)'
    )
    args = parser.parse_args()

    tester = FusekiWordNetQueryTester(args.fuseki_url, args.dataset)
    success = tester.run_all()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
