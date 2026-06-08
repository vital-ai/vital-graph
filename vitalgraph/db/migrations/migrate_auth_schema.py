"""
Auth schema migration script.

Migrates existing user tables to support the modernized authentication system:
- Adds new columns (password_hash, role, full_name, is_active, token_version, etc.)
- Creates user_space_access table
- Creates api_key table
- Hashes existing plaintext passwords

Can be run standalone or called from the admin CLI.
"""

import asyncio
import logging
import sys
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)


async def migrate_auth_schema(conn: asyncpg.Connection) -> None:
    """Migrate user table to support modern auth.

    Args:
        conn: Active asyncpg connection.
    """
    logger.info("Starting auth schema migration...")

    # 1. Add new columns to user table
    logger.info("Step 1: Adding new columns to user table...")
    await conn.execute('''
        ALTER TABLE "user" ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255);
        ALTER TABLE "user" ADD COLUMN IF NOT EXISTS full_name VARCHAR(255);
        ALTER TABLE "user" ADD COLUMN IF NOT EXISTS role VARCHAR(50) NOT NULL DEFAULT 'user';
        ALTER TABLE "user" ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true;
        ALTER TABLE "user" ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE "user" ADD COLUMN IF NOT EXISTS created_time TIMESTAMPTZ DEFAULT now();
        ALTER TABLE "user" ADD COLUMN IF NOT EXISTS last_login TIMESTAMPTZ;
    ''')

    # 2. Create user_space_access table
    logger.info("Step 2: Creating user_space_access table...")
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS user_space_access (
            user_id INTEGER NOT NULL REFERENCES "user"(user_id) ON DELETE CASCADE,
            space_id VARCHAR(255) NOT NULL,
            access_level VARCHAR(2) NOT NULL CHECK (access_level IN ('rw', 'r')),
            granted_by VARCHAR(255),
            granted_time TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (user_id, space_id)
        )
    ''')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_usa_space ON user_space_access(space_id)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_usa_user ON user_space_access(user_id)')

    # 3. Hash existing plaintext passwords
    logger.info("Step 3: Migrating plaintext passwords to bcrypt...")
    rows = await conn.fetch(
        'SELECT user_id, password FROM "user" WHERE password IS NOT NULL AND password_hash IS NULL'
    )
    if rows:
        from vitalgraph.auth.password import hash_password
        for row in rows:
            hashed = hash_password(row['password'])
            await conn.execute(
                'UPDATE "user" SET password_hash = $1 WHERE user_id = $2',
                hashed, row['user_id']
            )
        logger.info(f"  Migrated {len(rows)} password(s) to bcrypt")
    else:
        logger.info("  No plaintext passwords to migrate")

    # 4. Set existing users to admin role if they don't have one set
    await conn.execute('''
        UPDATE "user" SET role = 'admin'
        WHERE role = 'user' AND user_id = (
            SELECT MIN(user_id) FROM "user"
        ) AND NOT EXISTS (
            SELECT 1 FROM "user" WHERE role = 'admin'
        )
    ''')

    # 5. Create API key table
    logger.info("Step 4: Creating api_key table...")
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS api_key (
            key_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            key_prefix VARCHAR(8) NOT NULL,
            key_hash VARCHAR(255) NOT NULL,
            user_id INTEGER NOT NULL REFERENCES "user"(user_id) ON DELETE CASCADE,
            name VARCHAR(255) NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_time TIMESTAMPTZ DEFAULT now(),
            last_used TIMESTAMPTZ,
            expires_at TIMESTAMPTZ
        )
    ''')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_apikey_prefix ON api_key(key_prefix)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_apikey_user ON api_key(user_id)')

    # 6. Create audit_log table
    logger.info("Step 5: Creating audit_log table...")
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS audit_log (
            id BIGSERIAL PRIMARY KEY,
            timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
            event VARCHAR(50) NOT NULL,
            actor VARCHAR(255),
            target VARCHAR(255),
            ip INET,
            user_agent TEXT,
            details JSONB,
            level VARCHAR(10) NOT NULL DEFAULT 'INFO'
        )
    ''')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp DESC)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_log(event)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_log(actor)')

    logger.info("Auth schema migration complete.")


async def run_migration(dsn: Optional[str] = None, **kwargs) -> None:
    """Run migration using a DSN or connection parameters.

    Args:
        dsn: PostgreSQL DSN string. If None, uses kwargs for connection params.
        **kwargs: Connection params (host, port, database, user, password).
    """
    if dsn:
        conn = await asyncpg.connect(dsn)
    else:
        conn = await asyncpg.connect(**kwargs)

    try:
        async with conn.transaction():
            await migrate_auth_schema(conn)
    finally:
        await conn.close()


def main():
    """CLI entrypoint for running the migration standalone."""
    import argparse

    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    parser = argparse.ArgumentParser(description="Migrate VitalGraph auth schema")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--database", default="vitalgraph")
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--password", default="")
    parser.add_argument("--dsn", default=None, help="Full DSN (overrides other params)")
    args = parser.parse_args()

    if args.dsn:
        asyncio.run(run_migration(dsn=args.dsn))
    else:
        asyncio.run(run_migration(
            host=args.host,
            port=args.port,
            database=args.database,
            user=args.user,
            password=args.password,
        ))


if __name__ == "__main__":
    main()
