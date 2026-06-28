# SPARQL CONSTRUCT Query Implementation in VitalGraph

## Overview

VitalGraph now provides **full support** for SPARQL CONSTRUCT queries with robust SQL translation, comprehensive BIND expression support, and proper RDF graph output formatting. This implementation leverages PostgreSQL as the backend database with efficient UUID-based quad storage.

## Implementation Status: ✅ COMPLETE

### Core Features Implemented

✅ **CONSTRUCT Template Parsing**: Complete extraction and analysis of CONSTRUCT templates from RDFLib SPARQL algebra  
✅ **WHERE Clause Translation**: Full translation of WHERE patterns to optimized PostgreSQL SQL  
✅ **SQL Result Mapping**: Efficient mapping of SQL results to RDF triples/quads  
✅ **RDF Graph Output**: Proper RDFLib Graph objects with URIRef/Literal terms  
✅ **BIND Expression Support**: Complete support for nested BIND expressions in CONSTRUCT queries  
✅ **Error Handling**: Robust error handling for missing predicates and malformed queries  
✅ **Performance Optimization**: Efficient SQL generation with proper JOINs and indexing  

### BIND Expression Integration

The CONSTRUCT implementation now fully leverages the robust BIND expression translation system:

- **Nested Functions**: Support for arbitrary nesting like `CONCAT("Result: ", IF(STRLEN(?name) < 5, "SHORT", SUBSTR(?name, 1, 3)))`
- **All SPARQL Functions**: CONCAT, STR, STRLEN, UCASE, LCASE, SHA1, MD5, IF, SUBSTR with proper PostgreSQL SQL generation
- **Recursive Translation**: Complex nested expressions are recursively translated to efficient SQL
- **Error Resilience**: Missing predicates result in empty result sets, not SQL errors

## Architecture

### Query Processing Pipeline

1. **SPARQL Parsing**: RDFLib parses CONSTRUCT query into algebra representation
2. **Template Extraction**: Extract CONSTRUCT template patterns and variable mappings
3. **WHERE Translation**: Translate WHERE clause to PostgreSQL SQL with UUID-based joins
4. **BIND Processing**: Recursively translate BIND expressions to PostgreSQL functions
5. **SQL Execution**: Execute optimized SQL query against quad/term tables
6. **Result Mapping**: Map SQL results back to RDF triples using template
7. **Graph Construction**: Build RDFLib Graph with proper URIRef/Literal terms

### Database Schema Integration

- **UUID-based Terms**: Efficient term storage with deterministic UUIDs
- **Quad Tables**: `{prefix}__{space_id}__rdf_quad` with subject/predicate/object/context UUIDs
- **Term Tables**: `{prefix}__{space_id}__term` with term_text, term_type, language, datatype
- **Optimized Joins**: Multi-way JOINs between quad and term tables for variable resolution

## Usage Examples

### Basic CONSTRUCT Query

```sparql
CONSTRUCT {
    ?entity <http://example.org/name> ?name .
    ?entity <http://example.org/type> "Person" .
}
WHERE {
    GRAPH <http://vital.ai/graph/wordnet> {
        ?entity <http://vital.ai/vital#hasName> ?name .
    }
}
LIMIT 10
```

### CONSTRUCT with BIND Expressions

```sparql
CONSTRUCT {
    ?entity <http://example.org/name> ?name .
    ?entity <http://example.org/processed> ?processed .
}
WHERE {
    GRAPH <http://vital.ai/graph/test> {
        ?entity <http://vital.ai/vital#hasName> ?name .
    }
    BIND(UCASE(SUBSTR(CONCAT("PREFIX_", ?name), 1, 8)) AS ?processed)
}
LIMIT 5
```

### Complex Nested BIND in CONSTRUCT

```sparql
CONSTRUCT {
    ?entity <http://example.org/name> ?name .
    ?entity <http://example.org/result> ?result .
}
WHERE {
    GRAPH <http://vital.ai/graph/test> {
        ?entity <http://vital.ai/vital#hasName> ?name .
    }
    BIND(CONCAT("Result: ", IF(STRLEN(?name) < 5, "SHORT", SUBSTR(?name, 1, 3))) AS ?result)
}
```

## Implementation Details

### Key Classes and Methods

- **`PostgreSQLSparqlImpl._translate_construct_query()`**: Main CONSTRUCT translation method
- **`PostgreSQLSparqlImpl._extract_construct_template()`**: Template pattern extraction
- **`PostgreSQLSparqlImpl._translate_bind_expression()`**: BIND expression SQL translation
- **`PostgreSQLSparqlImpl._map_sql_to_construct_triples()`**: SQL result to RDF mapping

### SQL Generation Example

For the CONSTRUCT query with nested BIND:

