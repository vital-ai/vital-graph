# Business Events Integration Example

## How to Add Business Events to test_multiple_organizations_crud.py

### Step 1: Add Import

Add this import at the top with the other case imports:

```python
from vitalgraph_client_test.multi_kgentity.case_create_business_events import CreateBusinessEventsTester
```

### Step 2: Add Business Events Creation Step

Add this section after the organization creation step (around line 150):

```python
# ============================================================================
# Step 2: Create Business Events (NEW)
# ============================================================================
print_section("📅 Step 2: Creating Business Events")
event_tester = CreateBusinessEventsTester(client)
event_results = event_tester.run_tests(
    space_id, 
    graph_id, 
    org_results["created_entity_uris"]  # Pass organization URIs
)
all_results.append(event_results)

# Store event URIs for later use
event_uris = event_results["created_event_uris"]
event_reference_ids = event_results["event_reference_ids"]

logger.info(f"✅ Created {len(event_uris)} business events")
logger.info(f"   Event URIs: {event_uris[:3]}...")  # Show first 3
```

### Step 3: Optional - Query Events by Organization

Add this as a new test case to demonstrate querying events for a specific organization:

```python
# ============================================================================
# Step X: Query Events for Specific Organization (OPTIONAL)
# ============================================================================
print_section("🔍 Step X: Query Events for Specific Organization")

# Example: Find all events for TechCorp Industries (first organization)
techcorp_uri = org_uris[0]
logger.info(f"Querying events for organization: {techcorp_uri}")

# List all events in the space
list_response = client.kgentities.list_kgentities(
    space_id=space_id,
    graph_id=graph_id,
    entity_type_uri="http://vital.ai/ontology/haley-ai-kg#BusinessEventEntity",
    page_size=100
)

if list_response.is_success:
    logger.info(f"Found {list_response.count} total business events")
    
    # Filter events that reference TechCorp
    techcorp_events = []
    for entity in list_response.entities:
        # Get entity graph to examine frames
        entity_uri = str(entity.URI)
        graph_response = client.kgentities.get_kgentity_with_entity_graph(
            space_id=space_id,
            graph_id=graph_id,
            uri=entity_uri
        )
        
        if graph_response.is_success:
            # Check if any slot contains the TechCorp URI
            for obj in graph_response.objects:
                if hasattr(obj, 'textSlotValue'):
                    slot_value = str(obj.textSlotValue)
                    if techcorp_uri in slot_value:
                        techcorp_events.append(entity_uri)
                        break
    
    logger.info(f"✅ Found {len(techcorp_events)} events for TechCorp Industries")
    for event_uri in techcorp_events:
        logger.info(f"   - {event_uri}")
```

### Complete Integration Example

Here's the complete flow with business events integrated:

