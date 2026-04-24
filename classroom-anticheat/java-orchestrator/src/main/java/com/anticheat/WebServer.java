package com.anticheat;

import com.anticheat.model.AnalysisResponse;
import com.anticheat.model.ExamRequest;
import com.anticheat.model.NotificationConfig;
import com.anticheat.service.AnalysisClient;
import com.anticheat.service.NotificationService;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import io.javalin.Javalin;
import io.javalin.http.UploadedFile;
import io.javalin.config.SizeUnit;
import io.javalin.json.JavalinGson;
import com.anticheat.postcv.JavaPostCvAllRunner;

import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

public class WebServer {
    private static final com.google.gson.Gson GSON = new com.google.gson.GsonBuilder()
            .setPrettyPrinting()
            .create();

    // Track job states on the Java side to handle the hybrid pipeline
    private static final Map<String, String> jobStates = new ConcurrentHashMap<>();
    private static final String STATE_PYTHON = "PYTHON_RUNNING";
    private static final String STATE_JAVA = "JAVA_RUNNING";
    private static final String STATE_COMPLETED = "COMPLETED";
    private static final String STATE_FAILED = "FAILED";

    private final AnalysisClient client;
    private final String cvServiceUrl;
    private final Path jobStoreRoot;

    public WebServer(String cvServiceUrl) {
        this.cvServiceUrl = cvServiceUrl;
        this.client = new AnalysisClient(cvServiceUrl);
        this.jobStoreRoot = resolveJobStoreRoot();
    }

    private static Path resolveJobStoreRoot() {
        Path cwd = Paths.get(System.getProperty("user.dir")).toAbsolutePath().normalize();
        Path cwdJobStore = cwd.resolve("job_store");
        Path nestedRepoJobStore = cwd.resolve("classroom-anticheat").resolve("job_store");
        Path parent = cwd.getParent();
        Path parentJobStore = parent == null ? null : parent.resolve("job_store");

        // Common case: launching from java-orchestrator while Python writes to ../job_store.
        if (cwd.getFileName() != null
                && "java-orchestrator".equals(cwd.getFileName().toString())
                && parentJobStore != null
                && Files.isDirectory(parentJobStore)) {
            return parentJobStore;
        }

        // Common case: launching from workspace root (/.../Code/Java) while artifacts are in
        // /.../Code/Java/classroom-anticheat/job_store.
        if (Files.isDirectory(nestedRepoJobStore)) {
            return nestedRepoJobStore;
        }
        if (Files.isDirectory(cwdJobStore)) {
            return cwdJobStore;
        }
        if (parentJobStore != null && Files.isDirectory(parentJobStore)) {
            return parentJobStore;
        }
        return cwdJobStore;
    }

