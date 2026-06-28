#!/usr/bin/env python3
"""
VitalGraph FTS & Search Mapping Endpoints Integration Test (JWT Client)

Integration test for:
  - Search Mappings: list, create, get, update, delete
  - Search Mapping Properties: add, remove
  - FTS Indexes: list, create, stats, update_languages, delete
  - FTS Populate: trigger population

Architecture: Uses client-based testing against a live server.
Requires environment variables for server connection.

Usage:
    python vitalgraph_client_test/test_fts_search_mapping_endpoints.py
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


class FtsSearchMappingEndpointTester:
    """Integration test runner for FTS indexes and search mapping endpoints."""

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

    # ==================================================================
    # FTS Indexes CRUD
    # ==================================================================

    async def test_list_fts_indexes_initial(self):
        """List FTS indexes on fresh space — may contain bootstrapped indexes."""
        logger.info("\n── List FTS Indexes (initial) ──")
        try:
            resp = await self.client.fts_indexes.list_indexes(space_id=self.space_id)
            indexes = resp.indexes if hasattr(resp, 'indexes') else resp.get("indexes", [])
            # Space bootstrap may create kgtype_default; just verify the call works
            self._record("FTS List (initial)", isinstance(indexes, list),
                         details=f"count={len(indexes)}")
        except Exception as e:
            self._record("FTS List (initial)", False, error=str(e))

    async def test_create_fts_index(self) -> str:
        """Create an FTS index and return its index_name."""
        logger.info("\n── Create FTS Index ──")
        index_name = ""
        try:
            resp = await self.client.fts_indexes.create_index(
                space_id=self.space_id,
                index_name="test_fts_default",
                languages=["english"],
            )
            index_name = resp.index_name if hasattr(resp, 'index_name') else resp.get("index_name", "")
            created = bool(index_name)
            self._record("FTS Create", created, details=f"index_name={index_name}")

            # Verify fields
            languages = resp.languages if hasattr(resp, 'languages') else resp.get("languages", [])
            self._record("Languages correct", languages == ["english"],
                         details=f"languages={languages}")
            index_id = resp.index_id if hasattr(resp, 'index_id') else resp.get("index_id", 0)
            self._record("Has index_id", index_id > 0, details=f"index_id={index_id}")

        except Exception as e:
            self._record("FTS Create", False, error=str(e))
        return index_name

    async def test_create_fts_multi_language(self) -> str:
        """Create a multi-language FTS index."""
        logger.info("\n── Create Multi-Language FTS Index ──")
        index_name = ""
        try:
            resp = await self.client.fts_indexes.create_index(
                space_id=self.space_id,
                index_name="test_fts_multi",
                languages=["english", "spanish"],
            )
            index_name = resp.index_name if hasattr(resp, 'index_name') else resp.get("index_name", "")
            languages = resp.languages if hasattr(resp, 'languages') else resp.get("languages", [])
            self._record("FTS Multi-lang Create", len(languages) == 2,
                         details=f"languages={languages}")
        except Exception as e:
            self._record("FTS Multi-lang Create", False, error=str(e))
        return index_name

    async def test_list_fts_indexes_after_create(self):
        """List FTS indexes after creation — should find 2."""
        logger.info("\n── List FTS Indexes (after create) ──")
        try:
            resp = await self.client.fts_indexes.list_indexes(space_id=self.space_id)
            indexes = resp.indexes if hasattr(resp, 'indexes') else resp.get("indexes", [])
            self._record("FTS List (after create)", len(indexes) >= 2,
                         details=f"count={len(indexes)}")
        except Exception as e:
            self._record("FTS List (after create)", False, error=str(e))

    async def test_fts_stats(self, index_name: str):
        """Get FTS index stats — should return zeros for empty index."""
        logger.info("\n── FTS Stats ──")
        try:
            resp = await self.client.fts_indexes.get_stats(
                space_id=self.space_id,
                index_name=index_name,
            )
            row_count = resp.row_count if hasattr(resp, 'row_count') else resp.get("row_count", -1)
            self._record("FTS Stats returns data", row_count >= 0,
                         details=f"row_count={row_count}")
        except Exception as e:
            self._record("FTS Stats returns data", False, error=str(e))

    async def test_update_fts_languages(self, index_name: str):
        """Update languages for an FTS index."""
        logger.info("\n── Update FTS Languages ──")
        try:
            resp = await self.client.fts_indexes.update_languages(
                space_id=self.space_id,
                index_name=index_name,
                languages=["english", "french"],
                refresh_tsv=False,
            )
            languages = resp.languages if hasattr(resp, 'languages') else resp.get("languages", [])
            self._record("FTS Update Languages", "french" in languages,
                         details=f"languages={languages}")
        except Exception as e:
            self._record("FTS Update Languages", False, error=str(e))

    async def test_delete_fts_index(self, index_name: str):
        """Delete an FTS index."""
        logger.info("\n── Delete FTS Index ──")
        try:
            resp = await self.client.fts_indexes.delete_index(
                space_id=self.space_id,
                index_name=index_name,
            )
            deleted = resp.deleted if hasattr(resp, 'deleted') else resp.get("deleted", False)
            self._record(f"FTS Delete ({index_name})", deleted is True,
                         details=f"deleted={deleted}")
        except Exception as e:
            self._record(f"FTS Delete ({index_name})", False, error=str(e))

    # ==================================================================
    # Search Mappings CRUD
    # ==================================================================

    async def test_list_mappings_empty(self):
        """List search mappings — should return empty list."""
        logger.info("\n── List Search Mappings (empty) ──")
        try:
            resp = await self.client.search_mappings.list_mappings(space_id=self.space_id)
            mappings = resp.mappings if hasattr(resp, 'mappings') else resp.get("mappings", [])
            self._record("SM List (empty)", len(mappings) == 0,
                         details=f"count={len(mappings)}")
        except Exception as e:
            self._record("SM List (empty)", False, error=str(e))

    async def test_create_mapping(self, index_name: str) -> int:
        """Create a search mapping tied to an FTS index."""
        logger.info("\n── Create Search Mapping ──")
        mapping_id = 0
        try:
            resp = await self.client.search_mappings.create_mapping(
                space_id=self.space_id,
                index_name=index_name,
                mapping_type="kgentity",
                type_uri="http://vital.ai/test#TestEntity",
                enabled=True,
                source_type="properties",
                separator=". ",
                include_pred_name=True,
                include_type_desc=True,
            )
            mapping_id = resp.mapping_id if hasattr(resp, 'mapping_id') else resp.get("mapping_id", 0)
            created = mapping_id > 0
            self._record("SM Create", created, details=f"mapping_id={mapping_id}")

            # Verify fields
            mapping_type = resp.mapping_type if hasattr(resp, 'mapping_type') else resp.get("mapping_type")
            source_type = resp.source_type if hasattr(resp, 'source_type') else resp.get("source_type")
            include_pred_name = resp.include_pred_name if hasattr(resp, 'include_pred_name') else resp.get("include_pred_name")
            self._record("SM mapping_type correct", mapping_type == "kgentity",
                         details=f"mapping_type={mapping_type}")
            self._record("SM source_type correct", source_type == "properties",
                         details=f"source_type={source_type}")
            self._record("SM include_pred_name correct", include_pred_name is True,
                         details=f"include_pred_name={include_pred_name}")

        except Exception as e:
            self._record("SM Create", False, error=str(e))
        return mapping_id

    async def test_get_mapping(self, mapping_id: int):
        """Get a single search mapping by ID."""
        logger.info("\n── Get Search Mapping ──")
        try:
            resp = await self.client.search_mappings.get_mapping(
                space_id=self.space_id,
                mapping_id=mapping_id,
            )
            mid = resp.mapping_id if hasattr(resp, 'mapping_id') else resp.get("mapping_id", 0)
            self._record("SM Get", mid == mapping_id, details=f"mapping_id={mid}")
        except Exception as e:
            self._record("SM Get", False, error=str(e))

    async def test_list_mappings_after_create(self):
        """List search mappings after creation — should find at least 1."""
        logger.info("\n── List Search Mappings (after create) ──")
        try:
            resp = await self.client.search_mappings.list_mappings(space_id=self.space_id)
            mappings = resp.mappings if hasattr(resp, 'mappings') else resp.get("mappings", [])
            self._record("SM List (after create)", len(mappings) >= 1,
                         details=f"count={len(mappings)}")
        except Exception as e:
            self._record("SM List (after create)", False, error=str(e))

    async def test_list_mappings_filter_by_type(self, index_name: str):
        """Filter search mappings by mapping_type."""
        logger.info("\n── List Search Mappings (filter by type) ──")
        try:
            resp = await self.client.search_mappings.list_mappings(
                space_id=self.space_id,
                mapping_type="kgentity",
            )
            mappings = resp.mappings if hasattr(resp, 'mappings') else resp.get("mappings", [])
            all_correct = all(
                (m.mapping_type if hasattr(m, 'mapping_type') else m.get("mapping_type")) == "kgentity"
                for m in mappings
            )
            self._record("SM List filter type=kgentity", all_correct and len(mappings) >= 1,
                         details=f"count={len(mappings)}")
        except Exception as e:
            self._record("SM List filter type=kgentity", False, error=str(e))

    async def test_update_mapping(self, mapping_id: int):
        """Update a search mapping (disable + change separator)."""
        logger.info("\n── Update Search Mapping ──")
        try:
            resp = await self.client.search_mappings.update_mapping(
                space_id=self.space_id,
                mapping_id=mapping_id,
                enabled=False,
                separator=" | ",
            )
            enabled = resp.enabled if hasattr(resp, 'enabled') else resp.get("enabled")
            separator = resp.separator if hasattr(resp, 'separator') else resp.get("separator")
            self._record("SM Update enabled=False", enabled is False,
                         details=f"enabled={enabled}")
            self._record("SM Update separator", separator == " | ",
                         details=f"separator={repr(separator)}")
        except Exception as e:
            self._record("SM Update", False, error=str(e))

    async def test_add_properties(self, mapping_id: int) -> tuple:
        """Add child properties to a search mapping."""
        logger.info("\n── Add Properties ──")
        pid1, pid2 = 0, 0
        try:
            resp1 = await self.client.search_mappings.add_property(
                space_id=self.space_id,
                mapping_id=mapping_id,
                property_uri="http://vital.ai/test#hasName",
                property_role="include",
                ordinal=1,
            )
            pid1 = resp1.property_id if hasattr(resp1, 'property_id') else resp1.get("property_id", 0)
            self._record("SM Add Property 1", pid1 > 0, details=f"property_id={pid1}")

            resp2 = await self.client.search_mappings.add_property(
                space_id=self.space_id,
                mapping_id=mapping_id,
                property_uri="http://vital.ai/test#hasDescription",
                property_role="include",
                ordinal=2,
            )
            pid2 = resp2.property_id if hasattr(resp2, 'property_id') else resp2.get("property_id", 0)
            self._record("SM Add Property 2", pid2 > 0, details=f"property_id={pid2}")

        except Exception as e:
            self._record("SM Add Properties", False, error=str(e))
        return pid1, pid2

    async def test_verify_properties_in_get(self, mapping_id: int, expected_count: int):
        """Verify properties appear in GET mapping response."""
        logger.info("\n── Verify Properties in GET ──")
        try:
            resp = await self.client.search_mappings.get_mapping(
                space_id=self.space_id,
                mapping_id=mapping_id,
            )
            props = resp.properties if hasattr(resp, 'properties') else resp.get("properties", [])
            self._record("SM Properties in GET", len(props) == expected_count,
                         details=f"property_count={len(props)}")
        except Exception as e:
            self._record("SM Properties in GET", False, error=str(e))

    async def test_remove_property(self, mapping_id: int, property_id: int):
        """Remove a child property from a search mapping."""
        logger.info("\n── Remove Property ──")
        try:
            resp = await self.client.search_mappings.remove_property(
                space_id=self.space_id,
                mapping_id=mapping_id,
                property_id=property_id,
            )
            deleted = resp.deleted if hasattr(resp, 'deleted') else resp.get("deleted", False)
            self._record("SM Remove Property", deleted is True,
                         details=f"deleted={deleted}")
        except Exception as e:
            self._record("SM Remove Property", False, error=str(e))

    async def test_delete_mapping(self, mapping_id: int):
        """Delete a search mapping (CASCADE)."""
        logger.info("\n── Delete Search Mapping ──")
        try:
            resp = await self.client.search_mappings.delete_mapping(
                space_id=self.space_id,
                mapping_id=mapping_id,
            )
            deleted = resp.deleted if hasattr(resp, 'deleted') else resp.get("deleted", False)
            self._record("SM Delete", deleted is True, details=f"deleted={deleted}")
        except Exception as e:
            self._record("SM Delete", False, error=str(e))

    # ==================================================================
    # Error Cases
    # ==================================================================

    async def test_error_cases(self):
        """Test error handling for invalid operations."""
        logger.info("\n── Error Cases ──")

        # Get non-existent mapping
        try:
            await self.client.search_mappings.get_mapping(
                space_id=self.space_id,
                mapping_id=999999,
            )
            self._record("SM Get non-existent → 404", False, details="No error raised")
        except VitalGraphClientError as e:
            self._record("SM Get non-existent → 404", "404" in str(e) or "not found" in str(e).lower(),
                         details=str(e)[:80])
        except Exception as e:
            self._record("SM Get non-existent → 404", "404" in str(e) or "not found" in str(e).lower(),
                         details=str(e)[:80])

        # Delete non-existent FTS index
        try:
            await self.client.fts_indexes.delete_index(
                space_id=self.space_id,
                index_name="nonexistent_index",
            )
            self._record("FTS Delete non-existent → 404", False, details="No error raised")
        except VitalGraphClientError as e:
            self._record("FTS Delete non-existent → 404", "404" in str(e) or "not found" in str(e).lower(),
                         details=str(e)[:80])
        except Exception as e:
            self._record("FTS Delete non-existent → 404", "404" in str(e) or "not found" in str(e).lower(),
                         details=str(e)[:80])


# ==================================================================
# Main test orchestration
# ==================================================================

async def test_fts_search_mapping_endpoints() -> bool:
    """Run full FTS + Search Mapping endpoint integration tests."""

    logger.info("=" * 80)
    logger.info("FTS & Search Mapping Endpoint Integration Tests")
    logger.info("=" * 80)

    client = None
    test_space_id = "fts_sm_test_space"

    try:
        # Connect
        logger.info("\n1. Connecting to VitalGraph server...")
        client = VitalGraphClient()
        await client.open()
        logger.info("   ✓ Connected")

        # Create test space
        logger.info(f"\n2. Setting up test space: {test_space_id}")
        try:
            spaces_response: SpacesListResponse = await client.list_spaces()
            existing = next((s for s in spaces_response.spaces if s.space == test_space_id), None)
            if existing:
                await client.delete_space(test_space_id)
        except Exception:
            pass

        await client.add_space(Space(
            space=test_space_id,
            space_name="FTS & Search Mapping Test Space",
            space_description="Integration test space for FTS and search mapping endpoints",
            tenant="test_tenant",
        ))
        logger.info(f"   ✓ Space created: {test_space_id}")

        # Run tests
        tester = FtsSearchMappingEndpointTester(client, test_space_id)

        logger.info("\n3. Running endpoint tests...")

        # === FTS Index lifecycle ===
        await tester.test_list_fts_indexes_initial()
        fts_index_name = await tester.test_create_fts_index()
        fts_multi_name = await tester.test_create_fts_multi_language()
        await tester.test_list_fts_indexes_after_create()

        if fts_index_name:
            await tester.test_fts_stats(fts_index_name)
            await tester.test_update_fts_languages(fts_index_name)

        # === Search Mapping lifecycle ===
        await tester.test_list_mappings_empty()

        mapping_id = 0
        if fts_index_name:
            mapping_id = await tester.test_create_mapping(fts_index_name)

        if mapping_id > 0:
            await tester.test_get_mapping(mapping_id)
            await tester.test_list_mappings_after_create()
            await tester.test_list_mappings_filter_by_type(fts_index_name)
            await tester.test_update_mapping(mapping_id)

            # Properties
            pid1, pid2 = await tester.test_add_properties(mapping_id)
            if pid1 > 0 and pid2 > 0:
                await tester.test_verify_properties_in_get(mapping_id, expected_count=2)
            if pid2 > 0:
                await tester.test_remove_property(mapping_id, pid2)
                await tester.test_verify_properties_in_get(mapping_id, expected_count=1)

            # Delete mapping
            await tester.test_delete_mapping(mapping_id)

        # === Cleanup FTS indexes ===
        if fts_index_name:
            await tester.test_delete_fts_index(fts_index_name)
        if fts_multi_name:
            await tester.test_delete_fts_index(fts_multi_name)

        # === Error cases ===
        await tester.test_error_cases()

        # Cleanup space
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
            logger.info(f"\n🎉 All FTS & Search Mapping endpoint tests PASSED!")

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
    success = await test_fts_search_mapping_endpoints()
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
