"""The server records what is running, because nothing else can.

`issues/137`. Production is built from a SECOND repository whose history shares
no commits with this one — populated by copying files, not forking — so no sha
is shared and `git log A..B` cannot span them. The image's OCI labels are
correct but reading them needs registry access AND knowing which repo to look
in, which was exactly the missing knowledge.

The `install` table already had the three columns; `apps/migrate_install_version.py`
added them and nothing ever wrote them. `db/common/models.py` types them
`Optional[str] = None` and says they "stay None until a server stamps them".

Two details the issue got wrong, both load-bearing:

* `apps/` is NOT copied into the image (the Dockerfile copies `vitalgraph/`
  only), so detection has to live in the package.
* the issue said to stamp "next to `_auto_init_auth_tables`" — that runs only
  when `VG_AUTO_INIT=true`, which is test environments. Stamping there would
  never run in production, the one deployment this exists to identify.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import inspect

import pytest

from vitalgraph import build_info as B


class _Conn:
    def __init__(self, columns=("vitalgraph_version", "git_commit",
                                "deployed_datetime"), updated=1):
        self.columns = columns
        self.updated = updated
        self.args = None

    async def fetch(self, _sql):
        return [{"column_name": c} for c in self.columns]

    async def execute(self, _sql, *args):
        self.args = args
        return f"UPDATE {self.updated}"


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("VITALGRAPH_BUILD_VERSION", "v0.0.51")
    monkeypatch.setenv("VITALGRAPH_GIT_COMMIT", "a" * 40)
    monkeypatch.setenv("VITALGRAPH_BUILD_TIME", "2026-07-30T16:51:05Z")


@pytest.mark.asyncio
async def test_it_stamps_version_and_commit(env):
    conn = _Conn()
    assert await B.stamp_install(conn) is True
    assert conn.args[0] == "v0.0.51"
    assert conn.args[1] == "a" * 40


@pytest.mark.asyncio
async def test_missing_columns_is_not_an_error(env):
    """The columns arrive via a deliberate migration step. Before it runs this
    must be quiet, not noisy or fatal."""
    assert await B.stamp_install(_Conn(columns=("id", "active"))) is False


@pytest.mark.asyncio
async def test_empty_provenance_warns_because_that_is_the_actual_defect(
        monkeypatch, caplog):
    """No build args means "what is running?" stays unanswerable — which is
    issues/137 itself, so it must not pass silently."""
    for v in ("VITALGRAPH_BUILD_VERSION", "VITALGRAPH_GIT_COMMIT"):
        monkeypatch.setenv(v, "")
    monkeypatch.setattr(B, "detect_version", lambda: "")
    monkeypatch.setattr(B, "detect_git_commit", lambda: "")

    with caplog.at_level("WARNING"):
        assert await B.stamp_install(_Conn()) is False
    assert any("provenance is EMPTY" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_no_active_row_warns(env, caplog):
    with caplog.at_level("WARNING"):
        assert await B.stamp_install(_Conn(updated=0)) is False
    assert any("no ACTIVE install row" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_it_never_raises(env):
    """A provenance stamp that can take the server down would be a worse defect
    than the one it fixes."""
    class _Boom:
        async def fetch(self, _sql):
            raise RuntimeError("database is on fire")

    assert await B.stamp_install(_Boom()) is False


def test_build_time_parses_the_z_suffix(monkeypatch):
    monkeypatch.setenv("VITALGRAPH_BUILD_TIME", "2026-07-30T16:51:05Z")
    dt = B.detect_build_time()
    assert dt is not None and dt.tzinfo is not None


def test_a_garbage_build_time_is_none_not_an_exception(monkeypatch):
    monkeypatch.setenv("VITALGRAPH_BUILD_TIME", "last tuesday")
    assert B.detect_build_time() is None


def test_the_stamp_is_not_gated_behind_vg_auto_init():
    """The whole point is production, and VG_AUTO_INIT is test-only."""
    from vitalgraph.impl import vitalgraphapp_impl as A

    src = inspect.getsource(A.VitalGraphAppImpl._setup_startup_events)
    call = src.index("_stamp_build_provenance()")
    gate = src.index("VG_AUTO_INIT")
    branch = src[gate:call]
    assert "await self._auto_init_tables()" in branch, (
        "sanity: the gate should be the auto-init branch")
    # The stamp must be dedented back out of that branch.
    line = next(ln for ln in src.splitlines() if "_stamp_build_provenance()" in ln)
    gate_line = next(ln for ln in src.splitlines() if "VG_AUTO_INIT" in ln)
    assert (len(line) - len(line.lstrip())) <= (
        len(gate_line) - len(gate_line.lstrip())), (
        "the stamp is inside the VG_AUTO_INIT branch, so it would never run in "
        "production — which is the only environment issues/137 is about")


def test_detection_lives_in_the_package_not_in_apps():
    """`apps/` is not copied into the image, so a running container could not
    import detection that lived there."""
    import apps.migrate_install_version as M
    assert M.detect_version.__module__ == "vitalgraph.build_info"
    assert M.detect_git_commit.__module__ == "vitalgraph.build_info"
