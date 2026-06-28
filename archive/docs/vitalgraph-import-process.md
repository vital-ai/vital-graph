# VitalGraph Import Process Documentation

## Overview

This document describes the currently implemented import process in VitalGraph and identifies what work remains to complete the full import cycle. The goal is to enable efficient bulk import of large RDF files into VitalGraph spaces using PostgreSQL's high-performance features.

## Current Architecture Status

### ✅ **Implemented Components**

#### 1. **Core Import Infrastructure**
- **PostgreSQLSpaceDBImport** (`vitalgraph/db/postgresql/space/postgresql_space_db_import.py`)
  - Bulk N-Triples parsing using pyoxigraph
  - CSV generation with deterministic UUID pre-computation
  - PostgreSQL COPY operations for high-speed data loading
  - UNLOGGED temp table creation and management
  - Term extraction and deduplication

#### 2. **Import Operation Framework**
- **GraphImportOp** (`vitalgraph/ops/graph_import_op.py`)
  - RDF file validation and format detection
  - Progress tracking and error handling
  - Operation lifecycle management
  - Currently handles validation only (actual import not connected)

#### 3. **REST API Endpoints**
- **ImportEndpoint** (`vitalgraph/endpoint/import_endpoint.py`)
  - Complete REST API for import job management
  - File upload handling
  - Import job lifecycle (create, execute, monitor, delete)
  - Currently stub implementations (no actual database integration)

#### 4. **Partition-Based Import Architecture**
- **Zero-Copy Partition Attachment** (Partially implemented)
  - UNLOGGED temp table creation with partition key support
  - Schema matching for partition attachment
  - Constraint management for PostgreSQL partition validation
  - LOGGED conversion for WAL safety

### ⚠️ **Partially Implemented**

#### 1. **Partition Import Process** ✅ **READY FOR USE**
- **Setup Phase**: ✅ Complete - Creates temp tables with partition keys
- **Loading Phase**: ✅ Complete - Loads data into temp tables  
- **Attachment Phase**: ✅ Complete - Main tables ARE partitioned by design
- **Cleanup Phase**: ✅ Complete - Temp table cleanup
- **Index Optimization**: ✅ Complete - Schema includes comprehensive index management

#### 2. **Traditional Import Process** ✅ **COMPLETE**
- **Bulk Loading**: ✅ Complete - COPY operations working
- **Term Processing**: ✅ Complete - UUID assignment and deduplication
- **Data Transfer**: ✅ Complete - transfer_to_main_tables_phase4() implemented
- **Index Management**: ✅ Complete - Drops/recreates expensive indexes during import

### ❌ **Not Implemented**

#### 1. **Import Job Persistence**
- No database tables for import job tracking
- No progress persistence across restarts
- No import history or audit trail

#### 2. **REST API Integration**
- REST API endpoints are stubs with no database operations
- No connection between import operations and space management

#### 3. **Production Features**
- No error recovery mechanisms
- No rollback capabilities
- No concurrent import handling
- No resource management (memory/disk limits)

## Detailed Implementation Analysis

### Current Import Process Flow

#### **Phase 1: File Validation** ✅ **COMPLETE**
```python
# In GraphImportOp.execute()
validation_result = validate_rdf_file(file_path)
# - Parses entire file to count triples
# - Validates RDF syntax
# - Detects format (N-Triples, Turtle, etc.)
# - Reports file statistics
```

#### **Phase 2: Bulk Data Loading** ✅ **COMPLETE**
```python
# In PostgreSQLSpaceDBImport.bulk_import_ntriples()
csv_file = convert_ntriples_to_csv(file_path)  # With pre-computed UUIDs
create_temp_import_table(temp_table_name)     # UNLOGGED for speed
bulk_copy_csv_to_table(csv_file, temp_table)  # PostgreSQL COPY
```

**Performance Achieved:**
- **Parsing**: ~97,582 triples/sec using pyoxigraph
- **COPY Loading**: ~302,670 triples/sec using binary streaming
- **Memory Usage**: Constant ~100MB regardless of file size

#### **Phase 3: Term Processing** ✅ **COMPLETE**
```python
# Extract unique terms and assign UUIDs
extract_and_deduplicate_terms(temp_table)
# - Single UNION ALL query for term extraction
# - Deterministic UUID generation
# - ON CONFLICT DO NOTHING for duplicates
```

#### **Phase 4: Data Transfer** ❌ **MISSING**
```python
# NOT IMPLEMENTED - Would transfer from temp to main tables
transfer_to_main_tables(temp_table, space_id, graph_uri)
# - INSERT INTO main_quad_table SELECT FROM temp_table
# - INSERT INTO main_term_table SELECT FROM temp_terms
# - Index management during bulk operations
```

### Partition Import Architecture

