# VitalGraph Space Backend Interface Implementation Plan

## Overview

This plan outlines the creation of an abstract interface for VitalGraph space backends to enable support for multiple database/storage backends (PostgreSQL, Oxigraph, Fuseki, Mock) through a unified interface.

## Current State Analysis

### Existing Implementation
- **PostgreSQLSpaceImpl**: Fully functional PostgreSQL backend with comprehensive RDF operations
- **MockSpace**: Basic mock implementation using pyoxigraph for testing
- **FusekiSpaceImpl**: Empty file, needs implementation
- **SpaceImpl**: Wrapper class that delegates to backend-specific implementations

### Methods Used by SpaceImpl
Based on analysis of `/vitalgraph/space/space_impl.py`, the following methods are called:

1. **Core Lifecycle Methods**:
   - `create_space_tables(space_id: str) -> bool` (async)
   - `delete_space_tables(space_id: str) -> bool` (async) 
   - `space_exists(space_id: str) -> bool` (async)

2. **Namespace Management**:
   - `add_namespace(space_id: str, prefix: str, namespace_uri: str) -> Optional[int]` (async)

## Implementation Plan

### Phase 1: Abstract Interface Design

#### 1.1 Create Abstract Base Class
**File**: `/vitalgraph/db/space_inf.py`

```python
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Union, Tuple, AsyncGenerator
from rdflib import URIRef, Literal, BNode, Variable
from rdflib.term import Identifier

class SpaceBackendInterface(ABC):
    """
    Abstract interface for VitalGraph space backend implementations.
    
    This interface defines the contract that all space backends must implement
    to provide RDF storage and retrieval capabilities.
    """
    
    # Core Lifecycle Methods
    @abstractmethod
    async def create_space_tables(self, space_id: str) -> bool:
        """Create database schema/storage for a space."""
        pass
    
    @abstractmethod
    async def delete_space_tables(self, space_id: str) -> bool:
        """Delete all data and schema for a space."""
        pass
    
    @abstractmethod
    async def space_exists(self, space_id: str) -> bool:
        """Check if a space exists."""
        pass
    
    # ... (additional methods defined below)
```

#### 1.2 Core Interface Methods

**Essential Methods** (used by SpaceImpl):
- Space lifecycle: `create_space_tables`, `delete_space_tables`, `space_exists`
- Namespace management: `add_namespace`, `get_namespace_uri`, `list_namespaces`

**Extended Methods** (for full functionality):
- Term management: `add_term`, `get_term_uuid`, `delete_term`
- Quad operations: `add_quad`, `remove_quad`, `get_quad_count`, `add_rdf_quads_batch`
- RDF operations: `add_rdf_quad`, `remove_rdf_quad`, `get_rdf_quad`, `quads`
- Utility methods: `get_manager_info`, `close`

### Phase 2: Backend Implementations

#### 2.1 PostgreSQL Backend Adaptation
**File**: `/vitalgraph/db/postgresql/postgresql_space_impl.py`

- Make `PostgreSQLSpaceImpl` inherit from `SpaceBackendInterface`
- Ensure all interface methods are properly implemented
- Add any missing methods with appropriate implementations

#### 2.2 Oxigraph Backend Implementation
**File**: `/vitalgraph/db/oxigraph/oxigraph_space_impl.py`

```python
class OxigraphSpaceImpl(SpaceBackendInterface):
    """
    Oxigraph-based implementation of space backend interface.
    
    Uses pyoxigraph for high-performance RDF storage with SPARQL support.
    """
    
    def __init__(self, storage_path: str, **kwargs):
        self.storage_path = storage_path
        self.stores: Dict[str, pyoxigraph.Store] = {}
    
    async def create_space_tables(self, space_id: str) -> bool:
        # Create pyoxigraph store for space
        pass
    
    # ... implement all interface methods
```

#### 2.3 Fuseki Backend Implementation  
**File**: `/vitalgraph/db/fuseki/fuseki_space_impl.py`

```python
class FusekiSpaceImpl(SpaceBackendInterface):
    """
    Apache Jena Fuseki-based implementation of space backend interface.
    
    Uses HTTP API to communicate with Fuseki server for RDF operations.
    """
    
    def __init__(self, fuseki_url: str, **kwargs):
        self.fuseki_url = fuseki_url
        self.session = aiohttp.ClientSession()
    
    async def create_space_tables(self, space_id: str) -> bool:
        # Create dataset in Fuseki
        pass
    
    # ... implement all interface methods
```

#### 2.4 Enhanced Mock Backend
**File**: `/vitalgraph/mock/client/space/mock_space_impl.py`

```python
class MockSpaceImpl(SpaceBackendInterface):
    """
    Mock implementation using pyoxigraph for testing.
    
    Enhanced version of MockSpace that implements full interface.
    """
    
    def __init__(self, **kwargs):
        self.spaces: Dict[str, pyoxigraph.Store] = {}
    
    # ... implement all interface methods
```

### Phase 3: Configuration System

#### 3.1 Backend Configuration
**File**: `/vitalgraph/config/backend_config.py`

