#!/usr/bin/env python3
"""
Query Production Fuseki for Slots Missing Values Due to Falsey Values Bug

Finds KGBooleanSlot, KGCurrencySlot, KGDoubleSlot, KGIntegerSlot, and KGLongSlot
objects that exist but are missing their corresponding value property — indicating
they were affected by the `if not term:` bug that dropped falsey values (false, 0, 0.0).

Usage:
    python query_missing_falsey_values.py [--dataset DATASET_NAME]

If --dataset is not specified, the script will list available datasets and query each one.
"""

import os
import sys
import logging
import argparse
import requests
from typing import Optional, Dict, Any, List
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.config.config_loader import get_config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Haley KG ontology prefix
HALEY_PREFIX = "http://vital.ai/ontology/haley-ai-kg#"
VITAL_PREFIX = "http://vital.ai/ontology/vital-core#"

# Slot types and their expected value properties
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


class FusekiMissingValuesQuery:
    """Query production Fuseki for slots missing values due to falsey values bug."""

    def __init__(self):
        """Initialize by loading configuration."""
        env_path = project_root / '.env'
        if not env_path.exists():
            raise FileNotFoundError(f"No .env file found at {env_path}")

        load_dotenv(env_path)
        config = get_config()
        fuseki_config = config.get_fuseki_config()
        keycloak_config = fuseki_config.get('keycloak', {})

        self.keycloak_url = keycloak_config.get('url')
        self.keycloak_realm = keycloak_config.get('realm')
        self.keycloak_client_id = keycloak_config.get('client_id')
        self.keycloak_client_secret = keycloak_config.get('client_secret')
        self.keycloak_username = keycloak_config.get('username')
        self.keycloak_password = keycloak_config.get('password')
        self.fuseki_url = fuseki_config.get('server_url')

        self.access_token: Optional[str] = None
        self.token_type: Optional[str] = None

    def get_jwt_token(self) -> bool:
        """Obtain JWT token from Keycloak."""
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
            response = requests.post(
                token_url,
                data=data,
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                timeout=10
            )
            if response.status_code == 200:
                token_data = response.json()
                self.access_token = token_data.get('access_token')
                self.token_type = token_data.get('token_type', 'Bearer')
                logger.info("Authenticated with Keycloak successfully")
                return True
            else:
                logger.error(f"Failed to obtain JWT token: {response.status_code} {response.text}")
                return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Error connecting to Keycloak: {e}")
            return False

    def _auth_headers(self) -> Dict[str, str]:
        return {
            'Authorization': f'{self.token_type} {self.access_token}',
            'Accept': 'application/sparql-results+json',
        }

    def list_datasets(self) -> List[str]:
        """List available Fuseki datasets."""
        datasets_url = f"{self.fuseki_url}/$/datasets"
        headers = {
            'Authorization': f'{self.token_type} {self.access_token}',
            'Accept': 'application/json',
        }
        try:
            response = requests.get(datasets_url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                datasets = [ds.get('ds.name', '') for ds in data.get('datasets', [])]
                return datasets
            else:
                logger.error(f"Failed to list datasets: {response.status_code}")
                return []
        except requests.exceptions.RequestException as e:
            logger.error(f"Error listing datasets: {e}")
            return []

    def execute_query(self, dataset: str, sparql: str, timeout: int = 60) -> Optional[List[Dict]]:
        """Execute a SPARQL query and return bindings."""
        query_url = f"{self.fuseki_url}{dataset}/query"
        try:
            response = requests.get(
                query_url,
                params={'query': sparql},
                headers=self._auth_headers(),
                timeout=timeout
            )
            if response.status_code == 200:
                results = response.json()
                return results.get('results', {}).get('bindings', [])
            else:
                logger.error(f"Query failed on {dataset}: {response.status_code} {response.text[:200]}")
                return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Error querying {dataset}: {e}")
            return None

    def count_slot_type(self, dataset: str, slot_type_uri: str) -> Optional[int]:
        """Count total instances of a slot type across all graphs."""
        sparql = f"""
        SELECT (COUNT(DISTINCT ?slot) AS ?total)
        WHERE {{
            GRAPH ?g {{
                ?slot a <{slot_type_uri}> .
            }}
        }}
        """
        bindings = self.execute_query(dataset, sparql)
        if bindings is not None and len(bindings) > 0:
            return int(bindings[0].get('total', {}).get('value', '0'))
        return None

    def find_slots_missing_value(self, dataset: str, slot_type_uri: str, value_prop_uri: str) -> Optional[List[Dict]]:
        """Find slots of a given type that are missing their value property."""
        sparql = f"""
        SELECT ?slot ?g ?name
        WHERE {{
            GRAPH ?g {{
                ?slot a <{slot_type_uri}> .
                OPTIONAL {{ ?slot <{VITAL_PREFIX}hasName> ?name }}
                FILTER NOT EXISTS {{ ?slot <{value_prop_uri}> ?val }}
            }}
        }}
        ORDER BY ?g ?slot
        """
        return self.execute_query(dataset, sparql, timeout=120)

    def query_dataset(self, dataset: str) -> Dict[str, Any]:
        """Query a single dataset for all slot types with missing values."""
        logger.info(f"\n{'='*80}")
        logger.info(f"Dataset: {dataset}")
        logger.info(f"{'='*80}")

        dataset_results = {}

        for slot_type_uri, info in SLOT_VALUE_PROPERTIES.items():
            label = info['label']
            value_prop = info['value_prop']
            falsey_vals = info['falsey_values']

            # Count total slots of this type
            total = self.count_slot_type(dataset, slot_type_uri)
            if total is None:
                logger.warning(f"  {label}: could not query")
                continue

            if total == 0:
                logger.info(f"  {label}: 0 instances (skipping)")
                continue

            # Find ones missing their value property
            missing = self.find_slots_missing_value(dataset, slot_type_uri, value_prop)
            if missing is None:
                logger.warning(f"  {label}: could not query for missing values")
                continue

            missing_count = len(missing)
            dataset_results[label] = {
                'total': total,
                'missing': missing_count,
                'affected_slots': missing,
                'falsey_values': falsey_vals,
            }

            if missing_count > 0:
                logger.info(f"  {label}: {missing_count}/{total} MISSING value property (likely had {falsey_vals})")
                # Show first few
                for slot in missing[:10]:
                    slot_uri = slot.get('slot', {}).get('value', '?')
                    slot_name = slot.get('name', {}).get('value', '(no name)')
                    graph = slot.get('g', {}).get('value', '?')
                    logger.info(f"    - {slot_uri}")
                    logger.info(f"      name: {slot_name}, graph: {graph}")
                if missing_count > 10:
                    logger.info(f"    ... and {missing_count - 10} more")
            else:
                logger.info(f"  {label}: {total} instances, all have values (OK)")

        return dataset_results

    def run(self, target_datasets: Optional[List[str]] = None):
        """Run the full missing values query."""
        if not self.get_jwt_token():
            return

        if target_datasets:
            datasets = target_datasets
        else:
            datasets = self.list_datasets()
            if not datasets:
                logger.error("No datasets found")
                return
            logger.info(f"Found {len(datasets)} dataset(s): {', '.join(datasets)}")

        all_results = {}
        for dataset in datasets:
            # Ensure dataset starts with /
            if not dataset.startswith('/'):
                dataset = f'/{dataset}'
            all_results[dataset] = self.query_dataset(dataset)

        # Summary
        logger.info(f"\n{'='*80}")
        logger.info("SUMMARY: Slots Missing Values (Falsey Values Bug)")
        logger.info(f"{'='*80}")

        total_affected = 0
        for dataset, results in all_results.items():
            has_issues = False
            for label, data in results.items():
                if data['missing'] > 0:
                    has_issues = True
                    total_affected += data['missing']
                    logger.info(f"  {dataset} / {label}: {data['missing']}/{data['total']} missing (falsey: {data['falsey_values']})")
            if not has_issues and results:
                logger.info(f"  {dataset}: all slot values present")

        if total_affected == 0:
            logger.info("\nNo affected slots found. Either the bug didn't affect this data or it has been re-ingested.")
        else:
            logger.info(f"\nTotal affected slots: {total_affected}")
            logger.info("These slots need to be re-ingested to restore their falsey values.")


def main():
    parser = argparse.ArgumentParser(description="Query production Fuseki for slots missing falsey values")
    parser.add_argument('--dataset', '-d', action='append', dest='datasets',
                        help="Dataset name to query (can specify multiple). If omitted, queries all datasets.")
    parser.add_argument('--profile', '-p', default='prod',
                        help="Config profile to use (default: prod). Sets VITALGRAPH_ENVIRONMENT.")
    args = parser.parse_args()

    # Set the profile so config loader reads the correct PROD_*/LOCAL_* env vars
    os.environ['VITALGRAPH_ENVIRONMENT'] = args.profile

    try:
        querier = FusekiMissingValuesQuery()
        querier.run(target_datasets=args.datasets)
    except Exception as e:
        logger.error(f"Failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
