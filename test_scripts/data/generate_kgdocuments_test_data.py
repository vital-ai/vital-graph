#!/usr/bin/env python3
"""
KG Documents Test Data — Loader (real Wikipedia content + segmentation)
=======================================================================

Creates (or resets) a test space/graph and loads ``KGDocument`` objects built
from the Wikipedia markdown files produced by ``fetch_wikipedia_test_docs.py``.
Each document carries real markdown **content**, and the space gets a
segmentation **config**, so the server's auto-segmentation hook builds real
segments on create.

Pipeline:
    1. fetch content:   python test_scripts/data/fetch_wikipedia_test_docs.py --count 500
    2. load + segment:  python test_scripts/data/generate_kgdocuments_test_data.py --count 500

Options:
    --count N            Max documents to load (default 500; capped by files available)
    --content-dir DIR    Where the .md files are (default test_files/wikipedia)
    --no-segment         Load documents only; do NOT create a segmentation config
    --max-segment-tokens Segment size target (default 512)
    --no-vectorize / --vectorize   Auto-vectorize segments (default: no — avoids embedding models)
    --space / --graph    Target space/graph (default doc_test / urn:doc_test)
    --batch N            Create batch size (default 25 — segmentation runs per doc on create)
    --keep               Do not delete the space first

Requires a running VitalGraph server (reads config from .env / environment).
"""

import argparse
import asyncio
import datetime
import logging
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from vitalgraph.client.vitalgraph_client import VitalGraphClient

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# ── Defaults ──────────────────────────────────────────────────────────────

DEFAULT_SPACE = "doc_test"
DEFAULT_GRAPH = "urn:doc_test"
DEFAULT_COUNT = 500
DEFAULT_BATCH = 25
DEFAULT_CONTENT_DIR = Path(__file__).resolve().parent.parent.parent / "test_files" / "wikipedia"

DOC_TYPE = "urn:doctype:wikipedia_article"
# Wikipedia markdown has headings → use the markdown heading segmenter.
SEGMENT_METHOD = "urn:segmethod:markdown_heading_split"
URI_PREFIX = "http://vital.ai/haley.ai/app/KGDocument"


# ── Helpers ───────────────────────────────────────────────────────────────

async def delete_space(client: VitalGraphClient, space_id: str):
    logger.info("Deleting existing space '%s' (if any)...", space_id)
    try:
        await client.spaces.delete_space(space_id)
        logger.info("  deleted '%s'", space_id)
    except Exception as e:  # noqa: BLE001
        if "404" in str(e) or "not found" in str(e).lower():
            logger.info("  '%s' not found (clean start)", space_id)
        else:
            raise


async def create_space(client: VitalGraphClient, space_id: str, graph_id: str):
    from vitalgraph.model.spaces_model import Space
    logger.info("Creating space '%s' + graph '%s'...", space_id, graph_id)
    try:
        await client.spaces.create_space(Space(
            space=space_id, space_name="KG Documents Test",
            space_description="Wikipedia documents with real content + segments.",
        ))
        logger.info("  created space")
    except Exception as e:  # noqa: BLE001
        if "already exists" in str(e).lower() or "409" in str(e) or "duplicate" in str(e).lower():
            logger.info("  space already exists")
        else:
            raise
    try:
        await client.create_graph(space_id, graph_id)
        logger.info("  created graph")
    except Exception as e:  # noqa: BLE001
        logger.info("  graph create skipped (%s)", str(e).split(chr(10))[0][:60])


async def create_seg_config(client: VitalGraphClient, space_id: str,
                            max_tokens: int, vectorize: bool):
    logger.info("Creating segmentation config (method=%s, max_tokens=%d, vectorize=%s)...",
                SEGMENT_METHOD, max_tokens, vectorize)
    resp = await client.create_segmentation_config(
        space_id=space_id,
        document_type_uri=DOC_TYPE,
        segment_method_uri=SEGMENT_METHOD,
        max_segment_tokens=max_tokens,
        min_segment_tokens=50,
        enabled=True,
        auto_vectorize=vectorize,
    )
    ok = getattr(resp, "is_success", True)
    logger.info("  segmentation config %s", "created" if ok else f"FAILED: {resp}")


def _headline(md_text: str, fallback: str) -> str:
    for line in md_text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()[:200]
    return fallback


def build_documents(content_dir: Path, count: int):
    from ai_haley_kg_domain.model.KGDocument import KGDocument
    files = sorted(content_dir.glob("*.md"))
    if not files:
        raise SystemExit(
            f"No .md files in {content_dir}. Run fetch_wikipedia_test_docs.py first "
            f"(e.g. --count {count}).")
    # Reach `count` documents by cycling through the available articles when
    # there are fewer files than requested — each doc still gets real content
    # and a unique URI (content repeats, headlines are disambiguated).
    if len(files) < count:
        logger.info("Only %d article file(s) available; cycling to reach %d documents.",
                    len(files), count)
    now = datetime.datetime.now(datetime.timezone.utc)
    docs = []
    for i in range(count):
        f = files[i % len(files)]
        rep = i // len(files)
        text = f.read_text(encoding="utf-8")
        base_title = _headline(text, f.stem.replace("_", " ").title())
        title = base_title if rep == 0 else f"{base_title} (copy {rep})"
        d = KGDocument()
        d.URI = f"{URI_PREFIX}/{uuid.uuid4().hex}"
        d.name = title
        d.kGDocumentHeadline = title
        d.kGDocumentType = DOC_TYPE
        d.kGDocumentContent = text          # real markdown → segmentable
        d.kGDocumentURL = f"https://en.wikipedia.org/wiki/{f.stem}"
        d.kGIndexDateTime = now - datetime.timedelta(minutes=i)
        docs.append(d)
    logger.info("Built %d documents from %d article file(s) in %s",
                len(docs), len(files), content_dir)
    return docs