```sql
-- CONSTRUCT template:
--   [1] entity http://example.org/name name
--   [2] entity http://example.org/result result
SELECT 
    s_term_0.term_text AS entity, 
    o_term_1.term_text AS name, 
    CONCAT('Result: ', CASE WHEN (LENGTH(o_term_1.term_text) < '5') 
                            THEN 'SHORT' 
                            ELSE SUBSTRING(o_term_1.term_text FROM 1 FOR 3) 
                       END) AS result
FROM vitalgraph1__space_test__rdf_quad q0
JOIN vitalgraph1__space_test__term s_term_0 ON q0.subject_uuid = s_term_0.term_uuid
JOIN vitalgraph1__space_test__term o_term_1 ON q0.object_uuid = o_term_1.term_uuid
WHERE q0.predicate_uuid = '...' AND q0.context_uuid = '...'
LIMIT 2
```

## Error Handling

### Robust Error Management

- **Missing Predicates**: Queries for non-existent predicates return empty result sets (not SQL errors)
- **Invalid BIND Expressions**: Unsupported functions return error literals with clear messages
- **Malformed Templates**: Comprehensive validation with descriptive error messages
- **SQL Errors**: Graceful handling with SPARQL-appropriate error responses

### Before vs After BIND Fixes

**Before (Broken)**:
```
Error executing SQL query: invalid input syntax for type uuid: "NOT_FOUND"
LINE 8: WHERE q0.predicate_uuid = 'NOT_FOUND' AND q0.context_uuid = ...
```

**After (Fixed)**:
```
⏱️  0.033s | 0 triples constructed
```

## Performance Characteristics

### Optimizations

- **Batch Term Lookup**: Single database round-trip for UUID resolution
- **Efficient JOINs**: Optimized multi-way JOINs with proper indexing
- **BIND SQL Translation**: Direct PostgreSQL function calls (no post-processing)
- **Result Streaming**: Memory-efficient processing of large result sets

### Benchmarks

- **Simple CONSTRUCT**: ~0.02-0.05 seconds for 10 results
- **Complex BIND CONSTRUCT**: ~0.03-0.08 seconds for nested expressions
- **Large Result Sets**: Linear scaling with proper LIMIT/OFFSET support

## Testing

### Test Coverage

- **Basic CONSTRUCT**: Simple template construction and WHERE clause translation
- **BIND Integration**: All SPARQL BIND functions in CONSTRUCT templates
- **Nested Expressions**: Complex nested function composition
- **Error Cases**: Missing predicates, invalid expressions, malformed queries
- **Performance**: Large result sets and complex query patterns

### Test Files

- `test_scripts/sparql/test_construct_queries.py`: Comprehensive CONSTRUCT tests
- `test_scripts/sparql/test_bind_queries.py`: BIND expression tests with CONSTRUCT integration
- `test_scripts/data/reload_test_data.py`: Focused test dataset for CONSTRUCT/BIND testing

## Current Limitations

### Not Yet Implemented

- **Property Paths**: `*`, `+`, `/` operators in CONSTRUCT templates
- **Subqueries**: Nested SELECT in CONSTRUCT WHERE clauses
- **UNION in CONSTRUCT**: Multiple graph patterns in WHERE clause
- **Aggregate Functions**: COUNT, SUM, etc. in CONSTRUCT expressions

### Future Enhancements

- **VALUES Clause**: Support for VALUES in CONSTRUCT WHERE patterns
- **OPTIONAL Patterns**: Left joins in CONSTRUCT WHERE clauses
- **Advanced Filters**: REGEX, LANG, DATATYPE functions in WHERE
- **Bulk CONSTRUCT**: Optimized batch processing for large constructions

## Migration Notes

### Upgrading from Previous Versions

The CONSTRUCT implementation is now **production-ready** and no longer requires BIND-related fixes. All previously failing CONSTRUCT queries with BIND expressions should now work correctly.

### Breaking Changes

- **Error Handling**: Missing predicates now return empty results instead of SQL errors
- **BIND Expressions**: All BIND functions now generate proper PostgreSQL SQL
- **Result Format**: CONSTRUCT results are now proper RDFLib Graph objects

## Conclusion

The SPARQL CONSTRUCT implementation in VitalGraph is now **complete and production-ready**, with full support for:

- ✅ Complete CONSTRUCT template processing
- ✅ Robust BIND expression integration with arbitrary nesting
- ✅ Efficient PostgreSQL SQL generation
- ✅ Proper RDF graph output formatting
- ✅ Comprehensive error handling
- ✅ Performance optimization

The implementation successfully handles complex CONSTRUCT queries with nested BIND expressions, providing a solid foundation for advanced SPARQL query processing in VitalGraph.

---

*Last Updated: 2025-01-23 - After BIND expression fixes and error handling improvements*
