"""
Registry embedding columns migration (entity and agent registries).

Moves a registry's vector tables from a single shared `embedding` column to one
column per embedding model:

    embedding_vitalsigns_onnx          vector(384)
    embedding_paraphrase_multilingual  vector(384)
    embedding_openai_3_small           vector(1536)

    --registry entity   entity_registry_vec_entity, entity_registry_vec_location
    --registry agent    agent_registry_vec_agent

WHICH COLUMN THE EXISTING DATA GOES INTO
----------------------------------------
The legacy `embedding` column carries no record of which model produced it —
that is the whole reason for this change. So the destination cannot be
detected; it must be stated by whoever knows how the environment was built.

    Default          --target-provider vitalsigns_onnx
                     (paraphrase-MiniLM-L3-v2, the historical default)

    STAGING, entity  --target-provider paraphrase_multilingual_minilm_l12_v2
                     Staging's existing ENTITY vectors were produced by the
                     multilingual model, NOT the ONNX default. Running the
                     default there would file multilingual vectors under
                     vitalsigns_onnx and every subsequent search would compare
                     across embedding spaces — the exact failure this schema
                     change exists to prevent.

The two registries are migrated separately and may take different targets: the
agent registry has always embedded with the ONNX default.

Get this wrong and nothing errors: both 384-wide candidates fit. Use --dry-run
first and confirm the reported target matches how the data was actually built.

The legacy column is KEPT by default so the copy can be verified and, if the
wrong target was chosen, redone. Drop it in a second pass with --drop-legacy.

Usage:
    # inspect, change nothing
    python -m vitalgraph.db.migrations.migrate_registry_embedding_columns \\
        --dsn "postgresql://user:pass@host/db" --registry entity --dry-run

    # staging entity registry
    python -m vitalgraph.db.migrations.migrate_registry_embedding_columns \\
        --dsn "..." --registry entity \\
        --target-provider paraphrase_multilingual_minilm_l12_v2

    # agent registry (historical default)
    python -m vitalgraph.db.migrations.migrate_registry_embedding_columns \\
        --dsn "..." --registry agent --target-provider vitalsigns_onnx

    # once verified, reclaim the space
    python -m vitalgraph.db.migrations.migrate_registry_embedding_columns \\
        --dsn "..." --registry entity \\
        --target-provider <same-as-before> --drop-legacy
"""

import asyncio
import logging
from typing import Optional

import asyncpg

from vitalgraph.vectorization.registry_vector_config import EMBEDDING_COLUMNS, OPENAI

logger = logging.getLogger(__name__)

DEFAULT_TARGET_PROVIDER = "vitalsigns_onnx"
REGISTRIES = ("entity", "agent")


class _Registry:
    """Everything the migration needs to know about one registry's schema."""

    def __init__(self, name: str):
        if name == "entity":
            from vitalgraph.entity_registry import entity_registry_vector_schema as sch
            self.tables = (sch.ENTITY_VECTOR_TABLE, sch.LOCATION_VECTOR_TABLE)
            self.seed_index = "entity"
        elif name == "agent":
            from vitalgraph.agent_registry import agent_registry_vector_schema as sch
            self.tables = (sch.AGENT_VECTOR_TABLE,)
            self.seed_index = "agent"
        else:
            raise ValueError(
                f"Unknown registry {name!r}: choose one of {', '.join(REGISTRIES)}"
            )

        self.name = name
        self.catalog_table = sch.VECTOR_INDEX_TABLE
        self.index_prefix = sch.VECTOR_TABLE_INDEX_PREFIX
        self.legacy_column = sch.LEGACY_EMBEDDING_COLUMN
        self.legacy_indexes = sch.LEGACY_HNSW_INDEXES
        self.index_ddl = sch.embedding_index_ddl


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------

async def _table_exists(conn: asyncpg.Connection, table: str) -> bool:
    return bool(await conn.fetchval("SELECT to_regclass($1)", table))


async def _column_width(
    conn: asyncpg.Connection, table: str, column: str,
) -> Optional[int]:
    """Return the declared vector(N) width, or None if the column is absent."""
    row = await conn.fetchrow(
        """
        SELECT format_type(a.atttypid, a.atttypmod) AS type
        FROM pg_attribute a
        WHERE a.attrelid = $1::regclass AND a.attname = $2 AND NOT a.attisdropped
        """,
        table, column,
    )
    if row is None:
        return None
    t = row["type"]                      # e.g. 'vector(384)'
    if "(" not in t:
        return None
    return int(t.split("(")[1].rstrip(")"))


