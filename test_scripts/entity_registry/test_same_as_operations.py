"""
Direct Entity Registry Tests - Same-As Operations

Tests create/retract same-as, transitive resolution, cycle prevention.
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


class SameAsTests:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.registry: EntityRegistryImpl = None
        self.entity_ids = []

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

            # Create three entities: A, B, C for chain testing
            for name in ['SameAs Entity A', 'SameAs Entity B', 'SameAs Entity C']:
                entity = await self.registry.create_entity(
                    type_key='business', primary_name=name, created_by='test_script',
                )
                self.entity_ids.append(entity['entity_id'])
            logger.info(f"Test entities: {self.entity_ids}")

            await self.test_create_same_as()
            await self.test_get_same_as()
            await self.test_transitive_resolution()
            await self.test_retract_same_as()
            await self.test_cycle_prevention()
        except Exception as e:
            logger.error(f"Test error: {e}")
            traceback.print_exc()
        finally:
            await pool.close()

        total = self.passed + self.failed
        logger.info(f"\nResults: {self.passed}/{total} passed, {self.failed} failed")
        return self.failed == 0

    async def test_create_same_as(self):
        logger.info("\n--- Create Same-As ---")
        a, b, c = self.entity_ids

        # A -> B
        mapping = await self.registry.create_same_as(
            source_entity_id=a, target_entity_id=b,
            relationship_type='same_as', reason='Duplicate detected',
            created_by='test_script',
        )
        self.check("Create A->B", mapping is not None)
        self.check("Source correct", mapping['source_entity_id'] == a)
        self.check("Target correct", mapping['target_entity_id'] == b)
        self.check("Status active", mapping['status'] == 'active')

        # B -> C (creates chain A -> B -> C)
        mapping2 = await self.registry.create_same_as(
            source_entity_id=b, target_entity_id=c,
            relationship_type='merged_into', created_by='test_script',
        )
        self.check("Create B->C", mapping2 is not None)

    async def test_get_same_as(self):
        logger.info("\n--- Get Same-As ---")
        a = self.entity_ids[0]
        mappings = await self.registry.get_same_as(a)
        self.check("Get same-as for A", len(mappings) >= 1, f"count={len(mappings)}")
        self.check("Source is A", mappings[0]['source_entity_id'] == a)

    async def test_transitive_resolution(self):
        logger.info("\n--- Transitive Resolution ---")
        a, b, c = self.entity_ids

        # Resolve A -> should end up at C (A->B->C)
        resolved = await self.registry.resolve_entity(a)
        self.check("A resolves to C (transitive)", resolved['entity_id'] == c,
                    f"resolved to {resolved['entity_id']}")

        # Resolve B -> should end up at C
        resolved2 = await self.registry.resolve_entity(b)
        self.check("B resolves to C", resolved2['entity_id'] == c)

        # Resolve C -> should be itself (no outgoing same-as)
        resolved3 = await self.registry.resolve_entity(c)
        self.check("C resolves to self", resolved3['entity_id'] == c)

    async def test_retract_same_as(self):
        logger.info("\n--- Retract Same-As ---")
        a, b, c = self.entity_ids

        # Get the A->B mapping
        mappings = await self.registry.get_same_as(a)
        if not mappings:
            self.check("Retract same-as", False, "No mappings found for A")
            return
        mapping_id = mappings[0]['same_as_id']

        retracted = await self.registry.retract_same_as(
            same_as_id=mapping_id, retracted_by='test_script', reason='Testing retraction',
        )
        self.check("Retract returns True", retracted is True)

        # After retracting A->B, A should resolve to self
        resolved = await self.registry.resolve_entity(a)
        self.check("A resolves to self after retraction", resolved['entity_id'] == a,
                    f"resolved to {resolved['entity_id']}")

        # B still resolves to C
        resolved2 = await self.registry.resolve_entity(b)
        self.check("B still resolves to C", resolved2['entity_id'] == c)

    async def test_cycle_prevention(self):
        logger.info("\n--- Cycle Prevention ---")
        a, b, c = self.entity_ids

        # Try to create C -> A (would form a cycle through B->C and the retracted A->B)
        # First re-create A->B
        await self.registry.create_same_as(
            source_entity_id=a, target_entity_id=b,
            relationship_type='same_as', created_by='test_script',
        )

        # Now try C->A — should be rejected as it would form a cycle
        try:
            await self.registry.create_same_as(
                source_entity_id=c, target_entity_id=a,
                relationship_type='same_as', created_by='test_script',
            )
            self.check("Cycle prevention", False, "Should have raised ValueError")
        except ValueError as e:
            self.check("Cycle prevention raises ValueError", 'cycle' in str(e).lower(),
                        str(e)[:80])
        except Exception as e:
            self.check("Cycle prevention", False, f"Unexpected error: {e}")


async def main():
    tests = SameAsTests()
    success = await tests.run()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    asyncio.run(main())
