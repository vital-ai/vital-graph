"""
Direct Entity Registry Tests - Identifier Operations

Tests add/remove/lookup identifiers, multi-namespace, lookup-by-value.
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


class IdentifierTests:
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

            # Create a test entity
            entity = await self.registry.create_entity(
                type_key='business', primary_name='Identifier Test Corp',
                created_by='test_script',
            )
            self.entity_id = entity['entity_id']
            logger.info(f"Test entity created: {self.entity_id}")

            await self.test_add_identifiers()
            await self.test_list_identifiers()
            await self.test_lookup_by_identifier()
            await self.test_remove_identifier()
            await self.test_multi_namespace()
        except Exception as e:
            logger.error(f"Test error: {e}")
            traceback.print_exc()
        finally:
            await pool.close()

        total = self.passed + self.failed
        logger.info(f"\nResults: {self.passed}/{total} passed, {self.failed} failed")
        return self.failed == 0

    async def test_add_identifiers(self):
        logger.info("\n--- Add Identifiers ---")
        ident1 = await self.registry.add_identifier(
            entity_id=self.entity_id, identifier_namespace='DUNS',
            identifier_value='987654321', is_primary=True, created_by='test_script',
        )
        self.check("Add DUNS identifier", ident1 is not None)
        self.check("Namespace correct", ident1['identifier_namespace'] == 'DUNS')
        self.check("Value correct", ident1['identifier_value'] == '987654321')
        self.check("Is primary", ident1['is_primary'] is True)
        self.check("Status active", ident1['status'] == 'active')

        ident2 = await self.registry.add_identifier(
            entity_id=self.entity_id, identifier_namespace='EIN',
            identifier_value='12-3456789', created_by='test_script',
        )
        self.check("Add EIN identifier", ident2 is not None)

    async def test_list_identifiers(self):
        logger.info("\n--- List Identifiers ---")
        idents = await self.registry.list_identifiers(self.entity_id)
        self.check("List returns 2", len(idents) == 2, f"got {len(idents)}")

    async def test_lookup_by_identifier(self):
        logger.info("\n--- Lookup by Identifier ---")
        entities = await self.registry.lookup_by_identifier('DUNS', '987654321')
        self.check("Lookup DUNS found", len(entities) >= 1, f"count={len(entities)}")
        found_ids = [e['entity_id'] for e in entities]
        self.check("Lookup returns correct entity", self.entity_id in found_ids)

        entities2 = await self.registry.lookup_by_identifier('EIN', '12-3456789')
        self.check("Lookup EIN found", len(entities2) >= 1)

        missing = await self.registry.lookup_by_identifier('DUNS', 'nonexistent')
        self.check("Lookup missing returns empty list", len(missing) == 0)

    async def test_remove_identifier(self):
        logger.info("\n--- Remove Identifier ---")
        idents = await self.registry.list_identifiers(self.entity_id)
        ein_ident = [i for i in idents if i['identifier_namespace'] == 'EIN'][0]
        removed = await self.registry.remove_identifier(ein_ident['identifier_id'])
        self.check("Remove returns True", removed is True)

        # Verify no longer in active list
        idents_after = await self.registry.list_identifiers(self.entity_id)
        self.check("List after removal", len(idents_after) == 1, f"got {len(idents_after)}")

        # Lookup should fail
        missing = await self.registry.lookup_by_identifier('EIN', '12-3456789')
        ein_ids = [e['entity_id'] for e in missing]
        self.check("Lookup retracted identifier excludes entity", self.entity_id not in ein_ids)

    async def test_multi_namespace(self):
        logger.info("\n--- Multi-Namespace ---")
        await self.registry.add_identifier(
            entity_id=self.entity_id, identifier_namespace='CRM',
            identifier_value='ACCT-001', created_by='test_script',
        )
        await self.registry.add_identifier(
            entity_id=self.entity_id, identifier_namespace='TICKER',
            identifier_value='ITST', created_by='test_script',
        )
        idents = await self.registry.list_identifiers(self.entity_id)
        namespaces = {i['identifier_namespace'] for i in idents}
        self.check("Multiple namespaces", namespaces == {'DUNS', 'CRM', 'TICKER'},
                    f"namespaces={namespaces}")


async def main():
    tests = IdentifierTests()
    success = await tests.run()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    asyncio.run(main())