#### **Current Partition Support**
```python
# Creates temp tables with partition key support
CREATE UNLOGGED TABLE temp_quad_table (
    -- ... quad columns ...
    dataset VARCHAR(50) NOT NULL DEFAULT 'import-12345',
    -- Constraint for partition attachment
    CONSTRAINT temp_quad_dataset_check CHECK (dataset = 'import-12345') NOT VALID
)
```

#### **Zero-Copy Attachment Process**
```python
# Convert UNLOGGED to LOGGED for partition attachment
ALTER TABLE temp_quad_table SET LOGGED;

# Attach as partition (zero-copy operation)
ALTER TABLE main_quad_table 
ATTACH PARTITION temp_quad_table 
FOR VALUES IN ('import-12345');
```

**Blocker**: Main tables must be partitioned first, but current schema is not partitioned.

### Test Data Available

Located in `/Users/hadfield/Local/vital-git/vital-graph/test_data/`:
- **kgframe-wordnet-0.0.2.nt**: 1.58GB, ~8.58M triples (primary test file)
- **kgentity_wordnet.nt**: 560MB, ~3.2M triples
- **kgframe-wordnet-0.0.1.nt**: 1.31GB, ~7.5M triples

## Required Work to Complete Import Process

### **Priority 1: Critical Missing Components**

#### 1. **Complete Phase 4 Data Transfer**
**File**: `postgresql_space_db_import.py`
**Missing Method**: `transfer_to_main_tables()`

```python
async def transfer_to_main_tables(self, temp_table_name: str, space_id: str, graph_uri: str):
    """Transfer processed data from temp table to main quad/term tables."""
    # Implementation needed:
    # 1. Get main table names for space
    # 2. Temporarily disable expensive indexes
    # 3. INSERT INTO main_term_table SELECT FROM temp_terms ON CONFLICT DO NOTHING
    # 4. INSERT INTO main_quad_table SELECT FROM temp_quads
    # 5. Re-enable indexes
    # 6. Update statistics
```

#### 2. **Connect GraphImportOp to Database Import**
**File**: `graph_import_op.py`
**Missing**: Integration with `PostgreSQLSpaceDBImport`

```python
# In GraphImportOp.execute() - Step 5 replacement
async def _perform_actual_import(self):
    """Perform actual database import after validation."""
    space_impl = self.get_space_impl()  # Need to add this
    db_import = PostgreSQLSpaceDBImport(space_impl)
    
    # Execute import process
    import_stats = await db_import.bulk_import_ntriples(
        self.file_path, 
        self.graph_uri,
        batch_size=self.batch_size
    )
    
    # Transfer to main tables
    await db_import.transfer_to_main_tables(
        import_stats['temp_table_name'],
        self.space_id,
        self.graph_uri
    )
```

#### 3. **Implement REST API Database Integration**
**File**: `import_endpoint.py`
**Missing**: Replace stub methods with actual database operations

```python
async def _execute_import_job(self, import_id: str, current_user: Dict):
    """Execute import job with actual database operations."""
    # 1. Get import job from database
    # 2. Create GraphImportOp instance
    # 3. Execute import with progress tracking
    # 4. Update import job status in database
    # 5. Handle errors and cleanup
```

### **Priority 2: Schema Migration for Partitioning**

#### 1. **Add Partition Key to Main Tables**
**Required SQL Migration**:
```sql
-- Add dataset column to existing tables
ALTER TABLE {space_id}__term ADD COLUMN dataset VARCHAR(50) NOT NULL DEFAULT 'primary';
ALTER TABLE {space_id}__rdf_quad ADD COLUMN dataset VARCHAR(50) NOT NULL DEFAULT 'primary';

-- Convert to partitioned tables
CREATE TABLE {space_id}__term_new (LIKE {space_id}__term) PARTITION BY LIST (dataset);
CREATE TABLE {space_id}__rdf_quad_new (LIKE {space_id}__rdf_quad) PARTITION BY LIST (dataset);

-- Create primary partitions
CREATE TABLE {space_id}__term_primary PARTITION OF {space_id}__term_new FOR VALUES IN ('primary');
CREATE TABLE {space_id}__rdf_quad_primary PARTITION OF {space_id}__rdf_quad_new FOR VALUES IN ('primary');

-- Migrate existing data
INSERT INTO {space_id}__term_new SELECT *, 'primary' FROM {space_id}__term;
INSERT INTO {space_id}__rdf_quad_new SELECT *, 'primary' FROM {space_id}__rdf_quad;

-- Swap tables
DROP TABLE {space_id}__term CASCADE;
DROP TABLE {space_id}__rdf_quad CASCADE;
ALTER TABLE {space_id}__term_new RENAME TO {space_id}__term;
ALTER TABLE {space_id}__rdf_quad_new RENAME TO {space_id}__rdf_quad;
```

#### 2. **Update Space Schema Generation**
**File**: `postgresql_space_schema.py`
**Required**: Modify table creation to include partition keys and partitioning

### **Priority 3: Import Job Persistence**

