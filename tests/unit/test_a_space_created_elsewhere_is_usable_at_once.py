"""A space created on one instance is usable on another at once — issues/348.

Two VitalGraph instances share one database. Each keeps its own map of space
id -> storage key, and `space_prefix` names every per-space table from it alone,
falling back to the bare id for a space it does not hold. In production a
space was created on A, and the client's next call (`GET /api/vector-indexes`)
reached B ~180 ms before B's NOTIFY handler had loaded the key: B queried
`<space_id>_vector_index` and answered 500.

Driven in-process: "B" is a real SpaceManager whose key map lacks the space,
over a fake backend standing in for the shared database. Requests go through
the real vector-index router, mounted with the resolver as the app mounts it
(`VitalGraphAppImpl._include_space_router`). The last test builds the real
app and checks every route that takes a `space_id` carries the resolver.
"""

from __future__ import annotations

import asyncio

import asyncpg
import httpx
import pytest
from fastapi import Depends, FastAPI

from vitalgraph.db.sparql_sql import space_names
from vitalgraph.space.space_manager import SpaceAlreadyExistsError, SpaceManager
from vitalgraph.space.space_resolution import space_resolving_dependency

pytestmark = [pytest.mark.unit]

SPACE = "app_memory"
KEY = "abcdefgh"


@pytest.fixture(autouse=True)
def _isolated_key_map():
    """The key map is module-level: each test starts with SPACE unknown."""
    saved = (dict(space_names._KEYS), dict(space_names._IDS),
             set(space_names._UNKEYED))
    space_names.forget_storage_key(SPACE)
    yield
    space_names._KEYS.clear(); space_names._KEYS.update(saved[0])
    space_names._IDS.clear(); space_names._IDS.update(saved[1])
    space_names._UNKEYED.clear(); space_names._UNKEYED.update(saved[2])


class SharedDb:
    """The shared database, as the sparql_sql backend presents it."""

    def __init__(self, rows=None, delay=0.0):
        self.rows = dict(rows if rows is not None else
                         {SPACE: {"space_id": SPACE, "space_name": SPACE,
                                  "space_description": "", "storage_key": KEY}})
        self.delay = delay
        self.reads = 0

    async def get_space_metadata(self, space_id):
        """Like the real one: returns the row and loads its key (or marks the
        space unkeyed)."""
        self.reads += 1
        await asyncio.sleep(self.delay)
        row = self.rows.get(space_id)
        if row:
            if row.get("storage_key"):
                space_names.register_storage_key(space_id, row["storage_key"])
            else:
                space_names.mark_unkeyed(space_id)
        return row

    async def list_spaces(self):
        return list(self.rows.values())

    async def space_exists(self, space_id):
        """Tables exist only under the key the row records."""
        row = self.rows.get(space_id)
        return bool(row and row.get("storage_key")
                    and space_names.space_prefix(space_id) == f"vgs_{row['storage_key']}")


class _Conn:
    def __init__(self, log):
        self.log = log

    async def fetch(self, sql, *args):
        table = sql.split(" FROM ", 1)[1].split()[0]
        self.log.append(table)
        if not table.startswith(f"vgs_{KEY}_"):
            raise asyncpg.UndefinedTableError(f'relation "{table}" does not exist')
        return []


class _Pool:
    def __init__(self, log):
        self.log = log

    async def acquire(self):
        return _Conn(self.log)

    async def release(self, conn):
        pass


class _AppImpl:
    def __init__(self, log, space_manager):
        self.db_impl = type("Db", (), {"connection_pool": _Pool(log)})()
        self.space_manager = space_manager


async def _admin():
    return {"username": "admin", "role": "admin"}


def _client(space_manager, log):
    from vitalgraph.endpoint.vector_indexes_endpoint import create_vector_indexes_router
    app = FastAPI()
    app.include_router(
        create_vector_indexes_router(_AppImpl(log, space_manager), _admin),
        prefix="/api",
        dependencies=[Depends(space_resolving_dependency(lambda: space_manager, _admin))])
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://b")


# ---------------------------------------------------------------------------
# The production failure
# ---------------------------------------------------------------------------

