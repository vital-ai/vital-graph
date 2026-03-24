"""
Direct Entity Registry Tests - Alias Operations

Tests add/retract aliases, search by alias, DBA/AKA types.
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


class AliasTests:
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

            entity = await self.registry.create_entity(
                type_key='business', primary_name='Alias Test Corp',
                created_by='test_script',
            )
            self.entity_id = entity['entity_id']
            logger.info(f"Test entity created: {self.entity_id}")

            await self.test_add_aliases()
            await self.test_list_aliases()
            await self.test_alias_types()
            await self.test_search_by_alias()
            await self.test_remove_alias()
        except Exception as e:
            logger.error(f"Test error: {e}")
            traceback.print_exc()
        finally:
            await pool.close()

        total = self.passed + self.failed
        logger.info(f"\nResults: {self.passed}/{total} passed, {self.failed} failed")
        return self.failed == 0

    async def test_add_aliases(self):
        logger.info("\n--- Add Aliases ---")
        alias1 = await self.registry.add_alias(
            entity_id=self.entity_id, alias_name='ATC',
            alias_type='abbreviation', is_primary=False, created_by='test_script',
        )
        self.check("Add abbreviation alias", alias1 is not None)
        self.check("Alias name correct", alias1['alias_name'] == 'ATC')
        self.check("Alias type correct", alias1['alias_type'] == 'abbreviation')
        self.check("Status active", alias1['status'] == 'active')

        alias2 = await self.registry.add_alias(
            entity_id=self.entity_id, alias_name='Alias Test Trading Co',
            alias_type='dba', created_by='test_script',
        )
        self.check("Add DBA alias", alias2 is not None)

    async def test_list_aliases(self):
        logger.info("\n--- List Aliases ---")
        aliases = await self.registry.list_aliases(self.entity_id)
        self.check("List returns 2", len(aliases) == 2, f"got {len(aliases)}")

    async def test_alias_types(self):
        logger.info("\n--- Alias Types ---")
        # Add various types
        for alias_type in ['former', 'aka', 'trade_name']:
            alias = await self.registry.add_alias(
                entity_id=self.entity_id, alias_name=f'Test {alias_type} Name',
                alias_type=alias_type, created_by='test_script',
            )
            self.check(f"Add '{alias_type}' alias", alias is not None and alias['alias_type'] == alias_type)

        aliases = await self.registry.list_aliases(self.entity_id)
        types = {a['alias_type'] for a in aliases}
        self.check("All alias types present",
                    types == {'abbreviation', 'dba', 'former', 'aka', 'trade_name'},
                    f"types={types}")

    async def test_search_by_alias(self):
        logger.info("\n--- Search by Alias ---")
        # Search should find entity by its alias text
        results, total = await self.registry.search_entities(query='ATC')
        found_ids = [e['entity_id'] for e in results]
        self.check("Search by alias finds entity", self.entity_id in found_ids,
                    f"total={total}")

        results2, total2 = await self.registry.search_entities(query='Trading Co')
        found_ids2 = [e['entity_id'] for e in results2]
        self.check("Search by DBA alias finds entity", self.entity_id in found_ids2,
                    f"total={total2}")

    async def test_remove_alias(self):
        logger.info("\n--- Remove Alias ---")
        aliases = await self.registry.list_aliases(self.entity_id)
        initial_count = len(aliases)
        target = aliases[0]

        removed = await self.registry.remove_alias(target['alias_id'])
        self.check("Remove returns True", removed is True)

        aliases_after = await self.registry.list_aliases(self.entity_id)
        self.check("List decreased by 1", len(aliases_after) == initial_count - 1,
                    f"before={initial_count}, after={len(aliases_after)}")


async def main():
    tests = AliasTests()
    success = await tests.run()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    asyncio.run(main())
