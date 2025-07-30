# SPARQL 1.1 UPDATE/INSERT/DELETE Implementation Plan

## Overview

This document outlines the comprehensive implementation plan for adding SPARQL 1.1 UPDATE operations to VitalGraph's PostgreSQL-backed SPARQL engine. The implementation will support all major SPARQL 1.1 update operations while maintaining compatibility with the existing query infrastructure.

## SPARQL 1.1 Update Operations to Implement

### 1. Graph Update Operations

#### 1.1 INSERT DATA
- **Purpose**: Add ground triples (no variables) to graphs
- **Syntax**: `INSERT DATA { <triples> }` or `INSERT DATA { GRAPH <uri> { <triples> } }`
- **Behavior**: Creates graphs if they don't exist, ignores duplicate triples

#### 1.2 DELETE DATA
- **Purpose**: Remove ground triples from graphs
- **Syntax**: `DELETE DATA { <triples> }` or `DELETE DATA { GRAPH <uri> { <triples> } }`
- **Behavior**: Ignores non-existent triples, no variables or blank nodes allowed

#### 1.3 INSERT/DELETE with WHERE
- **Purpose**: Pattern-based insert/delete operations
- **Syntax**: `INSERT { <template> } WHERE { <pattern> }`
- **Behavior**: Uses WHERE clause to find bindings, applies to INSERT/DELETE templates

#### 1.4 Combined DELETE/INSERT
- **Purpose**: Atomic update operations
- **Syntax**: `DELETE { <template1> } INSERT { <template2> } WHERE { <pattern> }`
- **Behavior**: Both operations use same variable bindings from WHERE clause

### 2. Graph Management Operations

#### 2.1 CREATE
- **Purpose**: Create empty named graphs
- **Syntax**: `CREATE GRAPH <uri>` or `CREATE SILENT GRAPH <uri>`
- **Behavior**: Fails if graph exists (unless SILENT)

#### 2.2 DROP
- **Purpose**: Delete entire graphs
- **Syntax**: `DROP GRAPH <uri>` or `DROP SILENT GRAPH <uri>`
- **Behavior**: Removes graph and all triples, fails if graph doesn't exist (unless SILENT)

#### 2.3 CLEAR
- **Purpose**: Remove all triples from graphs but keep graph
- **Syntax**: `CLEAR GRAPH <uri>` or `CLEAR SILENT GRAPH <uri>`
- **Behavior**: Empties graph content, keeps graph structure

#### 2.4 COPY
- **Purpose**: Copy all triples from source to destination graph
- **Syntax**: `COPY GRAPH <source> TO <destination>`
- **Behavior**: Replaces destination graph content with source content

#### 2.5 MOVE
- **Purpose**: Move all triples from source to destination graph
- **Syntax**: `MOVE GRAPH <source> TO <destination>`
- **Behavior**: Copies then drops source graph

#### 2.6 ADD
- **Purpose**: Add all triples from source to destination graph
- **Syntax**: `ADD GRAPH <source> TO <destination>`
- **Behavior**: Merges source triples into destination graph

### 3. LOAD Operation
- **Purpose**: Load triples from external RDF documents
- **Syntax**: `LOAD <document-uri>` or `LOAD <document-uri> INTO GRAPH <graph-uri>`
- **Behavior**: Fetches and parses external RDF, adds to specified graph

## Implementation Architecture

### Core Components

#### 1. Update Query Detection
```python
def is_update_query(sparql_query: str) -> bool:
    """Detect if SPARQL query is an UPDATE operation."""
    update_keywords = ['INSERT', 'DELETE', 'CREATE', 'DROP', 'CLEAR', 'COPY', 'MOVE', 'ADD', 'LOAD']
    # Implementation logic
```

#### 2. Update Query Parser
```python
def parse_update_query(sparql_query: str) -> UpdateOperation:
    """Parse SPARQL UPDATE query into structured operation."""
    # Use RDFLib's update parsing capabilities
    # Return structured representation of update operation
```