    public void start(int port) {
        Path uploadDir = Paths.get("videos");
        try {
            if (!Files.exists(uploadDir)) {
                Files.createDirectories(uploadDir);
            }
        } catch (Exception e) {
            throw new RuntimeException("Could not create upload directory", e);
        }

        Javalin app = Javalin.create(config -> {
            config.jsonMapper(new JavalinGson(GSON));
            config.staticFiles.add("/public");
            config.jetty.multipartConfig.maxFileSize(200, SizeUnit.MB);
            config.jetty.multipartConfig.maxTotalRequestSize(200, SizeUnit.MB);
            config.plugins.enableCors(cors -> cors.add(it -> {
                it.anyHost();
            }));
        }).start(port);

        System.out.println("Web Server started on http://localhost:" + port);

        app.post("/api/analyze", ctx -> {
            UploadedFile videoFile = ctx.uploadedFile("video");
            if (videoFile == null) {
                System.err.println("[WebServer POST /api/analyze] No video file in multipart request");
                ctx.status(400).json(Map.of("error", "No video file provided"));
                return;
            }

            String clientJobId = ctx.formParam("clientJobId");

            String examId = ctx.formParam("examId");
            if (examId == null || examId.isBlank()) {
                examId = "exam_" + UUID.randomUUID().toString().substring(0, 8);
            }

            Path videoPath = uploadDir.resolve(videoFile.filename());
            try (InputStream is = videoFile.content()) {
                Files.copy(is, videoPath, StandardCopyOption.REPLACE_EXISTING);
            }

            ExamRequest request = ExamRequest.builder()
                    .examId(examId)
                    .videoPath(videoFile.filename())
                    .fpsSampling(5)
                    .renderAnnotatedVideo(true)  // Prefer Python's true annotated render
                    .phase1Only(false)           // Run full Python pipeline for annotated output
                    .build();

            try {
                String jobId = client.submitAnalysis(request);
                persistClientJobIdMapping(clientJobId, jobId, examId);

                // Start background task to await completion and send email
                startBackgroundMonitor(jobId, request);

                Map<String, Object> response = new LinkedHashMap<>();
                response.put("jobId", jobId);
                response.put("examId", examId);
                if (clientJobId != null && !clientJobId.isBlank()) {
                    response.put("clientJobId", clientJobId.trim());
                }
                ctx.json(response);
            } catch (Exception e) {
                System.err.println("[WebServer POST /api/analyze] Error submitting to Python CV: " + e.getMessage());
                e.printStackTrace(System.err);
                ctx.status(500).json(Map.of("error", e.getMessage()));
            }
        });

        app.get("/api/status/{jobId}", ctx -> {
            String jobId = ctx.pathParam("jobId");
            try {
                String javaState = jobStates.getOrDefault(jobId, STATE_PYTHON);
                AnalysisClient.JobStatus status = client.getJobStatus(jobId);
                Path jobDir = jobStoreRoot.resolve(jobId);
                Path javaResultPath = jobDir.resolve("phase2_results_java.json");

                // Recover completed state after Java server restart using persisted artifacts.
                if (Files.exists(javaResultPath)) {
                    javaState = STATE_COMPLETED;
                    jobStates.put(jobId, STATE_COMPLETED);
                }

                // If Python is done but Java is still post-processing, keep it "running"
                if (status.status.equalsIgnoreCase("completed") && javaState.equals(STATE_JAVA)) {
                    status.status = "running";
                    status.message = "Java Post-Processing (Phase 2 Scoring & Phase 3 Rendering)...";
                    status.progress = 0.95; // Almost done
                } else if (javaState.equals(STATE_COMPLETED)) {
                    status.status = "completed";
                    status.message = "Analysis complete";
                    status.progress = 1.0;
                } else if (javaState.equals(STATE_FAILED)) {
                    status.status = "failed";
                }

                ctx.json(status);
            } catch (Exception e) {
                System.err.println("[WebServer GET /api/status/" + jobId + "] " + e.getMessage());
                e.printStackTrace(System.err);
                ctx.status(500).json(Map.of("error", e.getMessage()));
            }
        });

        app.get("/api/result/{jobId}", ctx -> {
            String jobId = ctx.pathParam("jobId");
            try {
                Path jobDir = jobStoreRoot.resolve(jobId);
                Path javaResultPath = jobDir.resolve("phase2_results_java.json");

                if (Files.exists(javaResultPath)) {
                    jobStates.put(jobId, STATE_COMPLETED);
                    String content = Files.readString(javaResultPath, StandardCharsets.UTF_8);
                    ctx.contentType("application/json").result(content);
                } else {
                    String javaState = jobStates.getOrDefault(jobId, STATE_PYTHON);
                    ctx.status(404).json(Map.of("error", "Results not ready yet. Current state: " + javaState));
                }
            } catch (Exception e) {
                System.err.println("[WebServer GET /api/result/" + jobId + "] " + e.getMessage());
                e.printStackTrace(System.err);
                ctx.status(500).json(Map.of("error", e.getMessage()));
            }
        });

        app.get("/api/video/{jobId}", ctx -> {
            String jobId = ctx.pathParam("jobId");
            try {
                Path jobDir = jobStoreRoot.resolve(jobId);
                Path annotatedPy = jobDir.resolve("phase2_annotated.mp4");
                Path annotatedJava = jobDir.resolve("phase2_annotated_java.mp4");

                // Prefer Python's true annotated render; fallback to Java artifact if needed.
                Path videoPath = Files.exists(annotatedPy) ? annotatedPy : annotatedJava;
                if (Files.exists(videoPath)) {
                    ctx.writeSeekableStream(Files.newInputStream(videoPath), "video/mp4");
                } else {
                    AnalysisResponse result = client.getResult(jobId);
                    String videoStatus = result.getAnnotatedVideo() == null ? "null" : result.getAnnotatedVideo().getStatus();
                    System.err.println("[WebServer GET /api/video/" + jobId + "] Annotated video not ready. Status: " + videoStatus);
                    ctx.status(404).json(Map.of("error", "Annotated video not ready (status: " + videoStatus + ")"));
                }
            } catch (Exception e) {
                System.err.println("[WebServer GET /api/video/" + jobId + "] " + e.getMessage());
                e.printStackTrace(System.err);
                ctx.status(500).json(Map.of("error", e.getMessage()));
            }
        });

        app.post("/api/integrity/check", ctx -> {
            String providedJobId = ctx.formParam("jobId");
            UploadedFile uploadedFile = ctx.uploadedFile("file");
            if (uploadedFile == null) {
                uploadedFile = ctx.uploadedFile("video");
            }

            if (providedJobId == null || providedJobId.isBlank()) {
                ctx.status(400).json(Map.of("error", "jobId is required"));
                return;
            }
            if (uploadedFile == null) {
                ctx.status(400).json(Map.of("error", "file is required"));
                return;
            }

            try {
                String resolvedJobId = resolveStoredJobId(providedJobId);
                if (resolvedJobId == null) {
                    ctx.status(404).json(Map.of("error", "Job ID not found in job_store"));
                    return;
                }

                Path jobDir = jobStoreRoot.resolve(resolvedJobId);
                String storedSha256 = readStoredPhase3Sha256(jobDir);
                if (storedSha256 == null || storedSha256.isBlank()) {
                    ctx.status(404).json(Map.of("error", "No stored phase3 SHA-256 found for this job"));
                    return;
                }

                String uploadedSha256;
                try (InputStream is = uploadedFile.content()) {
                    uploadedSha256 = sha256Hex(is);
                }

                String clientComputedHash = ctx.formParam("clientSha256");
                boolean hashMatch = storedSha256.equalsIgnoreCase(uploadedSha256);
                String integrityStatus = hashMatch ? "untampered" : "tampered";

                Map<String, Object> response = new LinkedHashMap<>();
                response.put("providedJobId", providedJobId);
                response.put("resolvedJobId", resolvedJobId);
                response.put("storedSha256", storedSha256);
                response.put("uploadedSha256", uploadedSha256);
                response.put("integrityStatus", integrityStatus);
                response.put("message", hashMatch
                        ? "Hashes match. Untampered file."
                        : "Hashes do not match. Tampered file.");
                response.put("artifact", jobDir.resolve("phase2_annotated_java.mp4").toString());
                if (clientComputedHash != null && !clientComputedHash.isBlank()) {
                    response.put("clientSha256", clientComputedHash.trim());
                    response.put("clientServerHashMatch", clientComputedHash.trim().equalsIgnoreCase(uploadedSha256));
                }

                ctx.json(response);
            } catch (Exception e) {
                System.err.println("[WebServer POST /api/integrity/check] " + e.getMessage());
                e.printStackTrace(System.err);
                ctx.status(500).json(Map.of("error", e.getMessage()));
            }
        });
    }

