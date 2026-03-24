"""
Direct Entity Registry Tests - Change Log

Tests that all operations produce correct changelog entries, filtering.
"""

import asyncio
import logging
import os
import sys
import traceback

import asyncpg

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from vitalgraph.entity_registry.entity_registry_impl import EntityRegistryImpl

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger(__name__)


async def get_pool() -> asyncpg.Pool:
    return await asyncpg.create_pool(
        host=os.environ.get('PGHOST', 'localhost'),
        port=int(os.environ.get('PGPORT', '5432')),
        user=os.environ.get('PGUSER', 'vitalgraph'),
        password=os.environ.get('PGPASSWORD', 'vitalgraph'),
        database=os.environ.get('PGDATABASE', 'vitalgraph'),
        min_size=1, max_size=5,
    )


class ChangeLogTests:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.registry: EntityRegistryImpl = None
        self.entity_id: str = None

    def check(self, name: str, condition: bool, detail: str = ""):
        if condition:
            self.passed += 1
            logger.info(f"  ✅ {name}{' - ' + detail if detail else ''}")
        else:
            self.failed += 1
            logger.error(f"  ❌ {name}{' - ' + detail if detail else ''}")

    async def run(self):
        pool = await get_pool()
        try:
            self.registry = EntityRegistryImpl(pool)
            await self.registry.ensure_tables()

            await self.test_entity_lifecycle_log()
            await self.test_filter_by_change_type()
            await self.test_recent_changes()
        except Exception as e:
            logger.error(f"Test error: {e}")
            traceback.print_exc()
        finally:
            await pool.close()

        total = self.passed + self.failed
        logger.info(f"\nResults: {self.passed}/{total} passed, {self.failed} failed")
        return self.failed == 0

    async def test_entity_lifecycle_log(self):
        logger.info("\n--- Entity Lifecycle Log ---")

        # Create entity
        entity = await self.registry.create_entity(
            type_key='business', primary_name='ChangeLog Test Corp',
            created_by='test_script',
        )
        self.entity_id = entity['entity_id']

        # Update entity
        await self.registry.update_entity(
            entity_id=self.entity_id, description='Updated',
            updated_by='test_script',
        )

        # Add alias
        alias = await self.registry.add_alias(
            entity_id=self.entity_id, alias_name='CLT Corp',
            alias_type='abbreviation', created_by='test_script',
        )

        # Add identifier
        ident = await self.registry.add_identifier(
            entity_id=self.entity_id, identifier_namespace='TEST',
            identifier_value='CL-001', created_by='test_script',
        )

        # Remove alias
        await self.registry.remove_alias(alias['alias_id'])

        # Remove identifier
        await self.registry.remove_identifier(ident['identifier_id'])

        # Soft-delete
        await self.registry.delete_entity(self.entity_id)

        # Fetch full change log
        entries, total = await self.registry.get_change_log(entity_id=self.entity_id)
        change_types = [e['change_type'] for e in entries]
        logger.info(f"  Change types: {change_types}")

        self.check("Has entity_created", 'entity_created' in change_types)
        self.check("Has entity_updated", 'entity_updated' in change_types)
        self.check("Has alias_added", 'alias_added' in change_types)
        self.check("Has alias_retracted", 'alias_retracted' in change_types)
        self.check("Has identifier_added", 'identifier_added' in change_types)
        self.check("Has identifier_retracted", 'identifier_retracted' in change_types)
        self.check("Has entity_deleted", 'entity_deleted' in change_types)
        self.check("Total >= 7 entries", total >= 7, f"total={total}")

    async def test_filter_by_change_type(self):
        logger.info("\n--- Filter by Change Type ---")
        entries, total = await self.registry.get_change_log(
            entity_id=self.entity_id, change_type='entity_created',
        )
        self.check("Filter entity_created", total == 1, f"total={total}")

        entries2, total2 = await self.registry.get_change_log(
            entity_id=self.entity_id, change_type='alias_added',
        )
        self.check("Filter alias_added", total2 >= 1, f"total={total2}")

    async def test_recent_changes(self):
        logger.info("\n--- Recent Changes (global) ---")
        entries = await self.registry.get_recent_changes(limit=10)
        self.check("Recent changes not empty", len(entries) > 0, f"count={len(entries)}")
        # Should be ordered newest first
        if len(entries) >= 2:
            self.check("Ordered newest first",
                        entries[0]['created_time'] >= entries[1]['created_time'])


async def main():
    tests = ChangeLogTests()
    success = await tests.run()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    asyncio.run(main())
