"""
Graphs CRUD Test Case — SPARQL-SQL Backend

Tests graph lifecycle: list, create, get_info, clear, drop.
"""

import logging
from typing import Dict, Any

from vitalgraph.model.quad_model import Quad, QuadRequest

logger = logging.getLogger(__name__)


class GraphsCrudTester:
    """Client-based test for graphs CRUD against sparql_sql backend."""

    def __init__(self, client):
        self.client = client

    async def run_tests(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """
        Run graphs CRUD tests.

        Args:
            space_id: Space to operate in
            graph_id: Named graph URI to create / test / drop

        Returns:
            Standard test results dict
        """
        results = {
            "test_name": "Graphs CRUD",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": [],
        }

        logger.info(f"\n{'=' * 80}")
        logger.info(f"  Graphs CRUD")
        logger.info(f"{'=' * 80}")

        # --- 1. List graphs (baseline) ---
        results["tests_run"] += 1
        try:
            lr = await self.client.graphs.list_graphs(space_id)
            if lr.is_success:
                logger.info(f"✅ PASS: List graphs — {lr.total} graph(s) in space")
                results["tests_passed"] += 1
            else:
                raise Exception(lr.error_message)
        except Exception as e:
            logger.error(f"❌ FAIL: List graphs — {e}")
            results["errors"].append(f"List graphs: {e}")

        # --- 2. Create named graph ---
        results["tests_run"] += 1
        try:
            cgr = await self.client.graphs.create_graph(space_id, graph_id)
            if cgr.is_success:
                logger.info(f"✅ PASS: Create graph '{graph_id}'")
                results["tests_passed"] += 1
            else:
                raise Exception(cgr.error_message)
        except Exception as e:
            logger.error(f"❌ FAIL: Create graph — {e}")
            results["errors"].append(f"Create graph: {e}")

        # --- 3. List graphs includes new graph ---
        results["tests_run"] += 1
        try:
            lr2 = await self.client.graphs.list_graphs(space_id)
            uris = [g.graph_uri for g in lr2.graphs] if lr2.graphs else []
            if graph_id in uris:
                logger.info(f"✅ PASS: List graphs includes '{graph_id}'")
                results["tests_passed"] += 1
            else:
                raise Exception(f"not found in {uris}")
        except Exception as e:
            logger.error(f"❌ FAIL: List graphs after create — {e}")
            results["errors"].append(f"List graphs after create: {e}")

        # --- 4. Get graph info ---
        results["tests_run"] += 1
        try:
            gi = await self.client.graphs.get_graph_info(space_id, graph_id)
            if gi.is_success and gi.graph:
                logger.info(f"✅ PASS: Get graph info — triple_count={getattr(gi.graph, 'triple_count', '?')}")
                results["tests_passed"] += 1
            else:
                raise Exception(getattr(gi, "error_message", "unexpected"))
        except Exception as e:
            logger.error(f"❌ FAIL: Get graph info — {e}")
            results["errors"].append(f"Get graph info: {e}")

        # --- 5. Add triples so we can test clear ---
        results["tests_run"] += 1
        try:
            quads = QuadRequest(quads=[
                Quad(s="<http://example.org/graphtest/1>",
                     p="<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>",
                     o="<http://example.org/TestNode>",
                     g=f"<{graph_id}>"),
                Quad(s="<http://example.org/graphtest/1>",
                     p="<http://example.org/label>",
                     o='"Graph Test Node"',
                     g=f"<{graph_id}>"),
            ])
            ar = await self.client.triples.add_triples(space_id, graph_id, quads)
            if ar.success:
                logger.info(f"✅ PASS: Add 2 triples to graph")
                results["tests_passed"] += 1
            else:
                raise Exception(ar.message)
        except Exception as e:
            logger.error(f"❌ FAIL: Add triples to graph — {e}")
            results["errors"].append(f"Add triples to graph: {e}")

        # --- 6. Clear graph ---
        results["tests_run"] += 1
        try:
            clr = await self.client.graphs.clear_graph(space_id, graph_id)
            if clr.is_success:
                logger.info(f"✅ PASS: Clear graph")
                results["tests_passed"] += 1
            else:
                raise Exception(clr.error_message)
        except Exception as e:
            logger.error(f"❌ FAIL: Clear graph — {e}")
            results["errors"].append(f"Clear graph: {e}")

        # --- 7. Verify clear ---
        results["tests_run"] += 1
        try:
            tr = await self.client.triples.list_triples(space_id, graph_id, page_size=10)
            if tr.success and tr.total_count == 0:
                logger.info(f"✅ PASS: Verify graph cleared — 0 triples")
                results["tests_passed"] += 1
            else:
                raise Exception(f"expected 0, got {getattr(tr, 'total_count', '?')}")
        except Exception as e:
            logger.error(f"❌ FAIL: Verify graph cleared — {e}")
            results["errors"].append(f"Verify graph cleared: {e}")

        # --- 8. Drop graph ---
        results["tests_run"] += 1
        try:
            dgr = await self.client.graphs.drop_graph(space_id, graph_id)
            if dgr.is_success:
                logger.info(f"✅ PASS: Drop graph")
                results["tests_passed"] += 1
            else:
                raise Exception(dgr.error_message)
        except Exception as e:
            logger.error(f"❌ FAIL: Drop graph — {e}")
            results["errors"].append(f"Drop graph: {e}")

        # --- 9. Verify drop ---
        results["tests_run"] += 1
        try:
            lr3 = await self.client.graphs.list_graphs(space_id)
            uris = [g.graph_uri for g in lr3.graphs] if lr3.graphs else []
            if graph_id not in uris:
                logger.info(f"✅ PASS: Verify graph dropped")
                results["tests_passed"] += 1
            else:
                raise Exception("still listed")
        except Exception as e:
            logger.error(f"❌ FAIL: Verify graph dropped — {e}")
            results["errors"].append(f"Verify graph dropped: {e}")

        return results
