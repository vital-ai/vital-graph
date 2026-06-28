#!/usr/bin/env python3
"""
VitalGraph Fuzzy Mapping Endpoints Test (JWT Client)

Integration test for:
  - Fuzzy Mappings: list, create, get, update, delete
  - Fuzzy Mapping Properties: add, remove
  - Fuzzy Populate: trigger population
  - Entity Registry find_similar: fuzzy search via client

Architecture: Uses client-based testing against a live server.
Requires environment variables for server connection.

Usage:
    python vitalgraph_client_test/test_fuzzy_mapping_endpoints.py
"""

import sys
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any, List

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError
from vitalgraph.model.spaces_model import Space, SpacesListResponse

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


class FuzzyMappingEndpointTester:
    """Integration test runner for fuzzy mapping endpoints."""

    def __init__(self, client: VitalGraphClient, space_id: str):
        self.client = client
        self.space_id = space_id
        self.results: List[Dict[str, Any]] = []

    def _record(self, name: str, passed: bool, **kwargs):
        entry = {'name': name, 'passed': passed}
        entry.update(kwargs)
        self.results.append(entry)
        status = "✓" if passed else "❌"
        detail = kwargs.get('details', kwargs.get('error', ''))
        logger.info(f"   {status} {name}: {detail}")

    # ------------------------------------------------------------------
    # Fuzzy Mappings CRUD
    # ------------------------------------------------------------------

    async def test_list_mappings_empty(self):
        """List mappings on a fresh space — should return empty list."""
        logger.info("\n── List Fuzzy Mappings (empty) ──")
        try:
            resp = await self.client.fuzzy_mappings.list_mappings(space_id=self.space_id)
            mappings = resp.mappings if hasattr(resp, 'mappings') else resp.get("mappings", [])
            self._record("List (empty space)", True, details=f"count={len(mappings)}")
        except Exception as e:
            self._record("List (empty space)", False, error=str(e))

    async def test_create_mapping(self) -> int:
        """Create a fuzzy mapping and return its mapping_id."""
        logger.info("\n── Create Fuzzy Mapping ──")
        mapping_id = 0
        try:
            resp = await self.client.fuzzy_mappings.create_mapping(
                space_id=self.space_id,
                index_name="test_fuzzy_idx",
                mapping_type="kgentity",
                type_uri="http://vital.ai/test#TestEntity",
                enabled=True,
                shingle_k=3,
                num_perm=64,
                lsh_threshold=0.3,
                phonetic_bonus=10.0,
            )
            mapping_id = resp.mapping_id if hasattr(resp, 'mapping_id') else resp.get("mapping_id", 0)
            created = mapping_id > 0
            self._record("Create mapping", created, details=f"mapping_id={mapping_id}")

            # Verify fields
            index_name = resp.index_name if hasattr(resp, 'index_name') else resp.get("index_name")
            mapping_type = resp.mapping_type if hasattr(resp, 'mapping_type') else resp.get("mapping_type")
            self._record("Index name correct", index_name == "test_fuzzy_idx",
                         details=f"index_name={index_name}")
            self._record("Mapping type correct", mapping_type == "kgentity",
                         details=f"mapping_type={mapping_type}")

            enabled = resp.enabled if hasattr(resp, 'enabled') else resp.get("enabled")
            self._record("Enabled is True", enabled is True, details=f"enabled={enabled}")
        except Exception as e:
            self._record("Create mapping", False, error=str(e))
        return mapping_id

    async def test_list_mappings_after_create(self):
        """List mappings — should include the created mapping."""
        logger.info("\n── List Fuzzy Mappings (after create) ──")
        try:
            resp = await self.client.fuzzy_mappings.list_mappings(space_id=self.space_id)
            mappings = resp.mappings if hasattr(resp, 'mappings') else resp.get("mappings", [])
            self._record("List after create", len(mappings) >= 1,
                         details=f"count={len(mappings)}")

            # Test filter by mapping_type
            resp2 = await self.client.fuzzy_mappings.list_mappings(
                space_id=self.space_id, mapping_type="kgentity",
            )
            filtered = resp2.mappings if hasattr(resp2, 'mappings') else resp2.get("mappings", [])
            self._record("Filter by type=kgentity", len(filtered) >= 1,
                         details=f"count={len(filtered)}")
        except Exception as e:
            self._record("List after create", False, error=str(e))

    async def test_get_mapping(self, mapping_id: int):
        """Get a single mapping by ID."""
        logger.info("\n── Get Fuzzy Mapping ──")
        try:
            resp = await self.client.fuzzy_mappings.get_mapping(
                space_id=self.space_id, mapping_id=mapping_id,
            )
            got_id = resp.mapping_id if hasattr(resp, 'mapping_id') else resp.get("mapping_id")
            self._record("Get mapping by ID", got_id == mapping_id,
                         details=f"mapping_id={got_id}")

            shingle_k = resp.shingle_k if hasattr(resp, 'shingle_k') else resp.get("shingle_k")
            self._record("Shingle K is 3", shingle_k == 3, details=f"shingle_k={shingle_k}")

            lsh_threshold = resp.lsh_threshold if hasattr(resp, 'lsh_threshold') else resp.get("lsh_threshold")
            self._record("LSH threshold is 0.3", abs(lsh_threshold - 0.3) < 0.01,
                         details=f"lsh_threshold={lsh_threshold}")
        except Exception as e:
            self._record("Get mapping", False, error=str(e))

    async def test_update_mapping(self, mapping_id: int):
        """Update mapping parameters."""
        logger.info("\n── Update Fuzzy Mapping ──")
        try:
            resp = await self.client.fuzzy_mappings.update_mapping(
                space_id=self.space_id,
                mapping_id=mapping_id,
                enabled=False,
                lsh_threshold=0.5,
                phonetic_bonus=15.0,
            )
            enabled = resp.enabled if hasattr(resp, 'enabled') else resp.get("enabled")
            self._record("Disabled mapping", enabled is False, details=f"enabled={enabled}")

            lsh = resp.lsh_threshold if hasattr(resp, 'lsh_threshold') else resp.get("lsh_threshold")
            self._record("LSH threshold updated to 0.5", abs(lsh - 0.5) < 0.01,
                         details=f"lsh_threshold={lsh}")

            bonus = resp.phonetic_bonus if hasattr(resp, 'phonetic_bonus') else resp.get("phonetic_bonus")
            self._record("Phonetic bonus updated to 15", abs(bonus - 15.0) < 0.01,
                         details=f"phonetic_bonus={bonus}")

            # Re-enable for subsequent tests
            await self.client.fuzzy_mappings.update_mapping(
                space_id=self.space_id, mapping_id=mapping_id, enabled=True,
            )
        except Exception as e:
            self._record("Update mapping", False, error=str(e))

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    async def test_add_properties(self, mapping_id: int):
        """Add properties to a mapping."""
        logger.info("\n── Add Fuzzy Mapping Properties ──")
        try:
            # Primary name property
            resp1 = await self.client.fuzzy_mappings.add_property(
                space_id=self.space_id,
                mapping_id=mapping_id,
                property_uri="http://vital.ai/ontology/vital-aimp#hasName",
                property_role="primary",
                ordinal=0,
            )
            pid1 = resp1.property_id if hasattr(resp1, 'property_id') else resp1.get("property_id", 0)
            self._record("Add primary property", pid1 > 0, details=f"property_id={pid1}")

            role1 = resp1.property_role if hasattr(resp1, 'property_role') else resp1.get("property_role")
            self._record("Role is 'primary'", role1 == "primary", details=f"role={role1}")

            # Alias property
            resp2 = await self.client.fuzzy_mappings.add_property(
                space_id=self.space_id,
                mapping_id=mapping_id,
                property_uri="http://vital.ai/ontology/vital-aimp#hasAlias",
                property_role="alias",
                ordinal=1,
            )
            pid2 = resp2.property_id if hasattr(resp2, 'property_id') else resp2.get("property_id", 0)
            self._record("Add alias property", pid2 > 0, details=f"property_id={pid2}")

            # Verify properties appear in mapping
            mapping = await self.client.fuzzy_mappings.get_mapping(
                space_id=self.space_id, mapping_id=mapping_id,
            )
            props = mapping.properties if hasattr(mapping, 'properties') else mapping.get("properties", [])
            self._record("Mapping has 2 properties", len(props) == 2,
                         details=f"count={len(props)}")

            return pid1, pid2
        except Exception as e:
            self._record("Add properties", False, error=str(e))
            return 0, 0

    async def test_remove_property(self, mapping_id: int, property_id: int):
        """Remove a property from a mapping."""
        logger.info("\n── Remove Fuzzy Mapping Property ──")
        try:
            resp = await self.client.fuzzy_mappings.remove_property(
                space_id=self.space_id,
                mapping_id=mapping_id,
                property_id=property_id,
            )
            has_message = (resp.get("message") is not None) if isinstance(resp, dict) else (getattr(resp, 'message', None) is not None)
            self._record("Remove property", has_message, details=f"property_id={property_id}")

            # Verify property gone
            mapping = await self.client.fuzzy_mappings.get_mapping(
                space_id=self.space_id, mapping_id=mapping_id,
            )
            props = mapping.properties if hasattr(mapping, 'properties') else mapping.get("properties", [])
            self._record("Property count after removal", len(props) == 1,
                         details=f"count={len(props)}")
        except Exception as e:
            self._record("Remove property", False, error=str(e))

    # ------------------------------------------------------------------
    # Populate
    # ------------------------------------------------------------------

    async def test_populate(self, mapping_id: int):
        """Trigger population for a mapping."""
        logger.info("\n── Populate Fuzzy Index ──")
        try:
            resp = await self.client.fuzzy_mappings.populate(
                space_id=self.space_id, mapping_id=mapping_id,
            )
            has_message = (resp.get("message") is not None) if isinstance(resp, dict) else (getattr(resp, 'message', None) is not None)
            self._record("Populate trigger", has_message,
                         details=f"resp_keys={list(resp.keys()) if isinstance(resp, dict) else type(resp).__name__}")
        except Exception as e:
            self._record("Populate trigger", False, error=str(e))

    # ------------------------------------------------------------------
    # Find Similar (Entity Registry)
    # ------------------------------------------------------------------

    async def test_find_similar(self):
        """Test entity registry find_similar endpoint via client."""
        logger.info("\n── Find Similar (Entity Registry) ──")
        try:
            resp = await self.client.entity_registry.find_similar(
                name="Test Entity",
                limit=5,
                min_score=10.0,
            )
            # Response may have 0 candidates on a test space — that's OK,
            # we're testing the endpoint works (no error)
            candidates = resp.candidates if hasattr(resp, 'candidates') else resp.get("candidates", [])
            self._record("find_similar endpoint works", True,
                         details=f"candidates={len(candidates)}")

            success = resp.success if hasattr(resp, 'success') else resp.get("success", False)
            self._record("find_similar success=True", success is True,
                         details=f"success={success}")
        except Exception as e:
            self._record("find_similar", False, error=str(e))

    async def test_find_similar_with_filters(self):
        """Test find_similar with type/location filters."""
        logger.info("\n── Find Similar (with filters) ──")
        try:
            resp = await self.client.entity_registry.find_similar(
                name="Acme Corporation",
                type_key="business",
                country="US",
                limit=5,
                min_score=10.0,
            )
            candidates = resp.candidates if hasattr(resp, 'candidates') else resp.get("candidates", [])
            self._record("find_similar with filters", True,
                         details=f"candidates={len(candidates)}")
        except Exception as e:
            self._record("find_similar with filters", False, error=str(e))

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    async def test_delete_mapping(self, mapping_id: int):
        """Delete a fuzzy mapping and verify cascade."""
        logger.info("\n── Delete Fuzzy Mapping ──")
        try:
            resp = await self.client.fuzzy_mappings.delete_mapping(
                space_id=self.space_id, mapping_id=mapping_id,
            )
            has_message = (resp.get("message") is not None) if isinstance(resp, dict) else (getattr(resp, 'message', None) is not None)
            self._record("Delete mapping", has_message,
                         details=f"mapping_id={mapping_id}")

            # Verify mapping is gone
            list_resp = await self.client.fuzzy_mappings.list_mappings(space_id=self.space_id)
            mappings = list_resp.mappings if hasattr(list_resp, 'mappings') else list_resp.get("mappings", [])
            ids = [m.mapping_id if hasattr(m, 'mapping_id') else m.get("mapping_id") for m in mappings]
            self._record("Mapping removed from list", mapping_id not in ids,
                         details=f"remaining_ids={ids}")
        except Exception as e:
            self._record("Delete mapping", False, error=str(e))

    # ------------------------------------------------------------------
    # Error Cases
    # ------------------------------------------------------------------

    async def test_error_cases(self):
        """Test expected error conditions."""
        logger.info("\n── Error Cases ──")

        # Get non-existent mapping
        try:
            await self.client.fuzzy_mappings.get_mapping(
                space_id=self.space_id, mapping_id=999999,
            )
            self._record("Get non-existent mapping → error", False,
                         details="Expected error but got success")
        except Exception:
            self._record("Get non-existent mapping → error", True,
                         details="Got expected error")

        # Create with missing index_name
        try:
            await self.client.fuzzy_mappings.create_mapping(
                space_id=self.space_id,
                index_name="",
                mapping_type="kgentity",
            )
            self._record("Create with empty index_name → error", False,
                         details="Expected error but got success")
        except Exception:
            self._record("Create with empty index_name → error", True,
                         details="Got expected error")


