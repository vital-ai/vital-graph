# VitalGraph Database Architecture

## Overview

VitalGraph is a graph database implementation built on PostgreSQL that provides RDF storage and SPARQL query capabilities. This document describes the intended architecture and proper calling conventions for the codebase.

## Architecture Layers

The VitalGraph implementation follows a layered architecture with clear separation of concerns:

```
┌─────────────────────────────────────────────────────────────┐
│                    Application Layer                        │
├─────────────────────────────────────────────────────────────┤
│  FastAPI REST Server     │  Command Line Tools              │
│  (VitalGraphAppImpl)      │  (bin/vitalgraph*)               │
└─────────────────┬───────────────────┬─────────────────────────┘
                  │                   │
                  ▼                   ▼
┌─────────────────────────────────────────────────────────────┐
│                 VitalGraphImpl                              │
│              (Main Entry Point)                             │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                   SpaceManager                              │
│            (Manages Multiple Spaces)                        │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    SpaceImpl                                │
│         (Abstract Interface for Graph Spaces)              │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              PostgreSQLSpaceImpl                            │
│           (PostgreSQL-specific Implementation)              │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                PostgreSQL Database                          │
│              (Physical Storage Layer)                       │
└─────────────────────────────────────────────────────────────┘
```

## Component Descriptions

### 1. VitalGraphImpl (Main Entry Point)

**Location**: `vitalgraph/impl/vitalgraph_impl.py`

**Purpose**: Primary entry point for all VitalGraph operations. All external code should interact with VitalGraph through this interface.

**Responsibilities**:
- Configuration management and initialization
- Database connection lifecycle management
- Access to SpaceManager for space operations
- Service-level operations and status reporting

**Key Methods**:
```python
async def initialize() -> bool
async def shutdown() -> bool
def get_space_manager() -> SpaceManager
async def get_service_status() -> dict
```

### 2. VitalGraphAppImpl (FastAPI Wrapper)

**Location**: `vitalgraph/app/vitalgraph_app_impl.py`

**Purpose**: Wraps VitalGraphImpl for FastAPI REST server deployment.

**Responsibilities**:
- FastAPI application lifecycle management
- REST endpoint routing and request handling
- Authentication and authorization
- HTTP request/response handling

**Usage**: Should only be used by the FastAPI server startup code.

### 3. SpaceManager

**Location**: `vitalgraph/space/space_manager.py`

**Purpose**: Manages multiple graph spaces within a VitalGraph instance.

**Responsibilities**:
- Space creation, deletion, and lifecycle management
- Space registry and metadata management
- Space discovery and enumeration
- Delegation to appropriate SpaceImpl instances

**Key Methods**:
```python
async def create_space(space_id: str) -> bool
async def delete_space(space_id: str) -> bool
async def get_space_impl(space_id: str) -> SpaceImpl
async def list_spaces() -> List[str]
```

### 4. SpaceImpl (Abstract Interface)

**Location**: `vitalgraph/space/space_impl.py`

**Purpose**: Abstract interface for graph space implementations.

**Responsibilities**:
- Defines the contract for space operations
- RDF triple/quad storage and retrieval
- SPARQL query execution
- Space-specific configuration and metadata

**Key Methods**:
```python
async def add_triple(triple: tuple, context: str = None) -> bool
async def remove_triple(triple: tuple, context: str = None) -> bool
async def get_triples(pattern: tuple, context: str = None) -> AsyncIterator
async def execute_sparql_query(query: str) -> dict
async def get_space_info() -> dict
```

### 5. PostgreSQLSpaceImpl (PostgreSQL Implementation)

**Location**: `vitalgraph/db/postgresql/postgresql_space_impl.py`

**Purpose**: PostgreSQL-specific implementation of SpaceImpl.

**Responsibilities**:
- PostgreSQL table management for each space
- RDF data storage in PostgreSQL tables
- SPARQL-to-SQL translation and execution
- PostgreSQL-specific optimizations and features

**Table Structure per Space**:
- `{global_prefix}__{space_id}__rdf_quad` - Stores RDF quads
- `{global_prefix}__{space_id}__term` - Stores RDF terms (URIs, literals, blank nodes)
- `{global_prefix}__{space_id}__datatype` - Stores datatype information
- `{global_prefix}__{space_id}__namespace` - Stores namespace prefixes

## Database Schema Architecture

### Global Tables (Per VitalGraph Instance)

These tables are shared across all spaces:

```sql
-- Space registry
{global_prefix}__space (
    id BIGSERIAL PRIMARY KEY,
    space_id VARCHAR(255) UNIQUE,
    created_at TIMESTAMP,
    tenant VARCHAR(255)
)

-- User management
{global_prefix}__user (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(255) UNIQUE,
    ...
)

-- Installation metadata
{global_prefix}__install (
    id BIGSERIAL PRIMARY KEY,
    version VARCHAR(255),
    installed_at TIMESTAMP
)
```

### Space-Specific Tables (Per Graph Space)

Each space gets its own set of tables:

```sql
-- RDF quads storage
{global_prefix}__{space_id}__rdf_quad (
    id BIGSERIAL PRIMARY KEY,
    subject_uuid UUID,
    predicate_uuid UUID,
    object_uuid UUID,
    context_uuid UUID
)

-- Term storage (URIs, literals, blank nodes)
{global_prefix}__{space_id}__term (
    term_uuid UUID PRIMARY KEY,
    term_text TEXT,
    term_type CHAR(1), -- 'U'=URI, 'L'=Literal, 'B'=Blank
    language VARCHAR(10),
    datatype_id BIGINT
)

-- Datatype registry
{global_prefix}__{space_id}__datatype (
    id BIGSERIAL PRIMARY KEY,
    datatype_uri TEXT UNIQUE
)

-- Namespace prefixes
{global_prefix}__{space_id}__namespace (
    id BIGSERIAL PRIMARY KEY,
    prefix VARCHAR(255),
    namespace_uri TEXT
)
```

