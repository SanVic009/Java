package com.anticheat;

import com.anticheat.model.AnalysisResponse;
import com.anticheat.model.ExamRequest;
import com.anticheat.report.TerminalReporter;
import com.anticheat.service.AnalysisClient;
import com.google.gson.Gson;
import com.google.gson.GsonBuilder;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

/**
 * Main entry point for the Classroom Anti-Cheat Orchestrator.
 * 
 * Usage:
 *   java -jar anticheat.jar <config.json>
 *   java -jar anticheat.jar --video <path> --exam-id <id>
 */
public class Main {
    private static final TerminalReporter reporter = new TerminalReporter();
    private static final Gson gson = new GsonBuilder().setPrettyPrinting().create();

    public static void main(String[] args) {
        try {
            if (args.length == 0) {
                printUsage();
                runDemo();
                return;
            }

            ExamRequest request = parseArguments(args);
            int pollIntervalSeconds = parsePollIntervalSeconds(args);
            int timeoutMinutes = parseTimeoutMinutes(args);
            runAnalysis(request, pollIntervalSeconds, timeoutMinutes);

        } catch (Exception e) {
            reporter.printError(e.getMessage());
            System.exit(1);
        }
    }

    private static void runAnalysis(ExamRequest request, int pollIntervalSeconds, int timeoutMinutes) {
        int pollIntervalMs = Math.max(1, pollIntervalSeconds) * 1000;
        int maxPollAttempts = Math.max(1, (timeoutMinutes * 60) / Math.max(1, pollIntervalSeconds));
        AnalysisClient client = new AnalysisClient("http://localhost:8000", pollIntervalMs, maxPollAttempts);

        reporter.printStatus("Checking Python CV service availability...");

        if (!client.healthCheck()) {
            reporter.printError("Python CV service is not available at localhost:8000");
            reporter.printStatus("Please start the Python service first:");
            System.out.println("  cd python-cv-service && python main.py");
            System.exit(1);
        }

        reporter.printStatus("Service is available. Submitting analysis job...");

        try {
            String jobId = client.submitAnalysis(request);
            reporter.printStatus("Job submitted: " + jobId);
            AnalysisResponse response = client.waitForResult(jobId);
            reporter.printReport(response);
        } catch (AnalysisClient.AnalysisException e) {
            reporter.printError("Analysis failed: " + e.getMessage());
            System.exit(1);
        }
    }

    private static ExamRequest parseArguments(String[] args) throws IOException {
        if (args.length == 1 && args[0].endsWith(".json")) {
            // Load from config file
            Path configPath = Paths.get(args[0]);
            String content = Files.readString(configPath);
            return gson.fromJson(content, ExamRequest.class);
        }

        // Parse command-line arguments
        String examId = null;
        String videoPath = null;
        int fps = 5;
        boolean renderAnnotated = false;

        for (int i = 0; i < args.length; i++) {
            switch (args[i]) {
                case "--exam-id":
                    examId = args[++i];
                    break;
                case "--video":
                    videoPath = args[++i];
                    break;
                case "--fps":
                    fps = Integer.parseInt(args[++i]);
                    break;
                case "--render-annotated-video":
                    renderAnnotated = true;
                    break;
                case "--poll-interval":
                    i += 1; // parsed separately
                    break;
                case "--timeout":
                    i += 1; // parsed separately
                    break;
                case "--help":
                case "-h":
                    printUsage();
                    System.exit(0);
                    break;
            }
        }

        // Only exam-id and video are required
        if (examId == null || videoPath == null) {
            throw new IllegalArgumentException(
                    "Missing required arguments (--exam-id and --video are required). Use --help for usage information.");
        }

        ExamRequest.Builder builder = ExamRequest.builder()
                .examId(examId)
                .videoPath(videoPath)
                .fpsSampling(fps)
                .renderAnnotatedVideo(renderAnnotated);

        return builder.build();
    }

    private static int parsePollIntervalSeconds(String[] args) {
        int pollIntervalSeconds = 3;
        for (int i = 0; i < args.length; i++) {
            if ("--poll-interval".equals(args[i]) && i + 1 < args.length) {
                pollIntervalSeconds = Integer.parseInt(args[i + 1]);
            }
        }
        return pollIntervalSeconds;
    }

    private static int parseTimeoutMinutes(String[] args) {
        int timeoutMinutes = 120;
        for (int i = 0; i < args.length; i++) {
            if ("--timeout".equals(args[i]) && i + 1 < args.length) {
                timeoutMinutes = Integer.parseInt(args[i + 1]);
            }
        }
        return timeoutMinutes;
    }

    private static void printUsage() {
        System.out.println();
        System.out.println("Classroom Anti-Cheat Analysis System");
        System.out.println("=====================================");
        System.out.println();
        System.out.println("Usage:");
        System.out.println("  java -jar anticheat.jar <config.json>");
        System.out.println("  java -jar anticheat.jar --video <path> --exam-id <id>");
        System.out.println();
        System.out.println("Options:");
        System.out.println("  --exam-id <id>      Unique identifier for the exam (required)");
        System.out.println("  --video <path>      Path to the CCTV video file (required)");
        System.out.println("  --fps <number>      Frame sampling rate (default: 5)");
        System.out.println("  --poll-interval <seconds>  Status polling interval (default: 3)");
        System.out.println("  --timeout <minutes> Max wait time before aborting (default: 120)");
        System.out.println("  --render-annotated-video  Enable Phase 3 annotated video rendering");
        System.out.println("  --help, -h          Show this help message");
        System.out.println();
        System.out.println("Examples:");
        System.out.println();
        System.out.println("  # Track-centric analysis:");
        System.out.println("  java -jar anticheat.jar --exam-id exam_001 --video /path/to/video.mp4");
        System.out.println();
        System.out.println("  # Using config file:");
        System.out.println("  java -jar anticheat.jar exam_config.json");
        System.out.println();
    }

    /**
     * Demo mode: prints a minimal command example.
     */
    private static void runDemo() {
        reporter.printStatus("DEMO mode: use --exam-id and --video");
        System.out.println();
        System.out.println("Example:");
        System.out.println("  java -jar anticheat.jar --exam-id demo_001 --video /path/to/video.mp4 --fps 5");
        System.out.println();
    }
}
