# VitalGraph Data Management Tables Design

## Overview

This document outlines the design for five new global tables to support comprehensive data management operations in VitalGraph. These tables will extend the existing global table architecture to support import, export, migration, tracking, and checkpoint functionality.

## Architecture Integration

### Location
These tables will be added to the existing global table management system in:
- **File**: `vitalgraph/db/postgresql/postgresql_db_impl.py`
- **Function**: `create_models_with_prefix()` 
- **Pattern**: Following the same SQLAlchemy ORM model pattern as Install, Space, and User tables

### Naming Convention
All tables use the configurable prefix pattern: `{prefix}table_name`
- Example: `vitalgraph1_data_import`, `vitalgraph1_data_export`, etc.

## Table Designs

### 1. DataImport Table (`{prefix}data_import`)

**Purpose**: Track file imports into specific space + graph combinations

**Use Cases**:
- Import RDF files (Turtle, N-Triples, RDF/XML, JSON-LD) into graphs
- Batch data loading operations
- Import progress monitoring and error tracking

```python
class DataImport(Base):
    __tablename__ = f'{prefix}data_import'
    __table_args__ = {'extend_existing': True}
    
    # Primary identification
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Target location
    space_id = Column(String(255), nullable=False, index=True)
    graph_uri = Column(String(1000), nullable=False, index=True)
    
    # Job metadata
    job_name = Column(String(255), nullable=False)
    job_description = Column(String(1000), nullable=True)
    
    # Source information
    source_type = Column(String(50), nullable=False)  # 'file', 'url', 'stream'
    source_location = Column(String(2000), nullable=False)
    source_format = Column(String(50), nullable=False)  # 'turtle', 'n-triples', 'rdf-xml', 'json-ld'
    source_size = Column(BigInteger, nullable=True)  # File size in bytes
    
    # Processing configuration
    import_mode = Column(String(50), nullable=False, default='append')  # 'append', 'replace', 'merge'
    batch_size = Column(Integer, nullable=True, default=1000)
    validation_level = Column(String(50), nullable=False, default='basic')  # 'none', 'basic', 'strict'
    
    # Status tracking
    status = Column(String(50), nullable=False, default='pending')  # 'pending', 'running', 'completed', 'failed', 'cancelled'
    progress_percent = Column(Float, nullable=True, default=0.0)
    
    # Timing
    created_time = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_time = Column(DateTime, nullable=True)
    completed_time = Column(DateTime, nullable=True)
    
    # Results
    total_triples = Column(BigInteger, nullable=True)
    imported_triples = Column(BigInteger, nullable=True, default=0)
    skipped_triples = Column(BigInteger, nullable=True, default=0)
    error_triples = Column(BigInteger, nullable=True, default=0)
    
    # Error handling
    error_message = Column(String(2000), nullable=True)
    error_details = Column(Text, nullable=True)  # JSON formatted error details
    
    # Audit
    tenant = Column(String(255), nullable=True)
    created_by = Column(String(255), nullable=False)
    
    # Indexes
    __table_args__ = (
        Index('idx_data_import_space_graph', 'space_id', 'graph_uri'),
        Index('idx_data_import_status', 'status'),
        Index('idx_data_import_created', 'created_time'),
        {'extend_existing': True}
    )
```

### 2. DataExport Table (`{prefix}data_export`)

**Purpose**: Track exports from specific space + graph combinations to files

**Use Cases**:
- Export RDF graphs to various formats
- Scheduled data backups
- Data sharing and distribution

```python
class DataExport(Base):
    __tablename__ = f'{prefix}data_export'
    __table_args__ = {'extend_existing': True}
    
    # Primary identification
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Source location
    space_id = Column(String(255), nullable=False, index=True)
    graph_uri = Column(String(1000), nullable=False, index=True)
    
    # Job metadata
    job_name = Column(String(255), nullable=False)
    job_description = Column(String(1000), nullable=True)
    
    # Export configuration
    export_type = Column(String(50), nullable=False)  # 'full', 'filtered', 'query', 'incremental'
    filter_query = Column(Text, nullable=True)  # SPARQL query for filtered exports
    export_format = Column(String(50), nullable=False)  # 'turtle', 'n-triples', 'rdf-xml', 'json-ld'
    
    # Destination information
    destination_type = Column(String(50), nullable=False)  # 'file', 'url', 'download', 's3', 'ftp'
    destination_location = Column(String(2000), nullable=True)
    compression = Column(String(50), nullable=True)  # 'none', 'gzip', 'zip'
    
    # Status tracking
    status = Column(String(50), nullable=False, default='pending')
    progress_percent = Column(Float, nullable=True, default=0.0)
    
    # Timing
    created_time = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_time = Column(DateTime, nullable=True)
    completed_time = Column(DateTime, nullable=True)
    
    # Results
    total_triples = Column(BigInteger, nullable=True)
    exported_triples = Column(BigInteger, nullable=True, default=0)
    file_size = Column(BigInteger, nullable=True)  # Output file size in bytes
    checksum = Column(String(128), nullable=True)  # SHA-256 checksum
    
    # Download support
    download_url = Column(String(2000), nullable=True)
    download_expires = Column(DateTime, nullable=True)
    
    # Error handling
    error_message = Column(String(2000), nullable=True)
    error_details = Column(Text, nullable=True)
    
    # Audit
    tenant = Column(String(255), nullable=True)
    created_by = Column(String(255), nullable=False)
    
    # Indexes
    __table_args__ = (
        Index('idx_data_export_space_graph', 'space_id', 'graph_uri'),
        Index('idx_data_export_status', 'status'),
        Index('idx_data_export_created', 'created_time'),
        {'extend_existing': True}
    )
```

