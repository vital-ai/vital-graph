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
from load_test_data import LOAD_TEST_SPACE_ID, LOAD_TEST_GRAPH_ID

DATA_FILE = _HERE / "load_test_data.py"


def _configure_client_env(cfg):
    os.environ.setdefault("VITALGRAPH_CLIENT_ENVIRONMENT", "test")
    os.environ["TEST_CLIENT_SERVER_URL"] = cfg["url"]
    os.environ["TEST_CLIENT_AUTH_USERNAME"] = cfg["username"]
    os.environ["TEST_CLIENT_AUTH_PASSWORD"] = cfg["password"]


def _write_data(entity_data):
    DATA_FILE.write_text(
        '"""Load-test data — populated by setup.py."""\n\n'
        f'LOAD_TEST_SPACE_ID = "{LOAD_TEST_SPACE_ID}"\n'
        f'LOAD_TEST_GRAPH_ID = "{LOAD_TEST_GRAPH_ID}"\n\n'
        f"ENTITY_DATA = {json.dumps(entity_data, indent=4)}\n\n"
        "def get_entity_uris():\n    return [e['uri'] for e in ENTITY_DATA]\n\n"
        "def get_entity_names():\n    return [e['name'] for e in ENTITY_DATA]\n")
    logger.info("Wrote %d entities to %s", len(entity_data), DATA_FILE)


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
        entity_data = []
        for i in range(num_entities):
            base = ORGANIZATIONS[i % len(ORGANIZATIONS)]
            name = base["name"] if i < len(ORGANIZATIONS) else f"{base['name']} #{i + 1}"
            objects = gen.create_organization_with_address(name)
            entity = next(o for o in objects if isinstance(o, KGEntity))
            cr = await client.kgentities.create_kgentities(
                space_id=LOAD_TEST_SPACE_ID, graph_id=LOAD_TEST_GRAPH_ID, objects=objects)
            if hasattr(cr, "is_success") and not cr.is_success:
                logger.warning("create entity %s: %s", name, getattr(cr, "error_message", cr))
                continue
            entity_data.append({"uri": str(entity.URI), "name": name})
            logger.info("  [%d/%d] %s", i + 1, num_entities, name)

        _write_data(entity_data)
        logger.info("SETUP COMPLETE — %d entities ready", len(entity_data))
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
        _write_data([])
        logger.info("CLEANUP COMPLETE")
    finally:
        await client.close()


def main():
    p = argparse.ArgumentParser(description="Load-test data setup/teardown")
    p.add_argument("--cleanup", action="store_true")
    p.add_argument("--entities", type=int, default=20)
    args = p.parse_args()
    asyncio.run(cleanup() if args.cleanup else setup(args.entities))


if __name__ == "__main__":
    main()
