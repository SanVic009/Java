package com.anticheat.postcv;

import com.anticheat.model.AnalysisResponse;
import com.anticheat.model.SuspiciousInterval;
import com.anticheat.model.TrackResult;
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
 * Java snapshot extraction equivalent for post-CV artifacts.
 */
public class JavaSnapshotExtractor {
    private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();

    public List<Map<String, Object>> extract(Path jobDir, Path sourceVideoPath, AnalysisResponse response, String metadataFileName) {
        List<Map<String, Object>> snapshots = new ArrayList<>();
        try {
            String ffmpeg = ToolPaths.resolveBinary("ffmpeg");
            Path snapshotDir = jobDir.resolve("snapshots");
            Files.createDirectories(snapshotDir);

            if (response == null || response.getResults() == null) {
                writeMeta(jobDir.resolve(metadataFileName), snapshots);
                return snapshots;
            }

            Path annotatedPy = jobDir.resolve("phase2_annotated.mp4");
            Path annotatedJava = jobDir.resolve("phase2_annotated_java.mp4");
            Path videoToCrop = sourceVideoPath;
            if (Files.exists(annotatedPy)) {
                // Python's endpoint renders actual CV bounding boxes
                videoToCrop = annotatedPy;
            } else if (Files.exists(annotatedJava)) {
                // Warning: JavaPhase3Renderer currently only does `-c copy` so it will lack annotations
                videoToCrop = annotatedJava;
            }

            for (TrackResult track : response.getResults()) {
                if (track.getIntervals() == null) {
                    continue;
                }
                for (SuspiciousInterval interval : track.getIntervals()) {
                    double start = Math.max(0.0, interval.getStart() - 1.0);
                    double duration = interval.getDuration() + 2.0;
                    String clipFilename = String.format("track_%d_t%.1f.mp4", track.getTrackId(), interval.getStart());
                    Path clipPath = snapshotDir.resolve(clipFilename);

                    ProcessBuilder pb = new ProcessBuilder(
                            ffmpeg,
                            "-y",
                            "-ss", String.valueOf(start),
                            "-i", videoToCrop.toString(),
                            "-t", String.valueOf(duration),
                            "-c", "copy",
                            clipPath.toString()
                    );
                    int code = pb.start().waitFor();
                    if (code != 0) {
                        continue;
                    }

                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("track_id", track.getTrackId());
                    row.put("start", interval.getStart());
                    row.put("end", interval.getEnd());
                    row.put("peak_score", interval.getPeakScore());
                    row.put("dominant_signals", interval.getDominantSignals());
                    row.put("clip_path", clipPath.toString());
                    row.put("clip_filename", clipFilename);
                    snapshots.add(row);
                }
            }

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