### 3. DataMigration Table (`{prefix}data_migration`)

**Purpose**: Track data migration between space + graph combinations

**Use Cases**:
- Move data between development/staging/production spaces
- Graph reorganization and consolidation
- Cross-tenant data migration

```python
class DataMigration(Base):
    __tablename__ = f'{prefix}data_migration'
    __table_args__ = {'extend_existing': True}
    
    # Primary identification
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Source location
    source_space_id = Column(String(255), nullable=False, index=True)
    source_graph_uri = Column(String(1000), nullable=False, index=True)
    
    # Destination location
    destination_space_id = Column(String(255), nullable=False, index=True)
    destination_graph_uri = Column(String(1000), nullable=False, index=True)
    
    # Job metadata
    migration_name = Column(String(255), nullable=False)
    migration_description = Column(String(1000), nullable=True)
    
    # Migration configuration
    migration_type = Column(String(50), nullable=False)  # 'copy', 'move', 'sync', 'merge'
    filter_query = Column(Text, nullable=True)  # SPARQL query to filter data
    conflict_resolution = Column(String(50), nullable=False, default='skip')  # 'skip', 'overwrite', 'merge', 'error'
    preserve_metadata = Column(Boolean, nullable=False, default=True)
    
    # Status tracking
    status = Column(String(50), nullable=False, default='pending')
    progress_percent = Column(Float, nullable=True, default=0.0)
    
    # Timing
    created_time = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_time = Column(DateTime, nullable=True)
    completed_time = Column(DateTime, nullable=True)
    
    # Results
    total_triples = Column(BigInteger, nullable=True)
    migrated_triples = Column(BigInteger, nullable=True, default=0)
    skipped_triples = Column(BigInteger, nullable=True, default=0)
    conflict_triples = Column(BigInteger, nullable=True, default=0)
    
    # Rollback support
    rollback_supported = Column(Boolean, nullable=False, default=False)
    rollback_data = Column(Text, nullable=True)  # JSON metadata for rollback
    
    # Error handling
    error_message = Column(String(2000), nullable=True)
    error_details = Column(Text, nullable=True)
    
    # Audit
    tenant = Column(String(255), nullable=True)
    created_by = Column(String(255), nullable=False)
    
    # Indexes
    __table_args__ = (
        Index('idx_data_migration_source', 'source_space_id', 'source_graph_uri'),
        Index('idx_data_migration_dest', 'destination_space_id', 'destination_graph_uri'),
        Index('idx_data_migration_status', 'status'),
        Index('idx_data_migration_created', 'created_time'),
        {'extend_existing': True}
    )
```

### 4. DataTracker Table (`{prefix}data_tracker`)

**Purpose**: Track processing cursors within space + graph data using hash-based ranges

**Use Cases**:
- Parallel processing coordination
- Incremental data processing
- Progress tracking for long-running operations
- Data validation and consistency checks

```python
class DataTracker(Base):
    __tablename__ = f'{prefix}data_tracker'
    __table_args__ = {'extend_existing': True}
    
    # Primary identification
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Target location
    space_id = Column(String(255), nullable=False, index=True)
    graph_uri = Column(String(1000), nullable=False, index=True)
    
    # Tracking metadata
    tracker_name = Column(String(255), nullable=False)
    tracker_description = Column(String(1000), nullable=True)
    operation_type = Column(String(100), nullable=False)  # 'validation', 'indexing', 'analysis', 'custom'
    
    # Hash-based cursor tracking
    tracking_mode = Column(String(50), nullable=False)  # 'single_cursor', 'range_slices'
    
    # Single cursor mode (simple hash-based cursor)
    current_hash = Column(String(128), nullable=True, index=True)  # SHA-256 hash of current position
    
    # Range slices mode (parallel processing support)
    total_slices = Column(Integer, nullable=True)  # Total number of parallel slices
    slice_number = Column(Integer, nullable=True)  # Current slice number (0-based)
    start_hash = Column(String(128), nullable=True, index=True)  # Start of hash range
    end_hash = Column(String(128), nullable=True, index=True)    # End of hash range
    slice_current_hash = Column(String(128), nullable=True)      # Current position within slice
    
    # Progress tracking
    status = Column(String(50), nullable=False, default='active')  # 'active', 'paused', 'completed', 'failed'
    progress_percent = Column(Float, nullable=True, default=0.0)
    items_processed = Column(BigInteger, nullable=True, default=0)
    items_total = Column(BigInteger, nullable=True)
    
    # Timing
    created_time = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_time = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    started_time = Column(DateTime, nullable=True)
    completed_time = Column(DateTime, nullable=True)
    
    # Configuration
    batch_size = Column(Integer, nullable=True, default=1000)
    checkpoint_interval = Column(Integer, nullable=True, default=10000)  # Items between checkpoints
    
    # Metadata
    processing_metadata = Column(Text, nullable=True)  # JSON metadata for the operation
    last_checkpoint_data = Column(Text, nullable=True)  # JSON data from last checkpoint
    
    # Error handling
    error_count = Column(Integer, nullable=True, default=0)
    last_error = Column(String(2000), nullable=True)
    error_details = Column(Text, nullable=True)
    
    # Audit
    tenant = Column(String(255), nullable=True)
    created_by = Column(String(255), nullable=False)
    process_id = Column(String(255), nullable=True)  # Process/worker ID for coordination
    
    # Indexes
    __table_args__ = (
        Index('idx_data_tracker_space_graph', 'space_id', 'graph_uri'),
        Index('idx_data_tracker_status', 'status'),
        Index('idx_data_tracker_hash', 'current_hash'),
        Index('idx_data_tracker_range', 'start_hash', 'end_hash'),
        Index('idx_data_tracker_updated', 'updated_time'),
        UniqueConstraint('space_id', 'graph_uri', 'tracker_name', 'slice_number', 
                        name='uq_tracker_slice'),
        {'extend_existing': True}
    )
```

