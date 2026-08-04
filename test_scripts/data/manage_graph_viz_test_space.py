#!/usr/bin/env python3
"""
Graph Visualization Test Space — Create / Delete
==================================================

Unified script to create or delete the ``graph_viz_test`` space used for
graph visualization development and testing.

Commands:
    create  — Generate .vital dataset files (A–F), create space, import all
    delete  — Delete the test space and all its data
    status  — Check if the space exists and show object counts

Usage:
    python test_scripts/data/manage_graph_viz_test_space.py create
    python test_scripts/data/manage_graph_viz_test_space.py delete
    python test_scripts/data/manage_graph_viz_test_space.py status

Requires a running VitalGraph server (reads config from .env / environment).

See: planning/planning_visualization/graph_session_architecture_plan.md §9.8
"""

import asyncio
import argparse
import logging
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from vitalgraph.client.vitalgraph_client import VitalGraphClient

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
GENERATOR_SCRIPT = PROJECT_ROOT / "test_scripts" / "data" / "generate_graph_viz_test_data.py"
OUTPUT_DIR = PROJECT_ROOT / "generated_instances"
PYTHON = sys.executable

# Each dataset gets its own space
DATASETS = [
    {"key": "A", "space_id": "graph_viz_a", "file": "graph_viz_test_A_people.vital",
     "name": "Graph Viz A — People & Employment", "desc": "Binary frames + relations"},
    {"key": "B", "space_id": "graph_viz_b", "file": "graph_viz_test_B_research.vital",
     "name": "Graph Viz B — Research", "desc": "N-ary frames"},
    {"key": "C", "space_id": "graph_viz_c", "file": "graph_viz_test_C_supply.vital",
     "name": "Graph Viz C — Supply Chain", "desc": "Mixed arity + subframes"},
    {"key": "D", "space_id": "graph_viz_d", "file": "graph_viz_test_D_social.vital",
     "name": "Graph Viz D — Social Network", "desc": "Pure relations, no frames"},
    {"key": "E", "space_id": "graph_viz_e", "file": "graph_viz_test_E_unary.vital",
     "name": "Graph Viz E — Unary Frames", "desc": "Annotation/tag pattern"},
    {"key": "F", "space_id": "graph_viz_f", "file": "graph_viz_test_F_toplevel.vital",
     "name": "Graph Viz F — Top-Level Frames", "desc": "Assertions, no owning entity"},
]


# ── Helpers ───────────────────────────────────────────────────────────────

async def _ignore_not_found(coro, label: str):
    """Run an async call, swallowing 404/not-found errors."""
    try:
        return await coro
    except Exception as e:
        if "404" in str(e) or "not found" in str(e).lower():
            logger.info("  %s not found (nothing to do)", label)
            return None
        raise


async def _ignore_conflict(coro, label: str):
    """Run an async call, swallowing 409/already-exists errors."""
    try:
        result = await coro
        logger.info("  Created %s", label)
        return result
    except Exception as e:
        msg = str(e).lower()
        if "409" in str(e) or "already exists" in msg or "duplicate" in msg:
            logger.info("  %s already exists (skipped)", label)
            return None
        raise


