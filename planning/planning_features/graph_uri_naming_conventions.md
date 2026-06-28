# VitalGraph URI Naming Conventions

## Overview

VitalGraph uses a hierarchical URI naming convention to organize graphs based on namespaces, account ownership, and global/private access patterns. This document describes the URI structure and naming patterns used throughout the VitalGraph system.

## URI Structure Components

The graph URI construction is based on four key components:

- **base_uri**: The root URI for the VitalGraph service
- **namespace**: A logical grouping identifier for related graphs
- **account_id**: Optional tenant/user identifier for multi-tenancy
- **graph_id**: The specific identifier for an individual graph
- **global_graph**: Boolean flag indicating if the graph is globally accessible

## URI Patterns

### 1. Private Graph (non-global, with account_id)
```
{base_uri}/{namespace}/{account_id}/{graph_id}
```

**Example:**
```
http://vital.ai/graph/myapp/user123/personal_data
```

**Use Case:** User-specific private graphs where each account has isolated access to their own graphs.

### 2. Private Graph (non-global, without account_id)
```
{base_uri}/{namespace}/{graph_id}
```

**Example:**
```
http://vital.ai/graph/myapp/shared_config
```

**Use Case:** Namespace-level private graphs that don't belong to a specific account but are still private to the namespace.

### 3. Global Graph (with account_id)
```
{base_uri}/{namespace}/GLOBAL/{account_id}/{graph_id}
```

**Example:**
```
http://vital.ai/graph/myapp/GLOBAL/user123/public_profile
```

**Use Case:** Account-owned graphs that are globally accessible across the namespace.

### 4. Global Graph (without account_id)
```
{base_uri}/{namespace}/GLOBAL/{graph_id}
```

**Example:**
```
http://vital.ai/graph/myapp/GLOBAL/reference_data
```

**Use Case:** System-wide global graphs accessible to all users within the namespace.

### 5. Service Graph (Special Case)
```
{base_uri}/{namespace}/{SERVICE_GRAPH_ID}
```

**Example:**
```
http://vital.ai/graph/myapp/vital-service-graph
```

**Use Case:** Internal service metadata graph for managing the VitalGraph service itself.

## Key Design Principles

### 1. Global Marker
- The literal string **"GLOBAL"** is inserted into the URI path to distinguish global graphs from private ones
- This provides clear visual identification of access scope

### 2. Account ID Placement
- **Private graphs**: `account_id` comes directly after `namespace`
- **Global graphs**: `account_id` comes after the "GLOBAL" marker
- Maintains hierarchical consistency while preserving access semantics

### 3. Optional Account ID
- Account IDs are optional in all patterns
- When not provided, they're omitted from the URI structure
- Enables both single-tenant and multi-tenant deployments

### 4. Namespace Isolation
- All graphs are scoped within a namespace
- Provides logical separation between different applications or domains
- Enables multiple VitalGraph applications on the same service instance

## Multi-Tenancy Support

### Account-Based Filtering
The URI convention enables sophisticated multi-tenant queries:

**With account_id specified:**
```sparql
?s <http://vital.ai/ontology/vital-core#hasSegmentTenantID> "user123"^^xsd:string .
```

**Without account_id (system graphs):**
```sparql
FILTER NOT EXISTS {
    ?s <http://vital.ai/ontology/vital-core#hasSegmentTenantID> ?value .
}
```

### Access Control Patterns
1. **Private + Account ID**: Strict tenant isolation
2. **Private + No Account ID**: Namespace-private, cross-tenant
3. **Global + Account ID**: Tenant-owned but globally readable
4. **Global + No Account ID**: System-wide shared resources

## Implementation Details

### URI Generation
The `get_graph_uri()` method in VitalGraphService constructs URIs based on the parameters:

```python
def get_graph_uri(self, *,
                  name_graph: VitalNameGraph = None,
                  graph_id: str|None = None,
                  account_id: str|None = None,
                  is_global: bool = False) -> str | None:
    
    base_uri = self.base_uri
    namespace = self.namespace
    
    if is_global is True or is_global == 1:
        if account_id:
            graph_uri = f"{base_uri}/{namespace}/GLOBAL/{account_id}/{graph_id}"
        else:
            graph_uri = f"{base_uri}/{namespace}/GLOBAL/{graph_id}"
    else:
        if account_id:
            graph_uri = f"{base_uri}/{namespace}/{account_id}/{graph_id}"
        else:
            graph_uri = f"{base_uri}/{namespace}/{graph_id}"
    
    return graph_uri
```

### URI Parsing
The `get_name_graph()` method parses URIs back into components:

```python
def get_name_graph(self, graph_uri: str) -> VitalNameGraph:
    # Parses URI components and returns VitalNameGraph object
    # with extracted graph_id, account_id, and global flag
```

## Usage Examples

### Creating Graphs
```python
# Private user graph
service.create_graph("user_data", account_id="user123", global_graph=False)
# URI: http://vital.ai/graph/myapp/user123/user_data

# Global reference graph
service.create_graph("ontology", global_graph=True)
# URI: http://vital.ai/graph/myapp/GLOBAL/ontology

# Account-owned global graph
service.create_graph("public_profile", account_id="user123", global_graph=True)
# URI: http://vital.ai/graph/myapp/GLOBAL/user123/public_profile
```

### Querying Graphs
```python
# List all graphs for a specific account
graphs = service.list_graphs(account_id="user123", include_global=True, include_private=True)

# List only global graphs
global_graphs = service.list_graphs(include_global=True, include_private=False)

# List only private graphs for an account
private_graphs = service.list_graphs(account_id="user123", include_global=False, include_private=True)
```

## Best Practices

### 1. Namespace Design
- Use descriptive namespace names that reflect the application domain
- Keep namespaces consistent across related services
- Avoid special characters in namespace names

### 2. Graph ID Naming
- Use descriptive, hierarchical graph IDs (e.g., "user_profile", "transaction_log")
- Avoid spaces and special characters
- Consider using kebab-case or snake_case for consistency

### 3. Account ID Management
- Use consistent account ID formats across the system
- Consider using UUIDs for account IDs to avoid collisions
- Document account ID semantics clearly

### 4. Global vs Private Decision Matrix
| Use Case | Account ID | Global | Pattern |
|----------|------------|--------|---------|
| User private data | Yes | No | `{base}/{ns}/{account}/{graph}` |
| Shared app config | No | No | `{base}/{ns}/{graph}` |
| User public profile | Yes | Yes | `{base}/{ns}/GLOBAL/{account}/{graph}` |
| System reference data | No | Yes | `{base}/{ns}/GLOBAL/{graph}` |

## Migration Considerations

When migrating from other graph systems:
1. Map existing graph identifiers to the VitalGraph URI convention
2. Determine appropriate global/private classification for each graph
3. Establish account ID mapping for multi-tenant scenarios
4. Update client code to use the new URI patterns

## Security Implications

The URI convention directly impacts access control:
- **Private graphs** are only accessible within their namespace/account scope
- **Global graphs** are readable across the namespace but may have write restrictions
- **Service graphs** require administrative privileges
- URI patterns should be validated to prevent unauthorized access attempts