```python
from enum import Enum
from typing import Dict, Any, Optional
from dataclasses import dataclass

class BackendType(Enum):
    POSTGRESQL = "postgresql"
    OXIGRAPH = "oxigraph" 
    FUSEKI = "fuseki"
    MOCK = "mock"

@dataclass
class BackendConfig:
    backend_type: BackendType
    connection_params: Dict[str, Any]
    pool_config: Optional[Dict[str, Any]] = None

# Example Fuseki configuration
fuseki_config = BackendConfig(
    backend_type=BackendType.FUSEKI,
    connection_params={
        "server_url": "http://localhost:3030",
        "dataset_name": "vitalgraph", 
        "username": "admin",
        "password": "admin123",
        "timeout": 30
    }
)
    
class BackendFactory:
    """Factory for creating space backend implementations."""
    
    @staticmethod
    def create_space_backend(config: BackendConfig) -> SpaceBackendInterface:
        """Create space backend implementation based on configuration."""
        if config.backend_type == BackendType.POSTGRESQL:
            from vitalgraph.db.postgresql.postgresql_space_impl import PostgreSQLSpaceImpl
            return PostgreSQLSpaceImpl(**config.connection_params)
        elif config.backend_type == BackendType.OXIGRAPH:
            from vitalgraph.db.oxigraph.oxigraph_space_impl import OxigraphSpaceImpl
            return OxigraphSpaceImpl(**config.connection_params)
        elif config.backend_type == BackendType.FUSEKI:
            from vitalgraph.db.fuseki.fuseki_space_impl import FusekiSpaceImpl
            return FusekiSpaceImpl(**config.connection_params)
        elif config.backend_type == BackendType.MOCK:
            from vitalgraph.db.mock.mock_space_impl import MockSpaceImpl
            return MockSpaceImpl(**config.connection_params)
        else:
            raise ValueError(f"Unsupported backend type: {config.backend_type}")
    
    @staticmethod
    def create_sparql_backend(config: BackendConfig) -> SparqlBackendInterface:
        """Create SPARQL backend implementation based on configuration."""
        if config.backend_type == BackendType.POSTGRESQL:
            from vitalgraph.db.postgresql.postgresql_sparql_impl import PostgreSQLSparqlImpl
            return PostgreSQLSparqlImpl(**config.connection_params)
        elif config.backend_type == BackendType.FUSEKI:
            from vitalgraph.db.fuseki.fuseki_sparql_impl import FusekiSparqlImpl
            return FusekiSparqlImpl(**config.connection_params)
        elif config.backend_type == BackendType.MOCK:
            from vitalgraph.db.mock.mock_sparql_impl import MockSparqlImpl
            return MockSparqlImpl(**config.connection_params)
        else:
            raise ValueError(f"SPARQL backend not supported for: {config.backend_type}")
    
    @staticmethod
    def create_signal_manager(config: BackendConfig) -> SignalManagerInterface:
        """Create signal manager implementation based on configuration."""
        signal_config = config.signal_manager_config or {}
        
        if config.backend_type == BackendType.POSTGRESQL:
            from vitalgraph.db.postgresql.postgresql_signal_manager import PostgreSQLSignalManager
            return PostgreSQLSignalManager(**signal_config)
        elif config.backend_type == BackendType.FUSEKI:
            from vitalgraph.db.fuseki.fuseki_signal_manager import FusekiSignalManager
            return FusekiSignalManager(**signal_config)
        elif config.backend_type == BackendType.MOCK:
            from vitalgraph.db.mock.mock_signal_manager import MockSignalManager
            return MockSignalManager(**signal_config)
        else:
            raise ValueError(f"Signal manager not supported for: {config.backend_type}")
```

#### 3.2 VitalGraph Configuration Integration
**File**: `/vitalgraph/config/vitalgraph_config.yaml`

```yaml
database:
  # Existing PostgreSQL config
  postgresql:
    host: localhost
    port: 5432
    database: vitalgraph
    # ... existing config

  # New backend selection
  backend:
    type: postgresql  # postgresql | oxigraph | fuseki | mock
    
  # Backend-specific configurations
  oxigraph:
    storage_path: /var/lib/vitalgraph/oxigraph
    
  fuseki:
    server_url: http://localhost:3030
    dataset_name: vitalgraph
    username: admin
    password: admin123
    timeout: 30
    
  mock:
    in_memory: true
```

### Phase 4: Ancillary Services Interface

#### 4.1 Signal Manager Interface
**File**: `/vitalgraph/db/signal_manager_inf.py`

```python
class SignalManagerInterface(ABC):
    """Abstract interface for backend-specific signal management."""
    
    @abstractmethod
    async def notify_space_created(self, space_id: str) -> None:
        pass
    
    @abstractmethod
    async def notify_space_deleted(self, space_id: str) -> None:
        pass
    
    @abstractmethod
    async def subscribe_to_space_events(self, callback) -> None:
        pass
```

#### 4.2 Backend-Specific Signal Managers
- **PostgreSQLSignalManager**: Uses PostgreSQL NOTIFY/LISTEN
- **OxigraphSignalManager**: File-based or HTTP webhook notifications
- **FusekiSignalManager**: HTTP-based notifications
- **MockSignalManager**: In-memory event system

### Phase 5: Integration and Migration

#### 5.1 Update SpaceImpl
**File**: `/vitalgraph/space/space_impl.py`

```python
class SpaceImpl:
    def __init__(self, *, space_id: str, db_impl):
        self.space_id = space_id
        self.db_impl = db_impl
        
        # Get backend-specific implementation through factory
        self._space_impl: SpaceBackendInterface = db_impl.get_space_impl()
```

#### 5.2 Update Database Implementations
- **PostgreSQLDbImpl**: Return PostgreSQLSpaceImpl instance
- **OxigraphDbImpl**: Return OxigraphSpaceImpl instance  
- **FusekiDbImpl**: Return FusekiSpaceImpl instance
- **MockDbImpl**: Return MockSpaceImpl instance