### 5. DataCheckpoint Table (`{prefix}data_checkpoint`)

**Purpose**: Reference points in time using timestamps and hash values for backup, sync, and change tracking

**Use Cases**:
- Backup completion markers
- Data synchronization points
- Change detection since last checkpoint
- Audit trail for data modifications
- PostgreSQL WAL-based point-in-time recovery integration

```python
class DataCheckpoint(Base):
    __tablename__ = f'{prefix}data_checkpoint'
    __table_args__ = {'extend_existing': True}
    
    # Primary identification
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Target location
    space_id = Column(String(255), nullable=False, index=True)
    graph_uri = Column(String(1000), nullable=False, index=True)
    
    # Checkpoint identification
    checkpoint_name = Column(String(255), nullable=False)
    checkpoint_identifier = Column(String(255), nullable=False, index=True)  # Unique identifier
    checkpoint_description = Column(String(1000), nullable=True)
    
    # Point-in-time reference
    checkpoint_timestamp = Column(DateTime, nullable=False, index=True)
    checkpoint_hash = Column(String(128), nullable=False, index=True)  # SHA-256 hash of data state
    
    # PostgreSQL-specific checkpoint integration
    wal_lsn = Column(String(50), nullable=True, index=True)  # WAL Log Sequence Number
    transaction_id = Column(BigInteger, nullable=True, index=True)  # Transaction ID when checkpoint created
    snapshot_id = Column(String(50), nullable=True)  # Transaction snapshot for consistent reads
    restore_point_name = Column(String(255), nullable=True)  # Named PostgreSQL restore point
    
    # Checkpoint type and context
    checkpoint_type = Column(String(50), nullable=False)  # 'backup', 'sync', 'milestone', 'audit', 'database_level', 'custom'
    operation_context = Column(String(100), nullable=True)  # Context that created this checkpoint
    
    # Data statistics at checkpoint time
    triple_count = Column(BigInteger, nullable=True)
    data_size = Column(BigInteger, nullable=True)  # Size in bytes
    database_size = Column(BigInteger, nullable=True)  # Total database size at checkpoint
    wal_size = Column(BigInteger, nullable=True)  # WAL size at checkpoint
    last_modified = Column(DateTime, nullable=True)  # Last data modification before checkpoint
    
    # Verification
    verification_status = Column(String(50), nullable=False, default='pending')  # 'pending', 'verified', 'failed'
    verification_hash = Column(String(128), nullable=True)  # Independent verification hash
    verification_time = Column(DateTime, nullable=True)
    
    # Recovery support
    recovery_config = Column(Text, nullable=True)  # JSON recovery configuration for PostgreSQL
    pitr_supported = Column(Boolean, nullable=False, default=False)  # Point-in-time recovery available
    
    # Metadata
    checkpoint_metadata = Column(Text, nullable=True)  # JSON metadata about the checkpoint
    related_operations = Column(Text, nullable=True)   # JSON list of related operation IDs
    
    # Retention
    retention_policy = Column(String(50), nullable=True)  # 'permanent', 'temporary', 'auto_expire'
    expires_at = Column(DateTime, nullable=True)
    
    # Creation tracking
    created_time = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # Audit
    tenant = Column(String(255), nullable=True)
    created_by = Column(String(255), nullable=False)
    
    # Indexes
    __table_args__ = (
        Index('idx_data_checkpoint_space_graph', 'space_id', 'graph_uri'),
        Index('idx_data_checkpoint_timestamp', 'checkpoint_timestamp'),
        Index('idx_data_checkpoint_hash', 'checkpoint_hash'),
        Index('idx_data_checkpoint_type', 'checkpoint_type'),
        Index('idx_data_checkpoint_identifier', 'checkpoint_identifier'),
        Index('idx_data_checkpoint_wal_lsn', 'wal_lsn'),
        Index('idx_data_checkpoint_transaction_id', 'transaction_id'),
        UniqueConstraint('space_id', 'graph_uri', 'checkpoint_identifier', 
                        name='uq_checkpoint_identifier'),
        {'extend_existing': True}
    )
```

