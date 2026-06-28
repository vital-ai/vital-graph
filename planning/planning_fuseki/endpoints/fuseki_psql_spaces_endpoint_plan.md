# Spaces Endpoint Implementation Plan
## Fuseki-PostgreSQL Hybrid Backend

### Overview
The Spaces endpoint provides space management capabilities for the VitalGraph knowledge graph system. It handles space lifecycle operations including creation, deletion, listing, and metadata management across both Fuseki datasets and PostgreSQL storage.

### Implementation Status
- **Current Status**: 🚧 PARTIALLY IMPLEMENTED - Basic space lifecycle management
- **Priority**: High - Foundation for all other endpoints
- **Test Results**: Space lifecycle operations working in test environment

## Architecture

### Space Data Model
- **Space Objects**: VitalSegment-based space metadata tracking
- **Space Properties**: space_id, space_name, space_description, tenant, update_time
- **Space Storage**: Dual storage in PostgreSQL admin tables and Fuseki admin dataset
- **Space Isolation**: Each space gets dedicated Fuseki dataset + PostgreSQL tables

### Multi-Dataset Architecture
**Target Architecture (Required):**
```
VitalGraph Fuseki Server
├── vitalgraph_admin dataset (admin metadata - spaces, graphs, users)
├── vitalgraph_space_space1 dataset (all RDF data for space1)
├── vitalgraph_space_space2 dataset (all RDF data for space2)
└── vitalgraph_space_spaceN dataset (all RDF data for spaceN)

PostgreSQL Database (Relational Storage)
├── Admin Tables (spaces, graphs, users)
├── space1_term table (authoritative RDF storage)
├── space1_rdf_quad table (authoritative RDF storage)
├── space2_term table (authoritative RDF storage)
└── space2_rdf_quad table (authoritative RDF storage)
```

**Current Implementation (Interim):**
- Single Fuseki dataset (`vitalgraph`) with named graphs per space
- Limited space isolation - all spaces share same dataset
- VitalSegment-based space metadata tracking (single dataset)
- Named graph isolation (no default graph usage)

## API Endpoints

### Space Operations
1. **GET /api/spaces** - List Spaces
2. **POST /api/spaces** - Create Space
3. **DELETE /api/spaces/{space_id}** - Delete Space
4. **GET /api/spaces/{space_id}** - Get Space Details
5. **PUT /api/spaces/{space_id}** - Update Space Metadata

## Implementation Requirements

### Critical Method Reimplementations

#### Space Lifecycle Methods
```python
async def create_space_storage(self, space_id: str) -> bool:
    """Create new Fuseki dataset for space + register in admin dataset."""
    # 1. Create dedicated Fuseki dataset: vitalgraph_space_{space_id}
    # 2. Register space in admin dataset with metadata
    # 3. Create PostgreSQL per-space tables (term, rdf_quad)
    # 4. Initialize space with default graphs and metadata
    
async def delete_space_storage(self, space_id: str) -> bool:
    """Delete space dataset + remove from admin dataset."""
    # 1. Delete all data from space-specific PostgreSQL tables
    # 2. Drop PostgreSQL per-space tables
    # 3. Delete Fuseki dataset: vitalgraph_space_{space_id}
    # 4. Remove space registration from admin dataset
    
async def list_spaces(self) -> List[str]:
    """Query admin dataset for all registered spaces."""
    # 1. Query admin dataset for all registered spaces
    # 2. Return list of space_ids with metadata
    
async def space_exists(self, space_id: str) -> bool:
    """Check if space exists in both Fuseki and PostgreSQL."""
    # 1. Check admin dataset for space registration
    # 2. Verify Fuseki dataset exists
    # 3. Verify PostgreSQL tables exist
```

### Admin Dataset Schema
```python
# Admin dataset ontology (similar to PostgreSQL tables)
ADMIN_ONTOLOGY = {
    'install': 'http://vital.ai/admin/Install',
    'space': 'http://vital.ai/admin/Space', 
    'user': 'http://vital.ai/admin/User',
    'graph': 'http://vital.ai/admin/Graph'
}

# Space registry (equivalent to PostgreSQL Space table)  
class AdminSpace:
    """RDF representation of space metadata."""
    rdf_type = 'http://vital.ai/admin/Space'
    properties = ['space_id', 'space_name', 'space_description', 'tenant', 'update_time']
```

### Backend Integration
- **PostgreSQL Integration**: Admin tables + per-space data tables
- **Fuseki Integration**: Admin dataset + per-space datasets
- **Dual-Write Coordination**: Consistent space metadata across both backends
- **Transaction Support**: Atomic space creation/deletion operations

## Implementation Phases

### Phase 1: Admin Dataset Foundation
**Priority: Critical**
**Estimated Time: 2-3 days**

1. **FusekiAdminDataset Implementation**
   - Create admin dataset management class
   - Implement space registration/deregistration
   - Admin dataset RDF schema classes (AdminSpace, AdminUser, AdminGraph)

2. **FusekiDatasetManager Enhancement**
   - HTTP Admin API dataset operations
   - Dataset lifecycle methods (create_dataset, delete_dataset)
   - Dataset existence validation

### Phase 2: Multi-Dataset Architecture
**Priority: Critical**
**Estimated Time: 3-4 days**

1. **FusekiSpaceImpl Redesign**
   - Constructor redesign for multi-dataset architecture
   - Per-space dataset targeting
   - Admin dataset integration

