"""
Direct Entity Registry Tests - ID Generation

Tests ID format, uniqueness, URI conversion.
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from vitalgraph.entity_registry.entity_registry_id import (
    generate_entity_id,
    entity_id_to_uri,
    uri_to_entity_id,
    is_valid_entity_id,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger(__name__)


class IdGenerationTests:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def check(self, name: str, condition: bool, detail: str = ""):
        if condition:
            self.passed += 1
            logger.info(f"  ✅ {name}{' - ' + detail if detail else ''}")
        else:
            self.failed += 1
            logger.error(f"  ❌ {name}{' - ' + detail if detail else ''}")

    def run(self):
        self.test_generate_id_format()
        self.test_uniqueness()
        self.test_uri_conversion()
        self.test_validation()

        total = self.passed + self.failed
        logger.info(f"\nResults: {self.passed}/{total} passed, {self.failed} failed")
        return self.failed == 0

    def test_generate_id_format(self):
        logger.info("\n--- ID Format ---")
        eid = generate_entity_id()
        self.check("Starts with e_", eid.startswith('e_'), eid)
        self.check("Total length 12 (e_ + 10)", len(eid) == 12, f"len={len(eid)}")

        # Characters should be base36 (lowercase alphanumeric)
        suffix = eid[2:]
        valid_chars = set('0123456789abcdefghijklmnopqrstuvwxyz')
        self.check("All chars base36", all(c in valid_chars for c in suffix), suffix)

    def test_uniqueness(self):
        logger.info("\n--- Uniqueness ---")
        ids = {generate_entity_id() for _ in range(1000)}
        self.check("1000 unique IDs", len(ids) == 1000, f"unique={len(ids)}")

    def test_uri_conversion(self):
        logger.info("\n--- URI Conversion ---")
        eid = generate_entity_id()
        uri = entity_id_to_uri(eid)
        self.check("URI starts with urn:entity:", uri.startswith('urn:entity:'), uri)
        self.check("URI contains entity_id", eid in uri)

        # Round-trip
        back = uri_to_entity_id(uri)
        self.check("Round-trip URI -> ID", back == eid, f"{uri} -> {back}")

        # Invalid URI
        try:
            uri_to_entity_id('invalid:uri')
            self.check("Invalid URI raises error", False)
        except ValueError:
            self.check("Invalid URI raises ValueError", True)

    def test_validation(self):
        logger.info("\n--- Validation ---")
        eid = generate_entity_id()
        self.check("Valid ID passes", is_valid_entity_id(eid))
        self.check("Missing prefix fails", not is_valid_entity_id('abc1234567'))
        self.check("Too short fails", not is_valid_entity_id('e_abc'))
        self.check("Empty fails", not is_valid_entity_id(''))
        self.check("None fails", not is_valid_entity_id(None))


def main():
    tests = IdGenerationTests()
    success = tests.run()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