## Implementation Timeline

### Phase 1: Interface Integration (Priority) - Week 1-2
**Goal**: Create interface-based architecture with PostgreSQL as default (no functional changes)

- [ ] **Create abstract `SpaceBackendInterface`** - Define complete interface contract
- [ ] **Create abstract `SparqlBackendInterface`** - Define SPARQL interface contract  
- [ ] **Extend PostgreSQL implementation** - Make `PostgreSQLSpaceImpl` implement SpaceBackendInterface
- [ ] **Create `BackendFactory`** - Factory pattern with PostgreSQL as default
- [ ] **Update VitalGraph configuration** - Add backend selection (default: postgresql)
- [ ] **Update VitalGraphImpl** - Use factory with PostgreSQL backend (no functional change)
- [ ] **Update SpaceManager** - Accept SpaceBackendInterface (PostgreSQL initially)
- [ ] **Update SpaceImpl** - Use interface methods (PostgreSQL implementation)
- [ ] **Comprehensive testing** - Ensure zero functional regression with PostgreSQL
- [ ] **Documentation** - Interface usage and backend selection guide

### Phase 2: Fuseki Backend Integration - Week 3
**Goal**: Enable Fuseki backend as alternative option

- [x] ✅ **Implement `FusekiSpaceImpl`** - Complete with space/graph management
- [x] ✅ **Implement `FusekiSparqlImpl`** - Complete with SPARQL delegation
- [x] ✅ **Create Fuseki configuration** - Complete with authentication
- [x] ✅ **Docker deployment setup** - Complete with local testing
- [x] ✅ **AWS ECS deployment** - Complete with ARM64, EFS, Python scripts
- [x] ✅ **Create fuseki signal manager** - No-op implementation complete
- [ ] **Integrate with BackendFactory** - Add Fuseki to factory pattern
- [ ] **Configuration testing** - Test backend switching via YAML config
- [ ] **Integration testing** - Verify Fuseki works with interface architecture

### Phase 3: Mock Backend - Week 4
- [ ] Implement enhanced `MockSpaceImpl`
- [ ] Create mock signal manager
- [ ] Test mock backend integration
- [ ] Update mock client to use new backend

### Phase 4: Oxigraph Backend - Week 5-6  
- [ ] Implement `OxigraphSpaceImpl`
- [ ] Create oxigraph signal manager
- [ ] Performance testing and optimization

### Phase 5: Integration & Migration - Week 7-8
- [ ] Update all dependent code to use interface
- [ ] Comprehensive testing across all backends
- [ ] Migration tools between backends
- [ ] Documentation and examples

## Benefits

1. **Zero Risk Migration**: Interface integration with PostgreSQL default ensures no functional changes
2. **Backend Flexibility**: Easy switching between storage backends via configuration
3. **Future-Proofing**: Clean interface architecture enables easy addition of new backends
4. **Fuseki Ready**: Production-ready SPARQL backend with authentication and AWS deployment
5. **Cloud-Native**: ARM64 ECS deployment with EFS persistence and cost optimization
6. **SPARQL Native**: Direct SPARQL query/update support without SQL translation
7. **Testing**: Robust mock backend for unit tests
8. **Gradual Migration**: Existing PostgreSQL users unaffected, new deployments can choose backends

## Migration Strategy: Zero Functional Changes

### Phase 1 Approach: Interface Wrapper Pattern
```python
# Current PostgreSQL usage (before interface)
class VitalGraphImpl:
    def __init__(self, config):
        self.db_impl = PostgreSQLDbImpl(config)
        self.space_manager = SpaceManager(db_impl=self.db_impl)

# After interface integration (functionally identical)
class VitalGraphImpl:
    def __init__(self, config):
        backend_config = BackendConfig(
            backend_type=BackendType.POSTGRESQL,  # Default
            connection_params=self._extract_postgres_params(config)
        )
        self.space_backend = BackendFactory.create_space_backend(backend_config)
        self.space_manager = SpaceManager(space_backend=self.space_backend)
```

### Configuration Backward Compatibility
```yaml
# Existing config (continues to work)
database:
  postgresql:
    host: localhost
    port: 5432
    database: vitalgraph
    username: postgres
    password: password

# New config (optional backend selection)
database:
  backend:
    type: postgresql  # Default if not specified
  postgresql:
    host: localhost
    port: 5432
    database: vitalgraph
    username: postgres
    password: password
```

### Implementation Guarantee
- **No API Changes**: All existing method signatures remain identical
- **No Behavior Changes**: PostgreSQL implementation wrapped, not modified
- **No Performance Impact**: Interface calls are direct method delegation
- **No Configuration Changes**: Existing YAML configs continue to work
- **Comprehensive Testing**: Full regression test suite before deployment

## Risks and Mitigation

1. **Interface Complexity**: Keep interface focused on essential methods ✅ **MITIGATED**: Start with PostgreSQL wrapper
2. **Performance Differences**: Provide backend-specific optimizations ✅ **MITIGATED**: Interface delegation has minimal overhead
3. **Feature Parity**: Ensure all backends support core functionality ✅ **MITIGATED**: PostgreSQL sets the interface contract
4. **Migration Complexity**: Provide migration tools between backends ✅ **MITIGATED**: Gradual rollout with PostgreSQL default

## Migration Analysis: PostgreSQLSpaceImpl References

Based on comprehensive search of the codebase, here are the key areas that need migration to the new interface:

### 1. **Core Integration Points**

