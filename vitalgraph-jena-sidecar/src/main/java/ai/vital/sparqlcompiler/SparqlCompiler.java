package ai.vital.sparqlcompiler;

import ai.vital.sparqlcompiler.serializer.*;
import ai.vital.sparqlcompiler.util.QueryMetadataExtractor;
import ai.vital.sparqlcompiler.util.TimingContext;
import org.apache.jena.query.Query;
import org.apache.jena.query.QueryException;
import org.apache.jena.query.QueryFactory;
import org.apache.jena.query.QueryParseException;
import org.apache.jena.query.Syntax;
import org.apache.jena.sparql.lang.SPARQLParser;
import org.apache.jena.graph.Node;
import org.apache.jena.graph.NodeFactory;
import org.apache.jena.irix.IRIs;
import org.apache.jena.irix.IRIx;
import org.apache.jena.sparql.graph.NodeTransform;
import org.apache.jena.sparql.syntax.syntaxtransform.QueryTransformOps;
import org.apache.jena.sparql.syntax.Element;
import org.apache.jena.sparql.syntax.ElementData;
import org.apache.jena.sparql.syntax.syntaxtransform.ElementTransform;
import org.apache.jena.sparql.syntax.syntaxtransform.ElementTransformSubst;
import org.apache.jena.sparql.syntax.syntaxtransform.ExprTransformNodeElement;
import org.apache.jena.sparql.core.Var;
import org.apache.jena.sparql.engine.binding.Binding;
import org.apache.jena.sparql.engine.binding.BindingBuilder;
import org.apache.jena.sparql.engine.binding.BindingFactory;
import org.apache.jena.sparql.expr.ExprTransform;
import org.apache.jena.sparql.expr.Expr;
import org.apache.jena.sparql.expr.ExprTransformer;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.regex.Pattern;
import org.apache.jena.sparql.core.Var;
import org.apache.jena.sparql.core.VarExprList;
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
            query = parseWithoutSystemBase(request.sparql);
            if (request.baseURI != null && !request.baseURI.isEmpty()) {
                query = resolveRelativeIris(query, request.baseURI);
            }
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
        } catch (QueryException qe) {
            // Jena raises grammar errors as QueryParseException, but throws a
            // bare QueryException for restrictions it checks AFTER the parse
            // succeeds -- `SELECT (1 AS ?X) (1 AS ?X)` gives "Duplicate variable
            // in result projection". Those escaped both catches and reached
            // App.java's blanket `catch (Exception)`, so a MALFORMED USER QUERY
            // came back as HTTP 500 / INTERNAL_ERROR.
            //
            // That is wrong twice over. It reports a caller error as a server
            // fault, which pages someone and pollutes error rates for input we
            // should simply reject; and it violates this project's rule that
            // domain outcomes return 200 with the outcome in the body, with
            // non-200 reserved for genuine server-level failures.
            //
            // No fallback to UpdateFactory here: reaching this catch means the
            // text DID parse as a query and was then rejected on its meaning,
            // so retrying it as an update would only replace a precise message
            // with a worse one. A QueryException carries no line or column,
            // hence the separate builder.
            timing.stop("parse");
            return buildSemanticError(qe, request.sparql, timing, trace);
        }
        timing.stop("parse");

        // Grammar restrictions Jena parses but SPARQL 1.1 forbids (issues/095).
        if ("QUERY".equals(sparqlForm)) {
            String violation = grammarViolation(query);
            if (violation != null) {
                return buildSemanticError(new QueryException(violation),
                                          request.sparql, timing, trace);
            }
        }

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

    /**
     * SPARQL 1.1 grammar restrictions that Jena accepts (issues/095).
     *
     * Over-acceptance is the mild direction of a syntax defect -- we answer
     * queries that should have been refused, rather than refusing valid ones --
     * with ONE exception, which is why this exists at all: `SELECT *` with
     * `GROUP BY` has NO DEFINED ANSWER. The spec forbids it precisely because
     * `*` cannot be resolved against a grouped solution, so whatever we return
     * is undefined behaviour rather than a documented extension, and two
     * engines that both accept it may still disagree.
     *
     * The projected-expression cases are milder but not cosmetic either: Jena
     * names the column with an internally allocated variable (`.0`, `.1`),
     * which is not a legal SPARQL variable name, so the caller receives a
     * result column they cannot refer to.
     *
     * Returns null when the query is fine. Deliberately NARROW -- this is a
     * slice of grammar enforcement Jena declines to do, and every rule here has
     * to earn its maintenance. `CONSTRUCT WHERE { GRAPH ... }` is knowingly not
     * checked: distinguishing the short form from the long one needs
     * syntax-level state Jena does not expose on Query, and the harm is a
     * template that behaves sensibly rather than an undefined answer.
     */
    static String grammarViolation(Query query) {
        if (query == null || !query.isSelectType()) {
            return null;
        }

        // SPARQL 1.1 §11.5 / grammar: SELECT * is not permitted with GROUP BY.
        if (query.isQueryResultStar() && query.hasGroupBy()) {
            return "SELECT * is not permitted with GROUP BY";
        }

        // A projected expression must be named: ( expr AS ?var ). Without AS,
        // Jena allocates an internal variable for it.
        VarExprList project = query.getProject();
        if (project != null) {
            for (Var var : project.getVars()) {
                if (var.isAllocVar() && project.hasExpr(var)) {
                    return "A projected expression must be named with AS "
                           + "(SELECT (expr AS ?var))";
                }
            }
        }
        return null;
    }

    private CompileResponse buildSemanticError(QueryException e, String sparql,
                                                TimingContext timing,
                                                CompileRequest.Trace trace) {
        // Reported as PARSE_ERROR, matching the grammar case: from a caller's
        // side both mean "this query was rejected, do not retry it", and
        // splitting them would make every client handle two codes for one
        // outcome. Line and column are omitted rather than faked -- Jena does
        // not carry a position on these, and a wrong caret is worse than none.
        CompileResponse response = CompileResponse.error("PARSE_ERROR",
                e.getMessage(), null, null, extractSnippet(sparql, 0));

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

    /**
     * Parse a query WITHOUT letting Jena invent a base IRI.
     *
     * {@code QueryFactory.create} substitutes {@code IRIs.getSystemBase()}
     * when no base is supplied, and that is the PROCESS WORKING DIRECTORY --
     * in this container, {@code file:///app/}. Two consequences, both bad:
     *
     * <ol>
     * <li>A relative IRI in a caller's query silently resolves against
     *     whatever directory the service happens to be run from.</li>
     * <li>Once ANY base is set, {@code QueryParserBase.resolveIRI} sends every
     *     IRI through {@code IRIx.resolve}, which applies RFC 3986
     *     {@code remove_dot_segments} even to an ABSOLUTE IRI. So
     *     {@code <eXAMPLE://a/./b/../b/c>} came back as
     *     {@code eXAMPLE://a/b/c} and could never match the term the data
     *     holds verbatim. SPARQL 1.1 resolves only RELATIVE IRIs against the
     *     base, and performs neither Syntax-Based nor Scheme-Based
     *     Normalization -- path-segment removal being the former,
     *     RFC 3986 section 6.2.2.3. See issues/132.</li>
     * </ol>
     *
     * Jena implements what we want, twice, and neither copy is reachable:
     * {@code IRI3986.strictResolver} is a hardcoded {@code false} and
     * {@code AlgResolveIRI.transformReferencesStrict} is private with no
     * callers. We cannot switch those on from outside a released artifact, so
     * we withhold the base instead -- {@code resolveIRI} returns the string
     * untouched when the prologue has none, leaving absolute IRIs intact and
     * relative ones still relative for the caller to resolve.
     *
     * A {@code BASE} written IN the query still behaves normally: the grammar
     * sets the prologue base as it parses and everything after it resolves.
     * That is a caller asking for resolution, which is not the same as us
     * inventing a base they never mentioned.
     */
    private static Query parseWithoutSystemBase(String sparql) {
        Query query = new Query();
        query.setSyntax(Syntax.defaultQuerySyntax);
        SPARQLParser parser = SPARQLParser.createParser(Syntax.defaultQuerySyntax);
        return parser.parse(query, sparql);
    }

    /** RFC 3986 scheme: ALPHA *( ALPHA / DIGIT / "+" / "-" / "." ) ":" */
    private static final Pattern HAS_SCHEME =
            Pattern.compile("^[A-Za-z][A-Za-z0-9+.-]*:");

    /**
     * Resolve the query's RELATIVE IRIs against {@code baseURI}, leaving
     * absolute ones exactly as written.
     *
     * This is the distinction Jena's parser cannot draw. Its base is a
     * parse-time switch: set one and EVERY IRI goes through RFC 3986
     * resolution, which strips dot-segments from absolute IRIs too. SPARQL
     * resolves only relative IRIs and performs neither Syntax-Based nor
     * Scheme-Based Normalization, so the two cases have to be separated, and
     * the only place to do that is after the parse.
     *
     * Callers used to get the same effect by prepending `BASE <...>` to the
     * query text. That works for relative IRIs and breaks absolute ones for
     * the reason above; it also shifts line numbers, so parse errors reported
     * positions that did not match what the caller sent.
     *
     * A `BASE` in the query still wins: it applies during the parse, so those
     * IRIs are already absolute here and carry a scheme, and are skipped.
     */
    private static Query resolveRelativeIris(Query query, String baseURI) {
        IRIx base = IRIs.resolveIRI(baseURI);
        NodeTransform nt = node -> {
            if (node == null || !node.isURI())
                return node;
            String resolved = resolveIfRelative(base, node.getURI());
            return resolved == null ? node : NodeFactory.createURI(resolved);
        };

        // VALUES data is NOT reached by a plain NodeTransform.
        // `ElementTransformSubst.transform(ElementData)` renames VARIABLES and
        // passes every VALUE through untouched -- it even short-circuits when
        // no variable changes, which is always the case for a transform that
        // rewrites IRIs. So `VALUES (?g) { (<empty.ttl>) }` kept a relative IRI
        // while every other position in the query resolved. Overriding it is
        // the only way to reach those nodes.
        //
        // Variables are left alone here deliberately: this transform only ever
        // rewrites URIs, so `nt.apply(var)` returns the var unchanged.
        ElementTransform eltrans = new ElementTransformSubst(nt) {
            @Override
            public ElementData transform(ElementData el) {
                ElementData copy = new ElementData();
                el.getVars().forEach(copy::add);
                Iterator<Binding> rows = el.getTable().rows();
                while (rows.hasNext())
                    copy.add(transformBinding(rows.next(), nt));
                return copy;
            }
        };
        ExprTransform exprTrans = new ExprTransformNodeElement(nt, eltrans);
        Query q2 = QueryTransformOps.transform(query, eltrans, exprTrans);

        // Repair HAVING. `QueryTransformOps.mutateExprList` has an index bug:
        //
        //     for (int i = 0; i < exprList.size(); i++) {
        //         Expr e1 = exprList.get(0);      // <- get(0), not get(i)
        //         ...
        //         exprList.set(i, e2);            // <- but writes at i
        //     }
        //
        // so every condition is overwritten with the transform of the FIRST
        // one. `HAVING (COUNT(*) > 1) (COUNT(*) < 3)` came back as
        // `(> (count) 1)` twice and the second condition stopped filtering.
        // It is the only caller of that method, and it only bites a query with
        // more than one HAVING condition -- which is why the transform looked
        // clean until agg-multiple-having ran.
        //
        // Redone here from the ORIGINAL list, at the right index.
        List<Expr> having = q2.getHavingExprs();
        List<Expr> havingBefore = query.getHavingExprs();
        if (having != null && havingBefore != null
                && having.size() == havingBefore.size()) {
            for (int i = 0; i < having.size(); i++) {
                Expr fixed = ExprTransformer.transform(exprTrans, havingBefore.get(i));
                having.set(i, fixed == null ? havingBefore.get(i) : fixed);
            }
        }

        // The top-level VALUES clause hangs off the Query, not the pattern.
        if (q2.hasValues()) {
            List<Binding> rows = new ArrayList<>();
            for (Binding b : q2.getValuesData())
                rows.add(transformBinding(b, nt));
            q2.setValuesDataBlock(q2.getValuesVariables(), rows);
        }

        // FROM / FROM NAMED are plain Strings on the Query, not Nodes, so the
        // NodeTransform above does not reach them. `shallowCopy` gave q2 its
        // own lists, so mutating them here is safe.
        resolveEach(base, q2.getGraphURIs());
        resolveEach(base, q2.getNamedGraphURIs());

        // DESCRIBE targets are Nodes but likewise live outside the pattern.
        java.util.List<Node> describeNodes = q2.getResultURIs();
        if (describeNodes != null)
            describeNodes.replaceAll(nt::apply);

        return q2;
    }

    /** A VALUES row with every node put through {@code nt}. */
    private static Binding transformBinding(Binding b, NodeTransform nt) {
        BindingBuilder out = BindingFactory.builder();
        Iterator<Var> vars = b.vars();
        while (vars.hasNext()) {
            Var v = vars.next();
            out.add(v, nt.apply(b.get(v)));
        }
        return out.build();
    }

    /** The resolved form, or null when the IRI is absolute and must not change. */
    private static String resolveIfRelative(IRIx base, String iri) {
        if (iri == null || iri.isEmpty())
            return null;
        // Jena carries blank nodes as `_:label` IRIs in some positions; those
        // are not relative references and resolving one would invent a node.
        if (iri.startsWith("_:"))
            return null;
        if (HAS_SCHEME.matcher(iri).find())
            return null;
        try {
            return base.resolve(iri).toString();
        } catch (Exception e) {
            // An IRI we cannot resolve is left as written rather than
            // replaced with a guess; the term simply will not match.
            return null;
        }
    }

    private static void resolveEach(IRIx base, java.util.List<String> uris) {
        if (uris == null)
            return;
        uris.replaceAll(u -> {
            String r = resolveIfRelative(base, u);
            return r == null ? u : r;
        });
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
