"""
Verify search modules — each module tests a specific search mode.
"""

import logging

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.sparql_model import SPARQLQueryRequest, SPARQLQueryResponse

from test_scripts.semantic_search.config import TEST_SPACE_ID

logger = logging.getLogger(__name__)


class SearchVerifier:
    """Runs search verification tests and tracks pass/fail counts."""

    def __init__(self, client: VitalGraphClient):
        self.client = client
        self.passed = 0
        self.failed = 0
        self.errors: list = []

    def check(self, label: str, condition: bool, detail: str = ""):
        if condition:
            self.passed += 1
            msg = f"  ✅ {label}"
            if detail:
                msg += f" — {detail}"
            logger.info(msg)
        else:
            self.failed += 1
            msg = f"  ❌ {label}"
            if detail:
                msg += f" — {detail}"
            logger.error(msg)
            self.errors.append(f"{label}: {detail}")

    async def sparql(self, query: str) -> SPARQLQueryResponse:
        """Execute a SPARQL query and return parsed response."""
        req = SPARQLQueryRequest(query=query)
        resp = await self.client.sparql.execute_sparql_query(
            space_id=TEST_SPACE_ID, request=req)
        return resp
