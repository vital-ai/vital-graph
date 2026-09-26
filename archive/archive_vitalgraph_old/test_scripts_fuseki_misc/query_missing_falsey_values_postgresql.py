#!/usr/bin/env python3
"""
Cross-check Fuseki Falsey Values Bug Against PostgreSQL

1. Queries production Fuseki for slot URIs missing their value property (same as query_missing_falsey_values.py)
2. For each affected slot URI, checks production PostgreSQL to see if the value triple exists there

This determines whether the data was lost at the Fuseki write layer only,
or whether PostgreSQL is also missing the data.

Usage:
    python query_missing_falsey_values_postgresql.py [--dataset DATASET_NAME] [--profile prod] [--limit N]
"""

import os
import sys
import logging
import argparse
import requests
import psycopg
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.config.config_loader import get_config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

HALEY_PREFIX = "http://vital.ai/ontology/haley-ai-kg#"
VITAL_PREFIX = "http://vital.ai/ontology/vital-core#"

# Slot types and their value properties
SLOT_VALUE_PROPERTIES = {
    f"{HALEY_PREFIX}KGBooleanSlot": {
        "value_prop": f"{HALEY_PREFIX}hasBooleanSlotValue",
        "label": "KGBooleanSlot",
        "falsey_values": "false",
    },
    f"{HALEY_PREFIX}KGCurrencySlot": {
        "value_prop": f"{HALEY_PREFIX}hasCurrencySlotValue",
        "label": "KGCurrencySlot",
        "falsey_values": "0.0",
    },
    f"{HALEY_PREFIX}KGDoubleSlot": {
        "value_prop": f"{HALEY_PREFIX}hasDoubleSlotValue",
        "label": "KGDoubleSlot",
        "falsey_values": "0.0",
    },
    f"{HALEY_PREFIX}KGIntegerSlot": {
        "value_prop": f"{HALEY_PREFIX}hasIntegerSlotValue",
        "label": "KGIntegerSlot",
        "falsey_values": "0",
    },
    f"{HALEY_PREFIX}KGLongSlot": {
        "value_prop": f"{HALEY_PREFIX}hasLongSlotValue",
        "label": "KGLongSlot",
        "falsey_values": "0",
    },
}

# Fuseki dataset name -> PostgreSQL space_id mapping
# Fuseki datasets are named: vitalgraph_space_{space_id}
# PostgreSQL tables are: {space_id}_term, {space_id}_rdf_quad
def fuseki_dataset_to_space_id(dataset_name: str) -> str:
    """Convert Fuseki dataset name to PostgreSQL space_id."""
    # Remove leading slash
    name = dataset_name.lstrip('/')
    # Remove vitalgraph_space_ prefix
    prefix = "vitalgraph_space_"
    if name.startswith(prefix):
        return name[len(prefix):]
    return name


