"""Unit tests for the KG document upload client and the worker's type policy.

`issues/284`: the client's upload sends the form the server reads.
`issues/286`: the segmentation worker takes its settings from the document
type's config, where it used to hardcode a minimum of 20 and no overlap.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from vitalgraph.document.segment_config import MarkdownSegmentConfig, PlainSplitConfig
from vitalgraph.document.segmentation_worker import SegmentationWorker


def _cfg(**kw):
    base = dict(segment_method_uri="urn:segmethod:plain_recursive_split",
                max_segment_tokens=300, min_segment_tokens=40, overlap_tokens=7)
    base.update(kw)
    return SimpleNamespace(**base)


class TestWorkerConfig:

    def test_the_type_config_supplies_what_the_job_leaves_unset(self):
        c = SegmentationWorker(None)._build_config(None, None, _cfg())
        assert isinstance(c, PlainSplitConfig)
        assert (c.max_segment_tokens, c.min_segment_tokens, c.overlap_tokens) == (300, 40, 7)

    def test_the_jobs_own_method_and_max_win(self):
        c = SegmentationWorker(None)._build_config(
            "urn:segmethod:markdown_heading_split", 128, _cfg())
        assert isinstance(c, MarkdownSegmentConfig)
        assert (c.max_segment_tokens, c.min_segment_tokens) == (128, 40)

    def test_without_a_config_the_old_defaults_hold(self):
        c = SegmentationWorker(None)._build_config(
            "urn:segmethod:plain_recursive_split", 128)
        assert (c.max_segment_tokens, c.min_segment_tokens, c.overlap_tokens) == (128, 20, 0)

    def test_the_stamp_reaches_the_stored_object(self):
        from ai_haley_kg_domain.model.KGDocument import KGDocument
        d = KGDocument()
        SegmentationWorker._apply_props(d, {
            "URI": "urn:seg:1",
            "kGIndexStatusURI": "http://vital.ai/ontology/haley-ai-kg#KGIndexStatus_NO_INDEX"})
        assert str(d.kGIndexStatusURI).endswith("KGIndexStatus_NO_INDEX")


class _Resp:
    status_code = 200

    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


class TestUploadClient:

    @pytest.fixture
    def endpoint(self):
        from vitalgraph.client.endpoint.kgdocuments_endpoint import KGDocumentsEndpoint
        ep = KGDocumentsEndpoint(client=None)
        ep.sent = {}
        ep._check_connection = lambda: None
        ep._get_server_url = lambda: "http://vg"

        async def fake(method, url, **kwargs):
            ep.sent = dict(method=method, url=url, **kwargs)
            return _Resp({"success": True, "status": "created",
                          "document_uri": "urn:kgdocument:x",
                          "file_node_uri": "urn:file:x", "converted": False})
        ep._make_authenticated_request = fake
        return ep

    def test_the_form_carries_every_field(self, endpoint):
        r = asyncio.run(endpoint.upload_kgdocument(
            "sp", "urn:g", b"# Title\n\ntext", filename="r.md",
            headline="R", source_url="https://x", store_original=False,
            document_type="urn:kgdoctype:research", vectorize=False))
        assert r.is_success and r.file_node_uri == "urn:file:x"
        s = endpoint.sent
        assert s["method"] == "POST" and s["url"].endswith("/api/graphs/kgdocuments/upload")
        assert s["params"] == {"space_id": "sp", "graph_id": "urn:g"}
        assert s["data"] == {"store_original": "false", "headline": "R",
                             "source_url": "https://x",
                             "document_type": "urn:kgdoctype:research",
                             "vectorize": "false"}
        name, data, ctype = s["files"]["file"]
        assert (name, data) == ("r.md", b"# Title\n\ntext")
        assert ctype == "text/markdown"

    def test_omitted_options_are_not_sent(self, endpoint, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_bytes(b"plain")
        asyncio.run(endpoint.upload_kgdocument("sp", "urn:g", str(f)))
        assert endpoint.sent["data"] == {"store_original": "true"}
        assert endpoint.sent["files"]["file"][0] == "notes.txt"

    def test_create_sends_vectorize_only_when_given(self, endpoint):
        from ai_haley_kg_domain.model.KGDocument import KGDocument
        d = KGDocument(); d.URI = "urn:d"
        asyncio.run(endpoint.create_kgdocuments("sp", "urn:g", [d], vectorize=True))
        assert endpoint.sent["params"]["vectorize"] == "true"
        asyncio.run(endpoint.create_kgdocuments("sp", "urn:g", [d]))
        assert "vectorize" not in endpoint.sent["params"]


def test_the_segment_mapping_helper_targets_segments():
    """The helper created a `kgdocument` mapping, which matches whole documents
    only, so segments routed through it were never embedded (`issues/285`)."""
    from vitalgraph.client.endpoint.kgdocuments_endpoint import KGDocumentsEndpoint
    captured = {}

    async def create_mapping(**kw):
        captured.update(kw)
    ep = KGDocumentsEndpoint(client=SimpleNamespace(
        search_mappings=SimpleNamespace(create_mapping=create_mapping)))
    ep._check_connection = lambda: None
    asyncio.run(ep.setup_document_segments_mapping("sp"))
    assert captured["mapping_type"] == "kgdocument_segment"


def test_deleting_segmentation_removes_the_index_rows_too(monkeypatch):
    """Deleting segment quads left their vector/FTS rows behind, so every
    re-segmentation orphaned the previous run's vectors (`issues/285`)."""
    from vitalgraph.document import segment_deletion
    from vitalgraph.vectorization import auto_sync

    async def find(*a, **k):
        return ["urn:p", "urn:p_seg_1"]

    class Backend:
        db_impl = object()
        async def execute_sparql_update(self, space_id, update):
            return True

    calls = []
    monkeypatch.setattr(segment_deletion, "find_segmentation_uris", find)
    monkeypatch.setattr(auto_sync, "schedule_sync", lambda **kw: calls.append(kw))
    n = asyncio.run(segment_deletion.delete_segmentation(
        Backend(), "sp", "urn:g", "urn:orig"))
    assert n == 2
    assert calls and calls[0]["operation"] == "delete"
    assert calls[0]["subject_uris"] == ["urn:p", "urn:p_seg_1"]


