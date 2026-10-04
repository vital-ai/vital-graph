"""The API suites refuse to check a different database than the server writes.

`tests/shared/db_target.mismatch`, which `tests/api/conftest.py::pg_conn` acts
on. Without it, a run against a deployed server with the localhost database
defaults wrote to one and asserted against the other: 24 failures reading as a
broken release (2026-10-04). Verified by hand three ways when the guard was
written; this is those three, kept.
"""

from tests.shared.db_target import is_local_url, mismatch


def test_a_remote_server_with_the_local_database_is_refused():
    why = mismatch("https://vg.example.com", "localhost", 5433, "sparql_sql_graph")
    assert why and "vg.example.com" in why and "localhost:5433" in why


def test_a_remote_server_with_its_own_database_runs():
    assert mismatch("https://vg.example.com", "db.example.com", 5432, "vg") is None


def test_the_local_stack_runs():
    assert mismatch("http://localhost:8002", "localhost", 5433, "sparql_sql_graph") is None
    assert mismatch("http://127.0.0.1:8002", "127.0.0.1", 5433, "x") is None


def test_the_api_suite_actually_consults_it():
    # The decision is only worth testing if the fixture acts on it.
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1] / "api" / "conftest.py").read_text()
    body = src[src.index("async def pg_conn("):]
    assert "mismatch(SERVER_URL, PG_HOST, PG_PORT, PG_DATABASE)" in body
    assert "pytest.fail(problem)" in body


def test_what_counts_as_local():
    assert is_local_url("http://localhost:8002")
    assert is_local_url("http://host.docker.internal:8001")
    assert not is_local_url("https://vitalgraph-test.example.com")