## Implementation Plan

### Phase 1: Model Integration
1. Add all five models to `create_models_with_prefix()` function
2. Update the return tuple to include new models
3. Update model cache and initialization logic
4. Create database migration scripts

### Phase 2: Management Methods
Add corresponding management methods to `PostgreSQLDbImpl` class:
- `list_data_imports()`, `add_data_import()`, `update_data_import()`, `remove_data_import()`
- `list_data_exports()`, `add_data_export()`, `update_data_export()`, `remove_data_export()`
- `list_data_migrations()`, `add_data_migration()`, `update_data_migration()`, `remove_data_migration()`
- `list_data_trackers()`, `add_data_tracker()`, `update_data_tracker()`, `remove_data_tracker()`
- `list_data_checkpoints()`, `add_data_checkpoint()`, `update_data_checkpoint()`, `remove_data_checkpoint()`

### Phase 3: Service Layer
Create service classes for each data management operation:
- `DataImportService` - Handle file imports with progress tracking
- `DataExportService` - Handle exports with format conversion
- `DataMigrationService` - Coordinate space-to-space migrations
- `DataTrackerService` - Manage cursor-based processing coordination
- `DataCheckpointService` - Create and verify checkpoints

### Phase 4: API Integration
Add REST API endpoints for data management operations:
- `/api/data/import/` - Import management endpoints
- `/api/data/export/` - Export management endpoints
- `/api/data/migration/` - Migration management endpoints
- `/api/data/tracker/` - Processing tracking endpoints
- `/api/data/checkpoint/` - Checkpoint management endpoints

## Key Design Features

### Multi-tenancy Support
All tables include optional `tenant` column for multi-tenant deployments.

### Space + Graph Targeting
All tables include both `space_id` and `graph_uri` for precise targeting of operations.

### Hash-based Tracking
DataTracker and DataCheckpoint use SHA-256 hashes for reliable cursor positioning and state verification.

### Parallel Processing Support
DataTracker supports both single cursor and range-based slicing for parallel processing coordination.

### Comprehensive Auditing
All tables include creation tracking, error handling, and audit fields.

### Performance Optimization
Strategic indexes on frequently queried columns (space_id, graph_uri, status, timestamps, hashes).

### Extensibility
JSON metadata fields allow for future extensions without schema changes.

## Usage Examples

### Import Workflow
```python
# Create import job
import_job = await db_impl.add_data_import({
    'space_id': 'my_space',
    'graph_uri': 'http://example.org/graph1',
    'job_name': 'Import WordNet Data',
    'source_type': 'file',
    'source_location': '/data/wordnet.ttl',
    'source_format': 'turtle',
    'created_by': 'admin'
})

# Track progress
await db_impl.update_data_import(import_job['id'], {
    'status': 'running',
    'progress_percent': 45.0,
    'imported_triples': 125000
})
```

### Checkpoint Creation
```python
# Create checkpoint after backup
checkpoint = await db_impl.add_data_checkpoint({
    'space_id': 'production_space',
    'graph_uri': 'http://example.org/main_graph',
    'checkpoint_name': 'Daily Backup',
    'checkpoint_identifier': 'backup_2025_08_30',
    'checkpoint_type': 'backup',
    'checkpoint_timestamp': datetime.utcnow(),
    'checkpoint_hash': calculate_graph_hash(space_id, graph_uri),
    'created_by': 'backup_service'
})
```

### Parallel Processing Setup
```python
# Create tracker for parallel validation
for slice_num in range(4):  # 4 parallel workers
    tracker = await db_impl.add_data_tracker({
        'space_id': 'large_space',
        'graph_uri': 'http://example.org/big_graph',
        'tracker_name': 'validation_job_001',
        'operation_type': 'validation',
        'tracking_mode': 'range_slices',
        'total_slices': 4,
        'slice_number': slice_num,
        'start_hash': calculate_slice_start_hash(slice_num, 4),
        'end_hash': calculate_slice_end_hash(slice_num, 4),
        'created_by': 'validation_service'
    })
```

## PostgreSQL Built-in Checkpoint Integration

### PostgreSQL Native Features

VitalGraph's DataCheckpoint system leverages PostgreSQL's built-in checkpoint and recovery mechanisms:

#### 1. **WAL (Write-Ahead Logging) Checkpoints**
- **Automatic**: Triggered by `checkpoint_timeout` (default 5 minutes) or `max_wal_size`
- **Manual**: Can be triggered with `CHECKPOINT` command
- **Integration**: Our checkpoints align with PostgreSQL WAL positions

#### 2. **Point-in-Time Recovery (PITR)**
```sql
-- Create a restore point
SELECT pg_create_restore_point('backup_before_import');

-- Get current WAL position
SELECT pg_current_wal_lsn();
-- Returns: 0/1A2B3C4D
```

