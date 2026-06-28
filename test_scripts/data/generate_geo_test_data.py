#!/usr/bin/env python3
"""
Generate geo test data for end-to-end testing of geo search systems.

Creates ~50 KGEntity objects representing well-known landmarks and locations
with precise coordinates, suitable for validating:
  - vg:geoDistance SPARQL function (distance computation)
  - vg:withinRadius SPARQL function (radius filtering)
  - Geo REST API proximity queries
  - Geo client integration tests

Output: JSON lines file with entity data + coordinates.

Usage:
    python test_scripts/data/generate_geo_test_data.py
"""

import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("generate_geo_test_data")

# ---------------------------------------------------------------------------
# Test data: Landmarks with known coordinates
# ---------------------------------------------------------------------------

# Major cities (global spread)
MAJOR_CITIES = [
    {"name": "New York City", "lat": 40.7128, "lon": -74.0060, "category": "city", "description": "Major US city and financial center"},
    {"name": "London", "lat": 51.5074, "lon": -0.1278, "category": "city", "description": "Capital of the United Kingdom"},
    {"name": "Tokyo", "lat": 35.6762, "lon": 139.6503, "category": "city", "description": "Capital of Japan"},
    {"name": "Paris", "lat": 48.8566, "lon": 2.3522, "category": "city", "description": "Capital of France"},
    {"name": "Sydney", "lat": -33.8688, "lon": 151.2093, "category": "city", "description": "Major Australian city"},
    {"name": "São Paulo", "lat": -23.5505, "lon": -46.6333, "category": "city", "description": "Largest city in Brazil"},
    {"name": "Dubai", "lat": 25.2048, "lon": 55.2708, "category": "city", "description": "Major city in the United Arab Emirates"},
    {"name": "Toronto", "lat": 43.6532, "lon": -79.3832, "category": "city", "description": "Largest city in Canada"},
    {"name": "Berlin", "lat": 52.5200, "lon": 13.4050, "category": "city", "description": "Capital of Germany"},
    {"name": "Singapore", "lat": 1.3521, "lon": 103.8198, "category": "city", "description": "City-state in Southeast Asia"},
]

# NYC area landmarks (for radius testing)
NYC_AREA = [
    {"name": "Times Square", "lat": 40.7580, "lon": -73.9855, "category": "landmark", "description": "Famous commercial intersection in Midtown Manhattan"},
    {"name": "Empire State Building", "lat": 40.7484, "lon": -73.9857, "category": "landmark", "description": "Iconic 102-story Art Deco skyscraper in Manhattan"},
    {"name": "Central Park", "lat": 40.7829, "lon": -73.9654, "category": "park", "description": "Urban park in Manhattan spanning 843 acres"},
    {"name": "Brooklyn Bridge", "lat": 40.7061, "lon": -73.9969, "category": "landmark", "description": "Hybrid cable-stayed suspension bridge connecting Manhattan and Brooklyn"},
    {"name": "Statue of Liberty", "lat": 40.6892, "lon": -74.0445, "category": "landmark", "description": "Colossal neoclassical sculpture on Liberty Island"},
    {"name": "JFK Airport", "lat": 40.6413, "lon": -73.7781, "category": "airport", "description": "Major international airport in Queens, New York"},
    {"name": "LaGuardia Airport", "lat": 40.7769, "lon": -73.8740, "category": "airport", "description": "Airport in northern Queens serving domestic flights"},
    {"name": "Newark Airport", "lat": 40.6895, "lon": -74.1745, "category": "airport", "description": "Major airport in Newark, New Jersey"},
    {"name": "Yankee Stadium", "lat": 40.8296, "lon": -73.9262, "category": "stadium", "description": "Baseball stadium in the Bronx"},
    {"name": "Wall Street", "lat": 40.7060, "lon": -74.0088, "category": "district", "description": "Financial district in Lower Manhattan"},
    {"name": "Columbia University", "lat": 40.8075, "lon": -73.9626, "category": "university", "description": "Ivy League university in Morningside Heights"},
    {"name": "Coney Island", "lat": 40.5749, "lon": -73.9794, "category": "neighborhood", "description": "Amusement area and beach in southern Brooklyn"},
    {"name": "Hoboken NJ", "lat": 40.7440, "lon": -74.0324, "category": "city", "description": "City in New Jersey across the Hudson from Manhattan"},
    {"name": "White Plains NY", "lat": 41.0340, "lon": -73.7629, "category": "city", "description": "City in Westchester County north of NYC"},
    {"name": "Stamford CT", "lat": 41.0534, "lon": -73.5387, "category": "city", "description": "City in Connecticut northeast of NYC"},
]