#### 1. **Create Import Job Tables**
```sql
CREATE TABLE import_jobs (
    import_id UUID PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    import_type VARCHAR(50) NOT NULL,
    space_id VARCHAR(50) NOT NULL,
    graph_uri TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'created',
    file_path TEXT,
    file_size_bytes BIGINT,
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_date TIMESTAMP,
    completed_date TIMESTAMP,
    progress_percent FLOAT DEFAULT 0.0,
    records_processed BIGINT DEFAULT 0,
    records_total BIGINT,
    error_message TEXT,
    config JSONB,
    temp_table_name VARCHAR(255),
    dataset_value VARCHAR(50)
);

CREATE TABLE import_job_logs (
    log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    import_id UUID REFERENCES import_jobs(import_id),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    level VARCHAR(20) NOT NULL,
    message TEXT NOT NULL,
    details JSONB
);
```

#### 2. **Implement Import Job Manager**
**New File**: `vitalgraph/import/import_job_manager.py`
```python
class ImportJobManager:
    """Manages import job lifecycle and persistence."""
    
    async def create_import_job(self, job_data: ImportJob) -> str:
        """Create and persist import job."""
    
    async def execute_import_job(self, import_id: str) -> None:
        """Execute import job with progress tracking."""
    
    async def get_import_status(self, import_id: str) -> ImportStatus:
        """Get current import job status."""
```

## Recommended Implementation Plan

### **Phase 1: Complete Basic Import (1-2 days)**
1. **Implement `transfer_to_main_tables()`** in `PostgreSQLSpaceDBImport`
2. **Connect `GraphImportOp`** to database import functionality
3. **Test end-to-end import** with small files
4. **Add index management** during bulk operations

### **Phase 2: Schema Migration for Partitioning (2-3 days)**
1. **Create migration scripts** for existing spaces
2. **Update schema generation** to create partitioned tables
3. **Test partition import process** with zero-copy attachment
4. **Validate performance improvements**

### **Phase 3: Production Features (3-4 days)**
1. **Implement import job persistence** and management
2. **Connect REST API endpoints** to actual database operations
3. **Add error recovery** and rollback capabilities
4. **Implement resource management** and concurrent import handling

### **Phase 4: Testing and Optimization (2-3 days)**
1. **Test with large files** (WordNet 1.58GB dataset)
2. **Performance benchmarking** and optimization
3. **Error scenario testing** and recovery validation
4. **Documentation and deployment guides**

## Test Plan for Complete Import Cycle

### **Test 1: Basic Import Process**
```bash
# Test with small file first
python test_scripts/import/test_basic_import.py

# Expected: Complete import from file to main tables
# Validation: Data queryable via SPARQL
```

### **Test 2: Large File Import**
```bash
# Test with WordNet dataset
python test_scripts/import/test_large_file_import.py

# File: test_data/kgframe-wordnet-0.0.2.nt (1.58GB, 8.58M triples)
# Expected: <2 minutes total import time
# Validation: All 8.58M triples imported correctly
```

### **Test 3: Partition Import Process**
```bash
# Test zero-copy partition attachment
python test_scripts/import/test_partition_import.py

# Expected: Near-instant Phase 4 (partition attachment)
# Validation: Data accessible through main tables
```

### **Test 4: REST API Integration**
```bash
# Test full API workflow
curl -X POST /api/import -d '{"name": "Test Import", "space_id": "test_space"}'
curl -X POST /api/import/{import_id}/upload -F "file=@test_data/small_test.nt"
curl -X POST /api/import/{import_id}/execute
curl -X GET /api/import/{import_id}/status

# Expected: Complete import via REST API
# Validation: Import job tracked and data imported
```

## Performance Targets

Based on existing optimizations and documentation:

### **Current Performance (Phase 2-3 only)**
- **Parsing**: 97,582 triples/sec
- **Loading**: 302,670 triples/sec
- **Term Processing**: 1,014,063 rows/sec

### **Target End-to-End Performance**
- **Small Files** (<100MB): <10 seconds
- **Medium Files** (100MB-1GB): <60 seconds  
- **Large Files** (1-10GB): <10 minutes
- **Memory Usage**: Constant regardless of file size

### **Partition Import Targets**
- **Phase 4 (Partition Attachment)**: <1 second (zero-copy)
- **Total Speedup**: 6-7x faster than traditional import
- **WordNet Dataset** (1.58GB): <2 minutes total

## Conclusion

The VitalGraph import process has a solid foundation with high-performance bulk loading capabilities already implemented. The main gaps are:

1. **Missing Phase 4 data transfer** to main tables
2. **Lack of integration** between components
3. **Schema migration needed** for partition support
4. **No import job persistence** or management

Completing these components will provide a production-ready import system capable of efficiently handling large RDF datasets with full transaction safety and excellent performance characteristics.

The existing architecture supports both traditional import (with data copying) and advanced partition-based import (with zero-copy attachment), providing flexibility for different use cases and performance requirements.
