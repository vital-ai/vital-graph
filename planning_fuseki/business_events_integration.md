# Business Events Integration

## Overview

The BusinessEvent entity type has been added to the test data framework to represent business events that reference organization entities. This allows testing of entity relationships and cross-entity references.

## Business Event Types

Three types of business events are supported:

1. **NewCustomer** - Represents acquiring a new customer
   - Customer name
   - Customer value (revenue potential)

2. **Transaction** - Represents a business transaction
   - Transaction amount
   - Transaction ID

3. **Cancellation** - Represents a customer/service cancellation
   - Cancellation reason
   - Affected customer

## Entity Structure

Each BusinessEvent entity includes:

### Core Entity
- **Entity Type**: `BusinessEventEntity`
- **Name**: Descriptive event name
- **Reference ID**: Optional identifier (e.g., "EVENT-0001")

### Frames

1. **Event Details Frame** (`EventDetailsFrame`)
   - Event Type (NewCustomer, Transaction, Cancellation)
   - Event Timestamp (datetime)
   - Event Status (Active, Completed, etc.)

2. **Source Business Frame** (`SourceBusinessFrame`)
   - Business Entity URI Slot - **References the organization entity URI**
   - This creates the link between the event and the source organization

3. **Event Data Frame** (`EventDataFrame`)
   - Event-specific data based on event type
   - NewCustomer: customer name, customer value
   - Transaction: transaction amount, transaction ID
   - Cancellation: cancellation reason, affected customer

## Integration with Multi-Organization Test

### File Structure

```
vitalgraph_client_test/
├── client_test_data.py                          # Added create_business_event() method
└── multi_kgentity/
    ├── case_create_organizations.py             # Existing - creates 10 organizations
    └── case_create_business_events.py           # NEW - creates 10 events referencing orgs
```

### Usage Pattern

```python
from vitalgraph_client_test.client_test_data import ClientTestDataCreator
from vitalgraph_client_test.multi_kgentity.case_create_business_events import CreateBusinessEventsTester

# 1. Create organizations first (existing functionality)
org_tester = CreateOrganizationsTester(client)
org_results = org_tester.run_tests(space_id, graph_id)
organization_uris = org_results["created_entity_uris"]

# 2. Create business events that reference the organizations
event_tester = CreateBusinessEventsTester(client)
event_results = event_tester.run_tests(space_id, graph_id, organization_uris)
```

### Data Flow

```
Organizations (10 entities)
    ↓
    └─> Organization URIs extracted
            ↓
            └─> Business Events (10 entities)
                    └─> Each event references one organization via URI
```

## Example Business Events

1. **TechCorp New Enterprise Client** (NewCustomer)
   - References: TechCorp Industries
   - Customer: "New Customer Inc"
   - Value: "$50,000"

2. **Global Finance Q4 Deal** (Transaction)
   - References: Global Finance Group
   - Amount: "$25,000"
   - Transaction ID: "TXN-XXXXXXXX"

3. **Retail Dynamics Store Closure** (Cancellation)
   - References: Retail Dynamics Corp
   - Reason: "Service no longer needed"
   - Customer: "Former Customer Corp"

## API Methods

### ClientTestDataCreator.create_business_event()

```python
def create_business_event(
    self, 
    event_type: str,              # "NewCustomer", "Transaction", "Cancellation"
    source_business_uri: str,     # URI of organization entity
    event_name: str = None,       # Optional event name
    reference_id: str = None      # Optional reference ID
) -> List[GraphObject]:
    """Create business event entity with frames."""
```

### CreateBusinessEventsTester.run_tests()

```python
def run_tests(
    self, 
    space_id: str, 
    graph_id: str, 
    organization_uris: List[str]  # URIs from organization creation
) -> Dict[str, Any]:
    """Create 10 business events referencing organizations."""
```

## Integration into test_multiple_organizations_crud.py

To add business events to the existing test, add after organization creation:

```python
# Import the new tester
from vitalgraph_client_test.multi_kgentity.case_create_business_events import CreateBusinessEventsTester

# After creating organizations
org_results = org_tester.run_tests(space_id, graph_id)
all_results.append(org_results)

# NEW: Create business events
print_section("📅 Creating Business Events")
event_tester = CreateBusinessEventsTester(client)
event_results = event_tester.run_tests(
    space_id, 
    graph_id, 
    org_results["created_entity_uris"]
)
all_results.append(event_results)
```

## Key Features

✅ **No Breaking Changes** - Existing organization tests work unchanged
✅ **Entity Relationships** - Events reference organizations via URI slots
✅ **Multiple Event Types** - Supports different business event scenarios
✅ **Consistent Pattern** - Follows same structure as organization/person entities
✅ **Reference IDs** - Events have reference IDs (EVENT-0001, etc.)
✅ **Complete Entity Graphs** - Events have full frame/slot/edge structures

## Testing Capabilities

With BusinessEvents, you can now test:

1. **Cross-entity references** - Events referencing organizations
2. **URI-based relationships** - Stored as text slots containing URIs
3. **Multiple entity types** - Organizations + Events in same space
4. **Complex queries** - Find all events for a specific organization
5. **Entity lifecycle** - Create, query, update, delete events

## Future Extensions

Potential additions:
- **ContractEvent** - Contract signing, renewal, expiration
- **EmployeeEvent** - Hiring, promotion, departure
- **ProductEvent** - Product launch, update, discontinuation
- **PartnershipEvent** - Partnership formation, collaboration
- **ComplianceEvent** - Audit, certification, violation

Each can follow the same pattern with a SourceBusinessFrame referencing the organization.