def generate_datasets():
    """Run the generator script to produce .vital files."""
    print("Generating dataset files...")
    if not GENERATOR_SCRIPT.exists():
        logger.error("  Generator script not found: %s", GENERATOR_SCRIPT)
        sys.exit(1)

    result = subprocess.run(
        [PYTHON, str(GENERATOR_SCRIPT), "--output-dir", str(OUTPUT_DIR)],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    if result.returncode != 0:
        logger.error("  Generator failed:\n%s", result.stderr)
        sys.exit(1)

    missing = [ds["file"] for ds in DATASETS if not (OUTPUT_DIR / ds["file"]).exists()]
    if missing:
        logger.error("  Missing files after generation: %s", missing)
        sys.exit(1)

    logger.info("  Generated %d dataset files in %s", len(DATASETS), OUTPUT_DIR)


async def import_file(client: VitalGraphClient, space_id: str, filename: str) -> bool:
    """Import one .vital file into a space."""
    from vitalgraph.model.import_model import ImportJobCreate, ImportMode, FileFormat

    vital_path = OUTPUT_DIR / filename
    graph_uri = f"urn:vitalgraph:{space_id}:data"
    if not vital_path.exists():
        logger.error("  File not found: %s", vital_path)
        return False

    job_create = ImportJobCreate(
        space_id=space_id,
        graph_uri=graph_uri,
        file_format=FileFormat.VITAL,
        mode=ImportMode.APPEND,
    )
    create_resp = await client.imports.create_import_job(job_create)
    job_id = create_resp.job.job_id

    await client.imports.upload_import_file(job_id, str(vital_path))
    await client.imports.execute_import_job(job_id)

    for _ in range(120):
        status_resp = await client.imports.get_import_status(job_id)
        status_str = str(status_resp.status).lower()
        if 'completed' in status_str or 'done' in status_str:
            logger.info("    ✓ %s records", status_resp.records_done)
            return True
        if 'failed' in status_str or 'error' in status_str:
            logger.error("    ✗ Import failed: %s", status_resp.error_message)
            return False
        await asyncio.sleep(1)

    logger.error("    ✗ Timed out after 120s")
    return False


async def get_space_counts(client: VitalGraphClient, space_id: str) -> dict[str, int] | None:
    """Query object counts in a space. Returns None if space doesn't exist."""
    from vitalgraph.model.sparql_model import SPARQLQueryRequest

    try:
        request = SPARQLQueryRequest(
            query="""
                SELECT
                    (COUNT(DISTINCT ?ent) AS ?entities)
                    (COUNT(DISTINCT ?frame) AS ?frames)
                    (COUNT(DISTINCT ?rel) AS ?relations)
                WHERE {
                    {
                        ?ent a <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                    } UNION {
                        ?frame a <http://vital.ai/ontology/haley-ai-kg#KGFrame> .
                    } UNION {
                        ?rel a <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelation> .
                    }
                }
            """,
        )
        result = await client.sparql.execute_sparql_query(space_id, request)

        bindings = (result.results or {}).get("bindings", [])
        if bindings:
            row = bindings[0]
            return {
                "entities": int(row.get("entities", {}).get("value", "0")),
                "frames": int(row.get("frames", {}).get("value", "0")),
                "relations": int(row.get("relations", {}).get("value", "0")),
            }
        return {"entities": 0, "frames": 0, "relations": 0}
    except Exception as e:
        if "404" in str(e) or "not found" in str(e).lower():
            return None
        raise


# ── Commands ──────────────────────────────────────────────────────────────

async def create_one_space(client: VitalGraphClient, ds: dict) -> bool:
    """Create a single space and import its dataset file."""
    from vitalgraph.model.spaces_model import Space

    space_id = ds["space_id"]
    filename = ds["file"]

    print(f"\n  [{ds['key']}] {ds['name']}")

    # Delete existing and wait until it's fully gone
    await _ignore_not_found(
        client.spaces.delete_space(space_id),
        f"space '{space_id}'",
    )
    for _ in range(30):
        resp = await client.spaces.get_space(space_id)
        if resp.error_code != 0 or resp.space is None:
            break
        await asyncio.sleep(1)
    else:
        logger.error("    Space '%s' still exists after delete — aborting", space_id)
        return False

    # Create and verify success
    space = Space(
        space=space_id,
        space_name=ds["name"],
        space_description=ds["desc"],
    )
    create_resp = await client.spaces.create_space(space)
    if create_resp.error_code != 0:
        logger.error("    Failed to create space '%s': %s", space_id,
                      create_resp.error_message or "unknown error")
        return False
    logger.info("    Created space '%s'", space_id)

    # Import
    ok = await import_file(client, space_id, filename)
    if ok:
        counts = await get_space_counts(client, space_id)
        if counts:
            total = sum(counts.values())
            logger.info("    %d entities, %d frames, %d relations = %d total",
                        counts["entities"], counts["frames"], counts["relations"], total)
    return ok


async def cmd_create():
    """Generate datasets, create one space per dataset, import."""
    print("=" * 60)
    print("CREATE — Graph Visualization Test Spaces")
    print("=" * 60)
    print(f"  Spaces: {len(DATASETS)}")
    for ds in DATASETS:
        print(f"    {ds['space_id']:16s}  {ds['name']}")
    print()

    generate_datasets()

    client = VitalGraphClient(token_expiry_seconds=300)
    await client.open()

    try:
        success = 0
        for ds in DATASETS:
            if await create_one_space(client, ds):
                success += 1
    finally:
        await client.close()

    print()
    if success == len(DATASETS):
        print(f"✅ All {len(DATASETS)} spaces created")
    else:
        print(f"⚠️  {success}/{len(DATASETS)} spaces created")
        sys.exit(1)


async def cmd_delete():
    """Delete all test spaces."""
    print("=" * 60)
    print("DELETE — Graph Visualization Test Spaces")
    print("=" * 60)
    print()

    client = VitalGraphClient(token_expiry_seconds=300)
    await client.open()

    try:
        for ds in DATASETS:
            resp = await _ignore_not_found(
                client.spaces.delete_space(ds["space_id"]),
                f"space '{ds['space_id']}'",
            )
            if resp is not None:
                logger.info("  Deleted '%s'", ds["space_id"])
    finally:
        await client.close()

    print()
    print(f"✅ All {len(DATASETS)} test spaces deleted")


async def cmd_status():
    """Check which spaces exist and show counts."""
    print("=" * 60)
    print("STATUS — Graph Visualization Test Spaces")
    print("=" * 60)
    print()

    client = VitalGraphClient(token_expiry_seconds=300)
    await client.open()

    try:
        for ds in DATASETS:
            counts = await get_space_counts(client, ds["space_id"])
            if counts is None:
                print(f"  [{ds['key']}] {ds['space_id']:16s}  ✗ does not exist")
            else:
                total = sum(counts.values())
                print(f"  [{ds['key']}] {ds['space_id']:16s}  "
                      f"{counts['entities']} ent, {counts['frames']} fr, "
                      f"{counts['relations']} rel = {total} total")
    finally:
        await client.close()

    # Check local files
    print()
    print("  Local dataset files:")
    for ds in DATASETS:
        path = OUTPUT_DIR / ds["file"]
        if path.exists():
            print(f"    ✓ {ds['file']} ({path.stat().st_size / 1024:.0f} KB)")
        else:
            print(f"    ✗ {ds['file']} (missing)")


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Manage graph visualization test spaces (one per dataset)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
commands:
  create   Generate datasets, create 6 spaces (A-F), import data
  delete   Delete all 6 test spaces
  status   Check which spaces exist and show object counts
        """,
    )
    parser.add_argument("command", choices=["create", "delete", "status"],
                        help="Action to perform")

    args = parser.parse_args()

    if args.command == "create":
        asyncio.run(cmd_create())
    elif args.command == "delete":
        asyncio.run(cmd_delete())
    elif args.command == "status":
        asyncio.run(cmd_status())


if __name__ == "__main__":
    main()
