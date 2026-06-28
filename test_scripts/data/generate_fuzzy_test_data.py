#!/usr/bin/env python3
"""
Generate fuzzy (fuzzy match) test data for end-to-end testing.

Creates ~100 entities with canonical names and intentional near-duplicates,
suitable for validating:
  - Entity registry find_similar() endpoint
  - vg:fuzzyMatch SPARQL function
  - MinHash LSH + RapidFuzz fuzzy pipeline
  - Client-level fuzzy integration tests

Output: Loads entities via entity registry API or exports JSON.

Usage:
    python test_scripts/data/generate_fuzzy_test_data.py --load
    python test_scripts/data/generate_fuzzy_test_data.py -o output.jsonl
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("generate_fuzzy_test_data")

# ---------------------------------------------------------------------------
# Canonical entities and their variants
# ---------------------------------------------------------------------------

# Each entry: {"canonical": "...", "variants": [...], "type_key": "..."}
FUZZY_TEST_DATA = [
    {
        "canonical": "Apple Inc",
        "type_key": "company",
        "country": "US",
        "variants": [
            {"name": "Aple Inc", "variant_type": "misspelling"},
            {"name": "Appel Inc", "variant_type": "misspelling"},
            {"name": "Apple Incorporated", "variant_type": "suffix_variation"},
            {"name": "APPLE INC", "variant_type": "case_variation"},
        ],
    },
    {
        "canonical": "Google LLC",
        "type_key": "company",
        "country": "US",
        "variants": [
            {"name": "Gogle LLC", "variant_type": "misspelling"},
            {"name": "Google Inc", "variant_type": "suffix_variation"},
            {"name": "Google", "variant_type": "missing_word"},
            {"name": "google llc", "variant_type": "case_variation"},
        ],
    },
    {
        "canonical": "Microsoft Corporation",
        "type_key": "company",
        "country": "US",
        "variants": [
            {"name": "Microsoft Corp.", "variant_type": "abbreviation"},
            {"name": "Microsoft Corp", "variant_type": "abbreviation"},
            {"name": "Microsft Corporation", "variant_type": "misspelling"},
            {"name": "MICROSOFT CORPORATION", "variant_type": "case_variation"},
        ],
    },
    {
        "canonical": "Amazon.com Inc",
        "type_key": "company",
        "country": "US",
        "variants": [
            {"name": "Amazon Inc", "variant_type": "missing_word"},
            {"name": "Amazon.com", "variant_type": "missing_word"},
            {"name": "Amazno.com Inc", "variant_type": "misspelling"},
            {"name": "Amaz0n.com Inc", "variant_type": "character_swap"},
        ],
    },
    {
        "canonical": "Meta Platforms Inc",
        "type_key": "company",
        "country": "US",
        "variants": [
            {"name": "Meta Inc", "variant_type": "missing_word"},
            {"name": "Meta Platforms", "variant_type": "missing_word"},
            {"name": "Meta Platfroms Inc", "variant_type": "misspelling"},
        ],
    },
    {
        "canonical": "Tesla Inc",
        "type_key": "company",
        "country": "US",
        "variants": [
            {"name": "Tessla Inc", "variant_type": "phonetic"},
            {"name": "Tesla Motors", "variant_type": "suffix_variation"},
            {"name": "TESLA INC", "variant_type": "case_variation"},
        ],
    },
    {
        "canonical": "Netflix Inc",
        "type_key": "company",
        "country": "US",
        "variants": [
            {"name": "NETFLIX INC", "variant_type": "case_variation"},
            {"name": "netflix inc", "variant_type": "case_variation"},
            {"name": "Netflixx Inc", "variant_type": "misspelling"},
        ],
    },
    {
        "canonical": "JPMorgan Chase & Co.",
        "type_key": "company",
        "country": "US",
        "variants": [
            {"name": "JP Morgan Chase", "variant_type": "spacing"},
            {"name": "J.P. Morgan Chase", "variant_type": "spacing"},
            {"name": "JPMorgan Chase", "variant_type": "missing_word"},
            {"name": "JP Morgan Chase & Co", "variant_type": "spacing"},
        ],
    },
    {
        "canonical": "Deutsche Bank AG",
        "type_key": "company",
        "country": "DE",
        "variants": [
            {"name": "Deutsche Bank", "variant_type": "missing_word"},
            {"name": "Deutche Bank AG", "variant_type": "misspelling"},
            {"name": "Deutsche Bank A.G.", "variant_type": "abbreviation"},
        ],
    },
    {
        "canonical": "Toyota Motor Corporation",
        "type_key": "company",
        "country": "JP",
        "variants": [
            {"name": "Toyota Motor Corp", "variant_type": "abbreviation"},
            {"name": "Toyota Motor Corp.", "variant_type": "abbreviation"},
            {"name": "Toyota Motors Corporation", "variant_type": "misspelling"},
        ],
    },
    {
        "canonical": "Samsung Electronics",
        "type_key": "company",
        "country": "KR",
        "variants": [
            {"name": "Samsung Electronics Co", "variant_type": "suffix_variation"},
            {"name": "Samsung Electornics", "variant_type": "misspelling"},
            {"name": "Samsnug Electronics", "variant_type": "character_swap"},
        ],
    },
    {
        "canonical": "Alibaba Group",
        "type_key": "company",
        "country": "CN",
        "variants": [
            {"name": "Alibaba Group Holding", "variant_type": "suffix_variation"},
            {"name": "Alibab Group", "variant_type": "misspelling"},
            {"name": "Ali Baba Group", "variant_type": "spacing"},
        ],
    },
    {
        "canonical": "Berkshire Hathaway Inc",
        "type_key": "company",
        "country": "US",
        "variants": [
            {"name": "Berkshire Hathaway", "variant_type": "missing_word"},
            {"name": "Berkshire Hathway Inc", "variant_type": "misspelling"},
        ],
    },
    {
        "canonical": "Johnson & Johnson",
        "type_key": "company",
        "country": "US",
        "variants": [
            {"name": "Johnson and Johnson", "variant_type": "spacing"},
            {"name": "J&J", "variant_type": "abbreviation"},
            {"name": "Johnson & Jonson", "variant_type": "misspelling"},
        ],
    },
    {
        "canonical": "Procter & Gamble",
        "type_key": "company",
        "country": "US",
        "variants": [
            {"name": "Proctor & Gamble", "variant_type": "misspelling"},
            {"name": "Procter and Gamble", "variant_type": "spacing"},
            {"name": "P&G", "variant_type": "abbreviation"},
        ],
    },
]

# Negative controls — should NOT match any of the above
NEGATIVE_CONTROLS = [
    {"name": "Quantum Dynamics Research Lab", "type_key": "research", "country": "US"},
    {"name": "Stellar Navigation Systems", "type_key": "aerospace", "country": "US"},
    {"name": "Pacific Rim Trading Co", "type_key": "trading", "country": "SG"},
    {"name": "Nordic Forestry Solutions", "type_key": "forestry", "country": "NO"},
    {"name": "Sahara Oasis Hospitality", "type_key": "hospitality", "country": "AE"},
    {"name": "Alpine Crystal Manufacturing", "type_key": "manufacturing", "country": "CH"},
    {"name": "Coral Reef Marine Biology", "type_key": "research", "country": "AU"},
    {"name": "Thunderbolt Express Logistics", "type_key": "logistics", "country": "US"},
    {"name": "Emerald Isle Distillery", "type_key": "beverage", "country": "IE"},
    {"name": "Crimson Tide Athletics", "type_key": "sports", "country": "US"},
]


# ---------------------------------------------------------------------------
# Generate flat entity list
# ---------------------------------------------------------------------------

def generate_all_entities():
    """Generate all entities (canonical + variants + negatives) as flat list."""
    entities = []

    for group in FUZZY_TEST_DATA:
        # Canonical entity
        entities.append({
            "name": group["canonical"],
            "type_key": group["type_key"],
            "country": group.get("country"),
            "is_canonical": True,
            "expected_group": group["canonical"],
            "variant_type": None,
        })
        # Variants
        for variant in group["variants"]:
            entities.append({
                "name": variant["name"],
                "type_key": group["type_key"],
                "country": group.get("country"),
                "is_canonical": False,
                "expected_group": group["canonical"],
                "variant_type": variant["variant_type"],
            })

    # Negative controls
    for neg in NEGATIVE_CONTROLS:
        entities.append({
            "name": neg["name"],
            "type_key": neg["type_key"],
            "country": neg.get("country"),
            "is_canonical": True,
            "expected_group": None,  # Should not match any canonical
            "variant_type": None,
        })

    return entities


# ---------------------------------------------------------------------------
# Expected match manifest
# ---------------------------------------------------------------------------

def generate_match_manifest():
    """Generate manifest of expected matches for test validation."""
    manifest = []
    for group in FUZZY_TEST_DATA:
        for variant in group["variants"]:
            manifest.append({
                "query": variant["name"],
                "expected_match": group["canonical"],
                "variant_type": variant["variant_type"],
                "min_expected_score": 40,  # Minimum expected fuzzy score
            })
    return manifest


# ---------------------------------------------------------------------------
# Database loading
# ---------------------------------------------------------------------------

async def load_via_entity_registry(api_key: str):
    """Load entities into the entity registry via REST API."""
    from vitalgraph.client.vitalgraph_client import VitalGraphClient
    from vitalgraph.model.entity_registry_model import EntityCreateRequest

    client = VitalGraphClient(api_key=api_key)
    await client.open()

    try:
        entities = generate_all_entities()
        loaded = 0

        for ent in entities:
            try:
                req = EntityCreateRequest(
                    primary_name=ent["name"],
                    type_key=ent["type_key"],
                    country=ent.get("country"),
                )
                await client.entity_registry.create_entity(request=req)
                loaded += 1
            except Exception as e:
                logger.warning("Failed to create entity '%s': %s", ent["name"], e)

        logger.info("Loaded %d/%d entities into entity registry", loaded, len(entities))
        return loaded > 0
    finally:
        await client.close()


async def load_into_space(pool):
    """Load entities directly into a PostgreSQL test space for SPARQL testing."""
    import uuid as uuid_mod
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema

    SPACE_ID = "sp_fuzzy_test"
    GRAPH_URI = "urn:vitalgraph:fuzzy_test:entities"
    URL_NS = uuid_mod.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

    def uri_for_entity(name: str) -> str:
        slug = name.lower().replace(" ", "_").replace(".", "").replace("&", "and")
        return f"http://vital.ai/test/fuzzy/{slug}"

    def uuid_for_uri(uri: str) -> uuid_mod.UUID:
        return uuid_mod.uuid5(URL_NS, uri)

    schema = SparqlSQLSchema()
    context_uuid = uuid_for_uri(GRAPH_URI)
    entities = generate_all_entities()

    async with pool.acquire() as conn:
        # Check pg_trgm
        check = await conn.fetchval(
            "SELECT COUNT(*) FROM pg_extension WHERE extname = 'pg_trgm'"
        )
        if check == 0:
            logger.error("pg_trgm extension not installed!")
            return False

        # Drop/create space
        for stmt in schema.drop_space_tables_sql(SPACE_ID):
            try:
                await conn.execute(stmt)
            except Exception:
                pass

        for stmt in schema.create_space_tables_sql(SPACE_ID):
            await conn.execute(stmt)
        for stmt in schema.create_space_indexes_sql(SPACE_ID):
            await conn.execute(stmt)

        # Enable trigram index on term table for fuzzy matching
        await conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_{SPACE_ID}_term_trgm
            ON {SPACE_ID}_term USING gin (term_text gin_trgm_ops)
            WHERE term_type = 'L'
        """)

        # Insert context
        await conn.execute(f"""
            INSERT INTO {SPACE_ID}_term (term_uuid, term_text, term_type)
            VALUES ($1, $2, 'U')
            ON CONFLICT DO NOTHING
        """, context_uuid, GRAPH_URI)

        # Predicates
        vitaltype_uri = "http://vital.ai/ontology/vital-core#vitaltype"
        has_name_uri = "http://vital.ai/ontology/vital-core#hasName"
        kgentity_type = "http://vital.ai/ontology/haley-ai-kg#KGEntity"

        vitaltype_uuid = uuid_for_uri(vitaltype_uri)
        has_name_uuid = uuid_for_uri(has_name_uri)
        kgentity_uuid = uuid_for_uri(kgentity_type)

        for uri, u in [(vitaltype_uri, vitaltype_uuid),
                       (has_name_uri, has_name_uuid),
                       (kgentity_type, kgentity_uuid)]:
            await conn.execute(f"""
                INSERT INTO {SPACE_ID}_term (term_uuid, term_text, term_type)
                VALUES ($1, $2, 'U')
                ON CONFLICT DO NOTHING
            """, u, uri)

        # Insert entities
        for ent in entities:
            uri = uri_for_entity(ent["name"])
            subj_uuid = uuid_for_uri(uri)

            await conn.execute(f"""
                INSERT INTO {SPACE_ID}_term (term_uuid, term_text, term_type)
                VALUES ($1, $2, 'U')
                ON CONFLICT DO NOTHING
            """, subj_uuid, uri)

            name_uuid = uuid_for_uri(f"{uri}#name#{ent['name']}")
            await conn.execute(f"""
                INSERT INTO {SPACE_ID}_term (term_uuid, term_text, term_type)
                VALUES ($1, $2, 'L')
                ON CONFLICT DO NOTHING
            """, name_uuid, ent["name"])

            await conn.execute(f"""
                INSERT INTO {SPACE_ID}_rdf_quad (subject_uuid, predicate_uuid, object_uuid, context_uuid)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT DO NOTHING
            """, subj_uuid, vitaltype_uuid, kgentity_uuid, context_uuid)

            await conn.execute(f"""
                INSERT INTO {SPACE_ID}_rdf_quad (subject_uuid, predicate_uuid, object_uuid, context_uuid)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT DO NOTHING
            """, subj_uuid, has_name_uuid, name_uuid, context_uuid)

        logger.info("Loaded %d entities into space '%s'", len(entities), SPACE_ID)
        return True


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_to_jsonl(output_path: str):
    """Export test data and manifest as JSONL."""
    entities = generate_all_entities()
    manifest = generate_match_manifest()

    with open(output_path, "w") as f:
        # Entities
        for ent in entities:
            f.write(json.dumps({"type": "entity", **ent}) + "\n")
        # Match manifest
        for m in manifest:
            f.write(json.dumps({"type": "expected_match", **m}) + "\n")

    logger.info("Exported %d entities + %d expected matches to %s",
                len(entities), len(manifest), output_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    import argparse
    import asyncpg

    parser = argparse.ArgumentParser(description="Generate fuzzy test data")
    parser.add_argument("-o", "--output", default=None,
                        help="Output JSONL file path")
    parser.add_argument("--load", action="store_true",
                        help="Load data into PostgreSQL test space")
    parser.add_argument("--load-registry", action="store_true",
                        help="Load data via entity registry REST API")
    parser.add_argument("--base-url", default="http://localhost:8001",
                        help="VitalGraph server URL (for --load-registry)")
    parser.add_argument("--token", default=None,
                        help="Auth token (for --load-registry)")
    args = parser.parse_args()

    if args.output:
        export_to_jsonl(args.output)

    if args.load:
        db_host = os.environ.get("LOCAL_DB_HOST", "localhost")
        if db_host == "host.docker.internal":
            db_host = "localhost"
        db_port = os.environ.get("LOCAL_DB_PORT", "5432")
        db_name = os.environ.get("LOCAL_DB_NAME", "sparql_sql_graph")
        db_user = os.environ.get("LOCAL_DB_USERNAME", "postgres")
        db_pass = os.environ.get("LOCAL_DB_PASSWORD", "")

        db_url = f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
        logger.info("Connecting to %s", db_url.split("@")[1])

        pool = await asyncpg.create_pool(db_url, min_size=2, max_size=4)
        try:
            ok = await load_into_space(pool)
            if not ok:
                sys.exit(1)
        finally:
            await pool.close()

    if args.load_registry:
        api_key = args.token or os.environ.get("VITALGRAPH_API_KEY", "")
        if not api_key:
            logger.error("--token or VITALGRAPH_API_KEY env var required for --load-registry")
            sys.exit(1)
        ok = await load_via_entity_registry(api_key)
        if not ok:
            sys.exit(1)

    if not args.output and not args.load and not args.load_registry:
        entities = generate_all_entities()
        manifest = generate_match_manifest()
        logger.info("Fuzzy test dataset:")
        logger.info("  Canonical entities: %d", len(FUZZY_TEST_DATA))
        logger.info("  Total entities (with variants): %d", len(entities))
        logger.info("  Negative controls: %d", len(NEGATIVE_CONTROLS))
        logger.info("  Expected matches: %d", len(manifest))
        logger.info("")
        logger.info("Use --load to populate database, -o <file> to export, "
                    "or --load-registry to use REST API")


if __name__ == "__main__":
    asyncio.run(main())
