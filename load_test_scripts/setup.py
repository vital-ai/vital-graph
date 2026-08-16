#!/usr/bin/env python3
"""Load-test setup/teardown — seed the space, graph, and organization entities.

Creates everything via VitalGraphClient (this repo's own client → the sanctioned
space-manager path), using the org-entity generator copied into data_gen/. Writes
the created entity URIs into load_test_data.py for Locust to consume.

Usage:
    python load_test_scripts/setup.py                 # seed 20 entities (local)
    python load_test_scripts/setup.py --entities 50
    python load_test_scripts/setup.py --cleanup       # delete them
    LOAD_TEST_ENV=test python load_test_scripts/setup.py   # target :8002
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("load_test.setup")

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE.parent))       # repo root — for `import vitalgraph`
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE / "data_gen"))

from load_test_config import load_env
from load_test_data import LOAD_TEST_SPACE_ID, LOAD_TEST_GRAPH_ID, ENTITY_FILE

# The generated list, NOT the module that reads it. Writing the module was
# issues/084: a setup run against an already-seeded space created nothing,
# wrote the empty result over a TRACKED source file, and left the driver
# refusing to start with advice to run the command that had just broken it.
DATA_FILE = ENTITY_FILE


def _configure_client_env(cfg):
    os.environ.setdefault("VITALGRAPH_CLIENT_ENVIRONMENT", "test")
    os.environ["TEST_CLIENT_SERVER_URL"] = cfg["url"]
    os.environ["TEST_CLIENT_AUTH_USERNAME"] = cfg["username"]
    os.environ["TEST_CLIENT_AUTH_PASSWORD"] = cfg["password"]


def _write_data(entity_data):
    """Write the generated entity list. Untracked JSON, not a source module."""
    DATA_FILE.write_text(json.dumps(entity_data, indent=4) + "\n")
    logger.info("Wrote %d entities to %s", len(entity_data), DATA_FILE.name)


async def _entities_in_space(client, limit: int = 5000):
    """Every entity the space actually holds, as [{'uri','name'}].

    The driver wants entities that EXIST, not entities this run happened to
    create — that distinction is the whole of issues/084. Reading the space back
    makes setup idempotent: run it twice and the second run still produces a
    usable list instead of an empty one.

    Returns None if the listing fails, which is different from an empty space
    and must not be written over a good file.
    """
    collected = []
    offset, page_size = 0, 200
    while offset < limit:
        resp = await client.kgentities.list_kgentities(
            space_id=LOAD_TEST_SPACE_ID, graph_id=LOAD_TEST_GRAPH_ID,
            page_size=page_size, offset=offset)
        if not getattr(resp, "is_success", False):
            logger.error("Could not list entities: %s",
                         getattr(resp, "error_message", resp))
            return None
        objects = getattr(resp, "objects", None) or []
        for obj in objects:
            uri = getattr(obj, "URI", None)
            if uri is None:
                continue
            name = getattr(obj, "name", None)
            collected.append({"uri": str(uri), "name": str(name) if name else str(uri)})
        # has_more is authoritative when the server sends it; fall back to a
        # short page meaning the end.
        if getattr(resp, "has_more", None) is False or len(objects) < page_size:
            break
        offset += page_size
    return collected


async def _open_client(cfg):
    _configure_client_env(cfg)
    from vitalgraph.client.vitalgraph_client import VitalGraphClient
    client = VitalGraphClient()
    await client.open()
    return client


async def setup(num_entities: int):
    cfg = load_env()
    logger.info("Seeding %d entities into %s/%s at %s",
                num_entities, LOAD_TEST_SPACE_ID, LOAD_TEST_GRAPH_ID, cfg["url"])
    client = await _open_client(cfg)
    try:
        from vitalgraph.model.spaces_model import Space
        from ai_haley_kg_domain.model.KGEntity import KGEntity
        from kg_test_data import KGAPITestDataCreator
        from organizations import ORGANIZATIONS

        # Space
        resp = await client.spaces.list_spaces()
        existing = [s.space for s in resp.spaces] if getattr(resp, "is_success", False) else []
        if LOAD_TEST_SPACE_ID not in existing:
            cr = await client.spaces.create_space(Space(
                space=LOAD_TEST_SPACE_ID, space_name="Load Test Space",
                space_description="Dedicated space for Locust load testing"))
            if not cr.is_success:
                raise RuntimeError(f"create_space failed: {cr.error_message}")
            logger.info("Created space %s", LOAD_TEST_SPACE_ID)

        # Graph
        gresp = await client.graphs.list_graphs(LOAD_TEST_SPACE_ID)
        gexisting = [g.graph_uri for g in gresp.graphs] if getattr(gresp, "is_success", False) else []
        if LOAD_TEST_GRAPH_ID not in gexisting:
            await client.graphs.create_graph(LOAD_TEST_SPACE_ID, LOAD_TEST_GRAPH_ID)
            logger.info("Created graph %s", LOAD_TEST_GRAPH_ID)

        # Entities (cycle the org list, numbering extras)
        gen = KGAPITestDataCreator()
        created = 0
        failed = 0
        for i in range(num_entities):
            base = ORGANIZATIONS[i % len(ORGANIZATIONS)]
            name = base["name"] if i < len(ORGANIZATIONS) else f"{base['name']} #{i + 1}"
            objects = gen.create_organization_with_address(name)
            entity = next(o for o in objects if isinstance(o, KGEntity))
            cr = await client.kgentities.create_kgentities(
                space_id=LOAD_TEST_SPACE_ID, graph_id=LOAD_TEST_GRAPH_ID, objects=objects)
            if hasattr(cr, "is_success") and not cr.is_success:
                failed += 1
                logger.warning("create entity %s: %s", name, getattr(cr, "error_message", cr))
                continue
            created += 1
            logger.info("  [%d/%d] %s", i + 1, num_entities, name)

        # Record what the space CONTAINS, not what this run created. The URIs are
        # derived from the org names, so a second run creates nothing and used to
        # write that nothing over the driver's fixture list (issues/084).
        entity_data = await _entities_in_space(client)

        if entity_data is None:
            # A failed listing is not an empty space. Leave the existing file
            # alone rather than replacing a good list with a lie.
            raise RuntimeError(
                "Could not read the space back, so the entity list was NOT "
                "rewritten. The previous list (if any) is untouched.")

        if not entity_data:
            raise RuntimeError(
                f"Space {LOAD_TEST_SPACE_ID} holds no entities after seeding "
                f"({created} created, {failed} failed). Not writing an empty "
                f"list — the driver would then refuse to start with no way to "
                f"tell an empty space from a lost fixture.")

        _write_data(entity_data)
        if created:
            logger.info("SETUP COMPLETE — %d created, %d entities in the space",
                        created, len(entity_data))
        else:
            logger.info("SETUP COMPLETE — nothing new to create; %d entities "
                        "already present and recorded", len(entity_data))
    finally:
        await client.close()


async def cleanup():
    cfg = load_env()
    client = await _open_client(cfg)
    try:
        from load_test_data import get_entity_uris
        uris = get_entity_uris()
        if uris:
            cr = await client.kgentities.delete_kgentities(
                space_id=LOAD_TEST_SPACE_ID, graph_id=LOAD_TEST_GRAPH_ID, uris=uris)
            logger.info("Deleted %d entities (%s)", len(uris),
                        getattr(cr, "is_success", cr))
        # Remove the generated list rather than writing an empty one: absent
        # and empty mean different things to the driver, and "no file" is the
        # honest state after a cleanup.
        if DATA_FILE.exists():
            DATA_FILE.unlink()
            logger.info("Removed %s", DATA_FILE.name)
        logger.info("CLEANUP COMPLETE")
    finally:
        await client.close()


def main():
    p = argparse.ArgumentParser(description="Load-test data setup/teardown")
    p.add_argument("--cleanup", action="store_true")
    p.add_argument("--entities", type=int, default=20)
    args = p.parse_args()
    try:
        asyncio.run(cleanup() if args.cleanup else setup(args.entities))
    except RuntimeError as exc:
        # Exit non-zero and say what happened. This used to print
        # "SETUP COMPLETE — 0 entities ready" and return 0 (issues/084), so a
        # script or a person had no way to tell a working seed from a broken
        # one.
        logger.error("SETUP FAILED — %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
