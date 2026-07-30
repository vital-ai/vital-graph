#!/usr/bin/env python3
"""Add deployed-version tracking columns to the ``install`` admin table.

Motivation
----------
During the 2026-07-29 prod saturation investigation, the deployed code vintage of
``cardiff-postgres-prod`` could not be read from the database. It had to be
*inferred* from schema artifacts — whether ``idx_{space}_rdf_stats_rc`` existed and
whether ``{space}_rdf_stats`` had been pruned — because the ``install`` table
carries only install/update timestamps. That inference cost real investigation time
and left the conclusion less certain than it should have been.

These columns let a running server record what it is, so "which code is this
database talking to?" is a lookup rather than a deduction.

Adds to ``install``:
    vitalgraph_version   VARCHAR(64)   e.g. '0.0.38'
    git_commit           VARCHAR(40)   full SHA, when available
    deployed_datetime    TIMESTAMP     when the running server last recorded itself

The migration is idempotent (``ADD COLUMN IF NOT EXISTS``) and safe to re-run.
Adding a nullable column is a catalog-only change in PostgreSQL — no table rewrite,
no long lock — so this is safe against a live database.

Usage:
    python apps/migrate_install_version.py
    DRY_RUN=true python apps/migrate_install_version.py

Environment variables (or .env file):
    DB_HOST      PostgreSQL host       (default: localhost)
    DB_PORT      PostgreSQL port       (default: 5432)
    DB_NAME      Database name         (default: vitalgraph)
    DB_USERNAME  Database user         (default: postgres)
    DB_PASSWORD  Database password     (default: postgres)
    DB_SSLMODE   SSL mode              (default: prefer)
    SET_VERSION  Also stamp the active row with the version detected locally
                 (default: false — the running server should normally do this)
    DRY_RUN      Set to 'true' to only report what would change
"""

import asyncio
import os
import subprocess
import sys

import asyncpg


# (column_name, column_type) — order is the order they are added.
NEW_COLUMNS = [
    ("vitalgraph_version", "VARCHAR(64)"),
    ("git_commit", "VARCHAR(40)"),
    ("deployed_datetime", "TIMESTAMP"),
]


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def detect_version() -> str:
    """Version of the running build.

    Order matters. ``VITALGRAPH_BUILD_VERSION`` is injected by the deploying
    pipeline (see Dockerfile) and is the only source that is correct inside a
    container. The local sources below are development conveniences.

    Note ``importlib.metadata`` scans ``sys.path``, which does NOT include the repo
    root when invoked as ``python apps/migrate_install_version.py`` — so an
    editable install is invisible to it; hence the pyproject.toml fallback.
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

    ``VITALGRAPH_GIT_COMMIT`` comes from the deploying pipeline via a Docker build
    arg. **A deployed container has no .git directory**, so the git fallback below
    only ever succeeds when this script is run by hand from a checkout — which is
    exactly the case where the answer is least interesting. If you are stamping a
    deployed environment and this returns empty, the pipeline is not passing
    ``--build-arg GIT_COMMIT``; fix that rather than trusting a local SHA, which
    would record the operator's working tree, not what is running.
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


async def existing_columns(conn: asyncpg.Connection) -> set:
    rows = await conn.fetch(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'install'"
    )
    return {r["column_name"] for r in rows}


async def migrate(conn: asyncpg.Connection, dry_run: bool, set_version: bool) -> int:
    """Add any missing columns. Returns the number of columns added."""
    present = await existing_columns(conn)
    if not present:
        print("  ✗ no 'install' table found — is this a VitalGraph database?")
        return 0

    added = 0
    for name, coltype in NEW_COLUMNS:
        if name in present:
            print(f"  · {name:20s} already present — skipping")
            continue
        stmt = f"ALTER TABLE install ADD COLUMN IF NOT EXISTS {name} {coltype}"
        if dry_run:
            print(f"  [dry-run] {stmt}")
        else:
            await conn.execute(stmt)
            print(f"  ✓ added {name} {coltype}")
        added += 1

    if set_version:
        version = detect_version()
        commit = detect_git_commit()
        if not version and not commit:
            print("  · SET_VERSION requested but neither version nor commit detected — skipping")
        else:
            stmt = (
                "UPDATE install SET vitalgraph_version = $1, git_commit = $2, "
                "deployed_datetime = now() WHERE active = true"
            )
            if dry_run:
                print(f"  [dry-run] stamp active row: version={version!r} commit={commit[:12]!r}")
            else:
                result = await conn.execute(stmt, version or None, commit or None)
                print(f"  ✓ stamped active row ({result}): "
                      f"version={version or '-'} commit={commit[:12] or '-'}")

    return added


async def main() -> int:
    dry_run = os.getenv("DRY_RUN", "").lower() == "true"
    set_version = os.getenv("SET_VERSION", "").lower() == "true"

    host = os.getenv("DB_HOST", "localhost")
    port = int(os.getenv("DB_PORT", "5432"))
    database = os.getenv("DB_NAME", "vitalgraph")
    user = os.getenv("DB_USERNAME", "postgres")
    password = os.getenv("DB_PASSWORD", "postgres")
    sslmode = os.getenv("DB_SSLMODE", "prefer")

    print(f"install-version migration → {user}@{host}:{port}/{database}"
          f"{'  [DRY RUN]' if dry_run else ''}")

    try:
        conn = await asyncpg.connect(
            host=host, port=port, database=database,
            user=user, password=password, ssl=sslmode, timeout=30,
        )
    except Exception as e:
        print(f"  ✗ connection failed: {e}")
        return 1

    try:
        added = await migrate(conn, dry_run, set_version)
    finally:
        await conn.close()

    if dry_run:
        print(f"\ndry run complete — {added} column(s) would be added")
    else:
        print(f"\nmigration complete — {added} column(s) added")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