class TestTheRequestDoesNotWaitForTheSignal:

    async def test_a_request_during_the_signal_handler_uses_the_key(self):
        """The production sequence: B's "created" handler is mid-read when the
        request arrives. The request resolves the space itself."""
        db = SharedDb(delay=0.18)
        b = SpaceManager(space_backend=db)
        log: list = []
        async with _client(b, log) as client:
            handler = asyncio.create_task(
                b._handle_space_signal({"type": "created", "space_id": SPACE}))
            await asyncio.sleep(0.001)
            r = await client.get("/api/vector-indexes", params={"space_id": SPACE})
            await handler
        assert r.status_code == 200, r.text
        assert log == [f"vgs_{KEY}_vector_index"]

    async def test_a_request_with_no_signal_at_all_uses_the_key(self):
        """A missed NOTIFY no longer means waiting for the 60 s refresh."""
        b = SpaceManager(space_backend=SharedDb())
        log: list = []
        async with _client(b, log) as client:
            r = await client.get("/api/vector-indexes", params={"space_id": SPACE})
        assert r.status_code == 200, r.text
        assert log == [f"vgs_{KEY}_vector_index"]
        assert SPACE in b._spaces

    async def test_a_known_space_is_not_read_again(self):
        db = SharedDb()
        b = SpaceManager(space_backend=db)
        assert await b.ensure_space_loaded(SPACE)
        assert await b.ensure_space_loaded(SPACE)
        assert db.reads == 1

    async def test_a_registered_space_without_its_key_is_read(self):
        """Registry membership is not proof the key is loaded: the signal path
        registers a space even when its key read failed."""
        db = SharedDb()
        b = SpaceManager(space_backend=db)
        await b._handle_space_signal({"type": "created", "space_id": SPACE})
        space_names.forget_storage_key(SPACE)          # the key read "failed"
        assert SPACE in b._spaces
        assert await b.ensure_space_loaded(SPACE)
        assert space_names.registered_storage_key(SPACE) == KEY

    async def test_an_unknown_id_stays_unknown(self):
        db = SharedDb(rows={})
        b = SpaceManager(space_backend=db)
        assert not await b.ensure_space_loaded("no_such_space")
        assert "no_such_space" not in b._spaces
        assert not space_names.is_resolved("no_such_space")

    async def test_an_unkeyed_space_is_read_once(self):
        """A space created before the key cutover has no key, correctly. It must
        not cost a database read on every request."""
        db = SharedDb(rows={"old_space": {"space_id": "old_space",
                                          "storage_key": None}})
        b = SpaceManager(space_backend=db)
        assert await b.ensure_space_loaded("old_space")
        assert await b.ensure_space_loaded("old_space")
        assert db.reads == 1
        assert space_names.space_prefix("old_space") == "old_space"

    async def test_a_registered_space_whose_read_fails_stays_available(self):
        """A failed read returns None, like a missing row. A space already
        registered is not dropped for it; deletion is the signal's job."""
        db = SharedDb(rows={})
        b = SpaceManager(space_backend=db)
        b._spaces[SPACE] = object()
        assert await b.ensure_space_loaded(SPACE)


class TestLoadStorageKeysMarksWhatItRead:

    async def test_an_unkeyed_row_is_marked_resolved(self):
        from vitalgraph.db.sparql_sql.space_storage_key import load_storage_keys

        class Conn:
            async def fetch(self, sql, *args):
                return [{"space_id": "old_space", "storage_key": None, "keyed": False}]

        await load_storage_keys(Conn(), "old_space")
        assert space_names.is_resolved("old_space")
        assert space_names.space_prefix("old_space") == "old_space"

    async def test_an_unmigrated_database_marks_the_space_read(self):
        from vitalgraph.db.sparql_sql.space_storage_key import load_storage_keys

        class Conn:
            async def fetch(self, sql, *args):
                raise asyncpg.UndefinedColumnError("no storage_key")

        await load_storage_keys(Conn(), "old_space")
        assert space_names.is_resolved("old_space")

    def test_registering_a_key_clears_the_unkeyed_mark(self):
        space_names.mark_unkeyed(SPACE)
        space_names.register_storage_key(SPACE, KEY)
        assert SPACE not in space_names._UNKEYED
        assert space_names.space_prefix(SPACE) == f"vgs_{KEY}"


# ---------------------------------------------------------------------------
# Create: refused for a space that exists elsewhere
# ---------------------------------------------------------------------------

class TestDuplicateCreate:

    async def test_a_create_for_a_space_made_elsewhere_is_refused(self):
        """B has not heard of the space. Before the fix, B looked for its tables
        under the bare id, found none, and created it again under a new key."""
        db = SharedDb()
        b = SpaceManager(space_backend=db)
        with pytest.raises(SpaceAlreadyExistsError):
            await b.create_space_with_tables(SPACE, SPACE)
        assert space_names.registered_storage_key(SPACE) == KEY


# ---------------------------------------------------------------------------
# Delete elsewhere: forgotten entirely
# ---------------------------------------------------------------------------