#### 3. **Transaction Snapshots**
```sql
-- Get current transaction snapshot
SELECT pg_export_snapshot();
-- Returns: 00000003-0000001B-1

-- Use snapshot in another transaction
SET TRANSACTION SNAPSHOT '00000003-0000001B-1';
```

### Enhanced Implementation Methods

#### Database-Level Checkpoint Creation
```python
async def create_database_checkpoint(self, space_id: str, graph_uri: str, checkpoint_name: str):
    """Create a checkpoint with PostgreSQL WAL integration"""
    
    # Create named restore point
    restore_point_name = f"vitalgraph_{checkpoint_name}_{int(time.time())}"
    
    with self.engine.connect() as conn:
        # Create PostgreSQL restore point
        result = conn.execute(text(f"SELECT pg_create_restore_point('{restore_point_name}')"))
        wal_lsn = result.scalar()
        
        # Get current transaction info
        tx_info = conn.execute(text("""
            SELECT 
                pg_current_wal_lsn() as current_lsn,
                txid_current() as transaction_id,
                pg_export_snapshot() as snapshot_id,
                pg_database_size(current_database()) as db_size,
                pg_wal_lsn_diff(pg_current_wal_lsn(), '0/0') as wal_size
        """)).fetchone()
        
        # Create our application-level checkpoint
        checkpoint_data = {
            'space_id': space_id,
            'graph_uri': graph_uri,
            'checkpoint_name': checkpoint_name,
            'checkpoint_identifier': f"{checkpoint_name}_{int(time.time())}",
            'checkpoint_timestamp': datetime.utcnow(),
            'checkpoint_hash': await self.calculate_graph_hash(space_id, graph_uri),
            'wal_lsn': str(tx_info.current_lsn),
            'transaction_id': tx_info.transaction_id,
            'snapshot_id': tx_info.snapshot_id,
            'restore_point_name': restore_point_name,
            'database_size': tx_info.db_size,
            'wal_size': tx_info.wal_size,
            'checkpoint_type': 'database_level',
            'pitr_supported': True,
            'recovery_config': json.dumps({
                'restore_point': restore_point_name,
                'wal_lsn': str(tx_info.current_lsn),
                'recovery_target_name': restore_point_name
            })
        }
        
        return await self.add_data_checkpoint(checkpoint_data)
```

#### Change Detection Since Checkpoint
```python
async def get_changes_since_checkpoint(self, checkpoint_id: int):
    """Detect changes since a specific checkpoint using PostgreSQL features"""
    
    checkpoint = await self.get_data_checkpoint(checkpoint_id)
    if not checkpoint:
        return None
    
    with self.engine.connect() as conn:
        # Query for WAL changes since checkpoint
        if checkpoint.get('wal_lsn'):
            wal_changes = conn.execute(text("""
                SELECT pg_wal_lsn_diff(pg_current_wal_lsn(), :checkpoint_lsn) as bytes_changed
            """), {'checkpoint_lsn': checkpoint['wal_lsn']}).scalar()
        
        # Query for table-level statistics changes
        stats_changes = conn.execute(text("""
            SELECT 
                schemaname, tablename, 
                n_tup_ins, n_tup_upd, n_tup_del,
                last_vacuum, last_autovacuum,
                last_analyze, last_autoanalyze
            FROM pg_stat_user_tables 
            WHERE schemaname = 'public'
            AND (last_vacuum > :checkpoint_time 
                 OR last_autovacuum > :checkpoint_time
                 OR last_analyze > :checkpoint_time 
                 OR last_autoanalyze > :checkpoint_time)
        """), {'checkpoint_time': checkpoint['checkpoint_timestamp']}).fetchall()
        
        return {
            'wal_bytes_changed': wal_changes,
            'table_changes': [dict(row) for row in stats_changes],
            'has_changes': wal_changes > 0 or len(stats_changes) > 0
        }
```

#### WAL-Based Recovery Configuration
```python
async def generate_recovery_config(self, checkpoint_id: int):
    """Generate PostgreSQL recovery configuration for checkpoint restoration"""
    
    checkpoint = await self.get_data_checkpoint(checkpoint_id)
    if not checkpoint or not checkpoint.get('pitr_supported'):
        raise ValueError("Checkpoint does not support point-in-time recovery")
    
    recovery_config = {
        'postgresql_recovery_conf': f"""
# Recovery to VitalGraph checkpoint: {checkpoint['checkpoint_name']}
# Created: {checkpoint['created_time']}

restore_command = 'cp /path/to/wal_archive/%f %p'
recovery_target_name = '{checkpoint['restore_point_name']}'
recovery_target_action = 'promote'

# Alternative recovery targets:
# recovery_target_lsn = '{checkpoint['wal_lsn']}'
# recovery_target_time = '{checkpoint['checkpoint_timestamp'].isoformat()}'
        """,
        'recovery_steps': [
            "1. Stop PostgreSQL server",
            "2. Replace data directory with base backup",
            "3. Create recovery.conf with above configuration",
            "4. Start PostgreSQL server (will enter recovery mode)",
            "5. Server will automatically promote after reaching target"
        ],
        'verification_queries': [
            f"SELECT txid_current() >= {checkpoint['transaction_id']} as recovery_complete;",
            f"SELECT pg_current_wal_lsn() >= '{checkpoint['wal_lsn']}' as lsn_reached;"
        ]
    }
    
    return recovery_config
```