# ---------------------------------------------------------------------------
# Migration steps
# ---------------------------------------------------------------------------

async def _add_columns(conn, table: str, dry_run: bool) -> None:
    for column, dims in EMBEDDING_COLUMNS.values():
        existing = await _column_width(conn, table, column)
        if existing == dims:
            logger.info("  %s.%s already present (vector(%d))", table, column, dims)
            continue
        if existing is not None:
            raise RuntimeError(
                f"{table}.{column} exists as vector({existing}) but the schema "
                f"expects vector({dims}). Refusing to alter it — inspect this "
                f"table by hand."
            )
        sql = f"ALTER TABLE {table} ADD COLUMN {column} vector({dims})"
        logger.info("  %s%s", "[dry-run] " if dry_run else "", sql)
        if not dry_run:
            await conn.execute(sql)


async def _copy_legacy_data(
    conn, reg: _Registry, table: str, target_column: str, dry_run: bool,
) -> int:
    """Copy legacy `embedding` values into the chosen per-model column."""
    legacy = reg.legacy_column

    # Under --dry-run the ALTER never ran, so the target column may not exist
    # yet. Count against the legacy column alone in that case.
    target_exists = await _column_width(conn, table, target_column) is not None

    if target_exists:
        to_copy = await conn.fetchval(
            f"SELECT count(*) FROM {table} "
            f"WHERE {legacy} IS NOT NULL AND {target_column} IS NULL"
        )
        already = await conn.fetchval(
            f"SELECT count(*) FROM {table} WHERE {target_column} IS NOT NULL"
        )
        if already:
            logger.info(
                "  %s.%s already holds %d row(s) — those are left untouched",
                table, target_column, already,
            )
    else:
        to_copy = await conn.fetchval(
            f"SELECT count(*) FROM {table} WHERE {legacy} IS NOT NULL"
        )

    if not to_copy:
        logger.info("  %s: nothing to copy into %s", table, target_column)
        return 0

    logger.info(
        "  %s%d row(s): %s.%s -> %s",
        "[dry-run] " if dry_run else "", to_copy, table, legacy, target_column,
    )
    if dry_run:
        return to_copy

    await conn.execute(
        f"UPDATE {table} SET {target_column} = {legacy} "
        f"WHERE {legacy} IS NOT NULL AND {target_column} IS NULL"
    )
    remaining = await conn.fetchval(
        f"SELECT count(*) FROM {table} "
        f"WHERE {legacy} IS NOT NULL AND {target_column} IS NULL"
    )
    if remaining:
        raise RuntimeError(
            f"{table}: {remaining} row(s) still uncopied after UPDATE — aborting"
        )
    return to_copy


async def _create_indexes(conn, reg: _Registry, table: str, dry_run: bool) -> None:
    """Build the per-model HNSW indexes, reusing the schema module's DDL."""
    for sql in reg.index_ddl(table, reg.index_prefix[table]):
        name = sql.split("IF NOT EXISTS")[1].split()[0]
        logger.info("  %sCREATE INDEX %s", "[dry-run] " if dry_run else "", name)
        if not dry_run:
            await conn.execute(sql)


async def _drop_legacy(conn, reg: _Registry, table: str, dry_run: bool) -> None:
    for sql in (
        f"DROP INDEX IF EXISTS {reg.legacy_indexes[table]}",
        f"ALTER TABLE {table} DROP COLUMN IF EXISTS {reg.legacy_column}",
    ):
        logger.info("  %s%s", "[dry-run] " if dry_run else "", sql)
        if not dry_run:
            await conn.execute(sql)


async def _update_catalog(
    conn, reg: _Registry, target_provider: str, dry_run: bool,
) -> None:
    """Point the vector-index catalog row at the model the data came from."""
    if not await _table_exists(conn, reg.catalog_table):
        return
    dims = EMBEDDING_COLUMNS[target_provider][1]
    logger.info(
        "  %s%s: provider -> %s, dimensions -> %d",
        "[dry-run] " if dry_run else "", reg.catalog_table, target_provider, dims,
    )
    if not dry_run:
        await conn.execute(
            f"UPDATE {reg.catalog_table} SET provider = $1, dimensions = $2 "
            f"WHERE index_name = $3",
            target_provider, dims, reg.seed_index,
        )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

