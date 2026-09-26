#!/usr/bin/env python3
"""Which predicates does a document SEGMENT actually carry?

`issues/245` left one failure open: the enriched document query requires
`?entity haley:hasKGDocumentContent ?_seg_content` and returns ZERO rows while its
count query returns 66. The processor sets `kGDocumentContent`, `_apply_props`
assigns it, and `test_segment_content_nonempty` passes — but that test accepts
`kGDocumentContent` OR `kGraphDescription`, so it cannot tell which one is present.

Every space the API tests create is torn down, so the quads cannot be inspected
afterwards. This builds the same shape in a space it LEAVES IN PLACE, then prints
the predicates the segment subjects actually have.

Read-only against everything except its own space.

    LOCAL_CLIENT_SERVER_URL=http://localhost:8002 \
      python3 test_scripts/debug/_segment_content_predicates.py
"""
import asyncio
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

SPACE = os.environ.get("PROBE_SPACE", "dbg_seg_predicates")
GRAPH = os.environ.get("PROBE_GRAPH", "urn:dbg:seg:predicates")
SERVER = os.environ.get("LOCAL_CLIENT_SERVER_URL", "http://localhost:8002")
DOC_TYPE = "urn:kgdoctype:wikipedia_article"
SEG_METHOD = "urn:segmethod:markdown_heading_split"
USER = os.environ.get("LOCAL_CLIENT_AUTH_USERNAME", "admin")
PASSWORD = os.environ.get("LOCAL_CLIENT_AUTH_PASSWORD", "admin")

TEXT = (
    "# Machine learning\n\n"
    "Machine learning is a field of study in artificial intelligence concerned "
    "with the development of statistical algorithms that can learn from data.\n\n"
    "## Neural networks\n\n"
    "Deep learning uses multiple layers to progressively extract higher-level "
    "features from raw input, trained by gradient descent.\n\n"
    "## Applications\n\n"
    "Applications include speech recognition, computer vision and translation.\n"
)


async def main() -> int:
    from vitalgraph.client.vitalgraph_client import VitalGraphClient

    # Same construction the API suite uses: config-driven, no kwargs. The server
    # comes from LOCAL_CLIENT_SERVER_URL, which must be set to the test stack or
    # this silently probes the DEV server on :8001 (the trap `issues/108` records).
    client = VitalGraphClient()
    await client.open()
    try:
        from vitalgraph.model.spaces_model import Space
        spaces = await client.spaces.list_spaces()
        names = {getattr(sp, "space", None) or getattr(sp, "space_id", None)
                 for sp in (spaces.spaces or [])}
        if SPACE not in names:
            # `space=`, not `space_id=`: the model's field is `space`
            await client.spaces.create_space(Space(
                space=SPACE, space_name=SPACE,
                space_description="issues/245 segment predicate probe"))
            print(f"created space {SPACE}")
        else:
            print(f"reusing space {SPACE}")

        try:
            await client.graphs.create_graph(SPACE, GRAPH)
        except Exception as exc:
            print("graph:", exc)

        cfg = await client.kgdocuments.create_segmentation_config(
            space_id=SPACE,
            document_type_uri=DOC_TYPE,
            segment_method_uri=SEG_METHOD,
            max_segment_tokens=512, min_segment_tokens=30, overlap_tokens=0,
            enabled=True, auto_vectorize=True,
        )
        print("segmentation config:", getattr(cfg, "config_id", cfg))

        doc_uri = f"urn:dbg:seg:doc:{uuid.uuid4().hex[:10]}"
        from ai_haley_kg_domain.model.KGDocument import KGDocument
        doc = KGDocument()
        doc.URI = doc_uri
        doc.name = "machine learning probe"
        doc.kGDocumentType = DOC_TYPE
        doc.kGDocumentContent = TEXT
        created = await client.kgdocuments.create_kgdocuments(SPACE, GRAPH, [doc])
        print("created doc:", doc_uri, "->", getattr(created, "status", created))

        resp = await client.kgdocuments.segment_document(
            space_id=SPACE, graph_id=GRAPH, document_uri=doc_uri,
            segment_method_uri=SEG_METHOD)
        print("segmentation:", getattr(resp, "status", resp))

        for _ in range(40):
            await asyncio.sleep(1.5)
            segs = await client.kgdocuments.list_segments(SPACE, GRAPH, doc_uri)
            if getattr(segs, "count", 0):
                print(f"segments: {segs.count}")
                break
        else:
            print("NO SEGMENTS — the probe could not build its own fixture")
            return 2

        print(f"\nspace LEFT IN PLACE: {SPACE}  graph: {GRAPH}")
        print("now inspect with:\n"
              f"  SELECT t.term_text, count(*) FROM {SPACE}_rdf_quad q\n"
              f"  JOIN {SPACE}_term t ON t.term_uuid=q.predicate_uuid\n"
              "  GROUP BY 1 ORDER BY 2 DESC;")
        return 0
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