#### 3. Update Translator
```python
class UpdateTranslator:
    """Translate SPARQL UPDATE operations to SQL."""
    
    async def translate_insert_data(self, operation) -> str:
        """Translate INSERT DATA to SQL INSERT statements."""
        
    async def translate_delete_data(self, operation) -> str:
        """Translate DELETE DATA to SQL DELETE statements."""
        
    async def translate_insert_delete_pattern(self, operation) -> str:
        """Translate pattern-based INSERT/DELETE to SQL."""
        
    async def translate_graph_management(self, operation) -> str:
        """Translate graph management operations to SQL."""
```

#### 4. Transaction Management
```python
class UpdateTransactionManager:
    """Manage ACID transactions for UPDATE operations."""
    
    async def execute_update_transaction(self, sql_operations: List[str]) -> bool:
        """Execute multiple SQL operations in single transaction."""
        # Begin transaction
        # Execute all operations
        # Commit or rollback on error
```

### Integration with Existing Code

#### 1. PostgreSQLSparqlImpl Extensions
```python
class PostgreSQLSparqlImpl:
    # Existing query methods...
    
    async def execute_sparql_update(self, space_id: str, sparql_update: str) -> bool:
        """Execute SPARQL UPDATE operation."""
        # Parse update operation
        # Translate to SQL
        # Execute in transaction
        # Return success/failure
        
    async def _translate_update_to_sql(self, update_operation) -> List[str]:
        """Translate UPDATE operation to SQL statements."""
        # Dispatch to appropriate translator method
        
    async def _execute_update_transaction(self, sql_statements: List[str]) -> bool:
        """Execute UPDATE SQL statements in transaction."""
        # Use PostgreSQL transaction management
```

#### 2. Space Implementation Extensions
```python
class PostgreSQLSpaceImpl:
    # Existing methods...
    
    async def create_graph(self, space_id: str, graph_uri: str) -> bool:
        """Create empty named graph."""
        
    async def drop_graph(self, space_id: str, graph_uri: str) -> bool:
        """Drop named graph and all triples."""
        
    async def clear_graph(self, space_id: str, graph_uri: str) -> bool:
        """Clear all triples from graph."""
        
    async def copy_graph(self, space_id: str, source_uri: str, dest_uri: str) -> bool:
        """Copy all triples from source to destination graph."""
```

## Implementation Phases

### Phase 1: Basic Ground Triple Operations (Week 1-2)
**Scope**: INSERT DATA and DELETE DATA with ground triples
**Deliverables**:
- Update query detection and parsing
- Basic INSERT DATA translation to SQL INSERT
- Basic DELETE DATA translation to SQL DELETE
- Transaction management for single operations
- Basic test coverage

**Key Files to Modify**:
- `postgresql_sparql_impl.py`: Add `execute_sparql_update()` method
- `postgresql_space_impl.py`: Add ground triple insert/delete methods
- Test script: Basic INSERT DATA/DELETE DATA tests

### Phase 2: Pattern-Based Operations (Week 3-4)
**Scope**: INSERT/DELETE with WHERE clauses
**Deliverables**:
- WHERE clause pattern matching integration
- Template-based INSERT/DELETE translation
- Variable binding from WHERE to INSERT/DELETE templates
- Combined DELETE/INSERT operations
- Advanced test coverage

**Key Files to Modify**:
- `postgresql_sparql_impl.py`: Extend with pattern-based operations
- Leverage existing `_translate_bgp()` for WHERE patterns
- Test script: Pattern-based operation tests

### Phase 3: Graph Management (Week 5-6)
**Scope**: CREATE, DROP, CLEAR, COPY, MOVE, ADD operations
**Deliverables**:
- Graph lifecycle management
- Graph-to-graph operations
- SILENT operation support
- Graph existence checking
- Comprehensive test coverage

**Key Files to Modify**:
- `postgresql_space_impl.py`: Add graph management methods
- `postgresql_sparql_impl.py`: Add graph operation translators
- Test script: Graph management tests

### Phase 4: LOAD Operation (Week 7)
**Scope**: LOAD operation for external RDF documents
**Deliverables**:
- HTTP/HTTPS document fetching
- RDF format detection and parsing
- Integration with existing triple insertion
- Error handling for network/parsing failures

**Key Files to Modify**:
- New module: `rdf_loader.py` for document fetching
- `postgresql_sparql_impl.py`: LOAD operation support
- Test script: LOAD operation tests

