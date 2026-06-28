"""
WordNet Basic SPARQL Query Test Cases

Tests basic SPARQL queries against the WordNet KGFrame dataset:
- Triple count
- Entity type counts
- Entity name lookup
- Predicate inventory
"""

import logging
import time
from typing import Dict, Any

from vitalgraph.model.sparql_model import SPARQLQueryRequest, SPARQLQueryResponse

logger = logging.getLogger(__name__)

# Ontology constants
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
VITAL_NAME = "http://vital.ai/ontology/vital-core#hasName"
HALEY_KG_ENTITY = "http://vital.ai/ontology/haley-ai-kg#KGEntity"
HALEY_KG_FRAME = "http://vital.ai/ontology/haley-ai-kg#KGFrame"


class WordNetBasicQueryTester:
    """Test case for basic SPARQL queries on WordNet data."""

    def __init__(self, client):
        self.client = client

    async def run_tests(self, space_id: str) -> Dict[str, Any]:
        """Run all basic query tests.

        Args:
            space_id: Space containing WordNet data

        Returns:
            Dict with test results
        """
        results = {
            "test_name": "WordNet Basic Queries",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": [],
        }

        tests = [
            ("Triple Count", self._test_triple_count),
            ("Entity Type Counts", self._test_type_counts),
            ("Find Happy Entities", self._test_find_happy),
            ("Predicate Inventory", self._test_predicate_inventory),
            ("LIMIT and OFFSET", self._test_limit_offset),
        ]

        for name, fn in tests:
            results["tests_run"] += 1
            try:
                passed = await fn(space_id)
                if passed:
                    results["tests_passed"] += 1
                    logger.info(f"  ✅ {name}")
                else:
                    results["tests_failed"] += 1
                    results["errors"].append(name)
                    logger.info(f"  ❌ {name}")
            except Exception as e:
                results["tests_failed"] += 1
                results["errors"].append(f"{name}: {e}")
                logger.info(f"  ❌ {name}: {e}")

        return results

    async def _query(self, space_id: str, sparql: str) -> SPARQLQueryResponse:
        req = SPARQLQueryRequest(query=sparql, format="json")
        return await self.client.execute_sparql_query(space_id, req)

    async def _test_triple_count(self, space_id: str) -> bool:
        """Count total triples in the space."""
        sparql = "SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o }"
        t0 = time.time()
        result = await self._query(space_id, sparql)
        dt = time.time() - t0

        bindings = result.results.get("bindings", []) if result.results else []
        if not bindings:
            logger.info("    No results returned")
            return False

        count = bindings[0].get("count", {}).get("value", "0")
        logger.info(f"    Total triples: {int(count):,}  ({dt:.3f}s)")
        return int(count) > 0

    async def _test_type_counts(self, space_id: str) -> bool:
        """Count entities grouped by rdf:type."""
        sparql = f"""
        SELECT ?type (COUNT(?s) AS ?count) WHERE {{
            ?s <{RDF_TYPE}> ?type .
        }}
        GROUP BY ?type
        ORDER BY DESC(?count)
        LIMIT 10
        """
        t0 = time.time()
        result = await self._query(space_id, sparql)
        dt = time.time() - t0

        bindings = result.results.get("bindings", []) if result.results else []
        if not bindings:
            logger.info("    No type counts returned")
            return False

        logger.info(f"    Top types ({dt:.3f}s):")
        for b in bindings[:5]:
            t = b.get("type", {}).get("value", "?")
            c = b.get("count", {}).get("value", "0")
            short = t.rsplit("#", 1)[-1] if "#" in t else t.rsplit("/", 1)[-1]
            logger.info(f"      {short}: {int(c):,}")
        return True

    async def _test_find_happy(self, space_id: str) -> bool:
        """Find KGEntity instances with 'happy' in their name."""
        sparql = f"""
        SELECT ?entity ?name WHERE {{
            ?entity <{RDF_TYPE}> <{HALEY_KG_ENTITY}> .
            ?entity <{VITAL_NAME}> ?name .
            FILTER(CONTAINS(?name, "happy"))
        }}
        LIMIT 20
        """
        t0 = time.time()
        result = await self._query(space_id, sparql)
        dt = time.time() - t0

        bindings = result.results.get("bindings", []) if result.results else []
        logger.info(f"    Found {len(bindings)} 'happy' entities ({dt:.3f}s)")
        for b in bindings[:5]:
            name = b.get("name", {}).get("value", "?")
            logger.info(f"      - {name}")
        return len(bindings) > 0

    async def _test_predicate_inventory(self, space_id: str) -> bool:
        """List distinct predicates used in the dataset."""
        sparql = """
        SELECT ?p (COUNT(*) AS ?count) WHERE {
            ?s ?p ?o .
        }
        GROUP BY ?p
        ORDER BY DESC(?count)
        LIMIT 15
        """
        t0 = time.time()
        result = await self._query(space_id, sparql)
        dt = time.time() - t0

        bindings = result.results.get("bindings", []) if result.results else []
        if not bindings:
            logger.info("    No predicates returned")
            return False

        logger.info(f"    {len(bindings)} predicates ({dt:.3f}s):")
        for b in bindings[:8]:
            p = b.get("p", {}).get("value", "?")
            c = b.get("count", {}).get("value", "0")
            short = p.rsplit("#", 1)[-1] if "#" in p else p.rsplit("/", 1)[-1]
            logger.info(f"      {short}: {int(c):,}")
        return True

    async def _test_limit_offset(self, space_id: str) -> bool:
        """Test LIMIT and OFFSET pagination."""
        sparql_page1 = f"""
        SELECT ?entity ?name WHERE {{
            ?entity <{RDF_TYPE}> <{HALEY_KG_ENTITY}> .
            ?entity <{VITAL_NAME}> ?name .
        }}
        ORDER BY ?name
        LIMIT 5 OFFSET 0
        """
        sparql_page2 = f"""
        SELECT ?entity ?name WHERE {{
            ?entity <{RDF_TYPE}> <{HALEY_KG_ENTITY}> .
            ?entity <{VITAL_NAME}> ?name .
        }}
        ORDER BY ?name
        LIMIT 5 OFFSET 5
        """
        r1 = await self._query(space_id, sparql_page1)
        r2 = await self._query(space_id, sparql_page2)

        b1 = r1.results.get("bindings", []) if r1.results else []
        b2 = r2.results.get("bindings", []) if r2.results else []

        if not b1 or not b2:
            logger.info("    Pagination returned empty pages")
            return False

        # Pages should be different
        names1 = {b.get("name", {}).get("value") for b in b1}
        names2 = {b.get("name", {}).get("value") for b in b2}
        overlap = names1 & names2

        logger.info(f"    Page 1: {len(b1)} results, Page 2: {len(b2)} results, overlap: {len(overlap)}")
        return len(overlap) == 0
