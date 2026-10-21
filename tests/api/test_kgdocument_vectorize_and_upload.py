"""API tests: per-type and per-request vectorization, auto-segmentation on create,
and the client's upload method.

`issues/284` -- the Python client could not upload; `issues/285` -- nothing could
keep a document out of vector indexes; `issues/286` -- a created document whose
type has a segmentation config was never segmented until someone asked.

ABSENCE IS ONLY ASSERTED AFTER A POSITIVE SIGNAL. Vectorization runs in the
background, so "no vectors yet" proves nothing on its own. Every document is
created together, and the "off" assertions run only once the "on" documents --
written at the same time, through the same paths -- have their vectors.

Requires the segmentation worker (the test stack runs it) and object storage
for the upload's original (the test stack's MinIO).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio

from ai_haley_kg_domain.model.KGDocument import KGDocument
from vitalgraph.db.sparql_sql.space_names import space_prefix

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

HALEY = "http://vital.ai/ontology/haley-ai-kg#"
NO_INDEX = f"{HALEY}KGIndexStatus_NO_INDEX"
VECTOR = f"{HALEY}KGIndexStatus_VECTOR"
INDEX_NAME = "doc_vec_policy"
TYPE_ON = "urn:kgdoctype:test_vec_on"
TYPE_OFF = "urn:kgdoctype:test_vec_off"
SEG_METHOD = "urn:segmethod:plain_recursive_split"

TEXT = "\n\n".join(
    f"Paragraph {i} discusses topic {i} at length. " * 12 for i in range(5))


def _doc(doc_type: str, name: str) -> KGDocument:
    d = KGDocument()
    d.URI = f"urn:test:vecpolicy:{name}:{uuid.uuid4().hex[:8]}"
    d.name = name
    d.kGDocumentType = doc_type
    d.kGDocumentContent = TEXT
    # The `default` mapping source embeds `hasKGraphDescription` and nothing
    # else, so without it a whole document has no text and is never embedded
    # whatever the policy says -- which would make every "off" assertion here
    # pass vacuously.
    d.kGraphDescription = TEXT
    return d


async def _status(pg_conn, space, uri):
    return await pg_conn.fetchval(
        f"SELECT t.term_text FROM {space_prefix(space)}_rdf_quad q "
        f"JOIN {space_prefix(space)}_term t ON t.term_uuid = q.object_uuid "
        f"WHERE q.subject_uuid = vitalgraph_term_uuid($1, 'U') "
        f"AND q.predicate_uuid = vitalgraph_term_uuid($2, 'U')",
        uri, f"{HALEY}hasKGIndexStatusURI")


async def _segments(pg_conn, space, original_uri):
    """Parent copy and segment URIs: the processor mints them under
    `<original>_parent_<method>`, and so are the edges between them -- which
    are not documents and are never embedded, so they are excluded."""
    rows = await pg_conn.fetch(
        f"SELECT term_text FROM {space_prefix(space)}_term WHERE term_text LIKE $1 "
        f"AND term_text NOT LIKE '%\\_edge\\_%'",
        original_uri.replace("_", r"\_") + r"\_parent\_%")
    return [r["term_text"] for r in rows]


async def _vectors(pg_conn, space, uris):
    if not uris:
        return 0
    return await pg_conn.fetchval(
        f"SELECT count(*) FROM {space_prefix(space)}_vec_{INDEX_NAME} "
        f"WHERE subject_uuid = ANY(SELECT vitalgraph_term_uuid(u, 'U') "
        f"FROM unnest($1::text[]) u)", list(uris))


async def _job_completed(vg_client, space, uri) -> bool:
    status = await vg_client.kgdocuments.get_segmentation_status(
        space_id=space, document_uri=uri)
    return any(j.get("status") == "completed" for j in status.jobs)


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def env(vg_client, test_space, test_graph, pg_conn):
    space = test_space
    configs = []
    for doc_type, auto in ((TYPE_ON, True), (TYPE_OFF, False)):
        c = await vg_client.kgdocuments.create_segmentation_config(
            space_id=space, document_type_uri=doc_type,
            segment_method_uri=SEG_METHOD, max_segment_tokens=128,
            min_segment_tokens=20, overlap_tokens=0, enabled=True,
            auto_vectorize=auto)
        assert c.config_id is not None, c
        configs.append(c.config_id)

    await vg_client.vector_indexes.create_index(
        space_id=space, index_name=INDEX_NAME, dimensions=384,
        distance_metric="cosine", provider="vitalsigns",
        model_name="paraphrase-multilingual-MiniLM-L12-v2",
        description="vectorize policy test")
    # Catch-all mappings for whole documents AND segments, so everything would
    # be embedded by default and only the policy can keep a subject out.
    mappings = []
    for mapping_type in ("kgdocument", "kgdocument_segment"):
        m = await vg_client.search_mappings.create_mapping(
            space_id=space, index_name=INDEX_NAME, mapping_type=mapping_type,
            enabled=True, source_type="default")
        await vg_client.search_mappings.add_index(
            space_id=space, mapping_id=m.mapping_id, index_type="vector",
            index_name=INDEX_NAME)
        mappings.append(m.mapping_id)

    docs = {
        "on": _doc(TYPE_ON, "on"),
        "off": _doc(TYPE_OFF, "off"),
        "forced_on": _doc(TYPE_OFF, "forced_on"),
        "forced_off": _doc(TYPE_ON, "forced_off"),
        "later_off": _doc(TYPE_ON, "later_off"),
    }
    for key, vectorize in (("on", None), ("off", None), ("forced_on", True),
                           ("forced_off", False), ("later_off", None)):
        r = await vg_client.kgdocuments.create_kgdocuments(
            space, test_graph, [docs[key]], vectorize=vectorize)
        assert r.is_success, f"{key}: {r.error_message}"
    uris = {k: str(d.URI) for k, d in docs.items()}

    # An upload carries no description, so the DOCUMENT is never embedded under
    # a `default` mapping; its SEGMENTS are. A type-on upload is the positive
    # control that makes the type-off upload's zero mean something.
    md = ("# Report\n\n" + TEXT + "\n\n## Findings\n\n" + TEXT).encode()
    up = None
    for key, doc_type in (("upload", TYPE_OFF), ("upload_on", TYPE_ON)):
        r = await vg_client.kgdocuments.upload_kgdocument(
            space, test_graph, md, filename=f"{key}.md", headline=key,
            document_type=doc_type, store_original=True)
        assert r.is_success, f"{key} failed: {r.message} {r.error_message}"
        uris[key] = r.document_uri
        up = up or r

    # No explicit segment_document call anywhere above: every job must come
    # from auto-segmentation on create.
    for _ in range(60):
        done = [await _job_completed(vg_client, space, u) for u in uris.values()]
        if all(done):
            break
        await asyncio.sleep(2.0)
    jobs_completed = {k: await _job_completed(vg_client, space, u) for k, u in uris.items()}

    async def vectors_for(key):
        return await _vectors(pg_conn, space, [uris[key]] + await _segments(pg_conn, space, uris[key]))

    # The positive signal: both "on" documents and their segments embedded,
    # and the type-on upload's segments.
    for _ in range(60):
        segs_on = await _segments(pg_conn, space, uris["on"])
        segs_forced = await _segments(pg_conn, space, uris["forced_on"])
        segs_up = await _segments(pg_conn, space, uris["upload_on"])
        if (segs_on and segs_forced and segs_up
                and await _vectors(pg_conn, space, segs_up) == len(segs_up)
                and await _vectors(pg_conn, space, [uris["on"]] + segs_on) == 1 + len(segs_on)
                and await _vectors(pg_conn, space, [uris["forced_on"]] + segs_forced)
                == 1 + len(segs_forced)):
            break
        await asyncio.sleep(2.0)

    yield {"space": space, "graph": test_graph, "uris": uris, "upload": up,
           "configs": dict(zip((TYPE_ON, TYPE_OFF), configs)),
           "jobs_completed": jobs_completed, "vectors_for": vectors_for}

    for u in uris.values():
        try:
            await vg_client.kgdocuments.delete_kgdocument(space, test_graph, u)
        except Exception:
            pass
    for mid in mappings:
        try:
            await vg_client.search_mappings.delete_mapping(space, mid)
        except Exception:
            pass
    try:
        await vg_client.vector_indexes.delete_index(space, INDEX_NAME)
    except Exception:
        pass
    for cid in configs:
        try:
            await vg_client.kgdocuments.delete_segmentation_config(space, cid)
        except Exception:
            pass


class TestAutoSegmentationOnCreate:

    async def test_every_typed_document_was_segmented_without_being_asked(self, env):
        assert all(env["jobs_completed"].values()), env["jobs_completed"]

    async def test_segments_exist(self, env, pg_conn):
        for key, uri in env["uris"].items():
            assert await _segments(pg_conn, env["space"], uri), f"{key} has no segments"


class TestTheTypeDefault:

    async def test_a_type_with_vectorize_on_is_embedded(self, env, pg_conn):
        segs = await _segments(pg_conn, env["space"], env["uris"]["on"])
        assert await env["vectors_for"]("on") == 1 + len(segs)

    async def test_a_type_with_vectorize_off_is_not_embedded(self, env, pg_conn):
        assert await env["vectors_for"]("off") == 0

    async def test_its_segments_are_stamped(self, env, pg_conn):
        for seg in await _segments(pg_conn, env["space"], env["uris"]["off"]):
            assert await _status(pg_conn, env["space"], seg) == NO_INDEX, seg


class TestTheRequestOverride:

    async def test_true_overrides_a_type_that_is_off(self, env, pg_conn):
        uri = env["uris"]["forced_on"]
        assert await _status(pg_conn, env["space"], uri) == VECTOR
        segs = await _segments(pg_conn, env["space"], uri)
        assert segs and await env["vectors_for"]("forced_on") == 1 + len(segs)
        for seg in segs:
            assert await _status(pg_conn, env["space"], seg) == VECTOR, seg

    async def test_false_overrides_a_type_that_is_on(self, env, pg_conn):
        uri = env["uris"]["forced_off"]
        assert await _status(pg_conn, env["space"], uri) == NO_INDEX
        assert await env["vectors_for"]("forced_off") == 0

    async def test_segment_with_vectorize_false_removes_existing_vectors(
            self, env, vg_client, pg_conn):
        uri = env["uris"]["later_off"]
        assert await _vectors(pg_conn, env["space"], [uri]) == 1, (
            "precondition: the document is embedded before the override")
        r = await vg_client.kgdocuments.segment_document(
            space_id=env["space"], graph_id=env["graph"], document_uri=uri,
            segment_method_uri=SEG_METHOD, max_segment_tokens=128,
            vectorize=False)
        assert r.is_success, r.message
        assert await _status(pg_conn, env["space"], uri) == NO_INDEX
        for _ in range(60):
            segs = await _segments(pg_conn, env["space"], uri)
            if (await env["vectors_for"]("later_off") == 0 and segs and all(
                    [await _status(pg_conn, env["space"], s) == NO_INDEX for s in segs])):
                break
            await asyncio.sleep(2.0)
        assert await env["vectors_for"]("later_off") == 0


class TestUpload:

    async def test_the_original_is_kept(self, env):
        assert env["upload"].file_node_uri, "store_original=True kept no FileNode"

    async def test_the_document_type_is_set(self, env, pg_conn):
        t = await pg_conn.fetchval(
            f"SELECT t.term_text FROM {env['space']}_rdf_quad q "
            f"JOIN {env['space']}_term t ON t.term_uuid = q.object_uuid "
            f"WHERE q.subject_uuid = vitalgraph_term_uuid($1, 'U') "
            f"AND q.predicate_uuid = vitalgraph_term_uuid($2, 'U')",
            env["uris"]["upload"], f"{HALEY}hasKGDocumentType")
        assert t == TYPE_OFF

    async def test_an_upload_follows_its_types_default(self, env, pg_conn):
        segs_on = await _segments(pg_conn, env["space"], env["uris"]["upload_on"])
        assert segs_on and await _vectors(pg_conn, env["space"], segs_on) == len(segs_on), (
            "control: a type-on upload's segments are embedded")
        assert await env["vectors_for"]("upload") == 0

    async def test_bytes_without_a_filename_are_refused(self, vg_client, env):
        from vitalgraph.client.utils.client_utils import VitalGraphClientError
        with pytest.raises(VitalGraphClientError):
            await vg_client.kgdocuments.upload_kgdocument(
                env["space"], env["graph"], b"text")


# ---------------------------------------------------------------------------
# PUT replaces, and a content change re-segments (`issues/286`); a config
# change that flips a type's default reaches its existing segments
# (`issues/285`).
# ---------------------------------------------------------------------------

TYPE_FLIP = "urn:kgdoctype:test_vec_flip"


async def _live(pg_conn, space, uris):
    """The URIs that still have quads -- the term table keeps deleted ones."""
    if not uris:
        return []
    rows = await pg_conn.fetch(
        f"SELECT DISTINCT u FROM unnest($1::text[]) u WHERE EXISTS ("
        f"SELECT 1 FROM {space_prefix(space)}_rdf_quad q "
        f"WHERE q.subject_uuid = vitalgraph_term_uuid(u, 'U'))", list(uris))
    return sorted(r["u"] for r in rows)


async def _values(pg_conn, space, uri, prop):
    rows = await pg_conn.fetch(
        f"SELECT t.term_text FROM {space_prefix(space)}_rdf_quad q "
        f"JOIN {space_prefix(space)}_term t ON t.term_uuid = q.object_uuid "
        f"WHERE q.subject_uuid = vitalgraph_term_uuid($1, 'U') "
        f"AND q.predicate_uuid = vitalgraph_term_uuid($2, 'U')", uri, prop)
    return sorted(r["term_text"] for r in rows)


async def _completed_jobs(pg_conn, space, uri) -> int:
    """From the job table: the status endpoint returns a document's LATEST job."""
    return await pg_conn.fetchval(
        f"SELECT count(*) FROM {space_prefix(space)}_segmentation_jobs "
        f"WHERE document_uri = $1 AND status = 'completed'", uri)


