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

from datetime import datetime
from pathlib import Path

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

    async def execute(self, sql, *args):
        # Reject what asyncpg rejects. The first version of this fake accepted
        # ANY argument, so it happily took a tz-aware datetime for a column the
        # migration and both schemas declare TIMESTAMP (without time zone).
        # Production logged "can't subtract offset-naive and offset-aware
        # datetimes", the handler swallowed it, and the stamp silently did
        # nothing. A fake that accepts more than the real driver does not test
        # the code, it tests the fake.
        for a in args:
            if isinstance(a, datetime) and a.tzinfo is not None:
                raise TypeError(
                    "invalid input for query argument: can't subtract "
                    "offset-naive and offset-aware datetimes")
        self.sql = sql
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
async def test_the_timestamp_comes_from_the_database_not_python(env):
    """`deployed_datetime` is TIMESTAMP without time zone.

    Passing a Python datetime at all is the bug: an aware one is rejected by the
    driver, and a naive one silently records the CLIENT's clock in whatever zone
    it happens to be. The database already produces this value for
    `install_datetime` and `update_datetime`, and for the migration script.
    """
    conn = _Conn()
    assert await B.stamp_install(conn) is True
    assert not any(isinstance(a, datetime) for a in conn.args), (
        "no datetime should be sent as a parameter")
    assert "now() AT TIME ZONE 'utc'" in conn.sql, (
        "the database must produce the timestamp, explicitly in UTC rather "
        "than relying on the session TimeZone")


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
    """The whole point is production, and VG_AUTO_INIT is test-only.

    Reads the SOURCE rather than importing the module. `vitalgraphapp_impl`
    pulls in the FastAPI server chain, which needs `itsdangerous` — not
    installed in the Tier 1 unit environment, so importing it here fails CI
    while passing locally. That is the trap `c504abe` already fixed once, for
    the same reason: a unit test has no business behind the server imports.
    """
    src = (Path(B.__file__).parent / "impl" / "vitalgraphapp_impl.py").read_text()

    lines = src.splitlines()
    call_at = next(i for i, ln in enumerate(lines)
                   if "await self._stamp_build_provenance()" in ln)
    # The NEAREST PRECEDING `if` that tests the flag -- not merely the first
    # line mentioning it, which is a docstring in another method entirely.
    gate_at = max(i for i, ln in enumerate(lines[:call_at])
                  if "VG_AUTO_INIT" in ln and ln.lstrip().startswith("if "))

    def indent(i):
        return len(lines[i]) - len(lines[i].lstrip())

    assert indent(call_at) <= indent(gate_at), (
        "the stamp is inside the VG_AUTO_INIT branch, so it would never run in "
        "production — which is the only environment issues/137 is about")


def test_detection_lives_in_the_package_not_in_apps():
    """`apps/` is not copied into the image, so a running container could not
    import detection that lived there."""
    import apps.migrate_install_version as M
    assert M.detect_version.__module__ == "vitalgraph.build_info"
    assert M.detect_git_commit.__module__ == "vitalgraph.build_info"
