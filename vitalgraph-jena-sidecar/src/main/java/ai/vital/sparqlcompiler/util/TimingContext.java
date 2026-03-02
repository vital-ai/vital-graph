package ai.vital.sparqlcompiler.util;

import java.util.LinkedHashMap;
import java.util.Map;

public class TimingContext {

    private final Map<String, Long> timings = new LinkedHashMap<>();
    private final Map<String, Long> startTimes = new LinkedHashMap<>();

    public void start(String phase) {
        startTimes.put(phase, System.nanoTime());
    }

    public void stop(String phase) {
        Long startTime = startTimes.remove(phase);
        if (startTime != null) {
            long elapsed = (System.nanoTime() - startTime) / 1_000_000;
            timings.merge(phase, elapsed, Long::sum);
        }
    }

    public Map<String, Long> getTimings() {
        return new LinkedHashMap<>(timings);
    }
}