async def _wait(cond, tries=60, delay=2.0):
    for _ in range(tries):
        if await cond():
            return True
        await asyncio.sleep(delay)
    return False


class TestUpdate:

    async def test_a_put_replaces_and_a_content_change_resegments(
            self, env, vg_client, pg_conn):
        space, graph = env["space"], env["graph"]
        doc = _doc(TYPE_ON, "put")
        assert (await vg_client.kgdocuments.create_kgdocuments(space, graph, [doc])).is_success
        uri = str(doc.URI)
        assert await _wait(lambda: _job_completed(vg_client, space, uri))
        old_segs = await _live(pg_conn, space, await _segments(pg_conn, space, uri))
        assert old_segs, "precondition: segmented at create"

        # A name change: replaced, not appended, and no re-segmentation.
        doc.name = "put renamed"
        assert (await vg_client.kgdocuments.update_kgdocuments(space, graph, [doc])).is_success
        assert await _values(pg_conn, space, uri, "http://vital.ai/ontology/vital-core#hasName") \
            == ["put renamed"]

        # A content change: replaced, and re-segmented with the new text.
        marker = "ZEBRAMARKER"
        doc.kGDocumentContent = TEXT + f"\n\nA closing paragraph about {marker} " * 3
        assert (await vg_client.kgdocuments.update_kgdocuments(space, graph, [doc])).is_success
        assert await _values(pg_conn, space, uri, f"{HALEY}hasKGDocumentContent") \
            == [str(doc.kGDocumentContent)]

        async def resegmented():
            live = await _live(pg_conn, space, await _segments(pg_conn, space, uri))
            return (await _completed_jobs(pg_conn, space, uri) >= 2
                    and live and not set(live) & set(old_segs))
        assert await _wait(resegmented), "content change did not re-segment"
        live = await _live(pg_conn, space, await _segments(pg_conn, space, uri))
        texts = [t for s in live for t in await _values(
            pg_conn, space, s, f"{HALEY}hasKGDocumentContent")]
        assert any(marker in t for t in texts)
        # Exactly two completed jobs: the create, the content change. The name
        # change, which came first, queued none.
        assert await _completed_jobs(pg_conn, space, uri) == 2

    async def test_a_put_keeps_the_documents_vectorize_decision(
            self, env, vg_client, pg_conn):
        space, graph = env["space"], env["graph"]
        doc = _doc(TYPE_ON, "put_keeps")
        r = await vg_client.kgdocuments.create_kgdocuments(space, graph, [doc], vectorize=False)
        assert r.is_success
        uri = str(doc.URI)
        doc.name = "put_keeps renamed"   # sent WITHOUT kGIndexStatusURI
        doc.kGIndexStatusURI = None
        assert (await vg_client.kgdocuments.update_kgdocuments(space, graph, [doc])).is_success
        assert await _status(pg_conn, space, uri) == NO_INDEX


