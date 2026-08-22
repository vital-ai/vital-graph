"""Is the running container serving the source in the working tree?

`issues/108`. Two correctness regressions shipped on 2026-08-17 and were found on
2026-08-18, both by the same accident: someone rebuilt the container. Between
them every frame looked absent (DELETE answered "Frame not found", 14 API tests
failed) and the frames list answered `total_count: 3, objects: []`. The image was
43 hours old, so no request had ever executed the new code.

**A green API suite says nothing about code the running image does not contain,
and nothing distinguishes the two.** That is worse than no signal: it is a signal
that gets read as coverage. It happened again on 2026-08-19, to the author of
this module, hours after reading the issue — `tests/api` was reported green for a
generator change the container did not contain.

WHAT THIS DOES AND DOES NOT DO

It fails the suite, naming the files that differ — and, since 2026-08-22, it
first TRIES TO FIX IT (`issues/108` option 2, in the form the measurements
justify).

The original objection to rebuilding automatically was "8 minutes on every run,
which will get worked around". That figure was a COLD build. Measured with a
warm layer cache, which is the normal state of a machine that has built this
image before:

    no-op build (nothing changed)            1.7 s
    rebuild after a real source change      24.1 s
    plus container recreate and health       13 s

So the honest cost is under two seconds when the image is already current, and
about forty when it is not — against a manual cycle that interrupted this
module's author four times in one day. The rebuild is attempted ONCE; if the
image still does not match afterwards, the suite fails exactly as before. A
guard that repairs the common case and still refuses the uncommon one is not
the thing that gets worked around.

FOUR THINGS THAT DECIDE WHETHER IT WORKS OR BECOMES NOISE

**The algorithm is sent, not shipped.** The hash is computed by a literal passed
to `python -c`, so both sides run the SAME code regardless of image age. A hasher
imported from the image would be the stale copy, and changing it would produce a
mismatch that is not staleness — a guard that cries wolf gets disabled, which is
the same outcome as not having one.

**Per-file, not one tree hash.** A single digest says "stale" and nothing else.
The diff distinguishes "you changed the generator, rebuild" from "you changed
something the image does not contain, carry on", which is what makes the failure
actionable rather than another opaque red.

**It fails rather than skips.** A skip inside a suite that is read as coverage is
the original defect wearing a different hat — and this repo has hit that shape
twice: a `HAS_INFRASTRUCTURE` probe that skipped silently in CI, and eight tests
that always skipped behind a swallowed `NameError`.

**The absent-container path is the one to get right.** "Docker is not here, so
pass" makes the guard a no-op exactly where nobody is looking. A missing
container while the target is localhost is a real problem, not an exemption, so
it fails; a target that is NOT localhost is a deliberate remote stack and is
exempt, because there the image is built from the commit under test.
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Only what the image contains. Editing tests/, scripts/ or planning/ needs no
# rebuild, and flagging those would train people to ignore this.
PACKAGE = "vitalgraph"
CONTAINER = os.environ.get("VG_TEST_APP_CONTAINER", "vitalgraph-test-app")
IN_IMAGE = "/app/vitalgraph"

ALLOW_STALE = "VG_ALLOW_STALE_IMAGE"

# Run on BOTH sides, sent as text so the image's own copy is never used.
_HASHER = r"""
import hashlib, json, os, sys
root = sys.argv[1]
out = {}
for dirpath, dirnames, filenames in os.walk(root):
    dirnames[:] = [d for d in dirnames if d != "__pycache__"]
    for fn in filenames:
        if not fn.endswith(".py"):
            continue
        full = os.path.join(dirpath, fn)
        rel = os.path.relpath(full, root)
        with open(full, "rb") as fh:
            out[rel] = hashlib.sha256(fh.read()).hexdigest()[:16]