class TestDeleteElsewhere:

    @pytest.fixture
    def invalidated(self, monkeypatch):
        from vitalgraph.db.sparql_sql import space_cache_invalidation as M
        seen: list = []
        monkeypatch.setattr(M, "invalidate_space_caches",
                            lambda sid, **kw: seen.append(sid) or {})
        return seen

    async def test_the_deleted_signal_forgets_the_key_and_caches(self, invalidated):
        b = SpaceManager(space_backend=SharedDb())
        assert await b.ensure_space_loaded(SPACE)
        await b._handle_space_signal({"type": "deleted", "space_id": SPACE})
        assert SPACE not in b._spaces
        assert not space_names.is_resolved(SPACE)
        assert invalidated == [SPACE]

    async def test_the_deleted_signal_forgets_an_unregistered_space_too(self, invalidated):
        """The key can be known without a registry record (a job loaded it)."""
        b = SpaceManager(space_backend=SharedDb())
        space_names.register_storage_key(SPACE, KEY)
        await b._handle_space_signal({"type": "deleted", "space_id": SPACE})
        assert not space_names.is_resolved(SPACE)
        assert invalidated == [SPACE]

    async def test_the_refresh_forgets_a_space_whose_row_is_gone(self, invalidated):
        """The path for a delete whose notice was missed."""
        db = SharedDb()
        b = SpaceManager(space_backend=db)
        assert await b.ensure_space_loaded(SPACE)
        db.rows.clear()
        await b._refresh_cache_from_db()
        assert SPACE not in b._spaces
        assert not space_names.is_resolved(SPACE)
        assert invalidated == [SPACE]

    async def test_the_refresh_keeps_a_space_created_during_its_read(self, invalidated):
        """A space this process registers while the refresh's read runs was not
        in what the read saw, and is not evicted for it."""
        db = SharedDb(rows={})
        b = SpaceManager(space_backend=db)
        real_list = db.list_spaces

        async def list_spaces_while_a_create_completes():
            rows = await real_list()
            space_names.register_storage_key(SPACE, KEY)
            b._spaces[SPACE] = object()
            return rows

        db.list_spaces = list_spaces_while_a_create_completes
        await b._refresh_cache_from_db()
        assert SPACE in b._spaces
        assert space_names.registered_storage_key(SPACE) == KEY
        assert invalidated == []


# ---------------------------------------------------------------------------
# Body-named spaces: import / export jobs
# ---------------------------------------------------------------------------

class TestJobsResolveTheirSpace:

    async def test_a_job_started_on_another_instance_loads_the_key(self):
        from vitalgraph.jobs.import_export_manager import ImportExportJobManager

        class Conn:
            async def fetch(self, sql, *args):
                return [{"space_id": SPACE, "storage_key": KEY, "keyed": True}]

        class Acquire:
            async def __aenter__(self):
                return Conn()

            async def __aexit__(self, *a):
                return False

        class Pool:
            def acquire(self):
                return Acquire()

        mgr = ImportExportJobManager.__new__(ImportExportJobManager)
        mgr._pool = Pool()
        await mgr._resolve_job_space(SPACE)
        assert space_names.space_prefix(SPACE) == f"vgs_{KEY}"


# ---------------------------------------------------------------------------
# Coverage: every space-scoped route in the real app
# ---------------------------------------------------------------------------

def test_space_routes_resolve_their_space(monkeypatch):
    """Every route that takes a `space_id` query or path parameter is mounted
    with the resolver. A router included with plain `include_router` instead of
    `_include_space_router` fails here, naming its routes."""
    from fastapi.routing import APIRoute, _IncludedRouter

    import vitalgraph.config.config_loader as CL
    import vitalgraph.storage.s3_file_manager as S3

    def _no_storage(*a, **k):
        raise RuntimeError("no object storage in this test")

    monkeypatch.setattr(S3, "create_s3_file_manager_from_config", _no_storage)
    # Building the app would load the repo's `.env` into `os.environ`. Modules
    # imported during the build would then keep values from it after the
    # environment was restored, and later tests would compare them against the
    # restored environment (`test_entity_registry_vector_config`,
    # `test_archive_tooling_reports_outcomes`). The routes do not depend on it.
    monkeypatch.setattr(CL, "load_dotenv_files", lambda: None)
    # Placeholders: building the app reads them but connects to nothing.
    for key, value in {"DB_HOST": "unused.invalid", "DB_PORT": "5432",
                       "DB_NAME": "unused", "DB_USERNAME": "unused"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 40)
    from vitalgraph.main.main import create_app
    app = create_app()

    def walk(dep):
        yield dep
        for sub in dep.dependencies:
            yield from walk(sub)

    def routes(rs, deps=()):
        for r in rs:
            if isinstance(r, _IncludedRouter):
                yield from routes(r.original_router.routes,
                                  deps + tuple(r.include_context.dependencies or ()))
            elif isinstance(r, APIRoute):
                yield r, deps

    scoped, missing = 0, []
    for route, deps in routes(app.routes):
        params = [p for d in walk(route.dependant)
                  for p in d.query_params + d.path_params]
        if not any(p.name == "space_id" for p in params):
            continue
        scoped += 1
        if not any(getattr(d.dependency, "__name__", "") == "resolve_request_space"
                   for d in deps):
            missing.append(f"{sorted(route.methods)} {route.path}")
    assert scoped >= 100, f"found only {scoped} space-scoped routes; the walk is broken"
    assert not missing, missing