class FusekiPostgreSQLCrossCheck:
    """Cross-check missing Fuseki values against PostgreSQL."""

    def __init__(self):
        env_path = project_root / '.env'
        if not env_path.exists():
            raise FileNotFoundError(f"No .env file found at {env_path}")
        load_dotenv(env_path)

        config = get_config()

        # Fuseki config (for JWT + SPARQL queries)
        fuseki_config = config.get_fuseki_config()
        keycloak_config = fuseki_config.get('keycloak', {})
        self.keycloak_url = keycloak_config.get('url')
        self.keycloak_realm = keycloak_config.get('realm')
        self.keycloak_client_id = keycloak_config.get('client_id')
        self.keycloak_client_secret = keycloak_config.get('client_secret')
        self.keycloak_username = keycloak_config.get('username')
        self.keycloak_password = keycloak_config.get('password')
        self.fuseki_url = fuseki_config.get('server_url')

        # PostgreSQL config
        db_config = config.get_database_config()
        self.pg_host = db_config.get('host', 'localhost')
        self.pg_port = int(db_config.get('port', 5432))
        self.pg_database = db_config.get('database', 'vitalgraphdb_fuseki')
        self.pg_username = db_config.get('username', 'postgres')
        self.pg_password = db_config.get('password', '')

        self.access_token: Optional[str] = None
        self.token_type: Optional[str] = None
        self.pg_conn = None

    # ── Fuseki auth ──────────────────────────────────────────────

    def get_jwt_token(self) -> bool:
        token_url = f"{self.keycloak_url}/realms/{self.keycloak_realm}/protocol/openid-connect/token"
        data = {
            'grant_type': 'password',
            'client_id': self.keycloak_client_id,
            'username': self.keycloak_username,
            'password': self.keycloak_password,
        }
        if self.keycloak_client_secret:
            data['client_secret'] = self.keycloak_client_secret
        try:
            resp = requests.post(token_url, data=data,
                                 headers={'Content-Type': 'application/x-www-form-urlencoded'}, timeout=10)
            if resp.status_code == 200:
                token_data = resp.json()
                self.access_token = token_data.get('access_token')
                self.token_type = token_data.get('token_type', 'Bearer')
                logger.info("Authenticated with Keycloak")
                return True
            else:
                logger.error(f"Keycloak auth failed: {resp.status_code}")
                return False
        except Exception as e:
            logger.error(f"Keycloak error: {e}")
            return False

    def _auth_headers(self) -> Dict[str, str]:
        return {
            'Authorization': f'{self.token_type} {self.access_token}',
            'Accept': 'application/sparql-results+json',
        }

    # ── Fuseki queries ───────────────────────────────────────────

    def fuseki_query(self, dataset: str, sparql: str, timeout: int = 120) -> Optional[List[Dict]]:
        query_url = f"{self.fuseki_url}{dataset}/query"
        try:
            resp = requests.get(query_url, params={'query': sparql},
                                headers=self._auth_headers(), timeout=timeout)
            if resp.status_code == 200:
                return resp.json().get('results', {}).get('bindings', [])
            else:
                logger.error(f"Fuseki query failed on {dataset}: {resp.status_code}")
                return None
        except Exception as e:
            logger.error(f"Fuseki query error: {e}")
            return None

    def get_missing_slot_uris(self, dataset: str, slot_type_uri: str,
                              value_prop_uri: str, limit: int = 0) -> Optional[List[str]]:
        """Get slot URIs that are missing their value property in Fuseki."""
        limit_clause = f"LIMIT {limit}" if limit > 0 else ""
        sparql = f"""
        SELECT ?slot
        WHERE {{
            GRAPH ?g {{
                ?slot a <{slot_type_uri}> .
                FILTER NOT EXISTS {{ ?slot <{value_prop_uri}> ?val }}
            }}
        }}
        ORDER BY ?slot
        {limit_clause}
        """
        bindings = self.fuseki_query(dataset, sparql)
        if bindings is None:
            return None
        return [b.get('slot', {}).get('value') for b in bindings if b.get('slot', {}).get('value')]

    # ── PostgreSQL queries ───────────────────────────────────────

    def connect_postgresql(self) -> bool:
        try:
            logger.info(f"Connecting to PostgreSQL: {self.pg_host}:{self.pg_port}/{self.pg_database}")
            self.pg_conn = psycopg.connect(
                host=self.pg_host,
                port=self.pg_port,
                dbname=self.pg_database,
                user=self.pg_username,
                password=self.pg_password,
                connect_timeout=10,
            )
            self.pg_conn.autocommit = True
            logger.info("Connected to PostgreSQL")
            return True
        except Exception as e:
            logger.error(f"PostgreSQL connection failed: {e}")
            return False

    def pg_table_exists(self, table_name: str) -> bool:
        cur = self.pg_conn.cursor()
        cur.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = %s
            )
        """, (table_name,))
        return cur.fetchone()[0]

    def pg_check_value_triples(self, space_id: str, slot_uris: List[str],
                               value_prop_uri: str) -> Dict[str, Optional[str]]:
        """
        For each slot URI, check if a quad exists in PostgreSQL with that subject
        and the given value property as predicate.

        Returns dict: slot_uri -> value_text (or None if missing).
        """
        term_table = f"{space_id}_term"
        quad_table = f"{space_id}_rdf_quad"

        if not self.pg_table_exists(term_table):
            logger.warning(f"Table {term_table} does not exist — skipping")
            return {uri: None for uri in slot_uris}

        cur = self.pg_conn.cursor()
        results = {}

        # Process in batches to avoid huge IN clauses
        batch_size = 200
        for i in range(0, len(slot_uris), batch_size):
            batch = slot_uris[i:i + batch_size]

            # Build parameterized query:
            # Join term table for subject (slot URI), predicate (value prop), and object (the value)
            placeholders = ','.join(['%s'] * len(batch))
            query = f"""
                SELECT
                    s_term.term_text AS slot_uri,
                    o_term.term_text AS value_text,
                    o_term.term_type AS value_type
                FROM {quad_table} q
                JOIN {term_table} s_term ON s_term.term_uuid = q.subject_uuid
                JOIN {term_table} p_term ON p_term.term_uuid = q.predicate_uuid
                JOIN {term_table} o_term ON o_term.term_uuid = q.object_uuid
                WHERE s_term.term_text IN ({placeholders})
                  AND p_term.term_text = %s
            """
            params = batch + [value_prop_uri]
            cur.execute(query, params)
            rows = cur.fetchall()

            found = {}
            for slot_uri, value_text, value_type in rows:
                found[slot_uri] = value_text

            for uri in batch:
                results[uri] = found.get(uri)

        return results

    # ── Main logic ───────────────────────────────────────────────

    def run(self, target_datasets: Optional[List[str]] = None, limit: int = 0):
        if not self.get_jwt_token():
            return
        if not self.connect_postgresql():
            return

        # Discover datasets if not specified
        if target_datasets:
            datasets = target_datasets
        else:
            headers = {
                'Authorization': f'{self.token_type} {self.access_token}',
                'Accept': 'application/json',
            }
            resp = requests.get(f"{self.fuseki_url}/$/datasets", headers=headers, timeout=10)
            if resp.status_code != 200:
                logger.error("Failed to list datasets")
                return
            datasets = [ds.get('ds.name', '') for ds in resp.json().get('datasets', [])]
            logger.info(f"Found {len(datasets)} datasets")

        grand_total_fuseki_missing = 0
        grand_total_pg_has = 0
        grand_total_pg_missing = 0

        summary_rows: List[Tuple[str, str, int, int, int]] = []

        for dataset in datasets:
            if not dataset.startswith('/'):
                dataset = f'/{dataset}'

            space_id = fuseki_dataset_to_space_id(dataset)
            term_table = f"{space_id}_term"

            if not self.pg_table_exists(term_table):
                continue  # skip datasets with no PostgreSQL tables

            logger.info(f"\n{'='*80}")
            logger.info(f"Dataset: {dataset}  (pg space: {space_id})")
            logger.info(f"{'='*80}")

            for slot_type_uri, info in SLOT_VALUE_PROPERTIES.items():
                label = info['label']
                value_prop = info['value_prop']

                # Step 1: Get slot URIs missing from Fuseki
                missing_uris = self.get_missing_slot_uris(dataset, slot_type_uri, value_prop, limit=limit)
                if missing_uris is None:
                    logger.warning(f"  {label}: Fuseki query failed")
                    continue
                if len(missing_uris) == 0:
                    continue

                fuseki_missing = len(missing_uris)
                logger.info(f"  {label}: {fuseki_missing} slots missing value in Fuseki")

                # Step 2: Check those same URIs in PostgreSQL
                pg_results = self.pg_check_value_triples(space_id, missing_uris, value_prop)

                pg_has_value = sum(1 for v in pg_results.values() if v is not None)
                pg_missing = sum(1 for v in pg_results.values() if v is None)

                grand_total_fuseki_missing += fuseki_missing
                grand_total_pg_has += pg_has_value
                grand_total_pg_missing += pg_missing

                summary_rows.append((dataset, label, fuseki_missing, pg_has_value, pg_missing))

                if pg_has_value > 0:
                    logger.info(f"    PostgreSQL HAS value:     {pg_has_value}/{fuseki_missing}")
                    # Show a few examples
                    shown = 0
                    for uri, val in pg_results.items():
                        if val is not None and shown < 5:
                            logger.info(f"      {uri}  ->  {val}")
                            shown += 1
                if pg_missing > 0:
                    logger.info(f"    PostgreSQL ALSO MISSING:  {pg_missing}/{fuseki_missing}")
                    shown = 0
                    for uri, val in pg_results.items():
                        if val is None and shown < 5:
                            logger.info(f"      {uri}  ->  (no value)")
                            shown += 1

        # ── Summary ──────────────────────────────────────────────
        logger.info(f"\n{'='*80}")
        logger.info("CROSS-CHECK SUMMARY")
        logger.info(f"{'='*80}")
        logger.info(f"{'Dataset':<50} {'Slot Type':<20} {'Fuseki Missing':>15} {'PG Has':>10} {'PG Missing':>12}")
        logger.info("-" * 110)
        for dataset, label, f_miss, pg_has, pg_miss in summary_rows:
            logger.info(f"{dataset:<50} {label:<20} {f_miss:>15} {pg_has:>10} {pg_miss:>12}")
        logger.info("-" * 110)
        logger.info(f"{'TOTAL':<72} {grand_total_fuseki_missing:>15} {grand_total_pg_has:>10} {grand_total_pg_missing:>12}")

        logger.info("")
        if grand_total_pg_has > 0 and grand_total_pg_missing == 0:
            logger.info("CONCLUSION: Data EXISTS in PostgreSQL but is MISSING from Fuseki.")
            logger.info("The bug dropped values only at the Fuseki write layer.")
            logger.info("Re-sync from PostgreSQL to Fuseki can restore the data.")
        elif grand_total_pg_missing > 0 and grand_total_pg_has == 0:
            logger.info("CONCLUSION: Data is MISSING from BOTH Fuseki and PostgreSQL.")
            logger.info("The bug affected both write paths. Full re-ingestion required.")
        elif grand_total_pg_has > 0 and grand_total_pg_missing > 0:
            logger.info("CONCLUSION: MIXED — some data exists in PostgreSQL, some is missing from both.")
            logger.info("Partial re-sync possible; remaining slots need full re-ingestion.")
        else:
            logger.info("No affected slots found.")

        if self.pg_conn:
            self.pg_conn.close()


def main():
    parser = argparse.ArgumentParser(description="Cross-check missing Fuseki slot values against PostgreSQL")
    parser.add_argument('--dataset', '-d', action='append', dest='datasets',
                        help="Dataset name to query (can specify multiple). If omitted, queries all.")
    parser.add_argument('--profile', '-p', default='prod',
                        help="Config profile (default: prod)")
    parser.add_argument('--limit', '-l', type=int, default=0,
                        help="Max slot URIs to check per slot type per dataset (0 = all)")
    args = parser.parse_args()

    os.environ['VITALGRAPH_ENVIRONMENT'] = args.profile

    try:
        checker = FusekiPostgreSQLCrossCheck()
        checker.run(target_datasets=args.datasets, limit=args.limit)
    except Exception as e:
        logger.error(f"Failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
