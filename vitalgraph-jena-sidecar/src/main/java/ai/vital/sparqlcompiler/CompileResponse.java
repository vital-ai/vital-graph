package ai.vital.sparqlcompiler;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class CompileResponse {

    public boolean ok;
    public Map<String, Object> meta;
    public Map<String, Object> input;
    public Map<String, Object> phases;
    public Map<String, Object> error;
    public List<String> warnings;

    public CompileResponse() {
        this.warnings = new ArrayList<>();
    }

    public static CompileResponse success() {
        CompileResponse r = new CompileResponse();
        r.ok = true;
        r.meta = new LinkedHashMap<>();
        r.meta.put("serviceVersion", SparqlCompiler.SERVICE_VERSION);
        r.meta.put("jenaVersion", org.apache.jena.Jena.VERSION);
        r.phases = new LinkedHashMap<>();
        return r;
    }

    public static CompileResponse error(String code, String message,
                                         Integer line, Integer column, String snippet) {
        CompileResponse r = new CompileResponse();
        r.ok = false;
        r.meta = new LinkedHashMap<>();
        r.meta.put("serviceVersion", SparqlCompiler.SERVICE_VERSION);
        r.meta.put("jenaVersion", org.apache.jena.Jena.VERSION);
        r.error = new LinkedHashMap<>();
        r.error.put("code", code);
        r.error.put("message", message);
        if (line != null) r.error.put("line", line);
        if (column != null) r.error.put("column", column);
        if (snippet != null) r.error.put("snippet", snippet);
        return r;
    }

    public void setTiming(Map<String, Long> timingMs) {
        if (meta == null) meta = new LinkedHashMap<>();
        meta.put("timingMs", timingMs);
    }
}
