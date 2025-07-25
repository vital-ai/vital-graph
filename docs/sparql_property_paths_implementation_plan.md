# SPARQL Property Paths Implementation Plan for VitalGraph

## Overview

This document outlines the implementation plan for adding SPARQL 1.1 Property Path support to VitalGraph's PostgreSQL-backed SPARQL engine. Property paths enable graph traversal queries using operators like `+` (one or more), `*` (zero or more), `/` (sequence), and `|` (alternative).

## Current Architecture Analysis

### Database Schema
- **UUID-based RDF storage**: `rdf_quad` table with (subject_uuid, predicate_uuid, object_uuid, context_uuid)
- **Term resolution**: Separate `term` table for UUID-to-text mapping
- **Space-based**: Multi-tenant with `{global_prefix}__{space_id}__{table_name}` naming
- **PostgreSQL 17.5**: Full support for WITH RECURSIVE CTEs

### Current SPARQL Implementation
- **Main file**: `vitalgraph/db/postgresql/postgresql_sparql_impl.py` (4555 lines)
- **Pattern dispatcher**: `_translate_pattern()` routes based on `pattern.name`
- **BGP handler**: `_translate_bgp()` processes Basic Graph Patterns with triple arrays
- **Variable mapping**: Maintains `Dict[Variable, str]` for SQL column mapping
- **Join generation**: Creates JOINs between quad and term tables

