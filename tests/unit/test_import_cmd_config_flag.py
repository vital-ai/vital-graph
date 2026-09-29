"""`vitalgraphimport --config` must not be accepted and ignored.

`issues/155`. `args.config` was never referenced and `VitalGraphConfig()` takes
no path, so the flag did nothing — and the failure that produces is WRITING TO
THE WRONG DATABASE silently. It only failed loudly in the reported case because
the space happened not to exist in the other target; fixture names are reused
across the host cluster and the docker stack, so the normal case is a silent
success against the wrong one.

NOT made to work, deliberately. Configuration has been environment-only since
2026-02-03 — seven months before that issue proposed adding a config path back —
so satisfying the flag would mean re-adding YAML loading that was removed on
purpose. It refuses and names the alternative instead.

The issue also asked for the general form: "every accepted argument changes
behaviour". `test_no_argument_is_accepted_and_ignored` is that, scoped to this
parser.
"""

import subprocess
import sys

CMD = [sys.executable, "-m", "vitalgraph.cmd.vitalgraph_import_cmd"]


def _run(*args):
    return subprocess.run(CMD + list(args), capture_output=True, text=True, timeout=60)


def test_config_is_refused_not_ignored():
    r = _run("-s", "any", "-f", "/tmp/none.nt", "-c", "/tmp/some.yaml")
    assert r.returncode != 0, "the flag was accepted; it used to be ignored silently"
    assert "NOT supported" in r.stderr


def test_the_refusal_exits_NON_ZERO():
    """`main()` ends in `sys.exit(exit_code)`, so an early `return` exits 0 and
    the refusal becomes as silent as the bug. This caught exactly that."""
    r = _run("-s", "any", "-f", "/tmp/none.nt", "--config", "/tmp/x.yaml")
    assert r.returncode == 2, f"expected exit 2, got {r.returncode}"


def test_it_names_what_to_use_instead():
    """A refusal that does not say what to do is a worse flag, not a better one."""
    r = _run("-s", "any", "-f", "/tmp/none.nt", "-c", "/tmp/x.yaml")
    assert "LOCAL_DB_HOST" in r.stderr and "issues/155" in r.stderr


def test_the_help_text_no_longer_promises_a_config_file():
    r = _run("--help")
    assert r.returncode == 0
    assert "Path to vitalgraphdb-config.yaml" not in r.stdout, (
        "the help still describes behaviour that does not exist")
    assert "NOT SUPPORTED" in r.stdout


def test_no_argument_is_accepted_and_ignored():
    """THE GENERAL FORM the issue asked for.

    Every argument the parser defines must either change behaviour or refuse.
    Asserted structurally: each `dest` is referenced somewhere beyond its own
    `add_argument` call. This is the check that would have caught `--config`
    on the day it was added — and `trigger_maintenance(space_id=)`, the other
    instance the issue names.
    """
    import inspect
    import re
    from vitalgraph.cmd import vitalgraph_import_cmd as m

    src = inspect.getsource(m)
    # One block per add_argument. The dest is the EXPLICIT `dest=` when present
    # and otherwise the long flag with dashes folded — deriving it from the flag
    # alone reports `--format` (dest="file_format") as unread, which is how this
    # test first produced a false positive.
    ignored = []
    for block in src.split("parser.add_argument(")[1:]:
        block = block.split("parser.add_argument")[0]
        m_dest = re.search(r'dest\s*=\s*"([A-Za-z_][A-Za-z0-9_]*)"', block)
        if m_dest:
            dest = m_dest.group(1)
        else:
            m_flag = re.search(r'"--([a-z0-9-]+)"', block)
            if not m_flag:
                continue
            dest = m_flag.group(1).replace("-", "_")
        if dest in ("help",):
            continue
        if f"args.{dest}" not in src:
            ignored.append(dest)

    assert not ignored, (
        f"accepted but never read: {ignored} — each is a flag that silently "
        f"does nothing, which is issues/155's defect")
