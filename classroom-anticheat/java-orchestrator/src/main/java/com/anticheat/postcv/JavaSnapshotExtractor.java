package com.anticheat.postcv;

import com.anticheat.model.AnalysisResponse;
import com.google.gson.Gson;
import com.google.gson.GsonBuilder;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Snapshot extraction is intentionally disabled.
 *
 * We keep this class to preserve output contracts by writing an empty
 * snapshots metadata file, but we do not generate per-interval clip files.
 */
public class JavaSnapshotExtractor {
    private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();

    public List<Map<String, Object>> extract(Path jobDir, Path sourceVideoPath, AnalysisResponse response, String metadataFileName) {
        List<Map<String, Object>> snapshots = new ArrayList<>();
        try {
            writeMeta(jobDir.resolve(metadataFileName), snapshots);
            return snapshots;
        } catch (Exception e) {
            try {
                writeMeta(jobDir.resolve(metadataFileName), snapshots);
            } catch (Exception ignored) {
            }
            return snapshots;
        }
    }

    private static void writeMeta(Path path, List<Map<String, Object>> snapshots) throws Exception {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("snapshots", snapshots);
        Files.writeString(path, GSON.toJson(payload), StandardCharsets.UTF_8);
    }
}
