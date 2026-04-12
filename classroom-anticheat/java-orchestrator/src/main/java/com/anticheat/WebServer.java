package com.anticheat;

import com.anticheat.model.AnalysisResponse;
import com.anticheat.model.ExamRequest;
import com.anticheat.model.NotificationConfig;
import com.anticheat.service.AnalysisClient;
import com.anticheat.service.NotificationService;
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

    public WebServer(String cvServiceUrl) {
        this.cvServiceUrl = cvServiceUrl;
        this.client = new AnalysisClient(cvServiceUrl);
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
                    .renderAnnotatedVideo(false) // Java will render Phase 3
                    .phase1Only(true)            // Python only does CV Phase 1
                    .build();

            try {
                String jobId = client.submitAnalysis(request);

                // Start background task to await completion and send email
                startBackgroundMonitor(jobId, request);

                ctx.json(Map.of("jobId", jobId, "examId", examId));
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
                String javaState = jobStates.getOrDefault(jobId, STATE_PYTHON);
                if (!javaState.equals(STATE_COMPLETED)) {
                    ctx.status(404).json(Map.of("error", "Results not ready yet. Current state: " + javaState));
                    return;
                }

                Path jobDir = Paths.get("job_store").resolve(jobId);
                Path javaResultPath = jobDir.resolve("phase2_results_java.json");
                
                if (Files.exists(javaResultPath)) {
                    String content = Files.readString(javaResultPath, StandardCharsets.UTF_8);
                    ctx.contentType("application/json").result(content);
                } else {
                    // This shouldn't really happen if state is COMPLETED but we check anyway
                    ctx.status(404).json(Map.of("error", "Result file missing on disk"));
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
                AnalysisResponse result = client.getResult(jobId);
                if (result.getAnnotatedVideo() != null && "ready".equals(result.getAnnotatedVideo().getStatus())) {
                    String filePath = result.getAnnotatedVideo().getFilePath();
                    // Map file path to Java-side output if it looks like the Python one
                    if (filePath.contains("phase2_annotated.mp4")) {
                        filePath = filePath.replace("phase2_annotated.mp4", "phase2_annotated_java.mp4");
                    }
                    Path videoPath = Paths.get(filePath);
                    if (Files.exists(videoPath)) {
                        ctx.writeSeekableStream(Files.newInputStream(videoPath), "video/mp4");
                    } else {
                        System.err.println("[WebServer GET /api/video/" + jobId + "] File not found: " + filePath);
                        ctx.status(404).json(Map.of("error", "Video file not found on disk: " + filePath));
                    }
                } else {
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
                Path jobDir = Paths.get("job_store").resolve(jobId).toAbsolutePath().normalize();
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
