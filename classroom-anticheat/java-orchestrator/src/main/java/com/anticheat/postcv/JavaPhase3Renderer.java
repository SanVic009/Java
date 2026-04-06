package com.anticheat.postcv;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Java Phase 3 renderer (artifact-level).
 *
 * Current implementation performs a deterministic ffmpeg-based output build
 * from the source video path and returns metadata compatible with API fields.
 */
public class JavaPhase3Renderer {

    public Map<String, Object> render(Path jobDir, Path sourceVideoPath, String outFileName) {
        Path outVideo = jobDir.resolve(outFileName);
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("file_path", outVideo.toString());
        result.put("status", "failed");
        result.put("resolution", null);
        result.put("frame_rate", null);
        result.put("duration_sec", null);

        try {
            String ffmpeg = ToolPaths.resolveBinary("ffmpeg");
            Files.createDirectories(outVideo.getParent());
            ProcessBuilder pb = new ProcessBuilder(
                    ffmpeg,
                    "-y",
                    "-i", sourceVideoPath.toString(),
                    "-c", "copy",
                    outVideo.toString()
            );
            Process p = pb.start();
            int code = p.waitFor();
            if (code != 0) {
                result.put("error", "ffmpeg exited with code " + code);
                return result;
            }

            result.put("status", "ready");
            enrichVideoMeta(result, outVideo);
            return result;
        } catch (Exception e) {
            result.put("error", e.getMessage());
            return result;
        }
    }

    private static void enrichVideoMeta(Map<String, Object> out, Path videoPath) throws IOException, InterruptedException {
        String ffprobe = ToolPaths.resolveBinary("ffprobe");
        ProcessBuilder pb = new ProcessBuilder(
                ffprobe,
                "-v", "error",
                "-show_entries", "stream=width,height,r_frame_rate:format=duration",
                "-of", "json",
                videoPath.toString()
        );
        Process p = pb.start();
        String json = new String(p.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
        int code = p.waitFor();
        if (code != 0 || json.isBlank()) {
            return;
        }

        JsonObject root = JsonParser.parseString(json).getAsJsonObject();
        JsonArray streams = root.has("streams") ? root.getAsJsonArray("streams") : new JsonArray();
        if (!streams.isEmpty()) {
            JsonObject s = streams.get(0).getAsJsonObject();
            Map<String, Object> res = new LinkedHashMap<>();
            if (s.has("width")) res.put("width", s.get("width").getAsInt());
            if (s.has("height")) res.put("height", s.get("height").getAsInt());
            out.put("resolution", res.isEmpty() ? null : res);

            if (s.has("r_frame_rate")) {
                out.put("frame_rate", parseRate(s.get("r_frame_rate").getAsString()));
            }
        }

        if (root.has("format") && root.get("format").isJsonObject()) {
            JsonObject fmt = root.getAsJsonObject("format");
            if (fmt.has("duration")) {
                out.put("duration_sec", fmt.get("duration").getAsDouble());
            }
        }
    }

    private static Double parseRate(String rate) {
        try {
            if (rate == null || rate.isBlank()) return null;
            if (!rate.contains("/")) return Double.parseDouble(rate);
            String[] p = rate.split("/");
            double a = Double.parseDouble(p[0]);
            double b = Double.parseDouble(p[1]);
            if (b == 0.0) return null;
            return a / b;
        } catch (Exception ignored) {
            return null;
        }
    }
}