    private synchronized void persistClientJobIdMapping(String clientJobId, String actualJobId, String examId) throws Exception {
        if (clientJobId == null || clientJobId.isBlank()) {
            return;
        }

        String normalizedClientJobId = clientJobId.trim();
        if (!isSafeJobId(normalizedClientJobId)) {
            throw new IllegalArgumentException("clientJobId must be a single path segment without separators");
        }

        Files.createDirectories(jobStoreRoot);
        Path mapPath = jobStoreRoot.resolve("client_job_id_map.json");

        JsonObject root = new JsonObject();
        if (Files.exists(mapPath)) {
            JsonElement existing = JsonParser.parseString(Files.readString(mapPath, StandardCharsets.UTF_8));
            if (existing.isJsonObject()) {
                root = existing.getAsJsonObject();
            }
        }

        JsonObject aliases = root.has("aliases") && root.get("aliases").isJsonObject()
                ? root.getAsJsonObject("aliases")
                : new JsonObject();
        aliases.addProperty(normalizedClientJobId, actualJobId);
        root.add("aliases", aliases);

        JsonObject metadata = root.has("metadata") && root.get("metadata").isJsonObject()
                ? root.getAsJsonObject("metadata")
                : new JsonObject();
        JsonObject current = metadata.has(actualJobId) && metadata.get(actualJobId).isJsonObject()
                ? metadata.getAsJsonObject(actualJobId)
                : new JsonObject();
        current.addProperty("client_job_id", normalizedClientJobId);
        current.addProperty("exam_id", examId);
        current.addProperty("updated_at", Instant.now().toString());
        metadata.add(actualJobId, current);
        root.add("metadata", metadata);

        Files.writeString(mapPath, GSON.toJson(root), StandardCharsets.UTF_8);
    }