### Integration Benefits

#### 1. **Atomic Consistency**
- PostgreSQL checkpoints ensure ACID compliance
- Application checkpoints align with database transaction boundaries
- Consistent state across all tables and spaces

#### 2. **Point-in-Time Recovery**
- Can restore entire database to exact checkpoint moment
- Combines application-level and database-level recovery
- Supports both named restore points and LSN-based recovery

#### 3. **Change Tracking**
- Use WAL LSN positions to detect any database changes
- Transaction IDs provide precise change ordering
- Table statistics show specific modification patterns

#### 4. **Performance Optimization**
- Leverage PostgreSQL's optimized checkpoint mechanisms
- Avoid reinventing database-level consistency features
- Efficient change detection using built-in monitoring

#### 5. **Operational Integration**
- Integrates with existing PostgreSQL backup/restore procedures
- Compatible with streaming replication and standby servers
- Works with PostgreSQL's continuous archiving

### Usage Examples with PostgreSQL Integration

#### Creating a Database-Level Checkpoint
```python
# Create checkpoint with full PostgreSQL integration
checkpoint = await db_impl.create_database_checkpoint(
    space_id='production_space',
    graph_uri='http://example.org/main_graph',
    checkpoint_name='pre_migration_backup'
)

# Checkpoint includes:
# - WAL LSN position
# - Transaction ID
# - Named restore point
# - Database size metrics
# - Recovery configuration
```

#### Detecting Changes Since Checkpoint
```python
# Check what changed since checkpoint
changes = await db_impl.get_changes_since_checkpoint(checkpoint['id'])

if changes['has_changes']:
    print(f"WAL bytes changed: {changes['wal_bytes_changed']}")
    print(f"Tables modified: {len(changes['table_changes'])}")
    
    # Optionally create new checkpoint
    if changes['wal_bytes_changed'] > 1000000:  # 1MB of changes
        await db_impl.create_database_checkpoint(
            space_id='production_space',
            graph_uri='http://example.org/main_graph',
            checkpoint_name='incremental_backup'
        )
```

#### Recovery Preparation
```python
# Generate recovery configuration
recovery_info = await db_impl.generate_recovery_config(checkpoint['id'])

# Save recovery configuration to file
with open('recovery.conf', 'w') as f:
    f.write(recovery_info['postgresql_recovery_conf'])

# Display recovery steps
for step in recovery_info['recovery_steps']:
    print(step)
```

## PostgreSQL CTID-Based Cursor Tracking

### Enhanced DataTracker with CTID Integration

Building on PostgreSQL's native row identifiers, the DataTracker system can leverage CTID (tuple identifiers) for highly efficient cursor tracking and parallel processing:

#### Enhanced DataTracker Schema
```python
class DataTracker(Base):
    # ... existing fields ...
    
    # CTID-based tracking
    min_ctid = Column(String(20), nullable=True)     # "(0,1)" - table minimum
    max_ctid = Column(String(20), nullable=True)     # "(999999,999)" - table maximum
    current_ctid = Column(String(20), nullable=True) # "(1234,56)" - current position
    
    # Range splitting for parallel processing
    ctid_range_start = Column(String(20), nullable=True)  # This worker's start CTID
    ctid_range_end = Column(String(20), nullable=True)    # This worker's end CTID
    
    # UUID mapping for shareable cursors
    cursor_uuid = Column(String(36), nullable=True)       # UUID representing current position
    uuid_to_ctid_map = Column(JSON, nullable=True)        # {"uuid": "ctid"} mapping
    
    # PostgreSQL-specific tracking fields
    last_transaction_id = Column(BigInteger, nullable=True)  # Last processed xmin
    cursor_type = Column(String(50), nullable=False, default='hybrid')  # 'hash', 'ctid', 'transaction', 'hybrid'
```

### CTID Range Analysis and Parallel Processing

#### Table Range Analysis
```python
async def analyze_table_ctid_range(self, space_id: str, graph_uri: str):
    """Analyze CTID range for efficient parallel processing setup"""
    
    table_name = f"{self.table_prefix}{space_id}__rdf_quad"
    
    with self.engine.connect() as conn:
        range_info = conn.execute(text(f"""
            SELECT 
                MIN(ctid) as min_ctid,
                MAX(ctid) as max_ctid,
                COUNT(*) as total_rows,
                -- Extract page numbers for range calculation
                MIN((ctid::text::point)[0]::bigint) as min_page,
                MAX((ctid::text::point)[0]::bigint) as max_page,
                -- Get approximate pages with data
                COUNT(DISTINCT (ctid::text::point)[0]::bigint) as pages_with_data
            FROM {table_name}
        """)).fetchone()
        
        return {
            'min_ctid': str(range_info.min_ctid),
            'max_ctid': str(range_info.max_ctid),
            'total_rows': range_info.total_rows,
            'min_page': range_info.min_page,
            'max_page': range_info.max_page,
            'pages_with_data': range_info.pages_with_data,
            'avg_rows_per_page': range_info.total_rows / max(range_info.pages_with_data, 1)
        }
```

