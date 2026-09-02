"""What is running, resolved from the build and recorded in the database.

`issues/137`. Production is built from a SECOND repository whose history shares
no commits with this one — populated by copying files, not by forking — so no
sha is shared and no `git log A..B` can span the two. The running image's OCI
labels are correct, but reading them requires knowing which repository to look
in, which is precisely the knowledge that was missing.

The `install` admin table already carries the three columns for this; they were
added by `apps/migrate_install_version.py` and left NULL because nothing ever
wrote them. `db/common/models.py` types them `Optional[str] = None` and says
they "stay None until a server stamps them". No server did. This module is the
server stamping them.

Note for anyone extending this: `apps/` is NOT copied into the image (see
`Dockerfile`, which copies `vitalgraph/` only), so detection logic that a
running container needs has to live here rather than beside the migration.
"""

from __future__ import annotations

import logging
import os
import subprocess
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def detect_version() -> str:
    """Version of the running build.

    `VITALGRAPH_BUILD_VERSION` is injected by the deploying pipeline and is the
    only source that is correct inside a container. The rest are development
    conveniences.
    """
    env = os.getenv("VITALGRAPH_BUILD_VERSION", "").strip()
    if env:
        return env
    try:
        import importlib.metadata as md
        return md.version("vital-graph")
    except Exception:
        pass
    try:
        with open(os.path.join(REPO_ROOT, "pyproject.toml")) as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("version"):
                    _, _, raw = line.partition("=")
                    return raw.strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def detect_git_commit() -> str:
    """Commit of the running build.

    A deployed container has NO `.git` directory, so the git fallback only ever
    succeeds when run from a checkout — exactly the case where the answer is
    least interesting. If a deployed environment stamps this empty, the pipeline
    is not passing `--build-arg GIT_COMMIT`; fix that rather than trusting a
    local sha, which would record the operator's working tree, not what is
    running.
    """
    env = os.getenv("VITALGRAPH_GIT_COMMIT", "").strip()
    if env:
        return env
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def detect_build_time() -> Optional[datetime]:
    """`VITALGRAPH_BUILD_TIME` as an aware datetime, or None."""
    raw = os.getenv("VITALGRAPH_BUILD_TIME", "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        logger.debug("VITALGRAPH_BUILD_TIME is not ISO-8601: %r", raw)
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def stamp_install(conn) -> bool:
    """Record version / commit / deploy time on the active `install` row.

    Returns True when a row was updated. NEVER raises: a provenance stamp that
    can take the server down would be a worse defect than the one it fixes, so
    every failure is logged and swallowed.

    `deployed_datetime` is stamped at START time, not build time. The column is
    named "deployed", a restart legitimately updates "since when has this code
    been running", and the build moment is still recoverable from the version
    and commit (and from the image's OCI labels). Build time is logged alongside
    so a running instance can report both.
    """
    version = detect_version()
    commit = detect_git_commit()
    built = detect_build_time()

    if not version and not commit:
        # Nothing to record. Say so loudly in a container -- it means the build
        # args are not being passed, which is the actual defect in issues/137.
        logger.warning(
            "Build provenance is EMPTY: neither VITALGRAPH_BUILD_VERSION nor "
            "VITALGRAPH_GIT_COMMIT is set. 'what is running?' stays "
            "unanswerable from the database; check the pipeline passes "
            "--build-arg GIT_COMMIT / VITALGRAPH_VERSION.")
        return False

    try:
        cols = {r["column_name"] for r in await conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'install'")}
        needed = {"vitalgraph_version", "git_commit", "deployed_datetime"}
        missing = needed - cols
        if missing:
            # The migration has not run here. Not an error -- the columns are
            # added by apps/migrate_install_version.py as a deliberate step.
            logger.info(
                "install table has no provenance columns (%s); skipping stamp. "
                "Run apps/migrate_install_version.py to enable it.",
                ", ".join(sorted(missing)))
            return False

        result = await conn.execute(
            "UPDATE install SET vitalgraph_version = $1, git_commit = $2, "
            "deployed_datetime = $3 WHERE active",
            version or None, commit or None, datetime.now(timezone.utc))
        updated = int(result.split()[-1]) if result else 0
        if not updated:
            logger.warning(
                "Build provenance not recorded: no ACTIVE install row. "
                "version=%s commit=%s", version, commit[:12])
            return False

        logger.info(
            "Build provenance stamped: version=%s commit=%s built=%s",
            version or "?", (commit[:12] + "...") if commit else "?",
            built.isoformat() if built else "?")
        return True
    except Exception as exc:
        logger.warning("Could not stamp build provenance: %s", exc)
        return False
