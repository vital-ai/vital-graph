package ai.vital.sparqlcompiler;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

@JsonIgnoreProperties(ignoreUnknown = true)
public class CompileRequest {

    public String sparql;

    /**
     * Base for resolving RELATIVE IRIs in the query. Optional.
     *
     * Absolute IRIs are never touched by it: SPARQL resolves only relative
     * IRIs and performs no syntax-based normalisation, so `<eXAMPLE://a/./b>`
     * must reach the caller with its dot-segments intact. See issues/132 and
     * planning/planning_sparql_features/iri_resolution.md.
     *
     * A `BASE` written IN the query wins -- it is applied during the parse, so
     * those IRIs are already absolute by the time this base is considered.
     */
    public String baseURI;
    public Phases phases;
    public Optimize optimize;
    public Trace trace;

    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class Phases {
        public boolean parsedQuery = true;
        public boolean syntaxTree = false;
        public boolean algebraCompiled = true;
        public boolean algebraOptimized = false;
        public boolean normalizedSparql = false;
        public boolean updateOperations = true;
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class Optimize {
        public boolean enabled = false;
        public boolean enableJoinReorder = false;
        public boolean enableFilterPushdown = true;
        public boolean enableExprSimplify = true;
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class Trace {
        public boolean includeTiming = true;
        public boolean includeWarnings = true;
        public boolean includePretty = true;
    }

    public Phases getPhases() {
        return phases != null ? phases : new Phases();
    }

    public Optimize getOptimize() {
        return optimize != null ? optimize : new Optimize();
    }

    public Trace getTrace() {
        return trace != null ? trace : new Trace();
    }
}
