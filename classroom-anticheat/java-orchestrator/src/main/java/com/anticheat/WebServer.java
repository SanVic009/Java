package com.anticheat;

import com.anticheat.model.AnalysisResponse;
import com.anticheat.model.ExamRequest;
import com.anticheat.model.NotificationConfig;
import com.anticheat.service.AnalysisClient;
import com.anticheat.service.NotificationService;
import io.javalin.Javalin;
import io.javalin.http.UploadedFile;

import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.util.Map;
import java.util.UUID;

public class WebServer {
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
            config.staticFiles.add("/public");
        }).start(port);

        System.out.println("Web Server started on http://localhost:" + port);

        app.post("/api/analyze", ctx -> {
            UploadedFile videoFile = ctx.uploadedFile("video");
            if (videoFile == null) {
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
                    .renderAnnotatedVideo(true)
                    .build();

            try {
                String jobId = client.submitAnalysis(request);

                // Start background task to await completion and send email
                startBackgroundMonitor(jobId, request);

                ctx.json(Map.of("jobId", jobId, "examId", examId));
            } catch (Exception e) {
                ctx.status(500).json(Map.of("error", e.getMessage()));
            }
        });

        app.get("/api/status/{jobId}", ctx -> {
            String jobId = ctx.pathParam("jobId");
            try {
                AnalysisClient.JobStatus status = client.getJobStatus(jobId);
                ctx.json(status);
            } catch (Exception e) {
                ctx.status(500).json(Map.of("error", e.getMessage()));
            }
        });

        app.get("/api/result/{jobId}", ctx -> {
            String jobId = ctx.pathParam("jobId");
            try {
                AnalysisResponse result = client.getResult(jobId);
                ctx.json(result);
            } catch (Exception e) {
                ctx.status(500).json(Map.of("error", e.getMessage()));
            }
        });

        app.get("/api/video/{jobId}", ctx -> {
            String jobId = ctx.pathParam("jobId");
            try {
                AnalysisResponse result = client.getResult(jobId);
                if (result.getAnnotatedVideo() != null && "ready".equals(result.getAnnotatedVideo().getStatus())) {
                    String filePath = result.getAnnotatedVideo().getFilePath();
                    Path videoPath = Paths.get(filePath);
                    if (Files.exists(videoPath)) {
                        ctx.writeSeekableStream(Files.newInputStream(videoPath), "video/mp4");
                    } else {
                        ctx.status(404).json(Map.of("error", "Video file not found on disk"));
                    }
                } else {
                    ctx.status(404).json(Map.of("error", "Annotated video not ready"));
                }
            } catch (Exception e) {
                ctx.status(500).json(Map.of("error", e.getMessage()));
            }
        });
    }

    private void startBackgroundMonitor(String jobId, ExamRequest request) {
        new Thread(() -> {
            try {
                System.out.println("[WebServer] Background monitor started for job: " + jobId);
                AnalysisResponse response = client.waitForResult(jobId);
                System.out.println("[WebServer] Job " + jobId + " completed successfully. Triggering notification.");

                NotificationConfig notifConfig = NotificationConfig.load();
                if (notifConfig.enabled && "immediate".equalsIgnoreCase(notifConfig.deliveryMode)) {
                    NotificationService notifier = new NotificationService(notifConfig, cvServiceUrl);
                    notifier.sendImmediateAlerts(jobId, request.getExamId(), response);
                }
            } catch (Exception e) {
                System.err.println("[WebServer] Background monitor failed for job " + jobId + ": " + e.getMessage());
            }
        }).start();
    }
}