    private String resolveStoredJobId(String providedJobId) {
        if (providedJobId == null || providedJobId.isBlank()) {
            return null;
        }

        String normalized = providedJobId.trim();
        if (!isSafeJobId(normalized)) {
            return null;
        }

        Path directJobDir = jobStoreRoot.resolve(normalized);
        if (Files.isDirectory(directJobDir)) {
            return normalized;
        }

        Path mapPath = jobStoreRoot.resolve("client_job_id_map.json");
        if (!Files.exists(mapPath)) {
            return null;
        }

        try {
            JsonElement rootEl = JsonParser.parseString(Files.readString(mapPath, StandardCharsets.UTF_8));
            if (!rootEl.isJsonObject()) {
                return null;
            }
            JsonObject aliases = rootEl.getAsJsonObject().getAsJsonObject("aliases");
            if (aliases == null || !aliases.has(normalized)) {
                return null;
            }
            String resolved = aliases.get(normalized).getAsString();
            if (!isSafeJobId(resolved)) {
                return null;
            }
            return Files.isDirectory(jobStoreRoot.resolve(resolved)) ? resolved : null;
        } catch (Exception e) {
            return null;
        }
    }

    private static boolean isSafeJobId(String jobId) {
        if (jobId == null || jobId.isBlank()) {
            return false;
        }
        return !jobId.contains("/") && !jobId.contains("\\") && !jobId.contains("..");
    }

    private String readStoredPhase3Sha256(Path jobDir) throws Exception {
        Path integrityPath = jobDir.resolve("integrity_phase3.json");
        if (Files.exists(integrityPath)) {
            JsonElement integrityEl = JsonParser.parseString(Files.readString(integrityPath, StandardCharsets.UTF_8));
            if (integrityEl.isJsonObject() && integrityEl.getAsJsonObject().has("sha256")) {
                return integrityEl.getAsJsonObject().get("sha256").getAsString();
            }
        }

        Path summaryPath = jobDir.resolve("postcv_java_summary.json");
        if (Files.exists(summaryPath)) {
            JsonElement summaryEl = JsonParser.parseString(Files.readString(summaryPath, StandardCharsets.UTF_8));
            if (summaryEl.isJsonObject() && summaryEl.getAsJsonObject().has("phase3_sha256")) {
                return summaryEl.getAsJsonObject().get("phase3_sha256").getAsString();
            }
        }

        Path artifactPath = jobDir.resolve("phase2_annotated_java.mp4");
        if (Files.exists(artifactPath)) {
            return sha256Hex(artifactPath);
        }

        return null;
    }

    private static String sha256Hex(Path filePath) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream inputStream = Files.newInputStream(filePath)) {
            byte[] buf = new byte[8192];
            int bytesRead;
            while ((bytesRead = inputStream.read(buf)) != -1) {
                digest.update(buf, 0, bytesRead);
            }
        }
        return HexFormat.of().formatHex(digest.digest());
    }

    private static String sha256Hex(InputStream inputStream) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        byte[] buf = new byte[8192];
        int bytesRead;
        while ((bytesRead = inputStream.read(buf)) != -1) {
            digest.update(buf, 0, bytesRead);
        }
        return HexFormat.of().formatHex(digest.digest());
    }

    private void startBackgroundMonitor(String jobId, ExamRequest request) {
        jobStates.put(jobId, STATE_PYTHON);
        new Thread(() -> {
            try {
                System.out.println("[WebServer] Background monitor started for job: " + jobId);
                
                // 1. Wait for Python to finish Phase 1
                client.waitForResult(jobId);
                System.out.println("[WebServer] Python Phase 1 finished for " + jobId + ". Delegating to Java...");
                
                // Transition to Java post-processing
                jobStates.put(jobId, STATE_JAVA);

                // 2. Run Java post-CV pipeline (Scoring + Rendering + Snapshots)
                Path jobDir = jobStoreRoot.resolve(jobId).toAbsolutePath().normalize();
                JavaPostCvAllRunner javaRunner = new JavaPostCvAllRunner();
                AnalysisResponse javaResponse = javaRunner.run(jobDir, request.getExamId());
                
                // Mark as completed
                jobStates.put(jobId, STATE_COMPLETED);
                System.out.println("[WebServer] Java post-processing completed for " + jobId + ". Triggering notification.");

                // 3. Trigger notification with Java results
                NotificationConfig notifConfig = NotificationConfig.load();
                if (notifConfig.enabled && "immediate".equalsIgnoreCase(notifConfig.deliveryMode)) {
                    NotificationService notifier = new NotificationService(notifConfig, cvServiceUrl);
                    notifier.sendImmediateAlerts(jobId, request.getExamId(), javaResponse);
                }
            } catch (Exception e) {
                jobStates.put(jobId, STATE_FAILED);
                System.err.println("[WebServer] Background monitor failed for job " + jobId + ": " + e.getMessage());
                e.printStackTrace(System.err);
            }
        }).start();
    }
}