# London area landmarks
LONDON_AREA = [
    {"name": "Tower Bridge London", "lat": 51.5055, "lon": -0.0754, "category": "landmark", "description": "Combined bascule and suspension bridge over the Thames"},
    {"name": "Westminster Abbey", "lat": 51.4993, "lon": -0.1273, "category": "landmark", "description": "Gothic abbey church west of the Palace of Westminster"},
    {"name": "Heathrow Airport", "lat": 51.4700, "lon": -0.4543, "category": "airport", "description": "Major international airport west of London"},
    {"name": "Greenwich Observatory", "lat": 51.4769, "lon": -0.0005, "category": "landmark", "description": "Royal Observatory at the Prime Meridian"},
    {"name": "Canary Wharf", "lat": 51.5054, "lon": -0.0235, "category": "district", "description": "Major business district on the Isle of Dogs"},
    {"name": "Camden Market", "lat": 51.5414, "lon": -0.1426, "category": "district", "description": "Famous market area in North London"},
    {"name": "Wimbledon", "lat": 51.4340, "lon": -0.2141, "category": "district", "description": "District famous for tennis championships"},
    {"name": "Wembley Stadium", "lat": 51.5560, "lon": -0.2795, "category": "stadium", "description": "National stadium in northwest London"},
    {"name": "Hampton Court Palace", "lat": 51.4036, "lon": -0.3378, "category": "landmark", "description": "Royal palace in Richmond upon Thames"},
    {"name": "Gatwick Airport", "lat": 51.1537, "lon": -0.1821, "category": "airport", "description": "Major airport south of London"},
]

# Tokyo area landmarks
TOKYO_AREA = [
    {"name": "Imperial Palace Tokyo", "lat": 35.6852, "lon": 139.7528, "category": "landmark", "description": "Primary residence of the Emperor of Japan"},
    {"name": "Ginza", "lat": 35.6717, "lon": 139.7649, "category": "district", "description": "Upscale shopping and entertainment district"},
    {"name": "Akihabara", "lat": 35.7023, "lon": 139.7745, "category": "district", "description": "Electronics and anime district in Tokyo"},
    {"name": "Shinjuku Station", "lat": 35.6896, "lon": 139.7006, "category": "station", "description": "Busiest railway station in the world"},
    {"name": "Shibuya Crossing", "lat": 35.6595, "lon": 139.7004, "category": "landmark", "description": "Famous pedestrian scramble intersection"},
    {"name": "Senso-ji Asakusa", "lat": 35.7148, "lon": 139.7967, "category": "temple", "description": "Ancient Buddhist temple in Asakusa"},
    {"name": "Odaiba", "lat": 35.6265, "lon": 139.7755, "category": "district", "description": "Artificial island in Tokyo Bay"},
    {"name": "Narita Airport", "lat": 35.7720, "lon": 140.3929, "category": "airport", "description": "Major international airport east of Tokyo"},
    {"name": "Yokohama", "lat": 35.4437, "lon": 139.6380, "category": "city", "description": "Port city south of Tokyo"},
    {"name": "Kamakura", "lat": 35.3192, "lon": 139.5467, "category": "city", "description": "Coastal city with historic temples south of Tokyo"},
]