async def load_documents(client, space_id, graph_id, docs, batch):
    total = 0
    for start in range(0, len(docs), batch):
        chunk = docs[start:start + batch]
        resp = await client.create_kgdocuments(space_id, graph_id, chunk)
        if getattr(resp, "is_success", None) is False:
            raise RuntimeError(f"create_kgdocuments failed: {getattr(resp, 'error_message', resp)}")
        total += len(chunk)
        logger.info("  loaded %d/%d (segmenting on create)...", total, len(docs))
    return total


async def segment_all(client, space_id, graph_id, uris, method, max_tokens, concurrency):
    """Enqueue a segmentation job per document (the background worker processes them)."""
    logger.info("Enqueuing segmentation for %d documents (method=%s)...", len(uris), method)
    sem = asyncio.Semaphore(concurrency)
    done = {"n": 0}

    async def _one(u):
        async with sem:
            try:
                await client.segment_document(space_id, graph_id, u,
                                              segment_method_uri=method, max_segment_tokens=max_tokens)
            except Exception as e:  # noqa: BLE001
                logger.warning("  enqueue failed for %s: %s", u, str(e)[:80])
            done["n"] += 1
            if done["n"] % 50 == 0 or done["n"] == len(uris):
                logger.info("  enqueued %d/%d", done["n"], len(uris))

    await asyncio.gather(*[_one(u) for u in uris])


async def wait_for_segments(client, space_id, graph_id, n_docs, wait_s):
    """Poll until the segment count stabilizes or the timeout elapses (worker is async)."""
    import time as _time
    logger.info("Waiting up to %ds for the segmentation worker to build segments...", wait_s)
    deadline = _time.monotonic() + wait_s
    last, stable = -1, 0
    while _time.monotonic() < deadline:
        r = await client.list_kgdocuments(space_id, graph_id, page_size=1, offset=0,
                                          include_segments=True)
        total = getattr(r, "count", 0) or 0
        segs = total - n_docs
        logger.info("  segments so far ≈ %d", segs)
        if segs == last:
            stable += 1
            if stable >= 3 and segs > 0:
                break
        else:
            last, stable = segs, 0
        await asyncio.sleep(4)


async def verify(client, space_id, graph_id):
    docs_only = await client.list_kgdocuments(space_id, graph_id, page_size=1, offset=0,
                                              include_segments=False)
    with_segs = await client.list_kgdocuments(space_id, graph_id, page_size=1, offset=0,
                                              include_segments=True)
    d = getattr(docs_only, "count", None)
    a = getattr(with_segs, "count", None)
    logger.info("Verify: documents=%s, documents+segments=%s, segments≈%s",
                d, a, (a - d) if (isinstance(a, int) and isinstance(d, int)) else "?")


# ── Main ──────────────────────────────────────────────────────────────────

async def run(args):
    logger.info("=" * 66)
    logger.info("  KG Documents loader — Wikipedia content%s",
                "" if args.no_segment else " + segmentation")
    logger.info("  space=%s graph=%s count=%d", args.space, args.graph, args.count)
    logger.info("=" * 66)

    docs = build_documents(Path(args.content_dir), args.count)

    client = VitalGraphClient(token_expiry_seconds=300)
    await client.open()
    try:
        if not args.keep:
            await delete_space(client, args.space)
        await create_space(client, args.space, args.graph)
        if not args.no_segment:
            # Config makes the doc type "segmentation-enabled" (drives re-segmentation
            # on future edits); the initial segments are built by explicit jobs below.
            await create_seg_config(client, args.space, args.max_segment_tokens,
                                    vectorize=args.vectorize)
        loaded = await load_documents(client, args.space, args.graph, docs, args.batch)
        logger.info("Loaded %d documents.", loaded)

        if not args.no_segment:
            uris = [str(d.URI) for d in docs]
            await segment_all(client, args.space, args.graph, uris,
                              SEGMENT_METHOD, args.max_segment_tokens, args.seg_concurrency)
            await wait_for_segments(client, args.space, args.graph, loaded, args.wait)

        await verify(client, args.space, args.graph)
    finally:
        await client.close()

    logger.info("✅ Done — open the KG Documents screen for '%s' / '%s'.", args.space, args.graph)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Load Wikipedia KGDocuments with real content + segments")
    p.add_argument("--space", default=DEFAULT_SPACE)
    p.add_argument("--graph", default=DEFAULT_GRAPH)
    p.add_argument("--count", type=int, default=DEFAULT_COUNT)
    p.add_argument("--content-dir", default=str(DEFAULT_CONTENT_DIR))
    p.add_argument("--batch", type=int, default=DEFAULT_BATCH)
    p.add_argument("--max-segment-tokens", type=int, default=512)
    p.add_argument("--no-segment", action="store_true", help="Load documents only, no segmentation config")
    p.add_argument("--vectorize", dest="vectorize", action="store_true", help="Auto-vectorize segments")
    p.add_argument("--no-vectorize", dest="vectorize", action="store_false", help="Do not vectorize (default)")
    p.set_defaults(vectorize=False)
    p.add_argument("--seg-concurrency", type=int, default=8, help="Concurrent segment-job enqueues")
    p.add_argument("--wait", type=int, default=180, help="Max seconds to wait for the worker to build segments")
    p.add_argument("--keep", action="store_true")
    asyncio.run(run(p.parse_args()))