#### Intelligent Range Splitting
```python
async def split_ctid_range_for_parallel_processing(self, space_id: str, graph_uri: str, num_workers: int):
    """Split CTID range into N balanced parallel processing ranges"""
    
    range_info = await self.analyze_table_ctid_range(space_id, graph_uri)
    if not range_info:
        return []
    
    min_page = range_info['min_page']
    max_page = range_info['max_page']
    total_pages = max_page - min_page + 1
    
    # Calculate pages per worker for balanced distribution
    pages_per_worker = max(1, total_pages // num_workers)
    
    ranges = []
    for worker_id in range(num_workers):
        start_page = min_page + (worker_id * pages_per_worker)
        
        if worker_id == num_workers - 1:
            # Last worker gets remaining pages
            end_page = max_page
        else:
            end_page = min(max_page, start_page + pages_per_worker - 1)
        
        # Create CTID range for this worker
        range_start = f"({start_page},1)"
        range_end = f"({end_page},65535)"  # Max tuple number per page
        
        ranges.append({
            'worker_id': worker_id,
            'ctid_range_start': range_start,
            'ctid_range_end': range_end,
            'estimated_pages': end_page - start_page + 1,
            'page_range': [start_page, end_page]
        })
    
    return ranges
```

### UUID-to-CTID Mapping for Shareable Cursors

#### Cursor Mapping Creation
```python
async def create_uuid_cursor_mapping(self, space_id: str, graph_uri: str, sample_size: int = 1000):
    """Create UUID-to-CTID mapping for shareable cursors across systems"""
    
    table_name = f"{self.table_prefix}{space_id}__rdf_quad"
    
    with self.engine.connect() as conn:
        # Sample rows across the CTID range to create mapping points
        sample_rows = conn.execute(text(f"""
            WITH table_sample AS (
                SELECT ctid, subject_uuid, predicate_uuid, object_uuid
                FROM {table_name} 
                TABLESAMPLE SYSTEM(10)  -- 10% sample for representative distribution
                ORDER BY ctid
                LIMIT :sample_size
            )
            SELECT 
                ctid,
                subject_uuid,
                -- Create a composite UUID for cursor positioning
                MD5(subject_uuid::text || predicate_uuid::text || object_uuid::text)::uuid as cursor_uuid,
                ROW_NUMBER() OVER (ORDER BY ctid) as position_rank
            FROM table_sample
        """), {'sample_size': sample_size}).fetchall()
        
        # Build UUID-to-CTID mapping for cursor sharing
        uuid_mapping = {}
        for row in sample_rows:
            uuid_mapping[str(row.cursor_uuid)] = {
                'ctid': str(row.ctid),
                'position_rank': row.position_rank,
                'subject_uuid': str(row.subject_uuid)
            }
        
        return uuid_mapping
```

#### Cursor Resolution
```python
async def find_ctid_by_uuid_cursor(self, uuid_cursor: str, uuid_mapping: dict):
    """Resolve UUID cursor to actual CTID position"""
    
    if uuid_cursor in uuid_mapping:
        return uuid_mapping[uuid_cursor]['ctid']
    
    # Find closest UUID cursor using hash-based proximity
    target_uuid_hash = int(uuid_cursor.replace('-', ''), 16)
    closest_ctid = None
    min_distance = float('inf')
    
    for uuid, data in uuid_mapping.items():
        uuid_hash = int(uuid.replace('-', ''), 16)
        distance = abs(uuid_hash - target_uuid_hash)
        
        if distance < min_distance:
            min_distance = distance
            closest_ctid = data['ctid']
    
    return closest_ctid
```

### Parallel Processing Implementation

#### Setup Parallel Workers
```python
async def setup_parallel_processing_with_ranges(self, space_id: str, graph_uri: str, operation_type: str, num_workers: int):
    """Setup parallel processing using CTID ranges and UUID cursors"""
    
    # Analyze table and split ranges
    ctid_ranges = await self.split_ctid_range_for_parallel_processing(space_id, graph_uri, num_workers)
    
    # Create UUID mapping for cursor sharing
    uuid_mapping = await self.create_uuid_cursor_mapping(space_id, graph_uri)
    
    trackers = []
    operation_id = f"{operation_type}_{int(time.time())}"
    
    for range_info in ctid_ranges:
        # Generate UUID cursor for this range start
        range_start_uuid = str(uuid.uuid4())
        
        tracker_data = {
            'space_id': space_id,
            'graph_uri': graph_uri,
            'tracker_name': f"{operation_id}_worker_{range_info['worker_id']}",
            'operation_type': operation_type,
            'tracking_mode': 'ctid_ranges',
            
            # CTID range for this worker
            'ctid_range_start': range_info['ctid_range_start'],
            'ctid_range_end': range_info['ctid_range_end'],
            'current_ctid': range_info['ctid_range_start'],
            
            # UUID cursor mapping
            'cursor_uuid': range_start_uuid,
            'uuid_to_ctid_map': json.dumps(uuid_mapping),
            
            # Parallel processing metadata
            'total_slices': num_workers,
            'slice_number': range_info['worker_id'],
            'estimated_pages': range_info['estimated_pages'],
            
            'created_by': 'parallel_processor'
        }
        
        tracker = await self.add_data_tracker(tracker_data)
        trackers.append(tracker)
    
    return trackers
```

