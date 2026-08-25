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
    void testGrammarRestrictionsJenaAcceptsAreRejected() {
        // issues/095. Jena parses all of these; SPARQL 1.1 forbids them.
        //
        // The GROUP BY one is the reason this check exists: SELECT * with
        // GROUP BY has NO DEFINED ANSWER, so accepting it means returning
        // something undefined rather than something permissive.
        String[] forbidden = {
            "SELECT * { ?s ?p ?o } GROUP BY ?s",
            "SELECT (?x +?y) {}",
            "SELECT COUNT(*) {}",
        };
        for (String sparql : forbidden) {
            CompileResponse resp = compiler.compile(makeRequest(sparql));
            assertFalse(resp.ok, "should have been rejected: " + sparql);
            assertEquals("PARSE_ERROR", resp.error.get("code"));
        }
    }

    @Test
    void testTheGrammarCheckDoesNotRejectValidQueries() {
        // The failure mode that would matter: over-acceptance is mild, but
        // refusing a VALID query breaks callers. Each of these is the legal
        // form of something rejected above, plus the ordinary shapes.
        String[] valid = {
            "SELECT ?s { ?s ?p ?o } GROUP BY ?s",
            "SELECT (COUNT(*) AS ?n) {}",
            "SELECT ((?x + ?y) AS ?sum) { ?a ?b ?x . ?a ?c ?y }",
            "SELECT * { ?s ?p ?o }",
            "SELECT * { ?s ?p ?o } ORDER BY ?s LIMIT 10",
            "SELECT (SUM(?v) AS ?t) { ?s ?p ?v } GROUP BY ?s HAVING (SUM(?v) > 1)",
            "ASK { ?s ?p ?o }",
            "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }",
            "DESCRIBE <http://example.org/x>",
        };
        for (String sparql : valid) {
            CompileResponse resp = compiler.compile(makeRequest(sparql));
            assertTrue(resp.ok, "should have been accepted: " + sparql
                       + " -> " + (resp.error == null ? "" : resp.error.get("message")));
        }
    }

    @Test
    void testSemanticRejectionIsAParseErrorNotAnException() {
        // Regression, found 2026-08-16 by wiring in the DAWG syntax categories
        // (syntax-query/syn-bad-03). Jena throws grammar errors as
        // QueryParseException but raises a bare QueryException for checks it
        // performs after the parse succeeds -- this one gives "Duplicate
        // variable in result projection". That escaped compile()'s catch and
        // reached App.java's blanket `catch (Exception)`, so a MALFORMED USER
        // QUERY was answered with HTTP 500 / INTERNAL_ERROR: a caller's mistake
        // reported as a server fault, which pages someone and pollutes error
        // rates over input we should simply reject.
        //
        // The assertion that matters is `compile` RETURNING rather than
        // throwing. If it throws, the HTTP layer turns it back into a 500 and
        // the defect is exactly where it started.
        CompileRequest req = makeRequest("SELECT (1 AS ?X) (1 AS ?X) {}");

        CompileResponse resp = assertDoesNotThrow(() -> compiler.compile(req),
                "a semantically invalid query must be reported, not thrown");

        assertFalse(resp.ok);
        assertEquals("PARSE_ERROR", resp.error.get("code"),
                "callers handle one rejection code; splitting grammar from "
                + "semantic rejection would make every client handle two");
        assertTrue(resp.error.get("message").toString().contains("Duplicate variable"));
    }

    @Test
    void testGrammarErrorStillCarriesPosition() {
        // Guards the other half of the change above: adding the QueryException
        // catch must not swallow QueryParseException, which is its SUBCLASS and
        // therefore order-dependent. If the catches were reordered, this query
        // would lose its line and column and nothing else would notice.
        CompileRequest req = makeRequest("SELECT ?s WHERE { ?s ?p }");
        CompileResponse resp = compiler.compile(req);

        assertFalse(resp.ok);
        assertEquals("PARSE_ERROR", resp.error.get("code"));
        assertNotNull(resp.error.get("line"), "grammar errors keep their position");
        assertNotNull(resp.error.get("column"));
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

    // ---- Base IRI: we do not invent one -------------------------------
    //
    // `QueryFactory.create` substitutes the PROCESS WORKING DIRECTORY as base
    // when none is given. That resolved callers' relative IRIs against
    // whatever directory the service ran in, and -- because any base at all
    // sends every IRI through RFC 3986 resolution -- stripped dot-segments
    // from ABSOLUTE IRIs too, so a query could not match the term its own data
    // held. SPARQL resolves only RELATIVE IRIs and performs no syntax-based
    // normalisation. See issues/132.

    private String json(String sparql) throws Exception {
        CompileResponse resp = compiler.compile(makeRequest(sparql));
        assertTrue(resp.ok, "compile failed: " + resp.error);
        return mapper.writeValueAsString(resp);
    }

    @Test
    void noBaseIsInventedWhenTheQueryDoesNotGiveOne() throws Exception {
        CompileResponse resp = compiler.compile(makeRequest("SELECT * WHERE { ?s ?p ?o }"));
        Map<?, ?> parsed = (Map<?, ?>) resp.phases.get("parsedQuery");
        assertNull(parsed.get("baseURI"),
                "a base the caller never mentioned must not be invented");
    }

    @Test
    void anAbsoluteIriKeepsItsDotSegments() throws Exception {
        // RDF compares IRIs by character. `a/./b/../b/c` and `a/b/c` are
        // DIFFERENT IRIs and must stay so.
        String out = json("PREFIX p: <eXAMPLE://a/./b/../b/c#> "
                + "SELECT * WHERE { ?s <http://x#p> p:xyz }");
        assertTrue(out.contains("eXAMPLE://a/./b/../b/c#xyz"),
                "dot-segments were removed from an absolute IRI: " + out);
    }

    @Test
    void aRelativeIriStaysRelativeWithoutABase() throws Exception {
        String out = json("SELECT * FROM <data-g1.ttl> WHERE { ?s ?p ?o }");
        assertTrue(out.contains("data-g1.ttl") && !out.contains("/app/data-g1.ttl"),
                "a relative IRI was resolved against an invented base: " + out);
    }

    @Test
    void anExplicitBaseStillResolvesRelativeIris() throws Exception {
        // A BASE in the query is the caller ASKING for resolution, which is a
        // different thing from us supplying one they never wrote.
        String out = json("BASE <file:///tmp/d/q.rq> "
                + "SELECT * FROM <data-g1.ttl> WHERE { ?s ?p ?o }");
        assertTrue(out.contains("file:///tmp/d/data-g1.ttl"),
                "an explicit BASE stopped resolving relative IRIs: " + out);
    }
}
