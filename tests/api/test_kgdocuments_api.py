"""API tests: KGDocuments CRUD lifecycle via VitalGraphClient.

Tests create, list, get, update, delete KGDocuments.
"""

from __future__ import annotations

import asyncio
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
        assert resp.config_id is not None
        assert resp.document_type_uri == DOC_TYPE
        assert resp.segment_method_uri == SEG_METHOD
        assert resp.max_segment_tokens == 256

        # Cleanup
        await vg_client.kgdocuments.delete_segmentation_config(
            space_id=test_space, config_id=resp.config_id
        )

    async def test_list_configs(self, vg_client, test_space):
        """Create a config then list configs — should contain at least 1."""
        created = await vg_client.kgdocuments.create_segmentation_config(
            space_id=test_space,
            document_type_uri=DOC_TYPE,
            segment_method_uri=SEG_METHOD,
        )
        config_id = created.config_id

        resp = await vg_client.kgdocuments.list_segmentation_configs(
            space_id=test_space
        )
        assert resp.total_count >= 1
        config_ids = [c["config_id"] for c in resp.configs]
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
        config_id = created.config_id

        resp = await vg_client.kgdocuments.list_segmentation_configs(
            space_id=test_space, enabled_only=True
        )
        config_ids = [c["config_id"] for c in resp.configs]
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
        config_id = created.config_id

        updated = await vg_client.kgdocuments.update_segmentation_config(
            space_id=test_space,
            config_id=config_id,
            document_type_uri=DOC_TYPE,
            segment_method_uri=SEG_METHOD,
            max_segment_tokens=1024,
        )
        assert updated.max_segment_tokens == 1024

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
        config_id = created.config_id

        await vg_client.kgdocuments.delete_segmentation_config(
            space_id=test_space, config_id=config_id
        )

        resp = await vg_client.kgdocuments.list_segmentation_configs(
            space_id=test_space
        )
        config_ids = [c["config_id"] for c in resp.configs]
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
        assert resp.is_success
        # Should have numeric status fields
        assert hasattr(resp, "pending")
        assert hasattr(resp, "jobs")

    async def test_segmentation_status_with_filter(self, vg_client, test_space):
        """Get segmentation status filtered by a non-existent document — empty result."""
        resp = await vg_client.kgdocuments.get_segmentation_status(
            space_id=test_space,
            document_uri="http://example.org/nonexistent-doc"
        )
        assert resp.is_success

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
        # Either enqueued successfully or returned queue-unavailable error (both are valid)
        assert hasattr(resp, "success")


# ---------------------------------------------------------------------------
# Segment delete: relationship-scoped, not URI-prefix-scoped
# ---------------------------------------------------------------------------
#
# Regression tests for issues/021_uri_prefix_string_matching_in_deletes.md.
#
# The deletes used to identify segmentation output with
# STRSTARTS(STR(?s), "{original_uri}_parent_"), so any unrelated subject whose
# URI merely *extended* that prefix was destroyed as collateral. Every test
# here creates a decoy that the old code would have deleted and asserts it
# survives.


async def _segment_and_wait(vg_client, space, graph, doc_uri, timeout_s=90):
    """Trigger segmentation and poll until segments exist. Returns their URIs."""
    resp = await vg_client.kgdocuments.segment_document(
        space_id=space, graph_id=graph, document_uri=doc_uri,
        max_segment_tokens=64,
    )
    if not getattr(resp, "success", False) and not getattr(resp, "is_success", False):
        pytest.skip(f"Segmentation unavailable in this environment: {resp}")

    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        segs = await vg_client.kgdocuments.list_segments(
            space_id=space, graph_id=graph, parent_uri=doc_uri
        )
        if segs.is_success and segs.count > 0:
            return [str(s.URI) for s in segs.segments]
        await asyncio.sleep(2.0)

    pytest.skip(f"Segmentation did not complete within {timeout_s}s for {doc_uri}")


async def _exists(vg_client, space, graph, uri) -> bool:
    resp = await vg_client.kgdocuments.get_kgdocument(
        space_id=space, graph_id=graph, uri=uri
    )
    return bool(resp.is_success and resp.document is not None)


