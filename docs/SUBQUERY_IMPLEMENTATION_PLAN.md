# Sub-SELECT (Subquery) Implementation Plan

## Overview

This document outlines the plan for implementing SPARQL sub-SELECT (subquery) support in VitalGraph's PostgreSQL-backed SPARQL engine. Sub-SELECT queries allow nested SELECT queries within the WHERE clause of outer SELECT queries, enabling complex filtering, aggregation, and EXISTS/NOT EXISTS patterns.

## Current State Analysis

### ✅ What's Working
- Basic SELECT query translation with BGP patterns
- UNION pattern support (fully implemented)
- CONSTRUCT query support
- BIND expressions and variable extensions
- Basic FILTER expressions
- GRAPH pattern support across named graphs

### ❌ What's Missing
- Sub-SELECT query recognition and parsing
- Nested query context management
- EXISTS/NOT EXISTS subquery translation
- Aggregation subqueries (COUNT, AVG, etc.)
- Subquery variable scoping and isolation
- LIMIT/OFFSET within subqueries
- Cross-graph subquery support

## SPARQL Subquery Patterns to Support

### 1. Basic Subqueries
```sparql
SELECT ?entity ?name WHERE {
  ?entity test:hasName ?name .
  FILTER(?entity IN {
    SELECT ?topEntity WHERE {
      ?topEntity test:hasScore ?score .
      FILTER(?score > 90)
    }
    LIMIT 5
  })
}
```

### 2. EXISTS/NOT EXISTS Subqueries
```sparql
SELECT ?entity ?name WHERE {
  ?entity test:hasName ?name .
  FILTER EXISTS {
    ?entity test:hasDescription ?desc .
  }
}
```

### 3. Aggregation Subqueries
```sparql
SELECT ?entity ?name WHERE {
  ?entity test:hasName ?name .
  FILTER(STRLEN(?name) > {
    SELECT (AVG(STRLEN(?avgName)) AS ?avgLength) WHERE {
      ?anyEntity test:hasName ?avgName .
    }
  })
}
```

### 4. Cross-Graph Subqueries
```sparql
SELECT ?entity ?testName WHERE {
  GRAPH <test> {
    ?entity test:hasName ?testName .
    FILTER EXISTS {
      GRAPH <global> {
        ?entity ex:hasName ?globalName .
      }
    }
  }
}
```

## Implementation Architecture

### 1. Query Algebra Recognition

**Location**: `postgresql_sparql_impl.py`

Add subquery pattern recognition in `_translate_pattern()`:

```python
async def _translate_pattern(self, pattern, table_config, projected_vars=None):
    if pattern.name == 'SelectQuery':
        # Handle nested SELECT query (subquery)
        return await self._translate_subquery(pattern, table_config, projected_vars)
    elif pattern.name == 'Filter':
        # Check if filter contains EXISTS/NOT EXISTS subqueries
        return await self._translate_filter_with_subquery(pattern, table_config, projected_vars)
    # ... existing pattern handling
```

### 2. Subquery Translation Method

**New Method**: `_translate_subquery()`

```python
async def _translate_subquery(self, subquery_algebra, table_config: TableConfig, projected_vars: List[Variable] = None) -> Tuple[str, List[str], List[str], Dict[Variable, str]]:
    """
    Translate a nested SELECT query (subquery) to SQL.
    
    Args:
        subquery_algebra: RDFLib algebra for the subquery
        table_config: Table configuration
        projected_vars: Variables projected by parent query
        
    Returns:
        Tuple of (from_clause, where_conditions, joins, variable_mappings)
    """
    # Create isolated context for subquery
    subquery_context = self._create_subquery_context()
    
    # Translate subquery with isolated variable/join counters
    subquery_sql = await self._translate_select_query(subquery_algebra, table_config)
    
    # Wrap as derived table with unique alias
    subquery_alias = f"subquery_{self._get_next_subquery_counter()}"
    derived_table = f"({subquery_sql}) {subquery_alias}"
    
    return derived_table, [], [], {}
```

### 3. EXISTS/NOT EXISTS Support

**New Method**: `_translate_exists_subquery()`

```python
async def _translate_exists_subquery(self, exists_pattern, table_config: TableConfig, is_not_exists: bool = False) -> str:
    """
    Translate EXISTS/NOT EXISTS subquery patterns to SQL.
    
    Returns SQL condition like:
    - EXISTS (SELECT 1 FROM ... WHERE ...)
    - NOT EXISTS (SELECT 1 FROM ... WHERE ...)
    """
    subquery_sql = await self._translate_pattern(exists_pattern.p, table_config)
    exists_clause = "NOT EXISTS" if is_not_exists else "EXISTS"
    return f"{exists_clause} (SELECT 1 {subquery_sql})"
```

### 4. Context Management

**New Class**: `SubqueryContext`

```python
class SubqueryContext:
    """Manages isolated context for subquery translation."""
    
    def __init__(self, parent_context=None):
        self.variable_counter = 0
        self.join_counter = 0
        self.table_aliases = set()
        self.parent_context = parent_context
        self.depth = (parent_context.depth + 1) if parent_context else 0
    
    def get_unique_alias(self, base_name: str) -> str:
        """Generate unique table alias for this subquery context."""
        counter = 0
        while True:
            alias = f"{base_name}_{self.depth}_{counter}"
            if alias not in self.table_aliases:
                self.table_aliases.add(alias)
                return alias
            counter += 1
```

### 5. Variable Scoping

**Enhanced Method**: `_manage_subquery_variables()`

