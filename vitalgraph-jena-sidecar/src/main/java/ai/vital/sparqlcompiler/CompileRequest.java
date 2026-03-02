package ai.vital.sparqlcompiler;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

@JsonIgnoreProperties(ignoreUnknown = true)
public class CompileRequest {

    public String sparql;
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
