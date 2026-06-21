#!/usr/bin/env python3
"""
VitalGraph Metrics Endpoint Test (JWT Client)

Integration test script for Metrics endpoint operations:
  - get_metrics (realtime, 24h, 7d, 30d)
  - get_slow_queries

Architecture: Uses client-based testing against a live server.
Requires environment variables for server connection.
"""

import sys
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError
from vitalgraph.model.spaces_model import Space, SpacesListResponse

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)


async def test_metrics_endpoint() -> bool:
    """
    Test metrics endpoint operations against a live server.

    Returns:
        bool: True if all tests passed
    """
    print("=" * 80)
    print("VitalGraph Metrics Endpoint Test (JWT Client)")
    print("=" * 80)

    results = []
    test_space_id = "space_metrics_test"
    client = None

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
            await client.delete_space(test_space_id)

        space_data = Space(
            space=test_space_id,
            space_name="Metrics Test Space",
            space_description="Dedicated space for metrics endpoint testing",
            tenant="test_tenant",
        )
        await client.add_space(space_data)
        print(f"   ✓ Test space created: {test_space_id}")

        # 3. Test get_metrics for each range
        for time_range in ["realtime", "24h", "7d", "30d"]:
            print(f"\n3. Testing get_metrics(range='{time_range}')...")
            try:
                response = await client.metrics.get_metrics(
                    space_id=test_space_id,
                    range=time_range,
                )
                success = response.get("success", False)
                has_timestamps = "timestamps" in response
                has_series = "series" in response
                has_totals = "totals" in response

                passed = success and has_timestamps and has_series and has_totals
                results.append({
                    'name': f'get_metrics(range={time_range})',
                    'passed': passed,
                    'details': f"success={success}, timestamps={has_timestamps}, series={has_series}, totals={has_totals}",
                })
                status = "✓" if passed else "❌"
                print(f"   {status} success={success}, has timestamps/series/totals={has_timestamps}/{has_series}/{has_totals}")
            except Exception as e:
                results.append({
                    'name': f'get_metrics(range={time_range})',
                    'passed': False,
                    'error': str(e),
                })
                print(f"   ❌ Exception: {e}")

        # 4. Test get_slow_queries
        print(f"\n4. Testing get_slow_queries...")
        try:
            response = await client.metrics.get_slow_queries(
                space_id=test_space_id,
                limit=10,
            )
            success = response.get("success", False)
            has_queries = "slow_queries" in response

            passed = success and has_queries
            results.append({
                'name': 'get_slow_queries',
                'passed': passed,
                'details': f"success={success}, has slow_queries={has_queries}, count={len(response.get('slow_queries', []))}",
            })
            status = "✓" if passed else "❌"
            print(f"   {status} success={success}, slow_queries present={has_queries}")
        except Exception as e:
            results.append({
                'name': 'get_slow_queries',
                'passed': False,
                'error': str(e),
            })
            print(f"   ❌ Exception: {e}")

        # 5. Cleanup
        print(f"\n5. Cleaning up...")
        try:
            await client.delete_space(test_space_id)
            print(f"   ✓ Test space deleted")
        except Exception as e:
            print(f"   ⚠️  Cleanup: {e}")

        await client.close()

        # Summary
        passed_count = sum(1 for r in results if r['passed'])
        failed = [r for r in results if not r['passed']]
        all_passed = len(failed) == 0

        print(f"\n{'=' * 80}")
        print(f"📊 Test Summary: {passed_count}/{len(results)} passed")
        for r in results:
            status = "✓" if r['passed'] else "❌"
            print(f"   {status} {r['name']}")
            if not r['passed'] and 'error' in r:
                print(f"     Error: {r['error']}")

        if all_passed:
            print(f"\n🎉 All metrics endpoint tests PASSED!")
        else:
            print(f"\n❌ {len(failed)} test(s) FAILED")

        return all_passed

    except VitalGraphClientError as e:
        print(f"\n❌ Client error: {e}")
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
    success = await test_metrics_endpoint()
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
