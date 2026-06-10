package ai.vital.sparqlcompiler;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Test how the sidecar handles vector/geo SPARQL extensions.
 *
 * Tests two mechanisms:
 * A) Property functions (magic properties): ?s vg:similarTo ("text" 10)
 * B) Custom FILTER/BIND functions: FILTER(vg:withinRadius(...))
 *
 * Results determine which SPARQL syntax we use for vector/geo queries.
 * See planning_vector_geo/vector_geo_plan.md §9.4 for context.
 */
class VectorGeoSparqlTest {

    private static SparqlCompiler compiler;
    private static final ObjectMapper mapper = new ObjectMapper();

    @BeforeAll
    static void setUp() {
        compiler = new SparqlCompiler(5000);
    }

    private CompileRequest makeRequest(String sparql) {
        CompileRequest req = new CompileRequest();
        req.sparql = sparql;
        req.phases = new CompileRequest.Phases();
        req.phases.parsedQuery = true;
        req.phases.syntaxTree = true;
        req.phases.algebraCompiled = true;
        req.phases.algebraOptimized = false;
        req.phases.normalizedSparql = true;
        req.phases.updateOperations = false;
        req.trace = new CompileRequest.Trace();
        req.trace.includeTiming = true;
        req.trace.includeWarnings = true;
        req.trace.includePretty = true;
        req.optimize = new CompileRequest.Optimize();
        return req;
    }

    // ================================================================
    // A) Property function tests
    // ================================================================

    @Test
    void testPropertyFunction_UnregisteredURI() {
        // Test: unregistered property function URI as simple triple
        // Expected: parsed as regular triple pattern (OpBGP), NOT OpPropFunc
        String sparql = """
            PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
            SELECT ?entity WHERE {
                ?entity vg:similarTo "search text" .
            }
            """;
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        System.out.println("=== Property Function (unregistered URI, simple object) ===");
        System.out.println("ok: " + resp.ok);
        if (resp.ok) {
            Map<String, Object> algebra = (Map<String, Object>) resp.phases.get("algebraCompiled");
            System.out.println("pretty: " + algebra.get("pretty"));
            Map<String, Object> op = (Map<String, Object>) algebra.get("op");
            System.out.println("op type: " + op.get("type"));
            // Should be OpBGP (regular triple) since URI is not registered as property function
        } else {
            System.out.println("error: " + resp.error);
        }
        assertTrue(resp.ok, "Simple triple with unregistered URI should parse");
    }

    @Test
    void testPropertyFunction_ListArgs() {
        // Test: property function with list arguments (Jena syntax)
        // This is the form used by spatial:nearby etc.
        // Without registration, this may parse as a path or fail
        String sparql = """
            PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
            SELECT ?entity WHERE {
                ?entity vg:similarTo ("search text" 10 "entity_default") .
            }
            """;
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        System.out.println("\n=== Property Function (list args, unregistered) ===");
        System.out.println("ok: " + resp.ok);
        if (resp.ok) {
            Map<String, Object> algebra = (Map<String, Object>) resp.phases.get("algebraCompiled");
            System.out.println("pretty: " + algebra.get("pretty"));
            Map<String, Object> op = (Map<String, Object>) algebra.get("op");
            System.out.println("op type: " + op.get("type"));
        } else {
            System.out.println("error: " + resp.error);
            System.out.println(">> List args with unregistered URI failed (expected)");
        }
        // Document whether this parses — don't assert, we're exploring
    }

    @Test
    void testPropertyFunction_JenaSpatialNearby() {
        // Test: Jena's spatial:nearby — may or may not be on classpath
        // If jena-spatial is not a dependency, this tests what happens
        String sparql = """
            PREFIX spatial: <http://jena.apache.org/spatial#>
            SELECT ?feature WHERE {
                ?feature spatial:nearby (40.730610 -73.935242 10) .
            }
            """;
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        System.out.println("\n=== Jena spatial:nearby ===");
        System.out.println("ok: " + resp.ok);
        if (resp.ok) {
            Map<String, Object> algebra = (Map<String, Object>) resp.phases.get("algebraCompiled");
            System.out.println("pretty: " + algebra.get("pretty"));
            Map<String, Object> op = (Map<String, Object>) algebra.get("op");
            System.out.println("op type: " + op.get("type"));
            System.out.println(">> Check if OpPropFunc appears or just OpBGP");
        } else {
            System.out.println("error: " + resp.error);
            System.out.println(">> spatial:nearby not available (jena-spatial not on classpath)");
        }
    }

