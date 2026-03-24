"""
Entity Registry - Run All Direct Tests

Runs all direct entity registry test scripts in sequence.
"""

import asyncio
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger(__name__)


async def main():
    start = time.time()
    all_passed = True

    # ID generation tests (sync, no DB needed)
    logger.info("\n" + "=" * 60)
    logger.info("Running: test_id_generation")
    logger.info("=" * 60)
    from test_id_generation import IdGenerationTests
    id_tests = IdGenerationTests()
    if not id_tests.run():
        all_passed = False

    # Entity CRUD tests
    logger.info("\n" + "=" * 60)
    logger.info("Running: test_entity_crud")
    logger.info("=" * 60)
    from test_entity_crud import EntityCrudTests
    crud_tests = EntityCrudTests()
    if not await crud_tests.run():
        all_passed = False

    # Identifier tests
    logger.info("\n" + "=" * 60)
    logger.info("Running: test_identifier_operations")
    logger.info("=" * 60)
    from test_identifier_operations import IdentifierTests
    ident_tests = IdentifierTests()
    if not await ident_tests.run():
        all_passed = False

    # Alias tests
    logger.info("\n" + "=" * 60)
    logger.info("Running: test_alias_operations")
    logger.info("=" * 60)
    from test_alias_operations import AliasTests
    alias_tests = AliasTests()
    if not await alias_tests.run():
        all_passed = False

    # Same-As tests
    logger.info("\n" + "=" * 60)
    logger.info("Running: test_same_as_operations")
    logger.info("=" * 60)
    from test_same_as_operations import SameAsTests
    same_as_tests = SameAsTests()
    if not await same_as_tests.run():
        all_passed = False

    # Change Log tests
    logger.info("\n" + "=" * 60)
    logger.info("Running: test_change_log")
    logger.info("=" * 60)
    from test_change_log import ChangeLogTests
    cl_tests = ChangeLogTests()
    if not await cl_tests.run():
        all_passed = False

    elapsed = time.time() - start
    logger.info("\n" + "=" * 60)
    logger.info(f"ALL TESTS {'PASSED' if all_passed else 'FAILED'} in {elapsed:.1f}s")
    logger.info("=" * 60)

    sys.exit(0 if all_passed else 1)


if __name__ == '__main__':
    asyncio.run(main())
