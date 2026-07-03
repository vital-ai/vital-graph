"""API tests: Ontology introspection endpoints.

Tests GET /ontology/classes and GET /ontology/properties via
vg_client.ontology (OntologyClientEndpoint).
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.api, pytest.mark.asyncio(loop_scope="session")]

KGENTITY_URI = "http://vital.ai/ontology/haley-ai-kg#KGEntity"


# ---------------------------------------------------------------------------
# GET /ontology/classes
# ---------------------------------------------------------------------------

class TestOntologyClasses:
    """GET /ontology/classes — list known class URIs."""

    async def test_list_classes(self, vg_client):
        """Returns a non-empty list of class URIs."""
        resp = await vg_client.ontology.list_classes()
        assert isinstance(resp.classes, list)
        assert len(resp.classes) > 0

    async def test_known_class_present(self, vg_client):
        """Known KGEntity class URI is in the list."""
        resp = await vg_client.ontology.list_classes()
        assert KGENTITY_URI in resp.classes


# ---------------------------------------------------------------------------
# GET /ontology/properties
# ---------------------------------------------------------------------------

class TestOntologyProperties:
    """GET /ontology/properties — list properties for a given class URI."""

    async def test_properties_for_kgentity(self, vg_client):
        """Properties for KGEntity returns non-empty list with expected fields."""
        resp = await vg_client.ontology.get_properties(KGENTITY_URI)
        assert resp.class_uri == KGENTITY_URI
        assert resp.total_count > 0
        assert len(resp.properties) == resp.total_count

        prop = resp.properties[0]
        assert prop.uri.startswith("http://")

    async def test_properties_have_metadata(self, vg_client):
        """At least some properties have local_name and short_name populated."""
        resp = await vg_client.ontology.get_properties(KGENTITY_URI)
        has_local = any(p.local_name for p in resp.properties)
        has_short = any(p.short_name for p in resp.properties)
        assert has_local, "Expected at least one property with local_name"
        assert has_short, "Expected at least one property with short_name"

    async def test_properties_unknown_class(self, vg_client):
        """Unknown class URI returns empty properties list."""
        resp = await vg_client.ontology.get_properties("http://example.org/UnknownClass")
        assert resp.total_count == 0
        assert resp.properties == []