async def migrate_embedding_columns(
    conn: asyncpg.Connection,
    registry: str = "entity",
    target_provider: str = DEFAULT_TARGET_PROVIDER,
    dry_run: bool = False,
    drop_legacy: bool = False,
) -> None:
    reg = _Registry(registry)

    if target_provider not in EMBEDDING_COLUMNS:
        raise ValueError(
            f"Unknown --target-provider {target_provider!r}. "
            f"Choose one of: {', '.join(sorted(EMBEDDING_COLUMNS))}"
        )
    if target_provider == OPENAI:
        raise ValueError(
            "Legacy registry vectors are 384-wide and cannot be OpenAI "
            "embeddings (1536). Re-vectorize with the openai provider instead "
            "of migrating existing data into it."
        )

    target_column, target_dims = EMBEDDING_COLUMNS[target_provider]
    mode = "DRY RUN" if dry_run else "LIVE"
    logger.info(
        "%s registry embedding-column migration [%s] — legacy data -> %s (%s)",
        reg.name, mode, target_column, target_provider,
    )

    for table in reg.tables:
        if not await _table_exists(conn, table):
            logger.info("%s: absent, skipping", table)
            continue
        logger.info("%s:", table)

        legacy_width = await _column_width(conn, table, reg.legacy_column)

        await _add_columns(conn, table, dry_run)

        if legacy_width is None:
            logger.info(
                "  no legacy '%s' column — already migrated, nothing to copy",
                reg.legacy_column,
            )
        else:
            if legacy_width != target_dims:
                raise RuntimeError(
                    f"{table}.{reg.legacy_column} is vector({legacy_width}) "
                    f"but target {target_column} is vector({target_dims}). "
                    f"These vectors were not produced by {target_provider!r}."
                )
            await _copy_legacy_data(conn, reg, table, target_column, dry_run)

        await _create_indexes(conn, reg, table, dry_run)

        if drop_legacy and legacy_width is not None:
            await _drop_legacy(conn, reg, table, dry_run)
        elif legacy_width is not None:
            logger.info(
                "  keeping '%s' (pass --drop-legacy once the copy is verified)",
                reg.legacy_column,
            )

    await _update_catalog(conn, reg, target_provider, dry_run)
    logger.info("Migration [%s] complete.", mode)


async def run_migration(
    dsn: Optional[str] = None,
    registry: str = "entity",
    target_provider: str = DEFAULT_TARGET_PROVIDER,
    dry_run: bool = False,
    drop_legacy: bool = False,
    **kwargs,
) -> None:
    conn = await asyncpg.connect(dsn) if dsn else await asyncpg.connect(**kwargs)
    try:
        if dry_run:
            await migrate_embedding_columns(
                conn, registry, target_provider, dry_run=True,
                drop_legacy=drop_legacy,
            )
        else:
            # One transaction: a partial copy would leave rows split across two
            # columns with no record of which is authoritative.
            async with conn.transaction():
                await migrate_embedding_columns(
                    conn, registry, target_provider, dry_run=False,
                    drop_legacy=drop_legacy,
                )
    finally:
        await conn.close()


def main():
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(
        description="Migrate registry vector tables to per-model embedding columns",
    )
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--database", default="vitalgraph")
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--password", default="")
    parser.add_argument("--dsn", default=None, help="Full DSN (overrides other params)")
    parser.add_argument(
        "--registry", default="entity", choices=REGISTRIES,
        help="Which registry's vector tables to migrate",
    )
    parser.add_argument(
        "--target-provider", default=DEFAULT_TARGET_PROVIDER,
        choices=sorted(EMBEDDING_COLUMNS),
        help="Which model produced the existing `embedding` data. STAGING's "
             "entity registry uses paraphrase_multilingual_minilm_l12_v2.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be done, change nothing")
    parser.add_argument("--drop-legacy", action="store_true",
                        help="Drop the old `embedding` column and its index "
                             "(do this only after verifying the copy)")
    args = parser.parse_args()

    common = dict(
        registry=args.registry,
        target_provider=args.target_provider,
        dry_run=args.dry_run,
        drop_legacy=args.drop_legacy,
    )
    if args.dsn:
        asyncio.run(run_migration(dsn=args.dsn, **common))
    else:
        asyncio.run(run_migration(
            host=args.host, port=args.port, database=args.database,
            user=args.user, password=args.password, **common,
        ))


if __name__ == "__main__":
    main()