class TestTypePolicyLookup:
    """issues/290: the segment stamp was skipped when a SECOND pool connection
    timed out, so an opted-out document's segments were embedded anyway."""

    NO_INDEX = "http://vital.ai/ontology/haley-ai-kg#KGIndexStatus_NO_INDEX"

    class _Conn:
        def __init__(self, fail=False):
            self.fail = fail

        async def fetchval(self, *a, **k):
            if self.fail:
                raise TimeoutError()
            return False          # no config table: no type default

        async def fetch(self, *a, **k):
            return []

    def _worker(self):
        w = SegmentationWorker(None)

        async def no_pool(space_id):
            raise AssertionError("must use the held connection, not the pool")
        w._get_pool = no_pool
        return w

    def test_uses_the_held_connection(self):
        job = SimpleNamespace(job_id=1, segment_method_uri=None)
        cfg, status = asyncio.run(self._worker()._resolve_type_policy(
            "sp", job, {"kGDocumentType": "urn:t", "kGIndexStatusURI": self.NO_INDEX},
            self._Conn()))
        assert status == self.NO_INDEX

    def test_an_explicit_opt_out_survives_a_failed_lookup(self):
        job = SimpleNamespace(job_id=1, segment_method_uri=None)
        cfg, status = asyncio.run(self._worker()._resolve_type_policy(
            "sp", job, {"kGDocumentType": "urn:t", "kGIndexStatusURI": self.NO_INDEX},
            self._Conn(fail=True)))
        assert (cfg, status) == (None, self.NO_INDEX)

    def test_without_an_explicit_status_a_failed_lookup_fails_the_job(self):
        job = SimpleNamespace(job_id=1, segment_method_uri=None)
        with pytest.raises(RuntimeError, match="TimeoutError"):
            asyncio.run(self._worker()._resolve_type_policy(
                "sp", job, {"kGDocumentType": "urn:t"}, self._Conn(fail=True)))