## Proper Calling Conventions

### ✅ Correct Usage Pattern

```python
# Application code should follow this pattern:

# 1. Initialize VitalGraphImpl
vitalgraph_impl = VitalGraphImpl(config)
await vitalgraph_impl.initialize()

# 2. Get SpaceManager
space_manager = vitalgraph_impl.get_space_manager()

# 3. Get or create space
space_impl = await space_manager.get_space_impl("my_space")
if not space_impl:
    await space_manager.create_space("my_space")
    space_impl = await space_manager.get_space_impl("my_space")

# 4. Perform operations
await space_impl.add_triple(("http://example.org/s", "http://example.org/p", "http://example.org/o"))
results = await space_impl.execute_sparql_query("SELECT * WHERE { ?s ?p ?o }")
```

### ❌ Incorrect Usage Patterns (To Be Fixed)

```python
# DON'T: Direct PostgreSQL access
from vitalgraph.db.postgresql.postgresql_db_impl import PostgreSQLDbImpl
db_impl = PostgreSQLDbImpl(config)  # Bypasses proper interfaces

# DON'T: Direct SpaceImpl instantiation
from vitalgraph.db.postgresql.postgresql_space_impl import PostgreSQLSpaceImpl
space_impl = PostgreSQLSpaceImpl(...)  # Should go through SpaceManager

# DON'T: Direct database operations
import psycopg2
conn = psycopg2.connect(...)  # Should use VitalGraphImpl interfaces
```

## Component Interfaces

### REST API Endpoints

**Location**: `vitalgraph/api/`

**Current Status**: ⚠️ Some endpoints may bypass proper interfaces

**Required Pattern**:
```python
# REST endpoints should follow this pattern:
@app.post("/api/spaces/{space_id}/query")
async def execute_sparql_query(space_id: str, query: str):
    vitalgraph_impl = get_vitalgraph_impl()  # From app context
    space_manager = vitalgraph_impl.get_space_manager()
    space_impl = await space_manager.get_space_impl(space_id)
    return await space_impl.execute_sparql_query(query)
```

### Command Line Tools

**Location**: `bin/`

**Current Status**: ⚠️ Some tools connect directly to underlying components

**Required Pattern**:
```python
# Command line tools should follow this pattern:
async def main():
    config = load_config()
    vitalgraph_impl = VitalGraphImpl(config)
    await vitalgraph_impl.initialize()
    
    # Use vitalgraph_impl for all operations
    space_manager = vitalgraph_impl.get_space_manager()
    # ... perform operations
    
    await vitalgraph_impl.shutdown()
```

## Migration Guidelines

### Code That Needs Updates

1. **Direct PostgreSQL Access**: Any code importing and using `PostgreSQLDbImpl` or `PostgreSQLSpaceImpl` directly
2. **Legacy Command Line Tools**: Tools that connect directly to databases
3. **Test Scripts**: Tests that bypass the proper interface layers
4. **REST Endpoints**: API endpoints that don't use VitalGraphImpl

### Migration Steps

1. **Identify Direct Database Access**:
   ```bash
   grep -r "PostgreSQLDbImpl\|PostgreSQLSpaceImpl" --include="*.py" .
   ```

2. **Update Import Statements**:
   ```python
   # Before
   from vitalgraph.db.postgresql.postgresql_space_impl import PostgreSQLSpaceImpl
   
   # After
   from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
   ```

3. **Update Initialization Code**:
   ```python
   # Before
   space_impl = PostgreSQLSpaceImpl(config)
   
   # After
   vitalgraph_impl = VitalGraphImpl(config)
   await vitalgraph_impl.initialize()
   space_manager = vitalgraph_impl.get_space_manager()
   space_impl = await space_manager.get_space_impl(space_id)
   ```

4. **Update Configuration Handling**:
   - Use VitalGraphImpl's configuration management
   - Remove direct database configuration handling

## Benefits of Proper Architecture

1. **Abstraction**: Clean separation between interface and implementation
2. **Testability**: Easy to mock interfaces for testing
3. **Flexibility**: Can swap implementations without changing client code
4. **Maintainability**: Clear boundaries and responsibilities
5. **Scalability**: Proper resource management and connection pooling
6. **Configuration**: Centralized configuration and initialization

## Next Steps

1. **Audit Current Code**: Identify all code that bypasses proper interfaces
2. **Update REST Endpoints**: Ensure all API endpoints use VitalGraphImpl
3. **Update Command Line Tools**: Migrate tools to use proper entry points
4. **Update Test Scripts**: Ensure tests follow proper patterns
5. **Documentation**: Update code documentation to reflect proper usage
6. **Deprecation**: Mark direct access methods as deprecated

## File Locations Reference

```
vitalgraph/
├── impl/
│   └── vitalgraph_impl.py          # Main entry point
├── app/
│   └── vitalgraph_app_impl.py      # FastAPI wrapper
├── space/
│   ├── space_manager.py            # Space management
│   └── space_impl.py               # Abstract space interface
├── db/
│   └── postgresql/
│       ├── postgresql_space_impl.py # PostgreSQL implementation
│       └── postgresql_db_impl.py    # Database admin operations
├── api/
│   └── *.py                        # REST API endpoints
└── config/
    └── config_loader.py            # Configuration management

bin/
├── vitalgraph                      # Main CLI tool
├── vitalgraphadmin                 # Admin CLI tool
└── vitalgraphdb                    # Database CLI tool
```

This architecture ensures clean separation of concerns, proper abstraction layers, and maintainable code that can evolve with changing requirements.
