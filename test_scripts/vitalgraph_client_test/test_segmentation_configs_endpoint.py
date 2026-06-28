#!/usr/bin/env python3
"""
VitalGraph Segmentation Configs Endpoint Test (JWT Client)

Integration test script for KGDocuments segmentation config CRUD operations:
  - list_segmentation_configs
  - create_segmentation_config
  - update_segmentation_config
  - delete_segmentation_config

Architecture: Uses client-based testing with modular test cases against a live server.
Requires environment variables for server connection (same as other client tests).
"""

import sys
import os
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError
from vitalgraph.model.spaces_model import Space, SpacesListResponse

from vitalgraph_client_test.segmentation_configs.case_config_create import ConfigCreateTester
from vitalgraph_client_test.segmentation_configs.case_config_list import ConfigListTester
from vitalgraph_client_test.segmentation_configs.case_config_update import ConfigUpdateTester
from vitalgraph_client_test.segmentation_configs.case_config_delete import ConfigDeleteTester

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)


async def test_segmentation_configs_endpoint() -> bool:
    """
    Test segmentation config CRUD operations against a live server.

    Returns:
        bool: True if all tests passed
    """
    print("=" * 80)
    print("VitalGraph Segmentation Configs Endpoint Test (JWT Client)")
    print("=" * 80)

    test_results = {
        'total_tests': 0,
        'passed_tests': 0,
        'failed_tests': [],
        'test_details': [],
    }

    test_space_id = "space_seg_config_test"
    client = None
    created_config_id = None

    try:
        # 1. Connect
        print("\n1. Initializing and connecting JWT client...")
        client = VitalGraphClient()
        await client.open()
        print(f"   ✓ Connected: {client.is_connected()}")

        # 2. Set up test space
        print("\n2. Setting up test space...")
        spaces_response: SpacesListResponse = await client.list_spaces()
        existing = next((s for s in spaces_response.spaces if s.space == test_space_id), None)

        if existing:
            print(f"   ⚠️  Deleting existing test space '{test_space_id}'...")
            await client.delete_space(test_space_id)

        space_data = Space(
            space=test_space_id,
            space_name="Segmentation Config Test Space",
            space_description="Dedicated space for segmentation config endpoint testing",
            tenant="test_tenant",
        )
        create_resp = await client.add_space(space_data)
        if create_resp and create_resp.created_count == 1:
            print(f"   ✓ Test space created: {test_space_id}")
        else:
            print(f"   ❌ Failed to create test space")
            return False

        # 3. Create config
        print("\n3. Testing segmentation config creation...")
        create_tester = ConfigCreateTester(client)
        create_results = await create_tester.run_tests(test_space_id)
        test_results['test_details'].append(create_results)
        test_results['total_tests'] += create_results['total_tests']
        test_results['passed_tests'] += create_results['passed_tests']

        # Extract config_id for subsequent tests
        for r in create_results['results']:
            if r.get('passed') and r.get('config_id'):
                created_config_id = r['config_id']
                break

        if create_results['passed']:
            print(f"   ✓ Create tests PASSED ({create_results['passed_tests']}/{create_results['total_tests']})")
        else:
            print(f"   ❌ Create tests FAILED")
            test_results['failed_tests'].extend(
                [r['name'] for r in create_results['results'] if not r['passed']]
            )

        # 4. List configs
        print("\n4. Testing segmentation config listing...")
        list_tester = ConfigListTester(client)
        list_results = await list_tester.run_tests(test_space_id, expected_min=1)
        test_results['test_details'].append(list_results)
        test_results['total_tests'] += list_results['total_tests']
        test_results['passed_tests'] += list_results['passed_tests']

        if list_results['passed']:
            print(f"   ✓ List tests PASSED ({list_results['passed_tests']}/{list_results['total_tests']})")
        else:
            print(f"   ❌ List tests FAILED")
            test_results['failed_tests'].extend(
                [r['name'] for r in list_results['results'] if not r['passed']]
            )

        # 5. Update config
        if created_config_id is not None:
            print("\n5. Testing segmentation config update...")
            update_tester = ConfigUpdateTester(client)
            update_results = await update_tester.run_tests(test_space_id, created_config_id)
            test_results['test_details'].append(update_results)
            test_results['total_tests'] += update_results['total_tests']
            test_results['passed_tests'] += update_results['passed_tests']

            if update_results['passed']:
                print(f"   ✓ Update tests PASSED ({update_results['passed_tests']}/{update_results['total_tests']})")
            else:
                print(f"   ❌ Update tests FAILED")
                test_results['failed_tests'].extend(
                    [r['name'] for r in update_results['results'] if not r['passed']]
                )
        else:
            print("\n5. ⚠️  Skipping update tests (no config_id from create)")

        # 6. Delete config
        if created_config_id is not None:
            print("\n6. Testing segmentation config deletion...")
            delete_tester = ConfigDeleteTester(client)
            delete_results = await delete_tester.run_tests(test_space_id, created_config_id)
            test_results['test_details'].append(delete_results)
            test_results['total_tests'] += delete_results['total_tests']
            test_results['passed_tests'] += delete_results['passed_tests']

            if delete_results['passed']:
                print(f"   ✓ Delete tests PASSED ({delete_results['passed_tests']}/{delete_results['total_tests']})")
            else:
                print(f"   ❌ Delete tests FAILED")
                test_results['failed_tests'].extend(
                    [r['name'] for r in delete_results['results'] if not r['passed']]
                )
        else:
            print("\n6. ⚠️  Skipping delete tests (no config_id from create)")

        # 7. Cleanup
        print(f"\n7. Cleaning up test space...")
        try:
            await client.delete_space(test_space_id)
            print(f"   ✓ Test space deleted: {test_space_id}")
        except Exception as e:
            print(f"   ⚠️  Cleanup warning: {e}")

        await client.close()
        print(f"\n8. Client closed")

        # Summary
        all_passed = len(test_results['failed_tests']) == 0
        print(f"\n{'=' * 80}")
        print(f"📊 Test Summary:")
        print(f"   Total:  {test_results['total_tests']}")
        print(f"   Passed: {test_results['passed_tests']}")
        print(f"   Failed: {len(test_results['failed_tests'])}")

        if test_results['failed_tests']:
            print(f"   Failed: {', '.join(test_results['failed_tests'])}")

        print(f"\n📋 Detailed Results:")
        for detail in test_results['test_details']:
            for r in detail['results']:
                status = "✓" if r['passed'] else "❌"
                print(f"   {status} {r['name']}")
                if not r['passed'] and 'error' in r:
                    print(f"     Error: {r['error']}")

        if all_passed:
            print(f"\n🎉 All segmentation config tests PASSED!")
        else:
            print(f"\n❌ Some tests FAILED")

        return all_passed

    except VitalGraphClientError as e:
        print(f"\n❌ VitalGraph client error: {e}")
        return False
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
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
    success = await test_segmentation_configs_endpoint()
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
