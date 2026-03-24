"""
Shared async database connection helper for prod_db test scripts.

Reads PROD_RDS_* variables from the project .env file and provides
an asyncpg-based connection pool identical to the sparql_sql backend.

Usage:
    from db_connect import get_prod_db_impl, get_prod_connection_params

    async def main():
        db_impl = await get_prod_db_impl()
        async with db_impl.connection_pool.acquire() as conn:
            row = await conn.fetchval("SELECT version()")
            print(row)
        await db_impl.disconnect()
"""

import os
import sys
from pathlib import Path

# Project root (two levels up from test_scripts/prod_db/)
PROJECT_ROOT = Path(__file__).parent.parent.parent

# Ensure project root is on sys.path for vitalgraph imports
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from vitalgraph.db.sparql_sql.sparql_sql_db_impl import SparqlSQLDbImpl


def _load_env() -> dict:
    """Load PROD_RDS_* variables from the project .env file."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return {}

    values = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        # Strip surrounding quotes
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        values[key] = val
    return values


def get_prod_connection_params() -> dict:
    """Return asyncpg-compatible connection parameters for the production RDS.

    Keys match what SparqlSQLDbImpl expects: host, port, database, username, password.
    """
    env = _load_env()
    return {
        "host": env.get("PROD_RDS_HOST", "localhost"),
        "port": int(env.get("PROD_RDS_PORT", "5432")),
        "database": env.get("PROD_RDS_DBNAME", "vitalgraphdb"),
        "username": env.get("PROD_RDS_USERNAME", "postgres"),
        "password": env.get("PROD_RDS_PASSWORD", ""),
    }


async def get_prod_db_impl() -> SparqlSQLDbImpl:
    """Create and connect a SparqlSQLDbImpl pointed at the production RDS.

    The caller is responsible for calling ``await db_impl.disconnect()``
    when finished.
    """
    params = get_prod_connection_params()
    db_impl = SparqlSQLDbImpl(params)
    connected = await db_impl.connect()
    if not connected:
        raise RuntimeError(
            f"Failed to connect to production RDS at {params['host']}:{params['port']}"
        )
    return db_impl


def print_connection_info():
    """Print connection target (without password) for verification."""
    params = get_prod_connection_params()
    print(f"  Host:     {params['host']}")
    print(f"  Port:     {params['port']}")
    print(f"  Database: {params['database']}")
    print(f"  User:     {params['username']}")
