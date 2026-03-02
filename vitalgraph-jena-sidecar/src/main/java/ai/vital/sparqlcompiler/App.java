package ai.vital.sparqlcompiler;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import io.javalin.Javalin;
import io.javalin.http.Context;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Map;

public class App {

    private static final Logger log = LoggerFactory.getLogger(App.class);
    private static final ObjectMapper mapper = new ObjectMapper()
            .configure(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS, true);

    private static SparqlCompiler compiler;
    private static int maxInputSize;

    public static void main(String[] args) {
        int port = Integer.parseInt(System.getenv().getOrDefault("PORT", "7070"));
        maxInputSize = Integer.parseInt(System.getenv().getOrDefault("MAX_INPUT_SIZE", "1048576"));
        int requestTimeoutMs = Integer.parseInt(System.getenv().getOrDefault("REQUEST_TIMEOUT_MS", "5000"));

        // Initialize Jena eagerly at startup (not lazily on first request)
        log.info("Initializing Apache Jena...");
        org.apache.jena.sys.JenaSystem.init();
        log.info("Jena initialized successfully");

        compiler = new SparqlCompiler(requestTimeoutMs);

        Javalin app = Javalin.create(config -> {
            config.routes.post("/v1/sparql/compile", App::handleCompile);
            config.routes.get("/health", App::handleHealth);
        }).start(port);

        log.info("SPARQL Compiler Sidecar started on port {}", port);
        log.info("Max input size: {} bytes, request timeout: {}ms", maxInputSize, requestTimeoutMs);
    }

    private static void handleCompile(Context ctx) {
        long startTime = System.nanoTime();

        try {
            String body = ctx.body();

            if (body.length() > maxInputSize) {
                ctx.status(413);
                ctx.json(CompileResponse.error("INPUT_TOO_LARGE",
                        "Input exceeds maximum size of " + maxInputSize + " bytes",
                        null, null, null));
                return;
            }

            CompileRequest request = mapper.readValue(body, CompileRequest.class);

            if (request.sparql == null || request.sparql.isBlank()) {
                ctx.status(400);
                ctx.json(CompileResponse.error("PARSE_ERROR",
                        "Missing or empty 'sparql' field",
                        null, null, null));
                return;
            }

            CompileResponse response = compiler.compile(request);

            long totalMs = (System.nanoTime() - startTime) / 1_000_000;
            log.info("Compiled SPARQL in {}ms (hash: {})", totalMs,
                    response.input != null ? response.input.get("sparqlHash") : "n/a");

            ctx.json(response);

        } catch (Exception e) {
            log.error("Unexpected error handling compile request", e);
            ctx.status(500);
            ctx.json(CompileResponse.error("INTERNAL_ERROR",
                    e.getMessage(), null, null, null));
        }
    }

    private static void handleHealth(Context ctx) {
        ctx.json(Map.of(
                "status", "ok",
                "serviceVersion", SparqlCompiler.SERVICE_VERSION,
                "jenaVersion", org.apache.jena.Jena.VERSION
        ));
    }
}