    // ================================================================
    // B) Custom FILTER/BIND function tests
    // ================================================================

    @Test
    void testFilterFunction_CustomURI() {
        // Test: unknown function URI in FILTER
        // Expected: E_Function / ExprFunctionN node with IRI and args
        String sparql = """
            PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
            SELECT ?entity WHERE {
                ?entity a <http://example.org/Entity> .
                FILTER(vg:withinRadius(?entity, 40.73, -73.93, 10.0))
            }
            """;
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        System.out.println("\n=== FILTER function (custom URI, 4 args) ===");
        System.out.println("ok: " + resp.ok);
        if (resp.ok) {
            Map<String, Object> algebra = (Map<String, Object>) resp.phases.get("algebraCompiled");
            System.out.println("pretty: " + algebra.get("pretty"));

            // Drill into the Op tree to find the filter expression
            Map<String, Object> op = (Map<String, Object>) algebra.get("op");
            System.out.println("top op type: " + op.get("type"));
            try {
                String json = mapper.writerWithDefaultPrettyPrinter()
                        .writeValueAsString(algebra.get("op"));
                System.out.println("full op JSON:\n" + json);
            } catch (Exception e) {
                System.out.println("(could not serialize op)");
            }
        } else {
            System.out.println("error: " + resp.error);
            fail("Custom FILTER function should parse successfully");
        }
        assertTrue(resp.ok, "Custom FILTER function should parse successfully");
    }

    @Test
    void testBindFunction_CustomURI() {
        // Test: unknown function URI in BIND
        // Expected: OpExtend with ExprFunctionN expression containing the IRI
        String sparql = """
            PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
            SELECT ?entity ?score WHERE {
                ?entity a <http://example.org/Entity> .
                BIND(vg:cosineSimilarity(?entity, "search text", "idx") AS ?score)
            }
            """;
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        System.out.println("\n=== BIND function (custom URI, 3 args) ===");
        System.out.println("ok: " + resp.ok);
        if (resp.ok) {
            Map<String, Object> algebra = (Map<String, Object>) resp.phases.get("algebraCompiled");
            System.out.println("pretty: " + algebra.get("pretty"));
            try {
                String json = mapper.writerWithDefaultPrettyPrinter()
                        .writeValueAsString(algebra.get("op"));
                System.out.println("full op JSON:\n" + json);
            } catch (Exception e) {
                System.out.println("(could not serialize op)");
            }
        } else {
            System.out.println("error: " + resp.error);
            fail("Custom BIND function should parse successfully");
        }
        assertTrue(resp.ok, "Custom BIND function should parse successfully");
    }

    @Test
    void testFilterFunction_VectorSearch() {
        // Test: realistic vector search SPARQL with BIND + FILTER + ORDER + LIMIT
        String sparql = """
            PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?entity ?score WHERE {
                ?entity rdf:type <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                BIND(vg:vectorSimilarity(?entity, "renewable energy", "entity_default") AS ?score)
                FILTER(?score > 0.7)
            }
            ORDER BY DESC(?score)
            LIMIT 20
            """;
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        System.out.println("\n=== Realistic vector search (BIND + FILTER + ORDER + LIMIT) ===");
        System.out.println("ok: " + resp.ok);
        if (resp.ok) {
            Map<String, Object> algebra = (Map<String, Object>) resp.phases.get("algebraCompiled");
            System.out.println("pretty: " + algebra.get("pretty"));
            try {
                String json = mapper.writerWithDefaultPrettyPrinter()
                        .writeValueAsString(algebra.get("op"));
                System.out.println("full op JSON:\n" + json);
            } catch (Exception e) {
                System.out.println("(could not serialize op)");
            }
        } else {
            System.out.println("error: " + resp.error);
        }
        assertTrue(resp.ok, "Realistic vector search should parse successfully");
    }