#### **VitalGraphImpl** (`/vitalgraph/impl/vitalgraph_impl.py`)
- **Current**: Direct `PostgreSQLDbImpl` import and instantiation
  ```python
  from vitalgraph.db.postgresql.postgresql_db_impl import PostgreSQLDbImpl
  self.db_impl = PostgreSQLDbImpl(db_config, tables_config, config_loader=self.config)
  ```
- **Migration**:
  - Replace with generic `DbBackendInterface` import (needs to be created)
  - Use `BackendFactory.create_db_backend()` for instantiation
  - Update `get_db_impl()` method documentation to be backend-agnostic
  ```python
  from vitalgraph.db.db_backend_inf import DbBackendInterface
  from vitalgraph.db.space_inf import BackendFactory, BackendConfig, BackendType
  
  # Read backend type from configuration
  backend_type_str = self.config.get_database_config().get('backend_type', 'postgresql')
  backend_type = BackendType(backend_type_str.upper())
  
  backend_config = BackendConfig(
      backend_type=backend_type,
      connection_string=db_config.connection_string,
      global_prefix=tables_config.prefix.rstrip('_')
  )
  self.db_impl = BackendFactory.create_db_backend(backend_config)
  ```
  - **Note**: Requires creating `DbBackendInterface` that abstracts database-level operations (users, spaces, install) separate from `SpaceBackendInterface` (RDF operations)

#### **PostgreSQLDbImpl** (`/vitalgraph/db/postgresql/postgresql_db_impl.py`)
- **Current**: Direct `PostgreSQLSpaceImpl` instantiation and management
- **Migration**: 
  - Change `get_space_impl()` return type to `SpaceBackendInterface`
  - Use `BackendFactory.create_backend()` for instantiation
  - Update initialization to use interface methods

#### **SpaceManager** (`/vitalgraph/space/space_manager.py`)
- **Current**: Calls `db_impl.get_space_impl()` then `space_exists()`, `create_space_tables()`, `delete_space_tables()`
- **Migration**:
  - Update method calls to new interface: `space_storage_exists()`, `init_space_storage()`, `delete_space_storage()`
  - Maintain same logic flow with renamed methods

#### **SpaceImpl** (`/vitalgraph/space/space_impl.py`)
- **Current**: Delegates to `_space_impl` with `create_space_tables()`, `space_exists()`, `delete_space_tables()`, `add_namespace()`
  ```python
  # Current type annotation and method calls
  db_impl: Instance of PostgreSQLDbImpl for database operations
  success = await self._space_impl.create_space_tables(self.space_id)
  tables_exist = await self._space_impl.space_exists(self.space_id)
  success = await self._space_impl.delete_space_tables(self.space_id)
  ```
- **Migration**:
  - Change `_space_impl` type annotation to `SpaceBackendInterface`
  - Update method calls to interface methods
  - Add backend-agnostic error handling
  ```python
  # New type annotation and method calls
  db_impl: Instance of SpaceBackendInterface for database operations
  success = await self._space_impl.init_space_storage(self.space_id)
  tables_exist = await self._space_impl.space_storage_exists(self.space_id)
  success = await self._space_impl.delete_space_storage(self.space_id)
  ```

#### **SpaceManager** (`/vitalgraph/space/space_manager.py`)
- **Current**: References `PostgreSQLDbImpl` in documentation and uses specific method names
  ```python
  # Current documentation and method calls
  db_impl: Database implementation instance (e.g., PostgreSQLDbImpl)
  tables_exist = await space_impl.space_exists(space_id)
  success = await space_impl.create_space_tables(space_id)
  success = await space_impl.delete_space_tables(space_id)
  ```
- **Migration**:
  - Update documentation to be backend-agnostic
  - Update method calls to new interface methods
  ```python
  # New documentation and method calls
  db_impl: Database implementation instance (SpaceBackendInterface)
  tables_exist = await space_impl.space_storage_exists(space_id)
  success = await space_impl.init_space_storage(space_id)
  success = await space_impl.delete_space_storage(space_id)
  ```

#### **SignalManager** (`/vitalgraph/signal/signal_manager.py`)
- **Current**: References `PostgreSQLDbImpl` in documentation
  ```python
  db_impl: PostgreSQLDbImpl instance to obtain database connections
  ```
- **Migration**:
  - Update documentation to be backend-agnostic
  - Ensure signal manager works with any backend that implements `SignalManagerInterface`
  ```python
  db_impl: Database backend instance that provides signal management capabilities
  ```

### 2. **REST API Endpoints**

#### **All SPARQL Endpoints** (`/vitalgraph/endpoint/sparql_*.py`)
- **Current**: Call `space_impl.get_db_space_impl()` to get PostgreSQL-specific implementation
- **Migration**:
  - Change to `space_impl.get_backend_impl()` or similar interface method
  - Update to use `SparqlBackendInterface` instead of direct PostgreSQL classes
  - Add backend capability checks before SPARQL operations

#### **Endpoint Implementations** (`/vitalgraph/endpoint/impl/*.py`)
- **Current**: Use `get_db_space_impl()` utility function extensively (100+ references)
- **Migration**:
  - Update `impl_utils.get_db_space_impl()` to return `SpaceBackendInterface`
  - Change all `db_space_impl.db_ops.*` calls to interface methods
  - Update transaction handling to be backend-agnostic

#### **Triples Endpoint** (`/vitalgraph/endpoint/triples_endpoint.py`)
- **Current**: Direct access to PostgreSQL-specific methods for fast SQL queries
- **Migration**:
  - Add interface methods for high-performance triple operations
  - Provide backend-specific optimizations through interface

