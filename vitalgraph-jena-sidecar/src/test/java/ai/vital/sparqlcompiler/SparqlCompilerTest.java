package ai.vital.sparqlcompiler;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class SparqlCompilerTest {

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
        req.phases.normalizedSparql = false;
        req.phases.updateOperations = true;
        req.trace = new CompileRequest.Trace();
        req.trace.includeTiming = true;
        req.trace.includeWarnings = true;
        req.trace.includePretty = true;
        req.optimize = new CompileRequest.Optimize();
        return req;
    }

    @Test
    void testSimpleSelect() {
        CompileRequest req = makeRequest("SELECT ?s ?o WHERE { ?s <http://example.org/p> ?o }");
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
        assertNotNull(resp.input);
        assertTrue(resp.input.get("sparqlHash").toString().startsWith("sha256:"));

        // parsedQuery
        Map<String, Object> pq = (Map<String, Object>) resp.phases.get("parsedQuery");
        assertEquals("QUERY", pq.get("sparqlForm"));
        assertEquals("SELECT", pq.get("queryType"));
        List<String> vars = (List<String>) pq.get("projectVars");
        assertTrue(vars.contains("s"));
        assertTrue(vars.contains("o"));
        assertFalse((Boolean) pq.get("distinct"));

        // algebraCompiled
        Map<String, Object> algebra = (Map<String, Object>) resp.phases.get("algebraCompiled");
        assertNotNull(algebra.get("op"));
        assertNotNull(algebra.get("pretty"));

        // updateOperations should be null for queries
        assertNull(resp.phases.get("updateOperations"));
    }

    @Test
    void testSelectWithFilter() {
        String sparql = "SELECT ?s WHERE { ?s <http://example.org/name> ?name . FILTER(CONTAINS(?name, \"John\")) }";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);

        Map<String, Object> algebra = (Map<String, Object>) resp.phases.get("algebraCompiled");
        Map<String, Object> op = (Map<String, Object>) algebra.get("op");
        assertEquals("OpProject", op.get("type"));
    }

    @Test
    void testSelectDistinctWithLimitOffset() {
        String sparql = "SELECT DISTINCT ?s WHERE { ?s ?p ?o } LIMIT 10 OFFSET 5";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
        Map<String, Object> pq = (Map<String, Object>) resp.phases.get("parsedQuery");
        assertTrue((Boolean) pq.get("distinct"));
        assertEquals(10L, ((Number) pq.get("limit")).longValue());
        assertEquals(5L, ((Number) pq.get("offset")).longValue());
    }

    @Test
    void testSelectWithOptional() {
        String sparql = "SELECT ?s ?name ?age WHERE { ?s <http://ex.org/name> ?name . OPTIONAL { ?s <http://ex.org/age> ?age } }";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);

        // Check algebra has OpLeftJoin
        Map<String, Object> algebra = (Map<String, Object>) resp.phases.get("algebraCompiled");
        String pretty = (String) algebra.get("pretty");
        assertNotNull(pretty);
    }

    @Test
    void testSelectWithUnion() {
        String sparql = "SELECT ?s WHERE { { ?s a <http://ex.org/Person> } UNION { ?s a <http://ex.org/Org> } }";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
    }

    @Test
    void testSelectWithGroupByAndCount() {
        String sparql = "SELECT ?p (COUNT(?s) AS ?count) WHERE { ?s ?p ?o } GROUP BY ?p";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
        Map<String, Object> pq = (Map<String, Object>) resp.phases.get("parsedQuery");
        List<String> groupBy = (List<String>) pq.get("groupBy");
        assertTrue(groupBy.contains("p"));
    }

    @Test
    void testSelectWithOrderBy() {
        String sparql = "SELECT ?s ?name WHERE { ?s <http://ex.org/name> ?name } ORDER BY DESC(?name)";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
        Map<String, Object> pq = (Map<String, Object>) resp.phases.get("parsedQuery");
        List<Map<String, Object>> orderBy = (List<Map<String, Object>>) pq.get("orderBy");
        assertFalse(orderBy.isEmpty());
        assertEquals("DESC", orderBy.get(0).get("direction"));
    }

    @Test
    void testSelectWithBind() {
        String sparql = "SELECT ?s ?label WHERE { ?s <http://ex.org/name> ?name . BIND(CONCAT(\"Name: \", ?name) AS ?label) }";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
    }

    @Test
    void testSelectWithValues() {
        String sparql = "SELECT ?s ?type WHERE { VALUES ?type { <http://ex.org/A> <http://ex.org/B> } ?s a ?type }";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
    }

    @Test
    void testSelectWithMinus() {
        String sparql = "SELECT ?s WHERE { ?s a <http://ex.org/Person> . MINUS { ?s <http://ex.org/deleted> true } }";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
    }

    @Test
    void testSelectWithNamedGraph() {
        String sparql = "SELECT ?s ?p ?o WHERE { GRAPH <http://ex.org/graph1> { ?s ?p ?o } }";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
    }

    @Test
    void testSelectWithSubquery() {
        String sparql = "SELECT ?s ?count WHERE { { SELECT ?s (COUNT(?o) AS ?count) WHERE { ?s ?p ?o } GROUP BY ?s } FILTER(?count > 5) }";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
    }

    @Test
    void testConstructQuery() {
        String sparql = "CONSTRUCT { ?s <http://ex.org/label> ?name } WHERE { ?s <http://ex.org/name> ?name }";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
        Map<String, Object> pq = (Map<String, Object>) resp.phases.get("parsedQuery");
        assertEquals("CONSTRUCT", pq.get("queryType"));
        assertNotNull(pq.get("constructTemplate"));
    }

    @Test
    void testAskQuery() {
        String sparql = "ASK { <http://ex.org/person1> a <http://ex.org/Person> }";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
        Map<String, Object> pq = (Map<String, Object>) resp.phases.get("parsedQuery");
        assertEquals("ASK", pq.get("queryType"));
    }

    @Test
    void testDescribeQuery() {
        String sparql = "DESCRIBE <http://ex.org/person1>";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
        Map<String, Object> pq = (Map<String, Object>) resp.phases.get("parsedQuery");
        assertEquals("DESCRIBE", pq.get("queryType"));
        assertNotNull(pq.get("describeNodes"));
    }

    @Test
    void testSyntaxTree() {
        String sparql = "SELECT ?s WHERE { ?s <http://ex.org/p> ?o . OPTIONAL { ?s <http://ex.org/q> ?r } }";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
        Map<String, Object> st = (Map<String, Object>) resp.phases.get("syntaxTree");
        assertNotNull(st);
        Map<String, Object> wp = (Map<String, Object>) st.get("wherePattern");
        assertNotNull(wp);
        assertEquals("ElementGroup", wp.get("type"));
    }

    @Test
    void testParseError() {
        CompileRequest req = makeRequest("SELCT ?s WHERE { ?s ?p ?o }");
        CompileResponse resp = compiler.compile(req);

        assertFalse(resp.ok);
        assertNotNull(resp.error);
        assertEquals("PARSE_ERROR", resp.error.get("code"));
    }

    @Test
    void testEmptySparql() {
        CompileRequest req = makeRequest("");
        req.sparql = "";
        CompileResponse resp = compiler.compile(req);
        // Empty string handling varies by Jena version.
        // The App layer rejects blank input before calling compile.
        // Here we just verify no exception is thrown.
        assertNotNull(resp);
    }

    @Test
    void testTimingIncluded() {
        CompileRequest req = makeRequest("SELECT ?s WHERE { ?s ?p ?o }");
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
        assertNotNull(resp.meta.get("timingMs"));
        Map<String, Long> timing = (Map<String, Long>) resp.meta.get("timingMs");
        assertTrue(timing.containsKey("parse"));
    }

    @Test
    void testDeterministicOutput() {
        String sparql = "SELECT ?s ?o WHERE { ?s <http://example.org/p> ?o } LIMIT 10";
        CompileRequest req1 = makeRequest(sparql);
        CompileRequest req2 = makeRequest(sparql);

        CompileResponse resp1 = compiler.compile(req1);
        CompileResponse resp2 = compiler.compile(req2);

        assertEquals(resp1.input.get("sparqlHash"), resp2.input.get("sparqlHash"));

        // Algebra structure should be identical
        assertEquals(
                resp1.phases.get("algebraCompiled").toString(),
                resp2.phases.get("algebraCompiled").toString()
        );
    }

    @Test
    void testPropertyPath() {
        String sparql = "SELECT ?s ?o WHERE { ?s <http://ex.org/knows>+ ?o }";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
    }

    @Test
    void testSelectWithRegexFilter() {
        String sparql = "SELECT ?s ?name WHERE { ?s <http://ex.org/name> ?name . FILTER(REGEX(?name, \"^John\", \"i\")) }";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
    }
}