    @Test
    void testFilterFunction_GeoSearch() {
        // Test: realistic geo search SPARQL
        String sparql = """
            PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?entity ?distance WHERE {
                ?entity rdf:type <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                BIND(vg:geoDistance(?entity, 40.7128, -74.0060) AS ?distance)
                FILTER(?distance < 50000)
            }
            ORDER BY ?distance
            LIMIT 50
            """;
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        System.out.println("\n=== Realistic geo search (BIND + FILTER + ORDER + LIMIT) ===");
        System.out.println("ok: " + resp.ok);
        if (resp.ok) {
            Map<String, Object> algebra = (Map<String, Object>) resp.phases.get("algebraCompiled");
            System.out.println("pretty: " + algebra.get("pretty"));
            try {
                String json = mapper.writerWithDefaultPrettyPrinter()
                        .writeValueAsString(algebra.get("op"));
                System.out.println("full op JSON:\n" + json);
            } catch (Exception e) {
                System.out.println("(could not serialize op)");
            }
        } else {
            System.out.println("error: " + resp.error);
        }
        assertTrue(resp.ok, "Realistic geo search should parse successfully");
    }

    @Test
    void testFilterFunction_GeoWithinRadius() {
        // Test: geo FILTER without BIND (pure filter, no result variable)
        String sparql = """
            PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?entity WHERE {
                ?entity rdf:type <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                FILTER(vg:withinRadius(?entity, 40.7128, -74.0060, 10000))
            }
            """;
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        System.out.println("\n=== Geo withinRadius (FILTER only, no BIND) ===");
        System.out.println("ok: " + resp.ok);
        if (resp.ok) {
            Map<String, Object> algebra = (Map<String, Object>) resp.phases.get("algebraCompiled");
            System.out.println("pretty: " + algebra.get("pretty"));
            try {
                String json = mapper.writerWithDefaultPrettyPrinter()
                        .writeValueAsString(algebra.get("op"));
                System.out.println("full op JSON:\n" + json);
            } catch (Exception e) {
                System.out.println("(could not serialize op)");
            }
        } else {
            System.out.println("error: " + resp.error);
        }
        assertTrue(resp.ok, "Geo withinRadius FILTER should parse successfully");
    }

    @Test
    void testVectorSearch_WithPrecomputedVector() {
        // Test: passing a pre-computed vector as a string literal
        String sparql = """
            PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?entity ?score WHERE {
                ?entity rdf:type <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                BIND(vg:vectorNearby(?entity, "[0.1, 0.2, 0.3, 0.4]", "entity_default") AS ?score)
                FILTER(?score > 0.8)
            }
            ORDER BY DESC(?score)
            LIMIT 10
            """;
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        System.out.println("\n=== Vector search with pre-computed vector ===");
        System.out.println("ok: " + resp.ok);
        if (resp.ok) {
            Map<String, Object> algebra = (Map<String, Object>) resp.phases.get("algebraCompiled");
            System.out.println("pretty: " + algebra.get("pretty"));
        } else {
            System.out.println("error: " + resp.error);
        }
        assertTrue(resp.ok, "Vector search with pre-computed vector should parse");
    }

    // ================================================================
    // C) Multi-vector search tests
    // ================================================================

    @Test
    void testMultiVectorSimilarity_TwoVectors() {
        // Test: vg:multiVectorSimilarity with 2 vector triplets (7 args total)
        // Expected: ExprFunctionN with functionIRI and 7 args
        String sparql = """
            PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?entity ?score WHERE {
                ?entity rdf:type <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                BIND(vg:multiVectorSimilarity(
                    ?entity,
                    "technology company", "entity_type_default", 0.3,
                    "renewable energy manufacturing", "entity_default", 0.7
                ) AS ?score)
                FILTER(?score > 0.4)
            }
            ORDER BY DESC(?score)
            LIMIT 20
            """;
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        System.out.println("\n=== Multi-vector similarity (2 vectors, 7 args) ===");
        System.out.println("ok: " + resp.ok);
        if (resp.ok) {
            Map<String, Object> algebra = (Map<String, Object>) resp.phases.get("algebraCompiled");
            System.out.println("pretty: " + algebra.get("pretty"));
            try {
                String json = mapper.writerWithDefaultPrettyPrinter()
                        .writeValueAsString(algebra.get("op"));
                System.out.println("full op JSON:\n" + json);
            } catch (Exception e) {
                System.out.println("(could not serialize op)");
            }
        } else {
            System.out.println("error: " + resp.error);
        }
        assertTrue(resp.ok, "multiVectorSimilarity with 2 vectors should parse");
    }

