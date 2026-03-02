package ai.vital.sparqlcompiler;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class SparqlUpdateCompilerTest {

    private static SparqlCompiler compiler;

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
        req.phases.updateOperations = true;
        req.trace = new CompileRequest.Trace();
        req.trace.includeTiming = true;
        req.trace.includeWarnings = true;
        req.trace.includePretty = true;
        req.optimize = new CompileRequest.Optimize();
        return req;
    }

    @Test
    void testInsertData() {
        String sparql = "INSERT DATA { <http://ex.org/s1> <http://ex.org/p1> \"hello\" }";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
        Map<String, Object> pq = (Map<String, Object>) resp.phases.get("parsedQuery");
        assertEquals("UPDATE", pq.get("sparqlForm"));
        assertEquals(1, ((Number) pq.get("operationCount")).intValue());

        List<Map<String, Object>> ops = (List<Map<String, Object>>) resp.phases.get("updateOperations");
        assertNotNull(ops);
        assertEquals(1, ops.size());
        assertEquals("UpdateDataInsert", ops.get(0).get("type"));

        List<Map<String, Object>> quads = (List<Map<String, Object>>) ops.get(0).get("quads");
        assertFalse(quads.isEmpty());
        Map<String, Object> quad = quads.get(0);
        Map<String, Object> subject = (Map<String, Object>) quad.get("subject");
        assertEquals("uri", subject.get("type"));
        assertEquals("http://ex.org/s1", subject.get("value"));
    }

    @Test
    void testDeleteData() {
        String sparql = "DELETE DATA { <http://ex.org/s1> <http://ex.org/p1> \"hello\" }";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
        List<Map<String, Object>> ops = (List<Map<String, Object>>) resp.phases.get("updateOperations");
        assertEquals("UpdateDataDelete", ops.get(0).get("type"));
    }

    @Test
    void testDeleteInsertWhere() {
        String sparql = "DELETE { ?s <http://ex.org/old> ?o } INSERT { ?s <http://ex.org/new> ?o } WHERE { ?s <http://ex.org/old> ?o }";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
        List<Map<String, Object>> ops = (List<Map<String, Object>>) resp.phases.get("updateOperations");
        assertEquals(1, ops.size());
        Map<String, Object> op = ops.get(0);
        assertEquals("UpdateModify", op.get("type"));

        List<Map<String, Object>> deleteQuads = (List<Map<String, Object>>) op.get("deleteQuads");
        assertFalse(deleteQuads.isEmpty());

        List<Map<String, Object>> insertQuads = (List<Map<String, Object>>) op.get("insertQuads");
        assertFalse(insertQuads.isEmpty());

        assertNotNull(op.get("wherePattern"));
    }

    @Test
    void testInsertDataIntoGraph() {
        String sparql = "INSERT DATA { GRAPH <http://ex.org/graph1> { <http://ex.org/s1> <http://ex.org/p1> \"hello\" } }";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
        List<Map<String, Object>> ops = (List<Map<String, Object>>) resp.phases.get("updateOperations");
        assertEquals("UpdateDataInsert", ops.get(0).get("type"));
        List<Map<String, Object>> quads = (List<Map<String, Object>>) ops.get(0).get("quads");
        Map<String, Object> quad = quads.get(0);
        Map<String, Object> graph = (Map<String, Object>) quad.get("graph");
        assertNotNull(graph);
        assertEquals("http://ex.org/graph1", graph.get("value"));
    }

    @Test
    void testLoad() {
        String sparql = "LOAD <http://example.org/data.ttl> INTO GRAPH <http://ex.org/graph1>";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
        List<Map<String, Object>> ops = (List<Map<String, Object>>) resp.phases.get("updateOperations");
        Map<String, Object> op = ops.get(0);
        assertEquals("UpdateLoad", op.get("type"));
        assertEquals("http://example.org/data.ttl", op.get("source"));
        assertEquals("http://ex.org/graph1", op.get("destGraph"));
    }

    @Test
    void testLoadSilent() {
        String sparql = "LOAD SILENT <http://example.org/data.ttl>";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
        List<Map<String, Object>> ops = (List<Map<String, Object>>) resp.phases.get("updateOperations");
        Map<String, Object> op = ops.get(0);
        assertEquals("UpdateLoad", op.get("type"));
        assertTrue((Boolean) op.get("silent"));
    }

    @Test
    void testClearGraph() {
        String sparql = "CLEAR GRAPH <http://ex.org/graph1>";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
        List<Map<String, Object>> ops = (List<Map<String, Object>>) resp.phases.get("updateOperations");
        Map<String, Object> op = ops.get(0);
        assertEquals("UpdateClear", op.get("type"));
        Map<String, Object> target = (Map<String, Object>) op.get("target");
        assertEquals("GRAPH", target.get("scope"));
        assertEquals("http://ex.org/graph1", target.get("graph"));
    }

    @Test
    void testClearAll() {
        String sparql = "CLEAR ALL";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
        List<Map<String, Object>> ops = (List<Map<String, Object>>) resp.phases.get("updateOperations");
        Map<String, Object> op = ops.get(0);
        assertEquals("UpdateClear", op.get("type"));
        Map<String, Object> target = (Map<String, Object>) op.get("target");
        assertEquals("ALL", target.get("scope"));
    }

    @Test
    void testDropGraph() {
        String sparql = "DROP SILENT GRAPH <http://ex.org/graph1>";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
        List<Map<String, Object>> ops = (List<Map<String, Object>>) resp.phases.get("updateOperations");
        Map<String, Object> op = ops.get(0);
        assertEquals("UpdateDrop", op.get("type"));
        assertTrue((Boolean) op.get("silent"));
    }

    @Test
    void testCreateGraph() {
        String sparql = "CREATE GRAPH <http://ex.org/newgraph>";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
        List<Map<String, Object>> ops = (List<Map<String, Object>>) resp.phases.get("updateOperations");
        Map<String, Object> op = ops.get(0);
        assertEquals("UpdateCreate", op.get("type"));
        assertEquals("http://ex.org/newgraph", op.get("graph"));
    }

    @Test
    void testCopyGraph() {
        String sparql = "COPY <http://ex.org/src> TO <http://ex.org/dest>";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
        List<Map<String, Object>> ops = (List<Map<String, Object>>) resp.phases.get("updateOperations");
        Map<String, Object> op = ops.get(0);
        assertEquals("UpdateCopy", op.get("type"));
    }

    @Test
    void testMoveGraph() {
        String sparql = "MOVE <http://ex.org/src> TO <http://ex.org/dest>";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
        List<Map<String, Object>> ops = (List<Map<String, Object>>) resp.phases.get("updateOperations");
        Map<String, Object> op = ops.get(0);
        assertEquals("UpdateMove", op.get("type"));
    }

    @Test
    void testAddGraph() {
        String sparql = "ADD <http://ex.org/src> TO <http://ex.org/dest>";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
        List<Map<String, Object>> ops = (List<Map<String, Object>>) resp.phases.get("updateOperations");
        Map<String, Object> op = ops.get(0);
        assertEquals("UpdateAdd", op.get("type"));
    }

    @Test
    void testMultipleOperations() {
        String sparql = "INSERT DATA { <http://ex.org/s1> <http://ex.org/p> \"a\" } ; DELETE DATA { <http://ex.org/s2> <http://ex.org/p> \"b\" }";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
        Map<String, Object> pq = (Map<String, Object>) resp.phases.get("parsedQuery");
        assertEquals(2, ((Number) pq.get("operationCount")).intValue());

        List<Map<String, Object>> ops = (List<Map<String, Object>>) resp.phases.get("updateOperations");
        assertEquals(2, ops.size());
        assertEquals("UpdateDataInsert", ops.get(0).get("type"));
        assertEquals("UpdateDataDelete", ops.get(1).get("type"));
    }

    @Test
    void testDeleteInsertWithUsing() {
        String sparql = "WITH <http://ex.org/graph1> DELETE { ?s <http://ex.org/old> ?o } INSERT { ?s <http://ex.org/new> ?o } WHERE { ?s <http://ex.org/old> ?o }";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
        List<Map<String, Object>> ops = (List<Map<String, Object>>) resp.phases.get("updateOperations");
        Map<String, Object> op = ops.get(0);
        assertEquals("UpdateModify", op.get("type"));
        Map<String, Object> withGraph = (Map<String, Object>) op.get("withGraph");
        assertNotNull(withGraph);
        assertEquals("http://ex.org/graph1", withGraph.get("value"));
    }

    @Test
    void testUpdateAlgebraIsNull() {
        String sparql = "INSERT DATA { <http://ex.org/s> <http://ex.org/p> \"v\" }";
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        assertTrue(resp.ok);
        // Algebra phases should be null for updates
        assertNull(resp.phases.get("syntaxTree"));
        assertNull(resp.phases.get("algebraCompiled"));
        assertNull(resp.phases.get("algebraOptimized"));
    }
}