### Property Path Support Gap
- **Missing detection**: No handling of RDFLib Path objects in BGP triples
- **No recursive SQL**: No WITH RECURSIVE CTE generation
- **Pattern types needed**: MulPath (+/*/?), SequencePath (/), AlternativePath (|), InvPath (~), NegatedPath (!)

## RDFLib Property Path Integration

### Path Object Types in BGP Triples
Property paths appear in BGP triples as the predicate position:
```python
# Normal triple: (subject_var, predicate_uri, object_var)
# Property path: (subject_var, MulPath(predicate_uri, '+'), object_var)
```

### Path Type Hierarchy
```python
from rdflib.paths import Path, MulPath, SequencePath, AlternativePath, InvPath, NegatedPath
from rdflib.paths import ZeroOrMore, OneOrMore, ZeroOrOne  # '*', '+', '?'
```

## Implementation Design

### 1. Path Detection in BGP Translation

**Location**: Modify `_translate_bgp()` method around line 750

```python
async def _translate_bgp(self, bgp_pattern, table_config: TableConfig, projected_vars: List[Variable] = None, context_constraint: str = None, alias_gen: AliasGenerator = None):
    # ... existing code ...
    
    for triple_idx, triple in enumerate(triples):
        subject, predicate, obj = triple
        
        # NEW: Detect property paths in predicate position
        if isinstance(predicate, Path):
            # Handle property path - delegate to specialized method
            path_sql, path_where, path_joins, path_vars = await self._translate_property_path(
                subject, predicate, obj, table_config, projected_vars, alias_gen
            )
            # Integrate path results with BGP results
            # ... integration logic ...
        else:
            # Existing logic for regular predicates
            # ... existing code ...
```

### 2. Property Path Translation Method

**New method**: `_translate_property_path()`

```python
async def _translate_property_path(self, subject, path, obj, table_config: TableConfig, projected_vars: List[Variable], alias_gen: AliasGenerator) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
    """
    Translate property path to SQL using PostgreSQL WITH RECURSIVE CTEs.
    
    Args:
        subject: Subject term (Variable or bound term)
        path: RDFLib Path object (MulPath, SequencePath, etc.)
        obj: Object term (Variable or bound term)
        table_config: Table configuration
        projected_vars: Variables to project
        alias_gen: Alias generator
        
    Returns:
        Tuple of (from_clause, where_conditions, joins, variable_mappings)
    """
    path_type = type(path).__name__
    
    if isinstance(path, MulPath):
        return await self._translate_mul_path(subject, path, obj, table_config, projected_vars, alias_gen)
    elif isinstance(path, SequencePath):
        return await self._translate_sequence_path(subject, path, obj, table_config, projected_vars, alias_gen)
    elif isinstance(path, AlternativePath):
        return await self._translate_alternative_path(subject, path, obj, table_config, projected_vars, alias_gen)
    elif isinstance(path, InvPath):
        return await self._translate_inverse_path(subject, path, obj, table_config, projected_vars, alias_gen)
    elif isinstance(path, NegatedPath):
        return await self._translate_negated_path(subject, path, obj, table_config, projected_vars, alias_gen)
    else:
        raise NotImplementedError(f"Property path type {path_type} not yet supported")
```

### 3. MulPath Implementation (*, +, ?)

**Core implementation**: `_translate_mul_path()`

```python
async def _translate_mul_path(self, subject, mul_path, obj, table_config: TableConfig, projected_vars: List[Variable], alias_gen: AliasGenerator):
    """
    Translate MulPath (*, +, ?) to PostgreSQL WITH RECURSIVE CTE.
    
    Examples:
    - foaf:knows+ -> one or more steps
    - foaf:knows* -> zero or more steps  
    - foaf:knows? -> zero or one step
    """
    base_path = mul_path.path  # The underlying path
    modifier = mul_path.mod    # '*', '+', or '?'
    
    # Generate unique CTE alias
    cte_alias = alias_gen.next_subquery_alias()
    
    # Get term UUIDs for bound terms
    subject_uuid = await self._get_bound_term_uuid(subject, table_config) if not isinstance(subject, Variable) else None
    obj_uuid = await self._get_bound_term_uuid(obj, table_config) if not isinstance(obj, Variable) else None
    base_path_uuid = await self._get_bound_term_uuid(base_path, table_config)
    
    if modifier == ZeroOrMore:  # '*'
        return await self._generate_zero_or_more_cte(subject, obj, base_path_uuid, subject_uuid, obj_uuid, cte_alias, table_config, projected_vars, alias_gen)
    elif modifier == OneOrMore:  # '+'
        return await self._generate_one_or_more_cte(subject, obj, base_path_uuid, subject_uuid, obj_uuid, cte_alias, table_config, projected_vars, alias_gen)
    elif modifier == ZeroOrOne:  # '?'
        return await self._generate_zero_or_one_cte(subject, obj, base_path_uuid, subject_uuid, obj_uuid, cte_alias, table_config, projected_vars, alias_gen)
```

### 4. PostgreSQL CTE Generation

**Zero or More (*)**: 
```sql
WITH RECURSIVE path_traversal AS (
    -- Base case: zero steps (subject = object for same nodes)
    SELECT s_term.term_text as start_node, s_term.term_text as end_node, 0 as depth, 
           ARRAY[s_term.term_uuid] as path_uuids
    FROM {term_table} s_term
    WHERE (?subject_constraint OR ?object_constraint)
    
    UNION ALL
    
    -- Recursive case: one or more steps
    SELECT pt.start_node, o_term.term_text as end_node, pt.depth + 1,
           pt.path_uuids || q.object_uuid
    FROM path_traversal pt
    JOIN {quad_table} q ON q.subject_uuid = (
        SELECT term_uuid FROM {term_table} WHERE term_text = pt.end_node
    )
    JOIN {term_table} o_term ON q.object_uuid = o_term.term_uuid
    WHERE q.predicate_uuid = '{base_path_uuid}'
      AND pt.depth < 10  -- Cycle prevention
      AND NOT (q.object_uuid = ANY(pt.path_uuids))  -- Cycle detection
)
SELECT start_node, end_node FROM path_traversal
WHERE (?subject_filter) AND (?object_filter)
```

**One or More (+)**:
```sql
WITH RECURSIVE path_traversal AS (
    -- Base case: exactly one step
    SELECT s_term.term_text as start_node, o_term.term_text as end_node, 1 as depth,
           ARRAY[q.subject_uuid, q.object_uuid] as path_uuids
    FROM {quad_table} q
    JOIN {term_table} s_term ON q.subject_uuid = s_term.term_uuid
    JOIN {term_table} o_term ON q.object_uuid = o_term.term_uuid
    WHERE q.predicate_uuid = '{base_path_uuid}'
      AND (?subject_constraint)
      AND (?object_constraint)
    
    UNION ALL
    
    -- Recursive case: additional steps
    SELECT pt.start_node, o_term.term_text as end_node, pt.depth + 1,
           pt.path_uuids || q.object_uuid
    FROM path_traversal pt
    JOIN {quad_table} q ON q.subject_uuid = (
        SELECT term_uuid FROM {term_table} WHERE term_text = pt.end_node
    )
    JOIN {term_table} o_term ON q.object_uuid = o_term.term_uuid
    WHERE q.predicate_uuid = '{base_path_uuid}'
      AND pt.depth < 10
      AND NOT (q.object_uuid = ANY(pt.path_uuids))
)
SELECT start_node, end_node FROM path_traversal
WHERE (?subject_filter) AND (?object_filter)
```

### 5. Sequence Path Implementation (/)

**Example**: `foaf:knows/foaf:name` (knows followed by name)

```python
async def _translate_sequence_path(self, subject, seq_path, obj, table_config, projected_vars, alias_gen):
    """
    Translate sequence path to nested JOINs or CTEs.
    
    For simple sequences, use JOINs:
    foaf:knows/foaf:name -> JOIN on intermediate variable
    
    For complex sequences with paths, use CTEs:
    foaf:knows+/foaf:name -> CTE for knows+, then JOIN for name
    """
    path_steps = seq_path.args  # List of path components
    
    if all(isinstance(step, URIRef) for step in path_steps):
        # Simple sequence - use JOINs
        return await self._translate_simple_sequence(subject, path_steps, obj, table_config, projected_vars, alias_gen)
    else:
        # Complex sequence with paths - use CTEs
        return await self._translate_complex_sequence(subject, path_steps, obj, table_config, projected_vars, alias_gen)
```

### 6. Alternative Path Implementation (|)

**Example**: `foaf:name|foaf:givenName` (name OR givenName)

```python
async def _translate_alternative_path(self, subject, alt_path, obj, table_config, projected_vars, alias_gen):
    """
    Translate alternative path to UNION.
    """
    alternatives = alt_path.args
    union_parts = []
    
    for alt in alternatives:
        if isinstance(alt, Path):
            # Recursive path
            alt_sql, alt_where, alt_joins, alt_vars = await self._translate_property_path(
                subject, alt, obj, table_config, projected_vars, alias_gen
            )
        else:
            # Simple predicate
            alt_sql, alt_where, alt_joins, alt_vars = await self._translate_simple_predicate(
                subject, alt, obj, table_config, projected_vars, alias_gen
            )
        
        union_parts.append((alt_sql, alt_where, alt_joins, alt_vars))
    
    # Combine with UNION
    return self._combine_union_parts(union_parts, alias_gen)
```

## Integration Challenges

### 1. Variable Mapping Integration
- Property path CTEs must integrate with existing variable mapping system
- Path results need to map to appropriate term table columns
- Maintain compatibility with other BGP triples in same pattern

### 2. JOIN Integration
- Property path results must JOIN correctly with other BGP patterns
- Shared variables between paths and regular triples need proper constraints
- Alias management across CTEs and regular JOINs

### 3. Performance Optimization
- Cycle detection and prevention in recursive CTEs
- Depth limits to prevent infinite recursion
- Index utilization for path traversal queries
- Query plan optimization for complex path combinations

## Implementation Phases

### Phase 1: Basic MulPath Support
1. Implement `_translate_property_path()` dispatcher
2. Implement `_translate_mul_path()` for `+`, `*`, `?`
3. Add CTE generation methods
4. Basic integration with BGP translation
5. Unit tests for simple property paths

### Phase 2: Sequence and Alternative Paths
1. Implement `_translate_sequence_path()` for `/`
2. Implement `_translate_alternative_path()` for `|`
3. Handle mixed path/predicate sequences
4. Integration tests with complex patterns

### Phase 3: Advanced Path Features
1. Implement `_translate_inverse_path()` for `~`
2. Implement `_translate_negated_path()` for `!`
3. Nested path combinations
4. Performance optimization and cycle detection

### Phase 4: Production Hardening
1. Comprehensive test suite with real-world data
2. Performance benchmarking and optimization
3. Error handling and edge cases
4. Documentation and examples

## Test Data Requirements

### Basic Traversal Data
```turtle
@prefix ex: <http://example.org/> .
@prefix foaf: <http://xmlns.com/foaf/0.1/> .

ex:alice foaf:knows ex:bob .
ex:bob foaf:knows ex:charlie .
ex:charlie foaf:knows ex:david .
ex:david foaf:knows ex:alice .  # Creates cycle

ex:alice foaf:name "Alice" .
ex:bob foaf:name "Bob" .
ex:charlie foaf:name "Charlie" .
ex:david foaf:name "David" .
```

### Test Queries
```sparql
# One or more: Find all people Alice knows transitively
SELECT ?person WHERE {
  ex:alice foaf:knows+ ?person .
}

# Zero or more: Include Alice herself
SELECT ?person WHERE {
  ex:alice foaf:knows* ?person .
}

# Sequence: Find names of people Alice knows directly
SELECT ?name WHERE {
  ex:alice foaf:knows/foaf:name ?name .
}

# Alternative: Find names using either property
SELECT ?name WHERE {
  ex:alice foaf:name|foaf:givenName ?name .
}
```

## Files to Modify

1. **`postgresql_sparql_impl.py`**:
   - Modify `_translate_bgp()` for Path detection
   - Add property path translation methods
   - Add CTE generation utilities

2. **New test file**: `test_scripts/sparql/test_property_paths.py`
   - Comprehensive property path test suite

3. **Test data**: `test_scripts/data/reload_test_data.py`
   - Add property path test data

4. **Documentation**: 
   - Update SPARQL feature support documentation
   - Add property path usage examples

## Success Criteria

1. **Functional**: All SPARQL 1.1 property path operators supported
2. **Performance**: Property path queries execute efficiently with proper cycle detection
3. **Integration**: Seamless integration with existing SPARQL features (OPTIONAL, UNION, FILTER, etc.)
4. **Compatibility**: Maintains backward compatibility with existing queries
5. **Testing**: Comprehensive test coverage for all path types and combinations

This implementation will bring VitalGraph's SPARQL support to near-complete SPARQL 1.1 compliance, enabling powerful graph traversal queries for production applications.
