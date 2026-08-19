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

It fails the suite, naming the files that differ. It cannot rebuild for you; that
is a separate decision (`issues/108` options 2-4), and an 8-minute rebuild
wired into every run would be worked around rather than waited for.

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
import os
import shlex
import subprocess
from pathlib import Path
from typing import Dict, Optional, Tuple

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


def check(server_url: str, repo_root: Path, container: str = CONTAINER) -> None:
    """Raise `ImageStale` unless the container's source matches the tree.

    Exempt only when the target is explicitly NOT local — a remote stack builds
    its image from the commit under test, so there is nothing to compare against
    a working tree that may not even be the same commit.
    """
    if os.environ.get(ALLOW_STALE) == "1":
        _report_only(server_url, repo_root, container)
        return

    if not _is_local_target(server_url):
        return

    local = _local(repo_root / PACKAGE)
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
        "  rebuild:  docker compose -f docker-compose.test.yml build vitalgraph",
        "            docker compose -f docker-compose.test.yml up -d --no-deps vitalgraph",
        f"  or set {ALLOW_STALE}=1 to run against the image as it is.",
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
