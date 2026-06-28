"""Debug: call list_segments to see what happens."""
import asyncio
from vitalgraph.client.vitalgraph_client import VitalGraphClient

async def main():
    c = VitalGraphClient()
    await c.open()
    
    # Call list_segments
    resp = await c.kgdocuments.list_segments(
        space_id="sp_semantic_search_test",
        graph_id="urn:semantic_search_test",
        parent_uri="urn:semantic_test:doc:tokyo_food_guide",
    )
    print(f"is_success: {resp.is_success}")
    print(f"count: {resp.count}")
    print(f"segments: {len(resp.segments) if resp.segments else 0}")
    if hasattr(resp, 'error_message') and resp.error_message:
        print(f"error: {resp.error_message}")
    if resp.segments:
        for s in resp.segments[:3]:
            print(f"  URI: {getattr(s, 'URI', '?')}")
            print(f"  segIndex: {getattr(s, 'kGDocumentSegmentIndex', '?')}")
    
    await c.close()

asyncio.run(main())