class TestTypeDefaultChange:

    async def test_flipping_auto_vectorize_restamps_existing_segments(
            self, env, vg_client, pg_conn):
        space, graph = env["space"], env["graph"]
        c = await vg_client.kgdocuments.create_segmentation_config(
            space_id=space, document_type_uri=TYPE_FLIP,
            segment_method_uri=SEG_METHOD, max_segment_tokens=128,
            min_segment_tokens=20, overlap_tokens=0, enabled=True,
            auto_vectorize=True)
        try:
            doc = _doc(TYPE_FLIP, "flip")
            assert (await vg_client.kgdocuments.create_kgdocuments(space, graph, [doc])).is_success
            uri = str(doc.URI)

            async def segs():
                return await _live(pg_conn, space, await _segments(pg_conn, space, uri))

            async def embedded():
                s = await segs()
                return s and await _vectors(pg_conn, space, [uri] + s) == 1 + len(s)
            assert await _wait(embedded), "precondition: embedded while on"

            async def set_auto(on):
                r = await vg_client.kgdocuments.update_segmentation_config(
                    space_id=space, config_id=c.config_id, document_type_uri=TYPE_FLIP,
                    segment_method_uri=SEG_METHOD, max_segment_tokens=128,
                    min_segment_tokens=20, overlap_tokens=0, enabled=True,
                    auto_vectorize=on)
                assert r.config_id == c.config_id

            await set_auto(False)

            async def off():
                s = await segs()
                return (s and await _vectors(pg_conn, space, [uri] + s) == 0 and all(
                    [await _status(pg_conn, space, x) == NO_INDEX for x in s]))
            assert await _wait(off), "turning the type off left vectors or no stamps"
            assert await _status(pg_conn, space, uri) is None, (
                "the original follows its type by lookup; it is not stamped")

            await set_auto(True)

            async def on_again():
                s = await segs()
                return (s and await _vectors(pg_conn, space, [uri] + s) == 1 + len(s)
                        and all([await _status(pg_conn, space, x) is None for x in s]))
            assert await _wait(on_again), "turning the type back on did not re-embed"
        finally:
            await vg_client.kgdocuments.delete_segmentation_config(space, c.config_id)

    async def test_an_explicit_decision_is_left_alone(self, env, vg_client, pg_conn):
        """Turn TYPE_OFF on: its unstamped document is embedded (the positive
        signal), while `forced_on` -- the same type, created with
        vectorize=True -- keeps its own stamp. Then back off."""
        space, uris = env["space"], env["uris"]

        async def set_off_type(on):
            r = await vg_client.kgdocuments.update_segmentation_config(
                space_id=space, config_id=env["configs"][TYPE_OFF],
                document_type_uri=TYPE_OFF, segment_method_uri=SEG_METHOD,
                max_segment_tokens=128, min_segment_tokens=20, overlap_tokens=0,
                enabled=True, auto_vectorize=on)
            assert r.config_id == env["configs"][TYPE_OFF]

        async def segs(key):
            return await _live(pg_conn, space, await _segments(pg_conn, space, uris[key]))

        await set_off_type(True)
        try:
            async def follows():
                s = await segs("off")
                return s and await _vectors(pg_conn, space, [uris["off"]] + s) == 1 + len(s)
            assert await _wait(follows), "the unstamped document did not follow its type"
            for x in await segs("off"):
                assert await _status(pg_conn, space, x) is None, x
            for x in await segs("forced_on"):
                assert await _status(pg_conn, space, x) == VECTOR, x
        finally:
            await set_off_type(False)

        async def off_again():
            s = await segs("off")
            return s and await _vectors(pg_conn, space, [uris["off"]] + s) == 0
        assert await _wait(off_again)
        for x in await segs("forced_on"):
            assert await _status(pg_conn, space, x) == VECTOR, x