print(json.dumps(out))
"""


# Bounds for the self-heal. A build that exceeds this is a cold build or a
# broken daemon; either way the suite should say so rather than hang.
REBUILD_TIMEOUT = 600
HEALTH_TIMEOUT = 90
# Opt out of the rebuild while keeping the check — for CI, where the image is
# already built from the commit under test, and for anyone who wants the
# failure without the side effect.
NO_REBUILD = "VG_NO_IMAGE_REBUILD"


class ImageStale(AssertionError):
    """The container is serving different source from the working tree."""


def _local(root: Path) -> Dict[str, str]:
    r = subprocess.run(["python", "-c", _HASHER, str(root)],
                       capture_output=True, text=True, timeout=120)
    r.check_returncode()
    return json.loads(r.stdout)


def _in_container(container: str) -> Optional[Dict[str, str]]:
    """None when the container is not reachable — the caller decides what that
    means, because the answer differs for a local and a remote target."""
    try:
        r = subprocess.run(
            ["docker", "exec", container, "python", "-c", _HASHER, IN_IMAGE],
            capture_output=True, text=True, timeout=120)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def diff(local: Dict[str, str], image: Dict[str, str]) -> Tuple[list, list, list]:
    """(only in tree, only in image, differing) — sorted, so output is stable."""
    lk, ik = set(local), set(image)
    return (sorted(lk - ik), sorted(ik - lk),
            sorted(k for k in (lk & ik) if local[k] != image[k]))


def _is_local_target(url: str) -> bool:
    return "localhost" in url or "127.0.0.1" in url


def _rebuild(repo_root: Path, server_url: str) -> bool:
    """Rebuild the app image and recreate its container. True if it completed.

    ONLY the app service, and ONLY with --no-deps. The postgres container in
    this stack keeps PGDATA in its writable layer (`issues/102`), so recreating
    it would destroy the fixtures — 50M quads that take hours to reload. This
    must never widen to `up -d` without a service name.
    """
    import subprocess
    compose = ["docker", "compose", "-f", "docker-compose.test.yml"]
    try:
        for args in (["build", "vitalgraph"],
                     ["up", "-d", "--no-deps", "vitalgraph"]):
            r = subprocess.run(compose + args, cwd=str(repo_root),
                               capture_output=True, text=True, timeout=REBUILD_TIMEOUT)
            if r.returncode != 0:
                logger.warning("image rebuild step %s failed: %s",
                               args[0], (r.stderr or r.stdout)[-400:])
                return False
    except Exception as exc:                      # docker missing, timeout, ...
        logger.warning("image rebuild could not run: %s", exc)
        return False

    # The container is up before it is READY; a request now races uvicorn's
    # startup and fails as a connection error that looks nothing like staleness.
    import time
    import urllib.request
    deadline = time.monotonic() + HEALTH_TIMEOUT
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{server_url.rstrip('/')}/health",
                                        timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(1)
    logger.warning("rebuilt image did not become healthy within %ss", HEALTH_TIMEOUT)
    return False


def check(server_url: str, repo_root: Path, container: str = CONTAINER) -> None:
    """Raise `ImageStale` unless the container's source matches the tree.

    On a mismatch, rebuild once and re-check before failing (`issues/108`
    option 2). Exempt only when the target is explicitly NOT local — a remote
    stack builds its image from the commit under test, so there is nothing to
    compare against a working tree that may not even be the same commit, and
    rebuilding someone else's stack from here would be worse than wrong.
    """
    if os.environ.get(ALLOW_STALE) == "1":
        _report_only(server_url, repo_root, container)
        return

    if not _is_local_target(server_url):
        return

    local = _local(repo_root / PACKAGE)
    image = _in_container(container)

    if image is not None and os.environ.get(NO_REBUILD) != "1":
        if any(diff(local, image)):
            logger.warning("image is stale; rebuilding %r once before failing",
                           container)
            if _rebuild(repo_root, server_url):
                image = _in_container(container)

    if image is None:
        raise ImageStale(
            f"the API target is {server_url} (local) but container "
            f"{container!r} could not be reached, so what is serving those "
            f"requests is unknown and unverifiable. A pass here would say "
            f"nothing about the code in this tree. Start the test stack, or "
            f"point at a remote target, or set {ALLOW_STALE}=1 to accept it.")

    added, removed, changed = diff(local, image)
    if not (added or removed or changed):
        return

    def _sample(names, label):
        if not names:
            return []
        shown = names[:8]
        more = f"  (+{len(names) - len(shown)} more)" if len(names) > len(shown) else ""
        return [f"  {label} ({len(names)}):"] + [f"    {n}" for n in shown] + ([more] if more else [])

    lines = [
        f"the image behind {server_url} does not contain this working tree's "
        f"{PACKAGE}/ source, so a green run here measures code you are not "
        f"looking at ({len(local)} files in tree, {len(image)} in image):",
        *_sample(changed, "CHANGED"),
        *_sample(added, "ONLY IN TREE — never built"),
        *_sample(removed, "ONLY IN IMAGE — deleted since the build"),
        "",
        "  A rebuild was attempted automatically and did NOT resolve this, so",
        "  something beyond staleness is wrong — a failing build, a container",
        "  that will not start, or a file the image genuinely cannot contain.",
        "",
        "  rebuild by hand:",
        "    docker compose -f docker-compose.test.yml build vitalgraph",
        "    docker compose -f docker-compose.test.yml up -d --no-deps vitalgraph",
        f"  {NO_REBUILD}=1 keeps this check but skips the rebuild.",
        f"  {ALLOW_STALE}=1 runs against the image as it is.",
    ]
    raise ImageStale("\n".join(lines))


def _report_only(server_url: str, repo_root: Path, container: str) -> None:
    """The escape hatch still says what it is skipping.

    Going quiet would reproduce the defect one level up: a run that passes while
    testing something other than what it names.
    """
    if not _is_local_target(server_url):
        return
    image = _in_container(container)
    if image is None:
        print(f"\n[{ALLOW_STALE}] container {container!r} unreachable; "
              f"the code behind {server_url} is unverified.")
        return
    added, removed, changed = diff(_local(repo_root / PACKAGE), image)
    n = len(added) + len(removed) + len(changed)
    print(f"\n[{ALLOW_STALE}] running against an image that differs from the "
          f"working tree in {n} file(s)."
          + (f" First: {(changed + added + removed)[0]}" if n else ""))