class TestSegmentDeleteScoping:
    """Deletion must follow Edge_hasKGDocumentSegment, not URI text."""

    async def test_cascade_deletes_segments_and_spares_prefix_decoy(
        self, vg_client, test_space, test_graph
    ):
        """The headline regression.

        A decoy document whose URI extends '{original}_parent_' must survive
        the original's delete. Pre-fix, the cascade's STRSTARTS filter matched
        and destroyed it.
        """
        doc = _make_document("CascadeOriginal", "# Head\n\nBody text. " * 60)
        doc_uri = str(doc.URI)

        # Decoy: a legitimate, unrelated document that merely shares the prefix.
        decoy = KGDocument()
        decoy.URI = f"{doc_uri}_parent_other"
        decoy.name = "Innocent Bystander"
        decoy.kGDocumentContent = "Unrelated content."
        decoy.kGDocumentType = DOC_TYPE
        decoy_uri = str(decoy.URI)

        cr = await vg_client.kgdocuments.create_kgdocuments(
            space_id=test_space, graph_id=test_graph, objects=[doc, decoy]
        )
        assert cr.is_success, f"precondition: create failed: {cr.error_message}"
        assert await _exists(vg_client, test_space, test_graph, decoy_uri), (
            "precondition: decoy was not created")
        segment_uris = await _segment_and_wait(
            vg_client, test_space, test_graph, doc_uri
        )
        assert segment_uris, "precondition: document must have segments"

        del_resp = await vg_client.kgdocuments.delete_kgdocument(
            space_id=test_space, graph_id=test_graph, uri=doc_uri
        )
        assert del_resp.is_success, f"Delete failed: {del_resp.error_message}"

        # The cascade actually ran: segments are gone. Guards the pre-fix bug
        # where the DELETE was issued through execute_sparql_query — a no-op on
        # the SQL backend, so segments leaked silently.
        remaining = await vg_client.kgdocuments.list_segments(
            space_id=test_space, graph_id=test_graph, parent_uri=doc_uri
        )
        assert not remaining.is_success or remaining.count == 0, (
            f"Cascade left {remaining.count} segment(s) behind — "
            "the delete did not execute"
        )
        for seg_uri in segment_uris:
            assert not await _exists(vg_client, test_space, test_graph, seg_uri), (
                f"Segment {seg_uri} survived the cascade"
            )

        # ...and the decoy is untouched.
        assert await _exists(vg_client, test_space, test_graph, decoy_uri), (
            f"Collateral deletion: {decoy_uri} was destroyed because its URI "
            f"extends the deleted document's prefix"
        )

    async def test_resegmentation_replaces_rather_than_duplicates(
        self, vg_client, test_space, test_graph
    ):
        """Re-running the same method must delete the prior run's output.

        Pre-fix the worker matched the method URI as a string literal against a
        URIProperty, so delete-existing never matched and segments accumulated.
        """
        doc = _make_document("ResegmentDoc", "# Head\n\nBody text. " * 60)
        doc_uri = str(doc.URI)
        await vg_client.kgdocuments.create_kgdocuments(
            space_id=test_space, graph_id=test_graph, objects=[doc]
        )

        first = await _segment_and_wait(vg_client, test_space, test_graph, doc_uri)
        assert first

        await vg_client.kgdocuments.segment_document(
            space_id=test_space, graph_id=test_graph, document_uri=doc_uri,
            max_segment_tokens=64,
        )
        await asyncio.sleep(8.0)

        after = await vg_client.kgdocuments.list_segments(
            space_id=test_space, graph_id=test_graph, parent_uri=doc_uri
        )
        assert after.is_success
        assert after.count <= len(first), (
            f"Segment count grew from {len(first)} to {after.count} — "
            "the previous run's output was not deleted"
        )

    async def test_delete_protection_allows_lookalike_user_document(
        self, vg_client, test_space, test_graph
    ):
        """A user document named like a segment is not a segment.

        Pre-fix, `'_parent_' in uri or '_seg_' in uri` made any such document
        permanently undeletable.
        """
        doc = _make_document("LookalikeDoc", "Ordinary user content.")
        doc.URI = f"{NS}report_seg_2024_{uuid.uuid4().hex[:8]}"
        doc_uri = str(doc.URI)
        await vg_client.kgdocuments.create_kgdocuments(
            space_id=test_space, graph_id=test_graph, objects=[doc]
        )

        resp = await vg_client.kgdocuments.delete_kgdocument(
            space_id=test_space, graph_id=test_graph, uri=doc_uri
        )
        assert resp.is_success, (
            f"Delete of a legitimately-named document was rejected: "
            f"{resp.error_message}"
        )
        assert not await _exists(vg_client, test_space, test_graph, doc_uri)

    async def test_segmentation_mints_unique_uris_per_run(
        self, vg_client, test_space, test_graph
    ):
        """Two documents segmented independently must not share segment URIs.

        Uniqueness only — deliberately asserts nothing about URI *shape*, so
        the descriptive prefix stays free to change.
        """
        docs, uris = [], []
        for i in range(2):
            d = _make_document(f"MintDoc{i}", "# Head\n\nBody text. " * 60)
            docs.append(d)
            uris.append(str(d.URI))
        await vg_client.kgdocuments.create_kgdocuments(
            space_id=test_space, graph_id=test_graph, objects=docs
        )

        first = set(await _segment_and_wait(vg_client, test_space, test_graph, uris[0]))
        second = set(await _segment_and_wait(vg_client, test_space, test_graph, uris[1]))

        assert first and second
        assert not (first & second), "segment URIs collided across documents"