#### Range Processing
```python
async def process_ctid_range(self, tracker_id: int, batch_size: int = 1000):
    """Process rows within a specific CTID range with precise positioning"""
    
    tracker = await self.get_data_tracker(tracker_id)
    table_name = f"{self.table_prefix}{tracker['space_id']}__rdf_quad"
    
    current_ctid = tracker['current_ctid']
    range_end = tracker['ctid_range_end']
    
    with self.engine.connect() as conn:
        # Process batch within CTID range
        rows = conn.execute(text(f"""
            SELECT ctid, subject_uuid, predicate_uuid, object_uuid, context_uuid
            FROM {table_name}
            WHERE ctid >= :current_ctid::tid 
              AND ctid <= :range_end::tid
            ORDER BY ctid
            LIMIT :batch_size
        """), {
            'current_ctid': current_ctid,
            'range_end': range_end,
            'batch_size': batch_size
        }).fetchall()
        
        if not rows:
            # Range completed
            await self.update_data_tracker(tracker_id, {
                'status': 'completed',
                'completion_time': datetime.utcnow()
            })
            return {'status': 'completed', 'processed': 0}
        
        # Process the rows and update position
        processed_count = len(rows)
        new_current_ctid = str(rows[-1].ctid)
        
        await self.update_data_tracker(tracker_id, {
            'current_ctid': new_current_ctid,
            'items_processed': tracker['items_processed'] + processed_count,
            'last_update_time': datetime.utcnow()
        })
        
        # Check if range is completed
        is_completed = (new_current_ctid >= range_end) or (len(rows) < batch_size)
        
        return {
            'status': 'completed' if is_completed else 'in_progress',
            'processed': processed_count,
            'current_ctid': new_current_ctid,
            'range_progress': f"{new_current_ctid} / {range_end}"
        }
```

### Benefits of CTID-Based Tracking

#### 1. **Efficient Range Distribution**
- **Page-based splitting**: Distributes work by PostgreSQL pages for balanced load
- **Sequential access**: CTID ordering enables efficient sequential scanning
- **Predictable performance**: Page-based ranges have consistent processing times

#### 2. **Shareable UUID Cursors**
- **Cross-system compatibility**: UUIDs can be shared between different systems
- **Resumable operations**: Workers can resume from UUID cursors without internal knowledge
- **Coordination**: Multiple systems can coordinate using shared UUID cursor positions

#### 3. **Precise Position Tracking**
- **Exact positioning**: CTID provides exact row location within table
- **Fine-grained progress**: Track progress down to individual row level
- **Fault tolerance**: Resume from exact position after failures

#### 4. **Hybrid Cursor Strategy**
```python
# Combine multiple cursor types for robust tracking
cursor_strategy = {
    'primary_cursor': 'ctid',           # For sequential scanning
    'secondary_cursor': 'transaction',   # For change detection
    'shareable_cursor': 'uuid',         # For cross-system coordination
    'verification_cursor': 'hash'       # For consistency checking
}
```

#### 5. **Load Balancing Optimization**
- **Page distribution**: Avoids hotspots by distributing pages evenly
- **Dynamic adjustment**: Can rebalance ranges based on actual processing rates
- **Resource utilization**: Maximizes parallel processing efficiency

### Usage Examples

#### Setting Up Parallel Export
```python
# Setup 4 parallel workers for data export
trackers = await db_impl.setup_parallel_processing_with_ranges(
    space_id='production_space',
    graph_uri='http://example.org/main_graph',
    operation_type='data_export',
    num_workers=4
)

# Each worker gets a balanced CTID range:
# Worker 0: pages 0-249    -> CTID range (0,1) to (249,65535)
# Worker 1: pages 250-499  -> CTID range (250,1) to (499,65535)
# Worker 2: pages 500-749  -> CTID range (500,1) to (749,65535)
# Worker 3: pages 750-999  -> CTID range (750,1) to (999,65535)
```

#### Processing with UUID Cursor Sharing
```python
# Worker can share progress using UUID cursor
worker_progress = {
    'uuid_cursor': '550e8400-e29b-41d4-a716-446655440000',
    'ctid_position': '(1234,56)',
    'range_completion': '45%'
}

# Other systems can resume from this UUID cursor
resume_ctid = await db_impl.find_ctid_by_uuid_cursor(
    worker_progress['uuid_cursor'],
    uuid_mapping
)
```

This comprehensive design provides a robust foundation for all data management operations in VitalGraph while maintaining consistency with the existing architecture patterns and leveraging PostgreSQL's powerful built-in checkpoint and recovery capabilities, enhanced with efficient CTID-based cursor tracking and UUID-based coordination for optimal parallel processing performance.