### Phase 5: Production Hardening (Week 8)
**Scope**: Error handling, performance, edge cases
**Deliverables**:
- Comprehensive error handling
- Performance optimization
- Edge case handling
- Security considerations
- Documentation and examples

## Database Schema Considerations

### Graph Metadata Table
```sql
CREATE TABLE IF NOT EXISTS {prefix}graph_metadata (
    graph_id BIGSERIAL PRIMARY KEY,
    graph_uri_uuid UUID NOT NULL REFERENCES {prefix}term(term_uuid),
    created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    triple_count BIGINT DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE
);
```

### Update Operation Logging
```sql
CREATE TABLE IF NOT EXISTS {prefix}update_log (
    log_id BIGSERIAL PRIMARY KEY,
    operation_type VARCHAR(50) NOT NULL,
    sparql_query TEXT NOT NULL,
    execution_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    success BOOLEAN NOT NULL,
    error_message TEXT,
    affected_graphs TEXT[],
    triple_count_delta INTEGER
);
```

## Testing Strategy

### Test Data Requirements
Add to `reload_test_data.py`:
- Base entities for update operations
- Multiple named graphs for graph management testing
- Hierarchical data for pattern-based operations
- Edge cases and error scenarios

### Test Categories
1. **Basic Operations**: INSERT DATA, DELETE DATA
2. **Pattern Operations**: INSERT/DELETE with WHERE
3. **Graph Management**: CREATE, DROP, CLEAR, COPY, MOVE, ADD
4. **Transaction Behavior**: Atomicity, rollback scenarios
5. **Error Handling**: Invalid syntax, constraint violations
6. **Performance**: Large batch operations, concurrent updates

### Test Script Structure
Following `test_agg_queries.py` pattern:
- Database connection setup/teardown
- Individual test functions for each operation type
- Result verification queries
- Debug mode for troubleshooting
- Performance metrics collection

## Performance Considerations

### Batch Operations
- Use PostgreSQL COPY for large INSERT DATA operations
- Batch multiple small operations into single transactions
- Optimize term UUID lookups with caching

### Index Optimization
- Ensure proper indexes for pattern matching in WHERE clauses
- Consider partial indexes for frequently updated graphs
- Monitor query performance during development

### Memory Management
- Stream large RDF documents during LOAD operations
- Limit transaction size for very large updates
- Implement progress reporting for long-running operations

## Security Considerations

### Input Validation
- Sanitize all SPARQL UPDATE queries
- Validate graph URIs and prevent injection attacks
- Implement query complexity limits

### Access Control
- Graph-level permissions for update operations
- User authentication for sensitive operations
- Audit logging for all update activities

### Resource Limits
- Maximum transaction size limits
- Timeout handling for long-running operations
- Rate limiting for update operations

## Error Handling Strategy

### Operation-Specific Errors
- Graph existence validation
- Triple constraint violations
- Pattern matching failures
- Network errors for LOAD operations

### Transaction Management
- Automatic rollback on any operation failure
- Detailed error reporting with context
- Recovery suggestions for common errors

### Graceful Degradation
- Continue processing valid operations when possible
- Partial success reporting for batch operations
- Clear error messages for debugging

## Success Criteria

### Functional Requirements
- ✅ All SPARQL 1.1 UPDATE operations implemented
- ✅ Full transaction support with ACID properties
- ✅ Integration with existing query infrastructure
- ✅ Comprehensive test coverage (>90%)

### Performance Requirements
- ✅ INSERT DATA: >10,000 triples/second
- ✅ Pattern operations: <1 second for typical queries
- ✅ Graph management: <100ms for typical operations
- ✅ Memory usage: <1GB for typical operations

### Quality Requirements
- ✅ Zero data corruption under any circumstances
- ✅ Proper error handling and reporting
- ✅ Production-ready logging and monitoring
- ✅ Complete documentation and examples

## Future Enhancements

### SPARQL 1.2 Features
- Enhanced UPDATE operations
- Improved performance optimizations
- Additional built-in functions

### Advanced Features
- Distributed update operations
- Conflict resolution for concurrent updates
- Advanced caching strategies
- Real-time update notifications

This implementation plan provides a comprehensive roadmap for adding full SPARQL 1.1 UPDATE support to VitalGraph while maintaining the high quality and performance standards of the existing codebase.