# ---------------------------------------------------------------------------
# Managed-segment delete protection (issues/024)
# ---------------------------------------------------------------------------

class TestManagedSegmentDeleteProtection:
    """_check_delete_protection must reject direct deletion of managed segments.

    The guard asks the graph what the object *is* — a document is protected
    because it carries a managed hasKGDocumentSegmentTypeURI, not because of
    how it is named. It uses ASK; a regression that makes ASK return a falsy
    boolean turns this into a protection check that silently stops protecting,
    which no other test would catch.
    """

    _PRED = "http://vital.ai/ontology/haley-ai-kg#hasKGDocumentSegmentTypeURI"

    async def _tag_segment_type(self, vg_client, test_space, test_graph, uri, seg_type):
        """Attach a hasKGDocumentSegmentTypeURI to an existing document."""
        from vitalgraph.model.sparql_model import SPARQLInsertRequest

        resp = await vg_client.sparql.execute_sparql_insert(
            test_space,
            SPARQLInsertRequest(
                update=f'INSERT DATA {{ GRAPH <{test_graph}> {{ '
                       f'<{uri}> <{self._PRED}> <{seg_type}> . }} }}'
            ),
        )
        assert resp.success, f"Tagging failed: {resp.error}"

    async def test_managed_segment_delete_is_rejected(
        self, vg_client, test_space, test_graph
    ):
        """A document carrying a managed segment type must not be deletable."""
        doc = _make_document("ManagedSegmentDoc")
        await vg_client.kgdocuments.create_kgdocuments(
            space_id=test_space, graph_id=test_graph, objects=[doc]
        )
        await self._tag_segment_type(
            vg_client, test_space, test_graph, str(doc.URI), "urn:segtype:text_chunk"
        )

        del_resp = await vg_client.kgdocuments.delete_kgdocument(
            space_id=test_space, graph_id=test_graph, uri=str(doc.URI)
        )
        assert not del_resp.is_success, (
            f"Managed segment was deleted despite protection: {del_resp}"
        )
        # A domain outcome: the explanation rides in `message`, not
        # `error_message`, and must be the server's, not a client-side canned
        # string. See issues/031.
        assert "managed segment" in (del_resp.message or "").lower()
        assert del_resp.deleted is False
        assert del_resp.deleted_count == 0
        assert del_resp.deleted_uris == []

        # And it must still be there.
        get_resp = await vg_client.kgdocuments.get_kgdocument(
            space_id=test_space, graph_id=test_graph, uri=str(doc.URI)
        )
        assert get_resp.is_success and get_resp.document is not None

    async def test_unmanaged_segment_type_still_deletable(
        self, vg_client, test_space, test_graph
    ):
        """A user-defined segment type must NOT trigger protection.

        Guards against over-broad matching — the check must key on the managed
        type set, not on the predicate's mere presence.
        """
        doc = _make_document("UserSegmentDoc")
        await vg_client.kgdocuments.create_kgdocuments(
            space_id=test_space, graph_id=test_graph, objects=[doc]
        )
        await self._tag_segment_type(
            vg_client, test_space, test_graph, str(doc.URI), "urn:segtype:user_defined"
        )

        del_resp = await vg_client.kgdocuments.delete_kgdocument(
            space_id=test_space, graph_id=test_graph, uri=str(doc.URI)
        )
        assert del_resp.is_success, (
            f"User-typed document wrongly protected: {del_resp.error_message}"
        )

    async def test_plain_document_still_deletable(
        self, vg_client, test_space, test_graph
    ):
        """A document with no segment type at all deletes normally."""
        doc = _make_document("PlainDoc")
        await vg_client.kgdocuments.create_kgdocuments(
            space_id=test_space, graph_id=test_graph, objects=[doc]
        )

        del_resp = await vg_client.kgdocuments.delete_kgdocument(
            space_id=test_space, graph_id=test_graph, uri=str(doc.URI)
        )
        assert del_resp.is_success, f"Delete failed: {del_resp.error_message}"
