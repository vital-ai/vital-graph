"""API tests: KGDocuments CRUD lifecycle via VitalGraphClient.

Tests create, list, get, update, delete KGDocuments.
"""

from __future__ import annotations

import uuid

import pytest

from ai_haley_kg_domain.model.KGDocument import KGDocument

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

NS = "http://example.org/apitest/kgdoc/"
DOC_TYPE = "http://vital.ai/ontology/haley-ai-kg#ArticleDocument"


def _make_document(title: str, content: str = "Test content body.") -> KGDocument:
    """Create a KGDocument with a unique URI."""
    doc = KGDocument()
    doc.URI = f"{NS}{uuid.uuid4().hex[:12]}"
    doc.name = title
    doc.kGDocumentHeadline = title
    doc.kGDocumentContent = content
    doc.kGDocumentType = DOC_TYPE
    return doc


# ---------------------------------------------------------------------------
# Full CRUD lifecycle
# ---------------------------------------------------------------------------

class TestKGDocumentsCrud:
    """KGDocument lifecycle: create → list → get → update → delete."""

    async def test_create_documents(self, vg_client, test_space, test_graph):
        """Create KGDocuments individually."""
        doc = _make_document("API Test Doc Alpha")
        resp = await vg_client.kgdocuments.create_kgdocuments(
            space_id=test_space, graph_id=test_graph, objects=[doc]
        )
        assert resp.is_success, f"Create failed: {resp.error_message}"
        assert resp.created_count >= 1

    async def test_create_batch(self, vg_client, test_space, test_graph):
        """Create multiple KGDocuments in a single request."""
        docs = [
            _make_document("Batch Doc 1", "Content for document one."),
            _make_document("Batch Doc 2", "Content for document two."),
            _make_document("Batch Doc 3", "Content for document three."),
        ]
        resp = await vg_client.kgdocuments.create_kgdocuments(
            space_id=test_space, graph_id=test_graph, objects=docs
        )
        assert resp.is_success, f"Batch create failed: {resp.error_message}"
        assert resp.created_count >= 3

    async def test_list_documents(self, vg_client, test_space, test_graph):
        """List documents — should include previously created ones."""
        doc = _make_document("ListTestDoc")
        await vg_client.kgdocuments.create_kgdocuments(
            space_id=test_space, graph_id=test_graph, objects=[doc]
        )

        resp = await vg_client.kgdocuments.list_kgdocuments(
            space_id=test_space, graph_id=test_graph
        )
        assert resp.is_success, f"List failed: {resp.error_message}"
        assert resp.count >= 1

    async def test_get_document_by_uri(self, vg_client, test_space, test_graph):
        """Get a specific KGDocument by URI."""
        doc = _make_document("GetByUriDoc")
        await vg_client.kgdocuments.create_kgdocuments(
            space_id=test_space, graph_id=test_graph, objects=[doc]
        )

        resp = await vg_client.kgdocuments.get_kgdocument(
            space_id=test_space, graph_id=test_graph, uri=str(doc.URI)
        )
        assert resp.is_success, f"Get failed: {resp.error_message}"
        assert resp.document is not None
        assert str(resp.document.URI) == str(doc.URI)

    async def test_update_document(self, vg_client, test_space, test_graph):
        """Create then update a KGDocument."""
        doc = _make_document("OriginalTitle", "Original content.")
        await vg_client.kgdocuments.create_kgdocuments(
            space_id=test_space, graph_id=test_graph, objects=[doc]
        )

        # Update
        doc.kGDocumentHeadline = "Updated Title"
        doc.kGDocumentContent = "Updated content body."
        resp = await vg_client.kgdocuments.update_kgdocuments(
            space_id=test_space, graph_id=test_graph, objects=[doc]
        )
        assert resp.is_success, f"Update failed: {resp.error_message}"
        assert resp.updated_count >= 1

    async def test_delete_document(self, vg_client, test_space, test_graph):
        """Create then delete a KGDocument and verify removal."""
        doc = _make_document("ToDeleteDoc")
        await vg_client.kgdocuments.create_kgdocuments(
            space_id=test_space, graph_id=test_graph, objects=[doc]
        )

        # Delete
        del_resp = await vg_client.kgdocuments.delete_kgdocument(
            space_id=test_space, graph_id=test_graph, uri=str(doc.URI)
        )
        assert del_resp.is_success, f"Delete failed: {del_resp.error_message}"
        assert del_resp.deleted_count >= 1

        # Verify gone
        get_resp = await vg_client.kgdocuments.get_kgdocument(
            space_id=test_space, graph_id=test_graph, uri=str(doc.URI)
        )
        assert not get_resp.is_success or get_resp.document is None

    async def test_list_segments_empty(self, vg_client, test_space, test_graph):
        """List segments for a newly created document — should be empty."""
        doc = _make_document("NoSegmentsDoc")
        await vg_client.kgdocuments.create_kgdocuments(
            space_id=test_space, graph_id=test_graph, objects=[doc]
        )

        resp = await vg_client.kgdocuments.list_segments(
            space_id=test_space, graph_id=test_graph, parent_uri=str(doc.URI)
        )
        assert resp.is_success, f"List segments failed: {resp.error_message}"
        assert resp.count == 0


# ---------------------------------------------------------------------------
# Segmentation config CRUD
# ---------------------------------------------------------------------------

SEG_METHOD = "http://vital.ai/ontology/haley-ai-kg#SentenceSplitter"