async def test_fuzzy_mapping_endpoints() -> bool:
    """Run all fuzzy mapping endpoint tests."""

    logger.info("=" * 80)
    logger.info("VitalGraph Fuzzy Mapping Endpoints Test (JWT Client)")
    logger.info("=" * 80)

    test_space_id = "space_fuzzy_test"
    client = None

    try:
        logger.info("\n1. Connecting...")
        client = VitalGraphClient()
        await client.open()
        logger.info("   ✓ Connected")

        # Space setup
        logger.info("\n2. Setting up test space...")
        spaces_response: SpacesListResponse = await client.list_spaces()
        existing = next((s for s in spaces_response.spaces if s.space == test_space_id), None)
        if existing:
            await client.delete_space(test_space_id)

        await client.add_space(Space(
            space=test_space_id,
            space_name="Fuzzy Mapping Test Space",
            space_description="Integration test space for fuzzy mapping endpoints",
            tenant="test_tenant",
        ))
        logger.info(f"   ✓ Space created: {test_space_id}")

        # Run tests
        tester = FuzzyMappingEndpointTester(client, test_space_id)

        logger.info("\n3. Running endpoint tests...")

        # CRUD lifecycle
        await tester.test_list_mappings_empty()
        mapping_id = await tester.test_create_mapping()

        if mapping_id > 0:
            await tester.test_list_mappings_after_create()
            await tester.test_get_mapping(mapping_id)
            await tester.test_update_mapping(mapping_id)

            # Properties
            pid1, pid2 = await tester.test_add_properties(mapping_id)
            if pid2 > 0:
                await tester.test_remove_property(mapping_id, pid2)

            # Populate
            await tester.test_populate(mapping_id)

            # Delete
            await tester.test_delete_mapping(mapping_id)

        # Entity registry find_similar (independent of mapping lifecycle)
        await tester.test_find_similar()
        await tester.test_find_similar_with_filters()

        # Error cases
        await tester.test_error_cases()

        # Cleanup
        logger.info(f"\n4. Cleanup...")
        try:
            await client.delete_space(test_space_id)
            logger.info(f"   ✓ Space deleted")
        except Exception as e:
            logger.warning(f"   ⚠️  {e}")

        await client.close()

        # Summary
        passed = sum(1 for r in tester.results if r['passed'])
        failed = [r for r in tester.results if not r['passed']]
        total = len(tester.results)

        logger.info(f"\n{'=' * 80}")
        logger.info(f"📊 Test Summary: {passed}/{total} passed")
        if failed:
            for r in failed:
                logger.error(f"   ❌ {r['name']}: {r.get('error', '')}")
            logger.info(f"\n❌ {len(failed)} test(s) FAILED")
        else:
            logger.info(f"\n🎉 All fuzzy mapping endpoint tests PASSED!")

        return len(failed) == 0

    except VitalGraphClientError as e:
        logger.error(f"\n❌ Client error: {e}")
        return False
    except Exception as e:
        logger.error(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if client:
            try:
                await client.close()
            except Exception:
                pass


async def main():
    success = await test_fuzzy_mapping_endpoints()
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