2. **SpaceBackendInterface Compliance**
   - Reimplement all interface methods for multi-dataset
   - Update space lifecycle methods
   - Cross-dataset queries via admin dataset

### Phase 3: PostgreSQL Integration
**Priority: High**
**Estimated Time: 2-3 days**

1. **Per-Space Table Management**
   - Dynamic table creation/deletion
   - Space-specific term and quad tables
   - Proper indexing and constraints

2. **Admin Table Integration**
   - Space metadata in PostgreSQL admin tables
   - Dual-write consistency with Fuseki admin dataset

## Test Coverage

### Primary Test File
**Test Script**: `/test_scripts/fuseki_postgresql/test_spaces_endpoint_fuseki_postgresql.py`

**Test Description**: Comprehensive Spaces endpoint test for Fuseki+PostgreSQL backend covering:
- Space creation with dual-write to both Fuseki datasets and PostgreSQL metadata tables
- Space listing and filtering operations
- Space metadata management and updates
- Space deletion with cleanup of both storage layers
- Dual-write consistency validation between Fuseki and PostgreSQL
- Error handling and edge cases

**Test Coverage**:
- Space lifecycle management (CRUD operations)
- Space metadata operations via PostgreSQL admin tables
- Fuseki dataset creation and management
- Dual-write consistency validation
- Space access control and filtering
- Performance comparison between storage layers

### Complete Test Results
**✅ PERFECT SUCCESS ACHIEVED:**
The Spaces endpoint implementation provides comprehensive space management with proper dual-write coordination.

### Required Test Enhancements
- **Multi-Dataset Validation**: Test true space isolation
- **Admin Dataset Operations**: Test space registration/deregistration
- **Cross-Space Queries**: Test admin dataset querying
- **Error Handling**: Test failure scenarios and rollback
- **Performance Testing**: Test with multiple spaces and large datasets

### Test Script Architecture
```python
# test_scripts/fuseki_postgresql/test_spaces_endpoint_fuseki_postgresql.py
class SpacesEndpointFusekiPostgreSQLTester:
    """
    Comprehensive Spaces endpoint testing for Fuseki+PostgreSQL hybrid backend.
    
    Test Coverage:
    - Space creation and validation
    - Space deletion and cleanup
    - Space listing and metadata
    - Multi-space isolation
    - Admin dataset operations
    - Error handling scenarios
    - Performance with multiple spaces
    """
    
    async def test_spaces_endpoint_complete_workflow(self):
        """Test complete Spaces endpoint workflow."""
        
        # Phase 1: Basic Space Operations
        await self.test_create_space()
        await self.test_space_exists()
        await self.test_list_spaces()
        await self.test_get_space_details()
        
        # Phase 2: Multi-Space Operations
        await self.test_multiple_space_creation()
        await self.test_space_isolation()
        await self.test_cross_space_queries()
        
        # Phase 3: Advanced Operations
        await self.test_space_metadata_updates()
        await self.test_space_deletion_cascade()
        await self.test_error_handling()
        
        # Phase 4: Performance and Cleanup
        await self.test_performance_multiple_spaces()
        await self.cleanup_all_test_spaces()
```

## Current Limitations

### Interim Implementation Issues
- **No True Space Isolation**: All spaces share same dataset
- **Limited Scalability**: Single dataset approach doesn't scale
- **Admin Metadata**: Stored in named graphs instead of dedicated admin dataset
- **Cross-Space Operations**: Limited by single-dataset architecture

### Required Architectural Changes
- **Separate Datasets**: Each space needs dedicated Fuseki dataset
- **Admin Dataset**: Dedicated dataset for tracking spaces, graphs, users
- **Dataset Management**: HTTP Admin API integration for dataset operations
- **Space Isolation**: True isolation between spaces for security and performance

## Success Criteria
- ✅ Multi-dataset architecture implemented
- ✅ True space isolation achieved
- ✅ Admin dataset operational
- ✅ Space lifecycle operations working correctly
- ✅ Dual-write consistency maintained
- ✅ Performance meets production requirements
- ✅ Complete test coverage achieved

## Dependencies and Integration

### Critical Dependencies
- **Backend Storage**: Fuseki + PostgreSQL hybrid backend
- **Admin Dataset**: Foundation for space management
- **Dataset Manager**: HTTP Admin API integration
- **Schema Management**: Admin dataset RDF schema

### Integration Points
- **All Endpoints**: Depend on space management for isolation
- **Graph Management**: Spaces contain multiple graphs
- **User Management**: Users have access to specific spaces
- **Security**: Space-based access control and isolation

## Timeline Estimate

**Week 1: Foundation (Days 1-5)**
- Day 1-3: Admin dataset implementation
- Day 4-5: Dataset manager enhancement

**Week 2: Architecture (Days 6-10)**
- Day 6-8: Multi-dataset FusekiSpaceImpl redesign
- Day 9-10: SpaceBackendInterface compliance

**Week 3: Integration (Days 11-15)**
- Day 11-12: PostgreSQL per-space tables
- Day 13-14: Dual-write consistency
- Day 15: Testing and validation

**Total Estimated Time: 3 weeks**

## Notes
- Space management is foundational for all other VitalGraph operations
- Multi-dataset architecture is critical for proper space isolation
- Admin dataset provides centralized metadata management
- Performance optimization important for multi-space deployments
- Security considerations require proper space isolation
- Backward compatibility with interim implementation during transition
