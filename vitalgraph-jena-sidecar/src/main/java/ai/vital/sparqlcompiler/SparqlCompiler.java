package ai.vital.sparqlcompiler;

import ai.vital.sparqlcompiler.serializer.*;
import ai.vital.sparqlcompiler.util.QueryMetadataExtractor;
import ai.vital.sparqlcompiler.util.TimingContext;
import org.apache.jena.query.Query;
import org.apache.jena.query.QueryFactory;
import org.apache.jena.query.QueryParseException;
import org.apache.jena.sparql.algebra.Algebra;
import org.apache.jena.sparql.algebra.Op;
import org.apache.jena.sparql.syntax.Element;
import org.apache.jena.update.UpdateFactory;
import org.apache.jena.update.UpdateRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Map;

public class SparqlCompiler {

    public static final String SERVICE_VERSION = "1.0.0";

    private static final Logger log = LoggerFactory.getLogger(SparqlCompiler.class);
    private final int requestTimeoutMs;

    public SparqlCompiler(int requestTimeoutMs) {
        this.requestTimeoutMs = requestTimeoutMs;
    }

    public CompileResponse compile(CompileRequest request) {
        CompileRequest.Phases phases = request.getPhases();
        CompileRequest.Optimize optimize = request.getOptimize();
        CompileRequest.Trace trace = request.getTrace();
        TimingContext timing = new TimingContext();

        String sparqlHash = computeHash(request.sparql);

        // Try parsing as a query first, then as an update
        Query query = null;
        UpdateRequest updateRequest = null;
        String sparqlForm;

        timing.start("parse");
        try {
            query = QueryFactory.create(request.sparql);
            sparqlForm = "QUERY";
        } catch (QueryParseException qpe) {
            try {
                updateRequest = UpdateFactory.create(request.sparql);
                sparqlForm = "UPDATE";
            } catch (Exception upe) {
                timing.stop("parse");
                // Return the query parse error since it's usually more informative
                return buildParseError(qpe, request.sparql, timing, trace);
            }
        }
        timing.stop("parse");

        CompileResponse response = CompileResponse.success();
        response.input = new LinkedHashMap<>();
        response.input.put("sparqlHash", "sha256:" + sparqlHash);

        if ("QUERY".equals(sparqlForm)) {
            compileQuery(query, response, phases, optimize, trace, timing);
        } else {
            compileUpdate(updateRequest, response, phases, trace, timing);
        }

        if (trace.includeTiming) {
            response.setTiming(timing.getTimings());
        }

        return response;
    }

    private void compileQuery(Query query, CompileResponse response,
                               CompileRequest.Phases phases,
                               CompileRequest.Optimize optimize,
                               CompileRequest.Trace trace,
                               TimingContext timing) {

        // Phase: parsedQuery
        if (phases.parsedQuery) {
            Map<String, Object> meta = QueryMetadataExtractor.extract(query);
            meta.put("sparqlForm", "QUERY");
            response.phases.put("parsedQuery", meta);
        }

        // Phase: syntaxTree
        if (phases.syntaxTree) {
            timing.start("syntaxTree");
            Element wherePattern = query.getQueryPattern();
            if (wherePattern != null) {
                Map<String, Object> tree = new LinkedHashMap<>();
                tree.put("wherePattern", ElementSerializer.serialize(wherePattern));
                response.phases.put("syntaxTree", tree);
            } else {
                response.phases.put("syntaxTree", null);
            }
            timing.stop("syntaxTree");
        }

        // Phase: algebraCompiled
        if (phases.algebraCompiled) {
            timing.start("compile");
            Op op = Algebra.compile(query);
            timing.stop("compile");

            timing.start("serialize");
            Map<String, Object> algebraResult = new LinkedHashMap<>();
            algebraResult.put("op", OpSerializer.serialize(op));
            if (trace.includePretty) {
                algebraResult.put("pretty", OpSerializer.prettyPrint(op));
            }
            response.phases.put("algebraCompiled", algebraResult);
            timing.stop("serialize");
        }

        // Phase: algebraOptimized
        if (phases.algebraOptimized && optimize.enabled) {
            timing.start("optimize");
            Op op = Algebra.compile(query);
            Op optimized = Algebra.optimize(op);
            timing.stop("optimize");

            Map<String, Object> algebraResult = new LinkedHashMap<>();
            algebraResult.put("op", OpSerializer.serialize(optimized));
            if (trace.includePretty) {
                algebraResult.put("pretty", OpSerializer.prettyPrint(optimized));
            }
            response.phases.put("algebraOptimized", algebraResult);
        } else {
            response.phases.put("algebraOptimized", null);
        }

        // Phase: normalizedSparql
        if (phases.normalizedSparql) {
            response.phases.put("normalizedSparql", query.serialize());
        } else {
            response.phases.put("normalizedSparql", null);
        }

        // updateOperations is null for queries
        response.phases.put("updateOperations", null);
    }

    private void compileUpdate(UpdateRequest updateRequest, CompileResponse response,
                                CompileRequest.Phases phases,
                                CompileRequest.Trace trace,
                                TimingContext timing) {

        // Phase: parsedQuery (basic metadata for updates)
        if (phases.parsedQuery) {
            Map<String, Object> meta = new LinkedHashMap<>();
            meta.put("sparqlForm", "UPDATE");
            meta.put("operationCount", updateRequest.getOperations().size());
            response.phases.put("parsedQuery", meta);
        }

        // syntaxTree and algebra phases are not applicable to updates
        response.phases.put("syntaxTree", null);
        response.phases.put("algebraCompiled", null);
        response.phases.put("algebraOptimized", null);
        response.phases.put("normalizedSparql", null);

        // Phase: updateOperations
        if (phases.updateOperations) {
            timing.start("serialize");
            response.phases.put("updateOperations",
                    UpdateSerializer.serialize(updateRequest, trace.includePretty));
            timing.stop("serialize");
        }
    }

    private CompileResponse buildParseError(QueryParseException e, String sparql,
                                             TimingContext timing,
                                             CompileRequest.Trace trace) {
        int line = e.getLine();
        int column = e.getColumn();
        String snippet = extractSnippet(sparql, line);

        CompileResponse response = CompileResponse.error("PARSE_ERROR",
                e.getMessage(), line > 0 ? line : null,
                column > 0 ? column : null, snippet);

        if (trace.includeTiming) {
            response.setTiming(timing.getTimings());
        }

        return response;
    }

    private String extractSnippet(String sparql, int line) {
        if (line <= 0) {
            return sparql.length() > 80 ? sparql.substring(0, 80) + "..." : sparql;
        }
        String[] lines = sparql.split("\n");
        if (line <= lines.length) {
            String l = lines[line - 1];
            return l.length() > 80 ? l.substring(0, 80) + "..." : l;
        }
        return null;
    }

    private String computeHash(String sparql) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] hash = digest.digest(sparql.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(hash);
        } catch (Exception e) {
            return "error";
        }
    }
}