### 3. **Test Scripts and Utilities**

#### **Test Scripts** (83 files with `get_space_impl` references)
- **Current**: Direct PostgreSQL implementation access
- **Migration**:
  - Update to use interface methods
  - Add backend selection for tests
  - Create backend-agnostic test utilities

#### **SPARQL Orchestrator** (`/vitalgraph/db/postgresql/sparql/postgresql_sparql_orchestrator.py`)
- **Current**: 16 direct `PostgreSQLSpaceImpl` references
- **Migration**:
  - Create PostgreSQL-specific SPARQL implementation
  - Implement `SparqlBackendInterface` for PostgreSQL
  - Update orchestrator to use interface

### 4. **Migration Strategy**

#### **Phase 1: Interface Compliance**
1. Make `PostgreSQLSpaceImpl` inherit from `SpaceBackendInterface`
2. Replace old methods with new interface methods directly
3. Update return types in `PostgreSQLDbImpl.get_space_impl()`

#### **Phase 2: Core System Migration**
1. Update `SpaceImpl` to use interface methods
2. Update `SpaceManager` method calls
3. Create `PostgreSQLSparqlImpl` implementing `SparqlBackendInterface`
4. Update `impl_utils.get_db_space_impl()` function

#### **Phase 3: Create FusekiSpaceImpl using HTTP API**
- Implement HTTP-based RDF operations using Fuseki REST API
- Support SPARQL endpoints for queries and updates
- Handle authentication and connection management
- **Architecture Details**:
  - Single Fuseki dataset for all VitalGraph data
  - Special "space-graph" (`<urn:vitalgraph:spaces>`) tracks space metadata
  - Each space maps to multiple named graphs via KGSegment objects
  - VitalSegment objects represent spaces in the space-graph
  - KGSegment objects link spaces to specific graph URIs
  - All operations target named graphs (not default graph)
  - HTTP requests to Fuseki SPARQL endpoints for all operations

#### **Phase 4: Test and Utility Migration**
1. Update test scripts to use interface
2. Create backend selection utilities for tests
3. Update documentation and examples

### 5. **Direct Migration Strategy**

#### **Method Replacement**
```python
# In PostgreSQLSpaceImpl - REPLACE old methods directly
async def init_space_storage(self, space_id: str) -> bool:
    """Initialize storage for a space (replaces create_space_tables)."""
    # Implementation stays the same, just renamed method
    
async def delete_space_storage(self, space_id: str) -> bool:
    """Delete storage for a space (replaces delete_space_tables)."""
    # Implementation stays the same, just renamed method
    
async def space_storage_exists(self, space_id: str) -> bool:
    """Check if storage exists (replaces space_exists)."""
    # Implementation stays the same, just renamed method
```

#### **Breaking Changes**
- Remove old method names completely
- Update all callers simultaneously
- No deprecation period - clean break

### 6. **Configuration System Design**

#### **Backend Type Enum**
```python
# In /vitalgraph/db/space_inf.py - Update BackendType enum
class BackendType(Enum):
    POSTGRESQL = "postgresql"
    OXIGRAPH = "oxigraph" 
    FUSEKI = "fuseki"
    MOCK = "mock"  # For testing only, not used in server config
```

#### **YAML Configuration Structure**
```yaml
# vitalgraphdb-config.yaml
backend:
  type: "postgresql"  # or "oxigraph", "fuseki" (mock not allowed in server config)

# PostgreSQL backend configuration (existing)
database:
  host: 'localhost'
  port: 5432
  database: 'vitalgraphdb'
  username: 'vitalgraph_user'
  password: 'vitalgraph_password'
  pool_size: 10
  max_overflow: 20

# Oxigraph backend configuration (new)
oxigraph:
  storage_path: '/var/lib/vitalgraph/oxigraph'
  memory_limit: '2GB'
  bulk_load_batch_size: 10000
  query_timeout: 30

# Fuseki backend configuration (new)
fuseki:
  server_url: 'http://localhost:3030'
  dataset_name: 'vitalgraph'
  username: 'admin'
  password: 'admin'
  timeout: 30
  retry_attempts: 3

# Existing configurations remain unchanged
tables:
  prefix: 'vg_'
auth:
  root_username: 'admin'
  root_password: 'admin'
```

#### **Config Loader Updates**
```python
# In /vitalgraph/config/config_loader.py - Add new methods
class VitalGraphConfigLoader:
    def get_backend_type(self) -> str:
        """Get the selected backend type from configuration."""
        return self.config_data.get('backend', {}).get('type', 'postgresql')
    
    def get_oxigraph_config(self) -> Dict[str, Any]:
        """Get Oxigraph backend configuration."""
        return self.config_data.get('oxigraph', {})
    
    def get_fuseki_config(self) -> Dict[str, Any]:
        """Get Fuseki backend configuration."""
        return self.config_data.get('fuseki', {})
    
    def _get_default_config(self) -> Dict[str, Any]:
        # Add default backend selection and new backend configs
        defaults = {
            'backend': {
                'type': 'postgresql'
            },
            'oxigraph': {
                'storage_path': '/tmp/vitalgraph/oxigraph',
                'memory_limit': '1GB',
                'bulk_load_batch_size': 5000,
                'query_timeout': 30
            },
            'fuseki': {
                'server_url': 'http://localhost:3030',
                'dataset_name': 'vitalgraph',
                'username': 'admin',
                'password': 'admin',
                'timeout': 30,
                'retry_attempts': 3
            }
            # ... existing defaults
        }
```