```python
def _manage_subquery_variables(self, subquery_vars: List[Variable], parent_vars: List[Variable]) -> Dict[Variable, str]:
    """
    Manage variable scoping between parent query and subquery.
    
    - Subquery variables are isolated from parent scope
    - Shared variables create proper JOIN conditions
    - Variable name conflicts are resolved with prefixes
    """
    variable_mappings = {}
    
    for var in subquery_vars:
        if var in parent_vars:
            # Shared variable - create correlation
            variable_mappings[var] = f"parent.{var.toPython()}"
        else:
            # Isolated subquery variable
            variable_mappings[var] = f"sub_{self.subquery_depth}.{var.toPython()}"
    
    return variable_mappings
```

## SQL Translation Examples

### 1. Basic Subquery Translation

**SPARQL**:
```sparql
SELECT ?entity ?name WHERE {
  ?entity test:hasName ?name .
  ?entity IN {
    SELECT ?topEntity WHERE {
      ?topEntity test:hasScore ?score .
      FILTER(?score > 90)
    }
    LIMIT 5
  }
}
```

**Generated SQL**:
```sql
SELECT s_term_0.term_text AS entity, o_term_1.term_text AS name
FROM vitalgraph1__space_test__rdf_quad q0
JOIN vitalgraph1__space_test__term s_term_0 ON q0.subject_uuid = s_term_0.term_uuid
JOIN vitalgraph1__space_test__term o_term_1 ON q0.object_uuid = o_term_1.term_uuid
WHERE q0.predicate_uuid = 'name_predicate_uuid'
  AND q0.subject_uuid IN (
    SELECT q1.subject_uuid
    FROM vitalgraph1__space_test__rdf_quad q1
    JOIN vitalgraph1__space_test__term o_term_2 ON q1.object_uuid = o_term_2.term_uuid
    WHERE q1.predicate_uuid = 'score_predicate_uuid'
      AND CAST(o_term_2.term_text AS INTEGER) > 90
    LIMIT 5
  )
```

### 2. EXISTS Subquery Translation

**SPARQL**:
```sparql
SELECT ?entity ?name WHERE {
  ?entity test:hasName ?name .
  FILTER EXISTS {
    ?entity test:hasDescription ?desc .
  }
}
```

**Generated SQL**:
```sql
SELECT s_term_0.term_text AS entity, o_term_1.term_text AS name
FROM vitalgraph1__space_test__rdf_quad q0
JOIN vitalgraph1__space_test__term s_term_0 ON q0.subject_uuid = s_term_0.term_uuid
JOIN vitalgraph1__space_test__term o_term_1 ON q0.object_uuid = o_term_1.term_uuid
WHERE q0.predicate_uuid = 'name_predicate_uuid'
  AND EXISTS (
    SELECT 1
    FROM vitalgraph1__space_test__rdf_quad q1
    WHERE q1.subject_uuid = q0.subject_uuid
      AND q1.predicate_uuid = 'description_predicate_uuid'
  )
```

## Implementation Steps

### Phase 1: Basic Subquery Support
1. **Add subquery pattern recognition** in `_translate_pattern()`
2. **Implement `_translate_subquery()`** method
3. **Add subquery context management** with isolated counters
4. **Create test cases** for basic subquery patterns
5. **Test with simple IN subqueries**

### Phase 2: EXISTS/NOT EXISTS Support
1. **Implement `_translate_exists_subquery()`** method
2. **Enhance filter translation** to detect EXISTS patterns
3. **Add EXISTS/NOT EXISTS test cases**
4. **Test cross-graph EXISTS patterns**

### Phase 3: Aggregation Subqueries
1. **Add aggregation function support** (COUNT, AVG, SUM, etc.)
2. **Implement GROUP BY handling** in subqueries
3. **Add HAVING clause support**
4. **Test complex aggregation scenarios**

### Phase 4: Advanced Features
1. **Add LIMIT/OFFSET in subqueries**
2. **Implement nested subquery support** (subqueries within subqueries)
3. **Add ORDER BY in subqueries**
4. **Optimize subquery performance**

### Phase 5: Integration and Testing
1. **Run comprehensive test suite**
2. **Performance optimization**
3. **Error handling and edge cases**
4. **Documentation and examples**

## Test Data Requirements

The test data in `reload_test_data.py` has been enhanced with:

- **Length-based entities** for string length subqueries
- **Entities with/without descriptions** for EXISTS/NOT EXISTS testing
- **Connection hub entities** for aggregation subqueries
- **Hierarchical categories** for nested subquery testing
- **Scored entities** for ORDER BY and LIMIT subqueries

## Performance Considerations

### 1. Subquery Optimization
- Use correlated subqueries only when necessary
- Prefer JOINs over subqueries where possible
- Add proper indexes on frequently queried columns

### 2. Context Isolation
- Minimize context switching overhead
- Reuse table aliases where safe
- Cache subquery translations when possible

### 3. Memory Management
- Limit subquery nesting depth
- Implement query complexity limits
- Monitor memory usage in deep subqueries

## Error Handling

### 1. Validation
- Check subquery nesting depth limits
- Validate variable scoping
- Ensure proper SQL syntax generation

### 2. Debugging
- Add detailed logging for subquery translation
- Include subquery context in error messages
- Provide clear error messages for unsupported patterns

## Success Criteria

### ✅ Implementation Complete When:
1. All basic subquery patterns translate correctly to SQL
2. EXISTS/NOT EXISTS subqueries work across graphs
3. Aggregation subqueries produce correct results
4. Variable scoping is properly isolated
5. Performance is acceptable for reasonable query complexity
6. Comprehensive test coverage passes
7. Error handling is robust and informative

This implementation will significantly enhance VitalGraph's SPARQL query capabilities, enabling complex analytical queries and advanced filtering patterns that are essential for sophisticated RDF applications.