```python
async def main():
    """Run the multiple organizations CRUD test with business events."""
    
    print_section("🏢 Multiple Organizations + Business Events CRUD Test")
    
    # Initialize client
    logger.info("🔧 Initializing VitalGraph client...")
    config_path = project_root / "vitalgraphclient_config" / "vitalgraphclient-config.yaml"
    client = VitalGraphClient(str(config_path))
    
    # Connect
    logger.info("🔐 Connecting to VitalGraph server...")
    client.open()
    
    # Setup space
    space_id = "test_multi_org_events"
    graph_id = "urn:test_multi_org_events"
    
    # Create space
    space = Space(space=space_id)
    client.spaces.create_space(space)
    
    all_results = []
    
    try:
        # ========== STEP 1: Create Organizations ==========
        print_section("🏢 Step 1: Creating 10 Organizations")
        org_tester = CreateOrganizationsTester(client)
        org_results = org_tester.run_tests(space_id, graph_id)
        all_results.append(org_results)
        
        org_uris = org_results["created_entity_uris"]
        org_ref_ids = org_results["reference_ids"]
        
        # ========== STEP 2: Create Business Events (NEW) ==========
        print_section("📅 Step 2: Creating 10 Business Events")
        event_tester = CreateBusinessEventsTester(client)
        event_results = event_tester.run_tests(space_id, graph_id, org_uris)
        all_results.append(event_results)
        
        event_uris = event_results["created_event_uris"]
        event_ref_ids = event_results["event_reference_ids"]
        
        # ========== STEP 3: List All Entities ==========
        print_section("📋 Step 3: Listing All Entities")
        list_tester = ListEntitiesTester(client)
        list_results = list_tester.run_tests(space_id, graph_id)
        all_results.append(list_results)
        
        # ========== STEP 4: Get Individual Organizations ==========
        print_section("🔍 Step 4: Getting Individual Organizations")
        get_tester = GetEntitiesTester(client)
        get_results = get_tester.run_tests(space_id, graph_id, org_uris)
        all_results.append(get_results)
        
        # ========== STEP 5: Get Individual Events (NEW) ==========
        print_section("🔍 Step 5: Getting Individual Business Events")
        get_event_results = get_tester.run_tests(space_id, graph_id, event_uris)
        all_results.append(get_event_results)
        
        # ========== STEP 6: Reference ID Operations ==========
        print_section("🔖 Step 6: Reference ID Operations")
        ref_tester = ReferenceIdOperationsTester(client)
        ref_results = ref_tester.run_tests(space_id, graph_id, org_ref_ids)
        all_results.append(ref_results)
        
        # ========== STEP 7: Update Organizations ==========
        print_section("✏️  Step 7: Updating Organizations")
        update_tester = UpdateEntitiesTester(client)
        update_results = update_tester.run_tests(space_id, graph_id, org_uris)
        all_results.append(update_results)
        
        # ========== STEP 8: Verify Updates ==========
        print_section("✅ Step 8: Verifying Updates")
        verify_tester = VerifyUpdatesTester(client)
        verify_results = verify_tester.run_tests(space_id, graph_id, org_uris)
        all_results.append(verify_results)
        
        # ========== STEP 9: Frame Operations ==========
        print_section("🖼️  Step 9: Frame Operations")
        frame_tester = FrameOperationsTester(client)
        frame_results = frame_tester.run_tests(space_id, graph_id, org_uris)
        all_results.append(frame_results)
        
        # ========== STEP 10: Entity Graph Operations ==========
        print_section("🕸️  Step 10: Entity Graph Operations")
        graph_tester = EntityGraphOperationsTester(client)
        graph_results = graph_tester.run_tests(space_id, graph_id, org_uris)
        all_results.append(graph_results)
        
        # ========== STEP 11: Delete Events First (NEW) ==========
        print_section("🗑️  Step 11: Deleting Business Events")
        delete_event_tester = DeleteEntitiesTester(client)
        delete_event_results = delete_event_tester.run_tests(space_id, graph_id, event_uris)
        all_results.append(delete_event_results)
        
        # ========== STEP 12: Delete Organizations ==========
        print_section("🗑️  Step 12: Deleting Organizations")
        delete_tester = DeleteEntitiesTester(client)
        delete_results = delete_tester.run_tests(space_id, graph_id, org_uris)
        all_results.append(delete_results)
        
    finally:
        # Cleanup
        print_section("🧹 Cleanup")
        logger.info("Deleting test space...")
        client.spaces.delete_space(space_id)
        logger.info("✅ Test space deleted")
        
        client.close()
        logger.info("✅ Client connection closed")
    
    # Print summary
    success = print_test_summary(all_results)
    
    if success:
        logger.info("🎉 All tests passed!")
        return 0
    else:
        logger.error("💥 Some tests failed!")
        return 1
```

## Key Points

1. **Order Matters**: Create organizations first, then events that reference them
2. **Pass URIs**: Event creation needs organization URIs from the previous step
3. **Delete Order**: Delete events before organizations (to avoid orphaned references)
4. **Reuse Testers**: Existing testers (GetEntitiesTester, DeleteEntitiesTester) work for events too
5. **No Breaking Changes**: All existing organization tests continue to work

## Expected Output

```
================================================================================
  📅 Step 2: Creating 10 Business Events
================================================================================

Creating business event 1/10: TechCorp New Enterprise Client...
   Event Type: NewCustomer
   Reference ID: EVENT-0001
   Source Business: http://vital.ai/test/kgentity/organization/techcorp_industries
   ✅ Created: TechCorp New Enterprise Client
      URI: http://vital.ai/test/kgentity/business_event/newcustomer_a1b2c3d4
      Objects created: 15

Creating business event 2/10: Global Finance Q4 Deal...
   Event Type: Transaction
   Reference ID: EVENT-0002
   Source Business: http://vital.ai/test/kgentity/organization/global_finance_group
   ✅ Created: Global Finance Q4 Deal
      URI: http://vital.ai/test/kgentity/business_event/transaction_e5f6g7h8
      Objects created: 15

...

✅ Successfully created 10/10 business events
```

## Testing the Integration

Run the updated test:

```bash
python vitalgraph_client_test/test_multiple_organizations_crud.py
```

Expected results:
- 10 organizations created ✅
- 10 business events created ✅
- Each event references one organization ✅
- All CRUD operations work on both entity types ✅