### 6. **VitalGraphImpl Integration with Interface**

#### **Updated VitalGraphImpl Constructor**
```python
# File: /vitalgraph/impl/vitalgraph_impl.py
from vitalgraph.config.backend_config import BackendFactory, BackendConfig, BackendType

class VitalGraphImpl:
    def __init__(self, config=None):
        self.config = config
        self.space_backend = None
        self.sparql_backend = None
        self.signal_manager = None
        
        # Initialize backends based on configuration
        if self.config:
            backend_config = self._create_backend_config()
            
            # Create all backend implementations
            self.space_backend = BackendFactory.create_space_backend(backend_config)
            self.sparql_backend = BackendFactory.create_sparql_backend(backend_config)
            self.signal_manager = BackendFactory.create_signal_manager(backend_config)
            
            # Initialize space manager with interface-based backend
            self.space_manager = SpaceManager(space_backend=self.space_backend)
    
    def _create_backend_config(self) -> BackendConfig:
        """Create backend configuration from VitalGraph config."""
        backend_type_str = self.config.get_backend_type()
        backend_type = BackendType(backend_type_str.lower())
        
        if backend_type == BackendType.POSTGRESQL:
            db_config = self.config.get_database_config()
            tables_config = self.config.get_tables_config()
            return BackendConfig(
                backend_type=backend_type,
                connection_params={
                    "connection_string": self._build_postgres_connection_string(db_config),
                    "global_prefix": tables_config.get('prefix', 'vg_').rstrip('_')
                }
            )
        elif backend_type == BackendType.FUSEKI:
            fuseki_config = self.config.get_fuseki_config()
            return BackendConfig(
                backend_type=backend_type,
                connection_params={
                    "server_url": fuseki_config.get('server_url', 'http://localhost:3030'),
                    "dataset_name": fuseki_config.get('dataset_name', 'vitalgraph'),
                    "username": fuseki_config.get('username', 'admin'),
                    "password": fuseki_config.get('password', 'admin123'),
                    "timeout": fuseki_config.get('timeout', 30)
                },
                signal_manager_config=fuseki_config.get('signal_manager', {})
            )
        elif backend_type == BackendType.MOCK:
            return BackendConfig(
                backend_type=backend_type,
                connection_params={}
            )
        else:
            raise ValueError(f"Unsupported backend type: {backend_type}")
    
    async def connect_database(self):
        """Connect to database using interface-based backend."""
        if not self.space_backend:
            print("⚠️ No space backend available")
            return False
            
        # Connect space backend
        connected = await self.space_backend.connect()
        if not connected:
            print("❌ Failed to connect space backend")
            return False
        
        # Connect SPARQL backend if different from space backend
        if self.sparql_backend and self.sparql_backend != self.space_backend:
            sparql_connected = await self.sparql_backend.connect()
            if not sparql_connected:
                print("❌ Failed to connect SPARQL backend")
                return False
        
        # Initialize space manager from backend
        await self.space_manager.initialize_from_backend()
        print(f"✅ SpaceManager initialized with {len(self.space_manager)} spaces")
        
        return True
```

#### **Updated SpaceManager Integration**
```python
# File: /vitalgraph/space/space_manager.py
class SpaceManager:
    def __init__(self, space_backend: SpaceBackendInterface):
        """Initialize with interface-based backend."""
        self.space_backend = space_backend
        self.spaces = {}
    
    async def initialize_from_backend(self):
        """Initialize spaces from backend using interface."""
        space_ids = await self.space_backend.list_spaces()
        for space_id in space_ids:
            space_impl = SpaceImpl(space_id=space_id, space_backend=self.space_backend)
            self.spaces[space_id] = space_impl
    
    async def create_space(self, space_id: str) -> SpaceImpl:
        """Create new space using interface."""
        success = await self.space_backend.init_space_storage(space_id)
        if success:
            space_impl = SpaceImpl(space_id=space_id, space_backend=self.space_backend)
            self.spaces[space_id] = space_impl
            return space_impl
        return None
```

#### **Updated SpaceImpl to Use Interface**
```python
# File: /vitalgraph/space/space_impl.py
class SpaceImpl:
    def __init__(self, *, space_id: str, space_backend: SpaceBackendInterface):
        """Initialize with interface-based backend."""
        self.space_id = space_id
        self.space_backend = space_backend
        
        # Get SPARQL implementation through interface
        self.sparql_impl = self.space_backend.get_sparql_impl()
    
    async def add_quad(self, subject, predicate, obj, graph_uri=None):
        """Add quad using interface."""
        return await self.space_backend.add_rdf_quad(
            self.space_id, subject, predicate, obj, graph_uri
        )
    
    async def execute_sparql_query(self, query: str):
        """Execute SPARQL query using interface."""
        return await self.sparql_impl.execute_sparql_query(self.space_id, query)
```

### 7. **Fuseki Backend Implementation Details**

#### **Fuseki Architecture Design**
```
Fuseki Dataset: "vitalgraph"
├── Space Graph: <urn:vitalgraph:spaces>
│   ├── VitalSegment objects (represent spaces)
│   └── KGSegment objects (link spaces to multiple graphs)
└── Named Graphs: <urn:vitalgraph:space:{space_id}:graph:{graph_id}>
    ├── Multiple graphs per space (like PostgreSQL)
    ├── Graphs created on-demand via KGSegment metadata
    └── RDF quads for each space/graph combination
```

