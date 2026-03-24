"""
Direct Entity Registry Tests - Entity CRUD

Tests entity create, get, update, soft-delete, and search
directly against EntityRegistryImpl using asyncpg.
"""

import asyncio
import logging
import os
import sys
import traceback

import asyncpg

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from vitalgraph.entity_registry.entity_registry_impl import EntityRegistryImpl
from vitalgraph.entity_registry.entity_registry_id import is_valid_entity_id, entity_id_to_uri

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger(__name__)


async def get_pool() -> asyncpg.Pool:
    """Create an asyncpg connection pool from environment variables."""
    return await asyncpg.create_pool(
        host=os.environ.get('PGHOST', 'localhost'),
        port=int(os.environ.get('PGPORT', '5432')),
        user=os.environ.get('PGUSER', 'vitalgraph'),
        password=os.environ.get('PGPASSWORD', 'vitalgraph'),
        database=os.environ.get('PGDATABASE', 'vitalgraph'),
        min_size=1,
        max_size=5,
    )


class EntityCrudTests:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.registry: EntityRegistryImpl = None
        self.created_ids = []

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
            logger.info("Entity Registry tables ensured")

            await self.test_create_entity()
            await self.test_get_entity()
            await self.test_update_entity()
            await self.test_search_entities()
            await self.test_soft_delete()
        except Exception as e:
            logger.error(f"Test error: {e}")
            traceback.print_exc()
        finally:
            await pool.close()

        total = self.passed + self.failed
        logger.info(f"\nResults: {self.passed}/{total} passed, {self.failed} failed")
        return self.failed == 0

    async def test_create_entity(self):
        logger.info("\n--- Create Entity ---")
        entity = await self.registry.create_entity(
            type_key='business',
            primary_name='Test Corp',
            description='A test corporation',
            country='US',
            region='New York',
            locality='Manhattan',
            website='https://test.example.com',
            created_by='test_script',
        )
        self.check("Entity created", entity is not None)
        self.check("Has entity_id", 'entity_id' in entity)
        self.check("Valid entity_id format", is_valid_entity_id(entity['entity_id']),
                    entity.get('entity_id', ''))
        self.check("Has entity_uri", entity.get('entity_uri', '').startswith('urn:entity:'))
        self.check("Status is active", entity.get('status') == 'active')
        self.created_ids.append(entity['entity_id'])

        # Create with aliases and identifiers
        entity2 = await self.registry.create_entity(
            type_key='person',
            primary_name='Jane Doe',
            country='US',
            created_by='test_script',
            aliases=[
                {'alias_name': 'J. Doe', 'alias_type': 'abbreviation'},
            ],
            identifiers=[
                {'identifier_namespace': 'SSN', 'identifier_value': '999-00-1234'},
            ],
        )
        self.check("Entity with alias+identifier created", entity2 is not None)
        self.created_ids.append(entity2['entity_id'])

    async def test_get_entity(self):
        logger.info("\n--- Get Entity ---")
        if not self.created_ids:
            self.check("Get entity", False, "No entities created")
            return
        entity = await self.registry.get_entity(self.created_ids[0])
        self.check("Get by ID", entity is not None)
        self.check("Name matches", entity['primary_name'] == 'Test Corp')
        self.check("Country matches", entity['country'] == 'US')
        self.check("Has type_key", entity.get('type_key') == 'business')

        # Get entity with aliases/identifiers
        entity2 = await self.registry.get_entity(self.created_ids[1])
        self.check("Get entity with sub-objects", entity2 is not None)
        self.check("Has aliases", entity2.get('aliases') is not None and len(entity2['aliases']) >= 1)
        self.check("Has identifiers", entity2.get('identifiers') is not None and len(entity2['identifiers']) >= 1)

        # Non-existent
        missing = await self.registry.get_entity('e_zzzzzzzzzz')
        self.check("Non-existent returns None", missing is None)

    async def test_update_entity(self):
        logger.info("\n--- Update Entity ---")
        if not self.created_ids:
            self.check("Update entity", False, "No entities created")
            return
        updated = await self.registry.update_entity(
            entity_id=self.created_ids[0],
            description='Updated description',
            website='https://updated.example.com',
            updated_by='test_script',
        )
        self.check("Update returns entity", updated is not None)
        self.check("Description updated", updated['description'] == 'Updated description')
        self.check("Website updated", updated['website'] == 'https://updated.example.com')

        # Verify via fresh get
        fetched = await self.registry.get_entity(self.created_ids[0])
        self.check("Persisted update", fetched['description'] == 'Updated description')

    async def test_search_entities(self):
        logger.info("\n--- Search Entities ---")
        # Search by name
        results, total = await self.registry.search_entities(query='Test Corp')
        self.check("Search by name", total >= 1, f"total={total}")

        # Search by type
        results2, total2 = await self.registry.search_entities(type_key='person')
        self.check("Search by type", total2 >= 1, f"total={total2}")

        # Pagination
        results3, total3 = await self.registry.search_entities(page=1, page_size=1)
        self.check("Pagination page_size=1", len(results3) == 1)

    async def test_soft_delete(self):
        logger.info("\n--- Soft Delete ---")
        if len(self.created_ids) < 2:
            self.check("Soft delete", False, "Need >= 2 entities")
            return
        deleted = await self.registry.delete_entity(self.created_ids[1])
        self.check("Delete returns True", deleted is True)

        # Should be excluded from active search
        results, total = await self.registry.search_entities(status='active')
        active_ids = [e['entity_id'] for e in results]
        self.check("Excluded from active search", self.created_ids[1] not in active_ids)

        # Still retrievable directly
        entity = await self.registry.get_entity(self.created_ids[1])
        self.check("Still retrievable", entity is not None)
        self.check("Status is deleted", entity['status'] == 'deleted')


async def main():
    tests = EntityCrudTests()
    success = await tests.run()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    asyncio.run(main())
