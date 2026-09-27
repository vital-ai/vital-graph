"""The archive/delete scripts must report what HAPPENED, not what was asked.

Both defects here were found on 2026-09-26 by a single local experiment that
reported "3,000 deleted, 0 blocked, 0 failed" having deleted nothing at all.
Two independent faults lined up to produce that, and each is tested separately
because either alone is enough to make a run lie:

  1. `load_env()` read the `.env` FILE and ignored `os.environ`, so the
     documented `LOCAL_CLIENT_SERVER_URL` override silently did nothing and the
     run went to the DEV stack instead of the test stack.
  2. `delete_batch()` accepted `not_found` as success, and the caller threw away
     the server's `deleted_count` and counted `len(uris)` instead.

Together: a run pointed at the wrong server, where nothing exists, reporting
total success. Separately they are a misdirected run and a false tally. This is
the same family as `issues/229` (a short read returning 200) and the copy path's
untrustworthy `created_count` — trust the outcome, not the call.
"""

import os
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import archive_kg_entities as ake  # noqa: E402
import delete_kg_entities as dke  # noqa: E402


# --------------------------------------------------------------------------
# 1. load_env: the environment must win
# --------------------------------------------------------------------------

def test_the_shell_overrides_the_env_file():
    """THE DEFECT THAT REDIRECTED A RUN TO THE WRONG SERVER.

    `docker-compose.test.yml` instructs operators to select the test stack with
    exactly this variable. Reading the file only made that instruction a no-op.
    """
    with mock.patch.dict(os.environ, {"LOCAL_CLIENT_SERVER_URL": "http://localhost:8002"}):
        assert ake.load_env()["LOCAL_CLIENT_SERVER_URL"] == "http://localhost:8002"


def test_the_file_still_supplies_what_the_shell_does_not():
    """The override is a precedence rule, not a replacement — credentials and
    everything else must keep coming from `.env`."""
    env = ake.load_env()
    assert env.get("LOCAL_CLIENT_SERVER_URL"), "file value lost when nothing overrides"
    assert len(env) > 5, "load_env stopped reading the file"


def test_an_override_is_announced():
    """A silent redirect is the whole problem. If a run targets somewhere other
    than `.env` says, that must be visible in its output."""
    with mock.patch.dict(os.environ, {"LOCAL_CLIENT_SERVER_URL": "http://localhost:9999"}):
        with mock.patch("builtins.print") as pr:
            ake.load_env()
    said = " ".join(str(c) for c in pr.call_args_list)
    assert "LOCAL_CLIENT_SERVER_URL" in said and "override" in said.lower()


def test_unrelated_shell_variables_do_not_leak_in():
    """Copying all of `os.environ` would let a stray shell variable shadow a
    credential. Only file keys and an explicit allowlist are overridable."""
    with mock.patch.dict(os.environ, {"SOME_UNRELATED_THING": "x"}):
        assert "SOME_UNRELATED_THING" not in ake.load_env()


# --------------------------------------------------------------------------
# 2. delete_batch: absent is not deleted
# --------------------------------------------------------------------------

class _Api:
    """Returns one canned response; records the call."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def _call(self, method, path, body=None):
        self.calls.append((method, path))
        return self.payload


class _Args:
    space = "sp"
    graph = "urn:g"


def test_not_found_is_no_longer_success():
    """`not_found` used to be in the accepted list. A whole run against a
    non-existent space therefore looked clean."""
    api = _Api({"status": "not_found", "deleted_count": 0})
    with pytest.raises(RuntimeError, match="not_found"):
        dke.delete_batch(api, _Args(), ["urn:a"])


def test_it_returns_the_servers_count_not_the_request_size():
    """The caller must be able to tell 2-of-3 from 3-of-3."""
    api = _Api({"status": "deleted", "deleted_count": 2})
    assert dke.delete_batch(api, _Args(), ["urn:a", "urn:b", "urn:c"]) == 2


def test_a_missing_deleted_count_is_an_error_not_a_zero():
    """Treating absent-field as 0 would silently under-report; treating it as
    len(uris) is the original bug. Neither: refuse to guess."""
    api = _Api({"status": "deleted"})          # no deleted_count at all
    with pytest.raises(RuntimeError, match="deleted_count"):
        dke.delete_batch(api, _Args(), ["urn:a"])


def test_a_real_failure_status_still_raises():
    api = _Api({"status": "store_failed", "deleted_count": 0,
                "message": "none of the 2 requested were deleted"})
    with pytest.raises(RuntimeError, match="store_failed"):
        dke.delete_batch(api, _Args(), ["urn:a", "urn:b"])


def test_the_phase_counts_and_exit_code_reflect_a_shortfall():
    """The tally, the warning and the exit code must all move together.

    Asserted against source: driving `phase_delete` needs a queue, a state dir,
    a thread pool and an Api, and what is under test is the accounting rule.
    """
    import inspect
    src = inspect.getsource(dke.phase_delete)
    assert 'tally["deleted"] += removed' in src, (
        "the tally counts requested URIs again, not what the server removed")
    assert 'tally["deleted"] += len(uris)' not in src
    assert '"absent"' in src, "a shortfall is not tracked"
    assert 'tally["absent"]' in src
    # and it must not exit 0 on a run that removed nothing it was asked to
    assert 'tally["absent"]' in src.split("return 1 if")[1]