#### **Space Management via RDF Metadata**
```sparql
# VitalSegment (Space) representation in space-graph
<urn:vitalgraph:space:store123> a vital:VitalSegment ;
    vital:hasSegmentID "store123" ;
    vital:hasName "Store 123 Data" ;
    vital:hasCreatedDate "2024-12-01T15:30:00Z"^^xsd:dateTime ;
    vital:isActive true .

# KGSegment (Graph) representation linking space to graph URIs
<urn:vitalgraph:kgsegment:store123:main> a vital:KGSegment ;
    vital:vitalSegmentID "store123" ;
    vital:kGSegmentGraphURI <urn:vitalgraph:space:store123:graph:main> ;
    vital:hasName "Main Graph" ;
    vital:isActive true .
```

#### **HTTP API Integration**
```python
# Fuseki REST endpoints used by implementation
class FusekiEndpoints:
    QUERY = "{server_url}/{dataset}/sparql"           # GET/POST SPARQL queries
    UPDATE = "{server_url}/{dataset}/update"          # POST SPARQL updates  
    GRAPH_STORE = "{server_url}/{dataset}/data"       # GET/PUT/DELETE graph operations
    UPLOAD = "{server_url}/{dataset}/upload"          # POST bulk data upload
```

#### **Space Operations Implementation**
```python
# Space lifecycle operations via SPARQL UPDATE
async def init_space_storage(self, space_id: str) -> bool:
    # 1. Insert VitalSegment triple into space-graph
    # 2. Create default KGSegment for main graph
    # 3. Initialize empty named graph for space
    
async def delete_space_storage(self, space_id: str) -> bool:
    # 1. Query space-graph for all KGSegment objects
    # 2. Delete all associated named graphs
    # 3. Delete VitalSegment and KGSegment metadata
    
async def space_storage_exists(self, space_id: str) -> bool:
    # Query space-graph for VitalSegment with given ID
```

#### **Graph Operations via Named Graphs**
```python
# All RDF operations target specific named graphs
async def add_rdf_quad(self, space_id: str, subject, predicate, object, graph_uri):
    # Construct graph URI: <urn:vitalgraph:space:{space_id}:graph:{graph_id}>
    # Use Fuseki Graph Store API or SPARQL UPDATE
    
async def quads(self, space_id: str, graph_uri=None):
    # Query specific named graph or all graphs for space
    # Use SPARQL SELECT with GRAPH clause
```

#### **SPARQL Delegation Pattern**
```python
class FusekiSparqlImpl(SparqlBackendInterface):
    async def execute_sparql_query(self, space_id: str, sparql_query: str):
        # 1. Validate query targets named graphs only
        # 2. Rewrite graph URIs to Fuseki format if needed
        # 3. Send HTTP POST to Fuseki SPARQL endpoint
        # 4. Parse JSON results and return standardized format
        
    async def execute_sparql_update(self, space_id: str, sparql_update: str):
        # 1. Validate update targets named graphs only
        # 2. Send HTTP POST to Fuseki UPDATE endpoint
        # 3. Return success/failure based on HTTP status
```

#### **Fuseki Implementation Discussion Questions**

1. **Graph URI Strategy**: Should we enforce a strict naming convention for graph URIs (e.g., `urn:vitalgraph:space:{space_id}:graph:{graph_id}`) or allow flexible graph naming?

2. **Space-Graph Management**: Should the space-graph (`urn:vitalgraph:spaces`) be automatically created on first use, or require explicit initialization?

3. **KGSegment Multiplicity**: ✅ **RESOLVED** - Each space supports multiple graphs via multiple KGSegment objects (matches PostgreSQL behavior). Graphs created on-demand when first accessed.

4. **Error Handling**: How should we handle Fuseki server unavailability? Retry logic, fallback behavior, or fail-fast?

5. **Authentication**: ✅ **IMPLEMENTED** - Using Apache Shiro Basic Authentication with configurable users (admin/admin123, vitalgraph_user/vitalgraph_pass, readonly_user/readonly_pass). SessionManager configured for Fuseki 5.6.0 compatibility.

6. **Bulk Operations**: How should batch RDF operations be implemented? Single large SPARQL UPDATE or multiple smaller requests?

7. **Graph Validation**: Should we validate that all SPARQL operations target named graphs, or allow some operations on default graph?

8. **Namespace Management**: Should namespaces be stored as RDF metadata in the space-graph or handled at the SPARQL level only?

9. **Performance Optimization**: Should we implement connection pooling, request batching, or query caching for better performance?

10. **Dataset Management**: ✅ **IMPLEMENTED** - Single dataset approach using "vitalgraph" dataset with named graphs for space/graph separation.

### 8. **Fuseki Deployment Configuration**

#### **Docker Configuration**
```yaml
# Local development (docker-compose.yml)
services:
  fuseki:
    image: vitalai/kgraphdb:5.6.0
    ports:
      - "3030:3030"
    volumes:
      - ./config/config.ttl:/fuseki/config.ttl
      - ./config/shiro.ini:/fuseki/shiro.ini
      - ./databases:/fuseki/databases
    environment:
      - ADMIN_PASSWORD=admin123
```

