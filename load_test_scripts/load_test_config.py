"""Load-test configuration — resolves the target VitalGraph service + credentials.

Selected by LOAD_TEST_ENV (local|test|prod). Values come from env vars so no
secrets live in the repo; defaults target the local dev service (:8001) with the
default admin/admin login.
"""

import os

_ENVS = {
    "local": {
        "url": os.environ.get("LOAD_TEST_LOCAL_VITALGRAPH_URL", "http://localhost:8001"),
        "username": os.environ.get("LOAD_TEST_LOCAL_VITALGRAPH_USERNAME", "admin"),
        "password": os.environ.get("LOAD_TEST_LOCAL_VITALGRAPH_PASSWORD", "admin"),
        "writes_enabled": True,
    },
    "test": {
        "url": os.environ.get("LOAD_TEST_TEST_VITALGRAPH_URL", "http://localhost:8002"),
        "username": os.environ.get("LOAD_TEST_TEST_VITALGRAPH_USERNAME", "admin"),
        "password": os.environ.get("LOAD_TEST_TEST_VITALGRAPH_PASSWORD", "admin"),
        "writes_enabled": True,
    },
    "prod": {
        "url": os.environ.get("LOAD_TEST_PROD_VITALGRAPH_URL", ""),
        "username": os.environ.get("LOAD_TEST_PROD_VITALGRAPH_USERNAME", "admin"),
        "password": os.environ.get("LOAD_TEST_PROD_VITALGRAPH_PASSWORD", ""),
        "writes_enabled": False,   # prod: read-only by default
    },
}


def load_env(env: str = None) -> dict:
    """Return the config dict for the selected environment."""
    env = (env or os.environ.get("LOAD_TEST_ENV", "local")).lower()
    if env not in _ENVS:
        raise ValueError(f"unknown LOAD_TEST_ENV={env!r}; choose local|test|prod")
    cfg = dict(_ENVS[env])
    cfg["env"] = env
    cfg["profile"] = {"writes_enabled": cfg["writes_enabled"]}
    return cfg