    @Test
    void testMultiVectorSimilarity_ThreeVectors() {
        // Test: vg:multiVectorSimilarity with 3 vector triplets (10 args total)
        // Verifies ExprFunctionN handles arbitrary N correctly
        String sparql = """
            PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?entity ?score WHERE {
                ?entity rdf:type <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                BIND(vg:multiVectorSimilarity(
                    ?entity,
                    "technology company", "entity_type_default", 0.2,
                    "renewable energy", "entity_default", 0.5,
                    "silicon valley startup", "entity_description", 0.3
                ) AS ?score)
                FILTER(?score > 0.5)
            }
            ORDER BY DESC(?score)
            LIMIT 10
            """;
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        System.out.println("\n=== Multi-vector similarity (3 vectors, 10 args) ===");
        System.out.println("ok: " + resp.ok);
        if (resp.ok) {
            Map<String, Object> algebra = (Map<String, Object>) resp.phases.get("algebraCompiled");
            System.out.println("pretty: " + algebra.get("pretty"));
            try {
                String json = mapper.writerWithDefaultPrettyPrinter()
                        .writeValueAsString(algebra.get("op"));
                System.out.println("full op JSON:\n" + json);
            } catch (Exception e) {
                System.out.println("(could not serialize op)");
            }
        } else {
            System.out.println("error: " + resp.error);
        }
        assertTrue(resp.ok, "multiVectorSimilarity with 3 vectors should parse");
    }

    @Test
    void testMultiVectorNearby_PrecomputedVectors() {
        // Test: vg:multiVectorNearby with pre-computed vector literals
        String sparql = """
            PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?entity ?score WHERE {
                ?entity rdf:type <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                BIND(vg:multiVectorNearby(
                    ?entity,
                    "[0.1, 0.2, 0.3]", "entity_type_default", 0.4,
                    "[0.4, 0.5, 0.6, 0.7]", "entity_default", 0.6
                ) AS ?score)
            }
            ORDER BY DESC(?score)
            LIMIT 20
            """;
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        System.out.println("\n=== Multi-vector nearby (pre-computed vectors) ===");
        System.out.println("ok: " + resp.ok);
        if (resp.ok) {
            Map<String, Object> algebra = (Map<String, Object>) resp.phases.get("algebraCompiled");
            System.out.println("pretty: " + algebra.get("pretty"));
            try {
                String json = mapper.writerWithDefaultPrettyPrinter()
                        .writeValueAsString(algebra.get("op"));
                System.out.println("full op JSON:\n" + json);
            } catch (Exception e) {
                System.out.println("(could not serialize op)");
            }
        } else {
            System.out.println("error: " + resp.error);
        }
        assertTrue(resp.ok, "multiVectorNearby with pre-computed vectors should parse");
    }

    @Test
    void testMultiVectorSimilarity_CombinedWithOtherPatterns() {
        // Test: multiVectorSimilarity alongside regular triple patterns and other BINDs
        // Verifies it integrates cleanly in a real query context
        String sparql = """
            PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            SELECT ?entity ?name ?score WHERE {
                ?entity rdf:type <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                ?entity vital:hasName ?name .
                BIND(vg:multiVectorSimilarity(
                    ?entity,
                    "technology company", "entity_type_default", 0.3,
                    "renewable energy manufacturing", "entity_default", 0.7
                ) AS ?score)
                FILTER(?score > 0.4)
                FILTER(CONTAINS(?name, "Energy"))
            }
            ORDER BY DESC(?score)
            LIMIT 20
            """;
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        System.out.println("\n=== Multi-vector with triple patterns and filters ===");
        System.out.println("ok: " + resp.ok);
        if (resp.ok) {
            Map<String, Object> algebra = (Map<String, Object>) resp.phases.get("algebraCompiled");
            System.out.println("pretty: " + algebra.get("pretty"));
            try {
                String json = mapper.writerWithDefaultPrettyPrinter()
                        .writeValueAsString(algebra.get("op"));
                System.out.println("full op JSON:\n" + json);
            } catch (Exception e) {
                System.out.println("(could not serialize op)");
            }
        } else {
            System.out.println("error: " + resp.error);
        }
        assertTrue(resp.ok, "multiVectorSimilarity combined with other patterns should parse");
    }
}
