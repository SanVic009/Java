package com.anticheat.postcv;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Lightweight parity diff between Python and Java Phase 2 result payloads.
 */
public class Phase2ParityDiff {

    public ParityReport compare(Path pythonResultsPath, Path javaResultsPath) throws IOException {
        JsonObject py = JsonParser.parseString(Files.readString(pythonResultsPath, StandardCharsets.UTF_8)).getAsJsonObject();
        JsonObject jv = JsonParser.parseString(Files.readString(javaResultsPath, StandardCharsets.UTF_8)).getAsJsonObject();

        Map<Integer, JsonObject> pyTracks = tracksById(py);
        Map<Integer, JsonObject> jvTracks = tracksById(jv);

        ParityReport report = new ParityReport();
        report.pythonTrackCount = pyTracks.size();
        report.javaTrackCount = jvTracks.size();

        report.pythonIntervalCount = totalIntervals(pyTracks);
        report.javaIntervalCount = totalIntervals(jvTracks);

        for (int trackId : pyTracks.keySet()) {
            JsonObject pyTrack = pyTracks.get(trackId);
            JsonObject jvTrack = jvTracks.get(trackId);
            if (jvTrack == null) {
                report.missingTracksInJava.add(trackId);
                continue;
            }

            JsonArray pyIntervals = array(pyTrack, "intervals");
            JsonArray jvIntervals = array(jvTrack, "intervals");
            if (pyIntervals.size() != jvIntervals.size()) {
                report.intervalCountMismatches.put(trackId, pyIntervals.size() + " vs " + jvIntervals.size());
            }

            int pairs = Math.min(pyIntervals.size(), jvIntervals.size());
            for (int i = 0; i < pairs; i++) {
                JsonObject p = pyIntervals.get(i).getAsJsonObject();
                JsonObject q = jvIntervals.get(i).getAsJsonObject();

                double s1 = d(p, "start");
                double e1 = d(p, "end");
                double s2 = d(q, "start");
                double e2 = d(q, "end");

                report.absStartDeltaSum += Math.abs(s1 - s2);
                report.absEndDeltaSum += Math.abs(e1 - e2);
                report.pairedIntervals += 1;

                String pyDom = dominantSignalsKey(p);
                String jvDom = dominantSignalsKey(q);
                if (!pyDom.equals(jvDom)) {
                    report.dominantSignalMismatches += 1;
                }
            }
        }

        for (int trackId : jvTracks.keySet()) {
            if (!pyTracks.containsKey(trackId)) {
                report.extraTracksInJava.add(trackId);
            }
        }

        return report;
    }

    private static Map<Integer, JsonObject> tracksById(JsonObject payload) {
        Map<Integer, JsonObject> out = new HashMap<>();
        JsonArray results = array(payload, "results");
        for (JsonElement el : results) {
            JsonObject tr = el.getAsJsonObject();
            int id = tr.get("track_id").getAsInt();
            out.put(id, tr);
        }
        return out;
    }

    private static int totalIntervals(Map<Integer, JsonObject> tracks) {
        int total = 0;
        for (JsonObject tr : tracks.values()) {
            total += array(tr, "intervals").size();
        }
        return total;
    }

    private static JsonArray array(JsonObject o, String key) {
        if (!o.has(key) || o.get(key).isJsonNull() || !o.get(key).isJsonArray()) {
            return new JsonArray();
        }
        return o.getAsJsonArray(key);
    }

    private static double d(JsonObject o, String key) {
        if (!o.has(key) || o.get(key).isJsonNull()) {
            return 0.0;
        }
        return o.get(key).getAsDouble();
    }

    private static String dominantSignalsKey(JsonObject interval) {
        JsonArray arr = array(interval, "dominant_signals");
        List<String> vals = new ArrayList<>();
        for (JsonElement el : arr) {
            vals.add(el.getAsString());
        }
        return String.join("|", vals);
    }

    public static class ParityReport {
        public int pythonTrackCount;
        public int javaTrackCount;
        public int pythonIntervalCount;
        public int javaIntervalCount;

        public final List<Integer> missingTracksInJava = new ArrayList<>();
        public final List<Integer> extraTracksInJava = new ArrayList<>();
        public final Map<Integer, String> intervalCountMismatches = new HashMap<>();

        public int pairedIntervals;
        public double absStartDeltaSum;
        public double absEndDeltaSum;
        public int dominantSignalMismatches;

        public double avgAbsStartDelta() {
            return pairedIntervals == 0 ? 0.0 : absStartDeltaSum / pairedIntervals;
        }

        public double avgAbsEndDelta() {
            return pairedIntervals == 0 ? 0.0 : absEndDeltaSum / pairedIntervals;
        }

        public String toSummaryString() {
            return "ParityReport{" +
                    "pythonTrackCount=" + pythonTrackCount +
                    ", javaTrackCount=" + javaTrackCount +
                    ", pythonIntervalCount=" + pythonIntervalCount +
                    ", javaIntervalCount=" + javaIntervalCount +
                    ", missingTracksInJava=" + missingTracksInJava +
                    ", extraTracksInJava=" + extraTracksInJava +
                    ", intervalCountMismatches=" + intervalCountMismatches +
                    ", pairedIntervals=" + pairedIntervals +
                    ", avgAbsStartDelta=" + avgAbsStartDelta() +
                    ", avgAbsEndDelta=" + avgAbsEndDelta() +
                    ", dominantSignalMismatches=" + dominantSignalMismatches +
                    '}';
        }
    }
}
