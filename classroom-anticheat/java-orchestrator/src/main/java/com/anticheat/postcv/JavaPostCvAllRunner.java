package com.anticheat.postcv;

import com.anticheat.model.AnalysisResponse;
import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Runs Java post-CV pipeline phases together:
 * 1) Phase2 scoring
 * 2) Phase3 annotated-video build
 * 3) Snapshot extraction
 */
public class JavaPostCvAllRunner {
    private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();

    public AnalysisResponse run(Path jobDir, String examId) throws Exception {
        JavaPhase2Scorer scorer = new JavaPhase2Scorer();
        AnalysisResponse response = scorer.run(
                jobDir,
                examId,
                "phase2_results_java.json",
                "phase2_stats_java.json",
                "phase2_frame_scores_java.jsonl"
        );

        Path sourceVideo = resolveSourceVideo(jobDir);

        JavaPhase3Renderer renderer = new JavaPhase3Renderer();
        Map<String, Object> videoInfo = renderer.render(jobDir, sourceVideo, "phase2_annotated_java.mp4");
        Path phase3VideoPath = jobDir.resolve("phase2_annotated_java.mp4");
        String phase3Sha256 = sha256Hex(phase3VideoPath);

        JavaSnapshotExtractor snapshotExtractor = new JavaSnapshotExtractor();
        List<Map<String, Object>> snaps = snapshotExtractor.extract(
                jobDir,
                sourceVideo,
                response,
                "snapshots_java.json"
        );

        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("exam_id", examId);
        summary.put("phase2_results_file", jobDir.resolve("phase2_results_java.json").toString());
        summary.put("phase2_stats_file", jobDir.resolve("phase2_stats_java.json").toString());
        summary.put("phase2_frame_scores_file", jobDir.resolve("phase2_frame_scores_java.jsonl").toString());
        summary.put("annotated_video", videoInfo);
        summary.put("phase3_sha256", phase3Sha256);
        summary.put("snapshot_count", snaps.size());
        summary.put("snapshots_file", jobDir.resolve("snapshots_java.json").toString());
        Files.writeString(jobDir.resolve("postcv_java_summary.json"), GSON.toJson(summary), StandardCharsets.UTF_8);

        Map<String, Object> integrity = new LinkedHashMap<>();
        integrity.put("job_id", jobDir.getFileName().toString());
        integrity.put("exam_id", examId);
        integrity.put("phase", "phase3");
        integrity.put("artifact", phase3VideoPath.toString());
        integrity.put("sha256", phase3Sha256);
        integrity.put("computed_at", Instant.now().toString());
        Files.writeString(jobDir.resolve("integrity_phase3.json"), GSON.toJson(integrity), StandardCharsets.UTF_8);

        return response;
    }

    private static String sha256Hex(Path filePath) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        byte[] fileBytes = Files.readAllBytes(filePath);
        byte[] hashed = digest.digest(fileBytes);
        return HexFormat.of().formatHex(hashed);
    }

    private static Path resolveSourceVideo(Path jobDir) throws Exception {
        Path statsPath = jobDir.resolve("phase1_stats.json");
        if (!Files.exists(statsPath)) {
            throw new IllegalArgumentException("phase1_stats.json not found in " + jobDir);
        }
        JsonObject o = JsonParser.parseString(Files.readString(statsPath, StandardCharsets.UTF_8)).getAsJsonObject();
        if (!o.has("video_path") || o.get("video_path").isJsonNull()) {
            throw new IllegalArgumentException("phase1_stats.json missing video_path");
        }
        return Path.of(o.get("video_path").getAsString());
    }
}
