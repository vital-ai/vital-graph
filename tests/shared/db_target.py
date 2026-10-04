"""Which deployment the API suites write to, and which database they check.

`tests/api` writes through the API and asserts against PostgreSQL directly, so
both halves must be the same deployment. Pointing `LOCAL_CLIENT_SERVER_URL` at a
deployed stack while `VG_TEST_PG_*` keeps its localhost default sends the writes
one way and the assertions the other — measured 2026-10-04, 24 tests failed with
`relation "apitest_xxxxxxxx_rdf_quad" does not exist`, which reads as a broken
release and is a misconfigured run.

Kept apart from the conftest so the decision is a plain function a unit test
can hold to (`tests/unit/test_api_suite_db_target.py`); the fixture only acts on
what it returns.
"""

from typing import Optional
from urllib.parse import urlparse

LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "host.docker.internal")


def is_local(host: str) -> bool:
    return (host or "") in LOCAL_HOSTS


def is_local_url(url: str) -> bool:
    return is_local(urlparse(url).hostname or "")


def mismatch(server_url: str, pg_host: str, pg_port, pg_database: str) -> Optional[str]:
    """Why the run must not go ahead, or None.

    A REMOTE server with a LOCAL database is the one combination that cannot be
    right: the writes land in the deployment and the assertions read the local
    stack. (A local server with a remote database is not something the suite is
    run as, and is left alone.)
    """
    if not is_local_url(server_url) and is_local(pg_host):
        return (f"the server is remote ({server_url}) but DB verification points at "
                f"{pg_host}:{pg_port}/{pg_database}. The writes and the assertions "
                f"would land in different databases. Set VG_TEST_PG_HOST / _PORT / "
                f"_DATABASE / _USER / _PASSWORD at the database that server uses.")
    return None