#### **AWS ECS Configuration**
```python
# AWS deployment parameters
fuseki_aws_config = {
    "image": "eclipse-temurin:17-jre",
    "platform": "linux/arm64",  # ARM64 for cost optimization
    "cpu": "1024",
    "memory": "2048",
    "environment": {
        "MEMORY_LIMIT": "2048",
        "EFS_MOUNT_POINT": "/efs",
        "JAVA_OPTIONS": "-Xmx1536m -Xms1536m -XX:+UseG1GC"
    },
    "persistent_storage": "EFS",  # AWS EFS for TDB2 database files
    "authentication": "Shiro Basic Auth"
}
```

#### **Production Configuration**
```yaml
# Production vitalgraph_config.yaml
database:
  backend:
    type: fuseki
    
  fuseki:
    server_url: https://fuseki.vitalgraph.internal
    dataset_name: vitalgraph
    username: vitalgraph_service
    password: ${FUSEKI_PASSWORD}  # From environment/secrets
    timeout: 60
    connection_pool:
      max_connections: 20
      timeout: 30
```

### 9. **Mock Backend Migration Strategy**

#### **Mock Backend Location**
- **Current**: Mock endpoints in `/vitalgraph/mock/client/endpoint/`
- **New**: Move mock backend to `/vitalgraph/db/mock/` for consistency
  ```
  /vitalgraph/db/mock/
  ├── mock_db_impl.py           # Database-level operations
  ├── mock_space_impl.py        # RDF space operations  
  ├── mock_sparql_impl.py       # SPARQL query processing
  └── mock_signal_manager.py    # In-memory event simulation
  ```

#### **Mock Backend Usage**
```python
# Mock backend NOT included in server configuration
# Used only by mock client for testing

# In mock client code:
from vitalgraph.db.mock.mock_db_impl import MockDbImpl
from vitalgraph.db.space_inf import BackendConfig, BackendType

# Direct instantiation in mock client (no config file)
mock_config = BackendConfig(
    backend_type=BackendType.MOCK,
    in_memory=True,
    auto_create_spaces=True
)
mock_db_impl = MockDbImpl(mock_config)
```

#### **Mock Endpoint Migration**
```python
# Move existing mock endpoint logic to mock backend
# From: /vitalgraph/mock/client/endpoint/mock_*_endpoint.py
# To:   /vitalgraph/db/mock/mock_space_impl.py

class MockSpaceImpl(SpaceBackendInterface):
    """Mock implementation of SpaceBackendInterface for testing."""
    
    def __init__(self, config: BackendConfig):
        # Initialize in-memory pyoxigraph store
        # Migrate existing mock endpoint logic here
        
    # Implement all SpaceBackendInterface methods
    # Using existing mock endpoint implementations
```

#### **Mock Client Integration**
```python
# Mock client creates mock backend directly
class MockVitalGraphClient:
    def __init__(self):
        # Create mock backend without config file
        self.mock_backend = MockDbImpl(BackendConfig(
            backend_type=BackendType.MOCK
        ))
        
        # Use mock backend for all operations
        self.space_manager = SpaceManager(db_impl=self.mock_backend)
```

## Success Criteria

### Phase 1: Interface Integration (Priority) - Zero Functional Changes
- [ ] **Create SpaceBackendInterface** - Abstract interface with all required methods
- [ ] **Create SparqlBackendInterface** - Abstract interface for SPARQL operations  
- [ ] **SignalManagerInterface** - Already exists in space_inf.py ✅
- [ ] **Extend PostgreSQLSpaceImpl** - Implement SpaceBackendInterface (no behavior change)
- [ ] **Create BackendFactory** - Factory pattern with PostgreSQL as default
- [ ] **Update VitalGraphImpl** - Use factory but default to PostgreSQL (no functional change)
- [ ] **Update SpaceManager** - Accept SpaceBackendInterface (PostgreSQL initially)
- [ ] **Update SpaceImpl** - Use interface methods (PostgreSQL implementation)
- [ ] **Add backend configuration** - YAML config with backend type selection (default: postgresql)
- [ ] **Update config loader** - Support get_backend_type() returning 'postgresql' by default
- [ ] **Regression testing** - Ensure all existing functionality works identically
- [ ] **Interface documentation** - Usage guide and backend selection

### Phase 2: Fuseki Backend Integration - Enable Alternative Backend
- [x] ✅ **Fuseki implementation complete** - FusekiSpaceImpl and FusekiSparqlImpl
- [x] ✅ **Authentication working** - Shiro Basic Auth with multiple users
- [x] ✅ **Docker deployment** - Local development with docker-compose
- [x] ✅ **AWS ECS deployment** - ARM64, EFS, Python boto3 scripts
- [x] ✅ **Configuration documented** - All connection parameters defined
- [x] ✅ **Signal manager implementation** - No-op FusekiSignalManager complete
- [ ] **Factory integration** - Add Fuseki to BackendFactory
- [ ] **Configuration testing** - Test switching from PostgreSQL to Fuseki via config
- [ ] **Integration testing** - Verify Fuseki works with interface architecture

### Phase 3-5: Other Backends & Migration
- [ ] PostgreSQL uses existing `database` config section
- [ ] Oxigraph uses new `oxigraph` config section  
- [ ] Mock backend excluded from server config (testing only)
- [ ] Mock endpoints migrated to `/vitalgraph/db/mock/`
- [ ] Mock client directly instantiates mock backend
- [ ] No performance regression on PostgreSQL
- [ ] Comprehensive test coverage across backends
- [ ] Clear documentation and migration guides
- [ ] All 100+ `get_space_impl` references migrated
- [ ] All SPARQL endpoints use `SparqlBackendInterface`
- [ ] All endpoint implementations use interface methods
- [ ] Clean break migration with no legacy method support