ALL_LOCATIONS = MAJOR_CITIES + NYC_AREA + LONDON_AREA + TOKYO_AREA

# ---------------------------------------------------------------------------
# Known distances for validation (approximate, in km)
# ---------------------------------------------------------------------------

KNOWN_DISTANCES_KM = {
    ("Times Square", "Empire State Building"): 1.1,
    ("Times Square", "Central Park"): 2.8,
    ("Times Square", "JFK Airport"): 19.2,
    ("Times Square", "LaGuardia Airport"): 10.3,
    ("Times Square", "Newark Airport"): 16.5,
    ("Times Square", "White Plains NY"): 35.0,
    ("Times Square", "Stamford CT"): 50.0,
    ("Tower Bridge London", "Westminster Abbey"): 3.5,
    ("Tower Bridge London", "Heathrow Airport"): 28.0,
    ("Tower Bridge London", "Gatwick Airport"): 39.0,
    ("Imperial Palace Tokyo", "Narita Airport"): 60.0,
    ("Imperial Palace Tokyo", "Yokohama"): 28.0,
    ("New York City", "London"): 5570.0,
    ("New York City", "Tokyo"): 10850.0,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

URL_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def uri_for_location(name: str) -> str:
    """Generate a deterministic URI for a location."""
    slug = name.lower().replace(" ", "_").replace(",", "")
    return f"http://vital.ai/test/geo/{slug}"


def uuid_for_uri(uri: str) -> uuid.UUID:
    return uuid.uuid5(URL_NS, uri)


# ---------------------------------------------------------------------------
# Data generation
# ---------------------------------------------------------------------------

SPACE_ID = "sp_geo_test"
GRAPH_URI = "urn:vitalgraph:geo_test:entities"
INDEX_NAME = "geo_entity_default"
DIMENSIONS = 384  # Standard MiniLM embedding size


async def setup_geo_test_space(pool):
    """Create the geo test space and populate with test entities."""
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema

    schema = SparqlSQLSchema()
    context_uuid = uuid_for_uri(GRAPH_URI)

    async with pool.acquire() as conn:
        # Check extensions
        for ext in ("vector", "postgis", "pg_trgm"):
            check = await conn.fetchval(
                "SELECT COUNT(*) FROM pg_extension WHERE extname = $1", ext
            )
            if check == 0:
                logger.error("Extension '%s' not installed!", ext)
                return False

        # Drop old test space
        drop_stmts = schema.drop_space_tables_sql(SPACE_ID)
        for stmt in drop_stmts:
            try:
                await conn.execute(stmt)
            except Exception:
                pass

        vec_table = schema.vec_table_name(SPACE_ID, INDEX_NAME)
        await conn.execute(f"DROP TABLE IF EXISTS {vec_table} CASCADE")

        # Create space
        create_stmts = schema.create_space_tables_sql(SPACE_ID)
        for stmt in create_stmts:
            await conn.execute(stmt)
        index_stmts = schema.create_space_indexes_sql(SPACE_ID)
        for stmt in index_stmts:
            await conn.execute(stmt)

        # Create vector table
        vec_stmts = schema.create_vector_data_table_sql(
            SPACE_ID, INDEX_NAME, DIMENSIONS, "cosine"
        )
        for stmt in vec_stmts:
            await conn.execute(stmt)

        # Register vector index
        await conn.execute(f"""
            INSERT INTO {SPACE_ID}_vector_index (index_name, dimensions, distance_metric, provider, provider_config)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (index_name) DO NOTHING
        """, INDEX_NAME, DIMENSIONS, "cosine", "vitalsigns_onnx", json.dumps({}))

        # Insert context
        await conn.execute(f"""
            INSERT INTO {SPACE_ID}_term (term_uuid, term_text, term_type)
            VALUES ($1, $2, 'U')
            ON CONFLICT DO NOTHING
        """, context_uuid, GRAPH_URI)

        # Predicate terms
        predicates = {
            "rdf_type": "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
            "vitaltype": "http://vital.ai/ontology/vital-core#vitaltype",
            "has_name": "http://vital.ai/ontology/vital-core#hasName",
            "has_description": "http://vital.ai/ontology/vital-core#hasKGraphDescription",
        }
        pred_uuids = {}
        for key, uri in predicates.items():
            u = uuid_for_uri(uri)
            pred_uuids[key] = u
            await conn.execute(f"""
                INSERT INTO {SPACE_ID}_term (term_uuid, term_text, term_type)
                VALUES ($1, $2, 'U')
                ON CONFLICT DO NOTHING
            """, u, uri)

        # KGEntity type
        kgentity_type = "http://vital.ai/ontology/haley-ai-kg#KGEntity"
        kgentity_uuid = uuid_for_uri(kgentity_type)
        await conn.execute(f"""
            INSERT INTO {SPACE_ID}_term (term_uuid, term_text, term_type)
            VALUES ($1, $2, 'U')
            ON CONFLICT DO NOTHING
        """, kgentity_uuid, kgentity_type)

        # Ensure geo datatype is seeded
        geo_datatype_uri = "http://vital.ai/ontology/vital-core#geoLocation"
        geo_dt_id = await conn.fetchval(f"""
            INSERT INTO {SPACE_ID}_datatype (datatype_uri, datatype_name)
            VALUES ($1, 'geoLocation')
            ON CONFLICT (datatype_uri) DO UPDATE SET datatype_name = 'geoLocation'
            RETURNING datatype_id
        """, geo_datatype_uri)

        # Also seed OGC wktLiteral datatype
        wkt_datatype_uri = "http://www.opengis.net/ont/geosparql#wktLiteral"
        await conn.execute(f"""
            INSERT INTO {SPACE_ID}_datatype (datatype_uri, datatype_name)
            VALUES ($1, 'wktLiteral')
            ON CONFLICT (datatype_uri) DO NOTHING
        """, wkt_datatype_uri)

        # Geo predicate
        geo_pred_uri = "http://vital.ai/ontology/haley-ai-kg#hasGeoLocationSlotValue"
        geo_pred_uuid = uuid_for_uri(geo_pred_uri)
        await conn.execute(f"""
            INSERT INTO {SPACE_ID}_term (term_uuid, term_text, term_type)
            VALUES ($1, $2, 'U')
            ON CONFLICT DO NOTHING
        """, geo_pred_uuid, geo_pred_uri)

        # Insert all locations
        for loc in ALL_LOCATIONS:
            uri = uri_for_location(loc["name"])
            subj_uuid = uuid_for_uri(uri)

            # Subject term
            await conn.execute(f"""
                INSERT INTO {SPACE_ID}_term (term_uuid, term_text, term_type)
                VALUES ($1, $2, 'U')
                ON CONFLICT DO NOTHING
            """, subj_uuid, uri)

            # Name literal
            name_uuid = uuid_for_uri(f"{uri}#name#{loc['name']}")
            await conn.execute(f"""
                INSERT INTO {SPACE_ID}_term (term_uuid, term_text, term_type)
                VALUES ($1, $2, 'L')
                ON CONFLICT DO NOTHING
            """, name_uuid, loc["name"])

            # Description literal
            desc_uuid = uuid_for_uri(f"{uri}#desc#{loc['description']}")
            await conn.execute(f"""
                INSERT INTO {SPACE_ID}_term (term_uuid, term_text, term_type)
                VALUES ($1, $2, 'L')
                ON CONFLICT DO NOTHING
            """, desc_uuid, loc["description"])

            # Geo WKT literal (POINT(lon lat) format with geoLocation datatype)
            wkt_value = f"POINT({loc['lon']} {loc['lat']})"
            geo_lit_uuid = uuid_for_uri(f"{uri}#geo#{wkt_value}")
            await conn.execute(f"""
                INSERT INTO {SPACE_ID}_term (term_uuid, term_text, term_type, datatype_id)
                VALUES ($1, $2, 'L', $3)
                ON CONFLICT DO NOTHING
            """, geo_lit_uuid, wkt_value, geo_dt_id)

            # Quads: type, name, description, geo
            await conn.execute(f"""
                INSERT INTO {SPACE_ID}_rdf_quad (subject_uuid, predicate_uuid, object_uuid, context_uuid)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT DO NOTHING
            """, subj_uuid, pred_uuids["vitaltype"], kgentity_uuid, context_uuid)

            await conn.execute(f"""
                INSERT INTO {SPACE_ID}_rdf_quad (subject_uuid, predicate_uuid, object_uuid, context_uuid)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT DO NOTHING
            """, subj_uuid, pred_uuids["has_name"], name_uuid, context_uuid)

            await conn.execute(f"""
                INSERT INTO {SPACE_ID}_rdf_quad (subject_uuid, predicate_uuid, object_uuid, context_uuid)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT DO NOTHING
            """, subj_uuid, pred_uuids["has_description"], desc_uuid, context_uuid)

            # Geo quad (geo-typed literal as object)
            await conn.execute(f"""
                INSERT INTO {SPACE_ID}_rdf_quad (subject_uuid, predicate_uuid, object_uuid, context_uuid)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT DO NOTHING
            """, subj_uuid, geo_pred_uuid, geo_lit_uuid, context_uuid)

            # Direct geo table insert (also populate for backward compat)
            await conn.execute(f"""
                INSERT INTO {SPACE_ID}_geo (subject_uuid, predicate_uuid, latitude, longitude, location, context_uuid)
                VALUES ($1, $2, $3, $4, ST_SetSRID(ST_GeomFromText($5), 4326)::geography, $6)
                ON CONFLICT (subject_uuid, context_uuid)
                DO UPDATE SET latitude = $3, longitude = $4,
                             location = ST_SetSRID(ST_GeomFromText($5), 4326)::geography
            """, subj_uuid, geo_pred_uuid, loc["lat"], loc["lon"], wkt_value, context_uuid)

        logger.info("Setup complete: %d geo entities loaded into space '%s'",
                    len(ALL_LOCATIONS), SPACE_ID)
        return True


def export_to_jsonl(output_path: str):
    """Export test data as JSON lines for reference."""
    with open(output_path, "w") as f:
        for loc in ALL_LOCATIONS:
            entry = {
                "uri": uri_for_location(loc["name"]),
                "name": loc["name"],
                "latitude": loc["lat"],
                "longitude": loc["lon"],
                "category": loc["category"],
                "description": loc["description"],
            }
            f.write(json.dumps(entry) + "\n")
    logger.info("Exported %d entries to %s", len(ALL_LOCATIONS), output_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    import argparse
    import asyncpg

    parser = argparse.ArgumentParser(description="Generate geo test data")
    parser.add_argument("-o", "--output", default=None,
                        help="Output JSONL file path (optional export)")
    parser.add_argument("--load", action="store_true",
                        help="Load data into PostgreSQL test space")
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
            ok = await setup_geo_test_space(pool)
            if not ok:
                sys.exit(1)
        finally:
            await pool.close()

    if not args.output and not args.load:
        # Just print summary
        logger.info("Geo test dataset: %d locations", len(ALL_LOCATIONS))
        logger.info("  Major cities: %d", len(MAJOR_CITIES))
        logger.info("  NYC area: %d", len(NYC_AREA))
        logger.info("  London area: %d", len(LONDON_AREA))
        logger.info("  Tokyo area: %d", len(TOKYO_AREA))
        logger.info("")
        logger.info("Use --load to populate database, or -o <file> to export JSONL")


if __name__ == "__main__":
    asyncio.run(main())