class TestSegmentationConfigCrud:
    """Segmentation config lifecycle: create → list → update → delete."""

    async def test_create_config(self, vg_client, test_space):
        """Create a segmentation config and verify returned fields."""
        resp = await vg_client.kgdocuments.create_segmentation_config(
            space_id=test_space,
            document_type_uri=DOC_TYPE,
            segment_method_uri=SEG_METHOD,
            max_segment_tokens=256,
            min_segment_tokens=30,
            overlap_tokens=10,
            enabled=True,
            auto_vectorize=False,
        )
        assert resp.get("config_id") is not None
        assert resp["document_type_uri"] == DOC_TYPE
        assert resp["segment_method_uri"] == SEG_METHOD
        assert resp["max_segment_tokens"] == 256

        # Cleanup
        await vg_client.kgdocuments.delete_segmentation_config(
            space_id=test_space, config_id=resp["config_id"]
        )

    async def test_list_configs(self, vg_client, test_space):
        """Create a config then list configs — should contain at least 1."""
        created = await vg_client.kgdocuments.create_segmentation_config(
            space_id=test_space,
            document_type_uri=DOC_TYPE,
            segment_method_uri=SEG_METHOD,
        )
        config_id = created["config_id"]

        resp = await vg_client.kgdocuments.list_segmentation_configs(
            space_id=test_space
        )
        assert resp.get("total_count", 0) >= 1
        config_ids = [c["config_id"] for c in resp.get("configs", [])]
        assert config_id in config_ids

        # Cleanup
        await vg_client.kgdocuments.delete_segmentation_config(
            space_id=test_space, config_id=config_id
        )

    async def test_list_configs_enabled_only(self, vg_client, test_space):
        """enabled_only=True filters out disabled configs."""
        created = await vg_client.kgdocuments.create_segmentation_config(
            space_id=test_space,
            document_type_uri=DOC_TYPE,
            segment_method_uri=SEG_METHOD,
            enabled=False,
        )
        config_id = created["config_id"]

        resp = await vg_client.kgdocuments.list_segmentation_configs(
            space_id=test_space, enabled_only=True
        )
        config_ids = [c["config_id"] for c in resp.get("configs", [])]
        assert config_id not in config_ids

        # Cleanup
        await vg_client.kgdocuments.delete_segmentation_config(
            space_id=test_space, config_id=config_id
        )

    async def test_update_config(self, vg_client, test_space):
        """Create config, update max_segment_tokens, verify change."""
        created = await vg_client.kgdocuments.create_segmentation_config(
            space_id=test_space,
            document_type_uri=DOC_TYPE,
            segment_method_uri=SEG_METHOD,
            max_segment_tokens=512,
        )
        config_id = created["config_id"]

        updated = await vg_client.kgdocuments.update_segmentation_config(
            space_id=test_space,
            config_id=config_id,
            document_type_uri=DOC_TYPE,
            segment_method_uri=SEG_METHOD,
            max_segment_tokens=1024,
        )
        assert updated["max_segment_tokens"] == 1024

        # Cleanup
        await vg_client.kgdocuments.delete_segmentation_config(
            space_id=test_space, config_id=config_id
        )

    async def test_delete_config(self, vg_client, test_space):
        """Create then delete config, verify it's gone from list."""
        created = await vg_client.kgdocuments.create_segmentation_config(
            space_id=test_space,
            document_type_uri=DOC_TYPE,
            segment_method_uri=SEG_METHOD,
        )
        config_id = created["config_id"]

        await vg_client.kgdocuments.delete_segmentation_config(
            space_id=test_space, config_id=config_id
        )

        resp = await vg_client.kgdocuments.list_segmentation_configs(
            space_id=test_space
        )
        config_ids = [c["config_id"] for c in resp.get("configs", [])]
        assert config_id not in config_ids


# ---------------------------------------------------------------------------
# Segmentation trigger & status
# ---------------------------------------------------------------------------


class TestSegmentationTriggerAndStatus:
    """Segmentation trigger and status endpoints."""

    async def test_segmentation_status_empty(self, vg_client, test_space):
        """Get segmentation status for a space — should return valid structure."""
        resp = await vg_client.kgdocuments.get_segmentation_status(
            space_id=test_space
        )
        assert isinstance(resp, dict)
        # Should have numeric status fields or jobs list
        has_valid_keys = any(k in resp for k in ("pending", "in_progress", "completed", "failed", "jobs"))
        assert has_valid_keys, f"Unexpected status response: {resp}"

    async def test_segmentation_status_with_filter(self, vg_client, test_space):
        """Get segmentation status filtered by a non-existent document — empty result."""
        resp = await vg_client.kgdocuments.get_segmentation_status(
            space_id=test_space,
            document_uri="http://example.org/nonexistent-doc"
        )
        assert isinstance(resp, dict)

    async def test_trigger_segment_returns_promptly(self, vg_client, test_space, test_graph):
        """Trigger segmentation — should return promptly (enqueued or queue-unavailable error)."""
        doc = _make_document("SegmentableDoc", "This is a long document body. " * 50)
        await vg_client.kgdocuments.create_kgdocuments(
            space_id=test_space, graph_id=test_graph, objects=[doc]
        )

        resp = await vg_client.kgdocuments.segment_document(
            space_id=test_space,
            graph_id=test_graph,
            document_uri=str(doc.URI),
        )
        assert isinstance(resp, dict)
        # Either enqueued successfully or returned queue-unavailable error (both are valid)
        assert "success" in resp or "message" in resp
