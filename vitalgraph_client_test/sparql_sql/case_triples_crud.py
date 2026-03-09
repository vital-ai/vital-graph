"""
Triples CRUD Test Case — SPARQL-SQL Backend

Tests triple lifecycle: add, list, filter (subject/predicate/object_filter), delete, verify.
"""

import logging
from typing import Dict, Any

from vitalgraph.model.quad_model import Quad, QuadRequest

logger = logging.getLogger(__name__)

NS = "http://example.org/test/"


class TriplesCrudTester:
    """Client-based test for triples CRUD against sparql_sql backend."""

    def __init__(self, client):
        self.client = client

    async def run_tests(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """
        Run triples CRUD tests.

        Args:
            space_id: Space to operate in
            graph_id: Graph URI for triple operations

        Returns:
            Standard test results dict
        """
        results = {
            "test_name": "Triples CRUD",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": [],
        }

        logger.info(f"\n{'=' * 80}")
        logger.info(f"  Triples CRUD")
        logger.info(f"{'=' * 80}")

        RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
        XSD_INT = "http://www.w3.org/2001/XMLSchema#integer"
        alice = f"{NS}person/alice"
        bob = f"{NS}person/bob"

        sample_quads = QuadRequest(quads=[
            Quad(s=f"<{alice}>", p=f"<{RDF_TYPE}>", o=f"<{NS}Person>", g=f"<{graph_id}>"),
            Quad(s=f"<{alice}>", p=f"<{NS}name>", o='"Alice"', g=f"<{graph_id}>"),
            Quad(s=f"<{alice}>", p=f"<{NS}age>", o=f'"30"^^<{XSD_INT}>', g=f"<{graph_id}>"),
            Quad(s=f"<{bob}>", p=f"<{RDF_TYPE}>", o=f"<{NS}Person>", g=f"<{graph_id}>"),
            Quad(s=f"<{bob}>", p=f"<{NS}name>", o='"Bob"', g=f"<{graph_id}>"),
            Quad(s=f"<{bob}>", p=f"<{NS}age>", o=f'"25"^^<{XSD_INT}>', g=f"<{graph_id}>"),
            Quad(s=f"<{alice}>", p=f"<{NS}knows>", o=f"<{bob}>", g=f"<{graph_id}>"),
        ])
        TOTAL = len(sample_quads.quads)

        # --- 1. Add triples ---
        results["tests_run"] += 1
        try:
            ar = await self.client.triples.add_triples(space_id, graph_id, sample_quads)
            if ar.success:
                logger.info(f"✅ PASS: Add {TOTAL} triples")
                results["tests_passed"] += 1
            else:
                raise Exception(ar.message)
        except Exception as e:
            logger.error(f"❌ FAIL: Add triples — {e}")
            results["errors"].append(f"Add triples: {e}")
            return results  # can't continue

        # --- 2. List all triples ---
        results["tests_run"] += 1
        try:
            lr = await self.client.triples.list_triples(space_id, graph_id, page_size=50)
            if lr.success and lr.total_count >= TOTAL:
                logger.info(f"✅ PASS: List triples — total_count={lr.total_count}")
                results["tests_passed"] += 1
            else:
                raise Exception(f"expected >= {TOTAL}, got {getattr(lr, 'total_count', '?')}")
        except Exception as e:
            logger.error(f"❌ FAIL: List triples — {e}")
            results["errors"].append(f"List triples: {e}")

        # --- 3. Filter by subject (alice) ---
        results["tests_run"] += 1
        try:
            fr_s = await self.client.triples.list_triples(space_id, graph_id, page_size=50, subject=alice)
            # alice: type, name, age, knows = 4
            if fr_s.success and fr_s.total_count >= 4:
                logger.info(f"✅ PASS: Filter by subject (alice) — {fr_s.total_count} triples")
                results["tests_passed"] += 1
            else:
                raise Exception(f"expected >= 4, got {getattr(fr_s, 'total_count', '?')}")
        except Exception as e:
            logger.error(f"❌ FAIL: Filter by subject — {e}")
            results["errors"].append(f"Filter by subject: {e}")

        # --- 4. Filter by predicate (rdf:type) ---
        results["tests_run"] += 1
        try:
            fr_p = await self.client.triples.list_triples(space_id, graph_id, page_size=50, predicate=RDF_TYPE)
            if fr_p.success and fr_p.total_count >= 2:
                logger.info(f"✅ PASS: Filter by predicate (rdf:type) — {fr_p.total_count} triples")
                results["tests_passed"] += 1
            else:
                raise Exception(f"expected >= 2, got {getattr(fr_p, 'total_count', '?')}")
        except Exception as e:
            logger.error(f"❌ FAIL: Filter by predicate — {e}")
            results["errors"].append(f"Filter by predicate: {e}")

        # --- 5. Filter by object_filter keyword ---
        results["tests_run"] += 1
        try:
            fr_kw = await self.client.triples.list_triples(space_id, graph_id, page_size=50, object_filter="Alice")
            if fr_kw.success and fr_kw.total_count >= 1:
                logger.info(f"✅ PASS: Filter by object_filter 'Alice' — {fr_kw.total_count} triples")
                results["tests_passed"] += 1
            else:
                raise Exception(f"expected >= 1, got {getattr(fr_kw, 'total_count', '?')}")
        except Exception as e:
            logger.error(f"❌ FAIL: Filter by object_filter — {e}")
            results["errors"].append(f"Filter by object_filter: {e}")

        # --- 6. Delete triples by subject (bob) ---
        results["tests_run"] += 1
        try:
            dr = await self.client.triples.delete_triples(space_id, graph_id, subject=bob)
            if dr.success:
                logger.info(f"✅ PASS: Delete triples for subject bob")
                results["tests_passed"] += 1
            else:
                raise Exception(dr.message)
        except Exception as e:
            logger.error(f"❌ FAIL: Delete triples (bob) — {e}")
            results["errors"].append(f"Delete triples (bob): {e}")

        # --- 7. Verify bob deleted ---
        results["tests_run"] += 1
        try:
            fr_bob = await self.client.triples.list_triples(space_id, graph_id, page_size=50, subject=bob)
            if fr_bob.success and fr_bob.total_count == 0:
                logger.info(f"✅ PASS: Verify bob deleted — 0 triples")
                results["tests_passed"] += 1
            else:
                raise Exception(f"expected 0, got {getattr(fr_bob, 'total_count', '?')}")
        except Exception as e:
            logger.error(f"❌ FAIL: Verify bob deleted — {e}")
            results["errors"].append(f"Verify bob deleted: {e}")

        # --- 8. Alice's knows edge still present ---
        results["tests_run"] += 1
        try:
            fr_knows = await self.client.triples.list_triples(
                space_id, graph_id, page_size=50, predicate=f"{NS}knows")
            if fr_knows.success and fr_knows.total_count >= 1:
                logger.info(f"✅ PASS: Alice's 'knows' edge still present")
                results["tests_passed"] += 1
            else:
                raise Exception(f"expected >= 1, got {getattr(fr_knows, 'total_count', '?')}")
        except Exception as e:
            logger.error(f"❌ FAIL: Alice knows edge — {e}")
            results["errors"].append(f"Alice knows edge: {e}")

        # --- 9. Delete by predicate (knows) ---
        results["tests_run"] += 1
        try:
            dr2 = await self.client.triples.delete_triples(space_id, graph_id, predicate=f"{NS}knows")
            if dr2.success:
                logger.info(f"✅ PASS: Delete triples by predicate (knows)")
                results["tests_passed"] += 1
            else:
                raise Exception(dr2.message)
        except Exception as e:
            logger.error(f"❌ FAIL: Delete by predicate — {e}")
            results["errors"].append(f"Delete by predicate: {e}")

        # --- 10. Delete remaining alice triples ---
        results["tests_run"] += 1
        try:
            dr3 = await self.client.triples.delete_triples(space_id, graph_id, subject=alice)
            if dr3.success:
                logger.info(f"✅ PASS: Delete remaining alice triples")
                results["tests_passed"] += 1
            else:
                raise Exception(dr3.message)
        except Exception as e:
            logger.error(f"❌ FAIL: Delete alice triples — {e}")
            results["errors"].append(f"Delete alice triples: {e}")

        # --- 11. Final verification — 0 triples ---
        results["tests_run"] += 1
        try:
            lr_final = await self.client.triples.list_triples(space_id, graph_id, page_size=50)
            if lr_final.success and lr_final.total_count == 0:
                logger.info(f"✅ PASS: Final verification — 0 triples remaining")
                results["tests_passed"] += 1
            else:
                raise Exception(f"expected 0, got {getattr(lr_final, 'total_count', '?')}")
        except Exception as e:
            logger.error(f"❌ FAIL: Final verification — {e}")
            results["errors"].append(f"Final verification: {e}")

        return results
