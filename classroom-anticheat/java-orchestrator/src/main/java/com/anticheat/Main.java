package com.anticheat;

import com.anticheat.model.AnalysisResponse;
import com.anticheat.model.ExamRequest;
import com.anticheat.model.NotificationConfig;
import com.anticheat.postcv.JavaPostCvAllRunner;
import com.anticheat.postcv.JavaPhase2Scorer;
import com.anticheat.postcv.Phase2ParityDiff;
import com.anticheat.report.TerminalReporter;
import com.anticheat.service.AnalysisClient;
import com.anticheat.service.NotificationService;
import com.anticheat.util.DotEnvLoader;
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
        // Load .env from the orchestrator directory (or its parent) before anything else.
        DotEnvLoader.load(Paths.get(System.getProperty("user.dir")));
        try {
            if (hasFlag(args, "--web")) {
                int webPort = 7070;
                String portVal = valueAfter(args, "--port");
                if (portVal != null) {
                    webPort = Integer.parseInt(portVal);
                }
                String cvUrl = valueAfter(args, "--cv-url");
                if (cvUrl == null) cvUrl = "http://localhost:8000";
                reporter.printStatus("Starting Web Server on port " + webPort + " (CV service: " + cvUrl + ")");
                WebServer webServer = new WebServer(cvUrl);
                webServer.start(webPort);
                return;
            }

            if (hasFlag(args, "--java-postcv-all")) {
                runJavaPostCvAll(args);
                return;
            }

            if (hasFlag(args, "--java-phase2-parity")) {
                runJavaPhase2Parity(args);
                return;
            }

            if (hasFlag(args, "--java-phase2")) {
                runJavaPhase2(args);
                return;
            }

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

    private static void runJavaPostCvAll(String[] args) throws Exception {
        String jobDirRaw = valueAfter(args, "--job-dir");
        if (jobDirRaw == null || jobDirRaw.isBlank()) {
            throw new IllegalArgumentException("--java-postcv-all requires --job-dir <path>");
        }

        Path jobDir = Paths.get(jobDirRaw).toAbsolutePath().normalize();
        String examId = valueAfter(args, "--exam-id");
        if (examId == null || examId.isBlank()) {
            examId = jobDir.getFileName().toString();
        }

        reporter.printStatus("Running all Java post-CV phases for: " + jobDir);
        JavaPostCvAllRunner runner = new JavaPostCvAllRunner();
        AnalysisResponse response = runner.run(jobDir, examId);
        reporter.printStatus("Java post-CV all phases completed.");
        reporter.printStatus("Summary: " + jobDir.resolve("postcv_java_summary.json"));
        reporter.printReport(response);
    }

    private static void runJavaPhase2Parity(String[] args) throws Exception {
        String jobDirRaw = valueAfter(args, "--job-dir");
        if (jobDirRaw == null || jobDirRaw.isBlank()) {
            throw new IllegalArgumentException("--java-phase2-parity requires --job-dir <path>");
        }

        Path jobDir = Paths.get(jobDirRaw).toAbsolutePath().normalize();
        String examId = valueAfter(args, "--exam-id");
        if (examId == null || examId.isBlank()) {
            examId = jobDir.getFileName().toString();
        }

        Path pyResults = jobDir.resolve("phase2_results.json");
        if (!Files.exists(pyResults)) {
            throw new IllegalArgumentException("Missing python baseline file: " + pyResults);
        }

        reporter.printStatus("Running Java Phase 2 parity mode for: " + jobDir);
        JavaPhase2Scorer scorer = new JavaPhase2Scorer();
        scorer.run(
                jobDir,
                examId,
                "phase2_results_java.json",
                "phase2_stats_java.json",
                "phase2_frame_scores_java.jsonl"
        );

        Path javaResults = jobDir.resolve("phase2_results_java.json");
        Phase2ParityDiff diff = new Phase2ParityDiff();
        Phase2ParityDiff.ParityReport report = diff.compare(pyResults, javaResults);

        reporter.printStatus("Parity diff completed.");
        System.out.println(report.toSummaryString());
        reporter.printStatus("Python: " + pyResults);
        reporter.printStatus("Java:   " + javaResults);
    }

    private static void runJavaPhase2(String[] args) throws Exception {
        String jobDirRaw = valueAfter(args, "--job-dir");
        if (jobDirRaw == null || jobDirRaw.isBlank()) {
            throw new IllegalArgumentException("--java-phase2 requires --job-dir <path>");
        }

        Path jobDir = Paths.get(jobDirRaw).toAbsolutePath().normalize();
        String examId = valueAfter(args, "--exam-id");
        if (examId == null || examId.isBlank()) {
            examId = jobDir.getFileName().toString();
        }

        reporter.printStatus("Running Java post-CV Phase 2 for job dir: " + jobDir);
        JavaPhase2Scorer scorer = new JavaPhase2Scorer();
        AnalysisResponse response = scorer.run(jobDir, examId);
        reporter.printStatus("Java Phase 2 completed.");
        reporter.printReport(response);
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
            AnalysisResponse pythonResponse = client.waitForResult(jobId);
            
            reporter.printStatus("Python Phase 1 finished! Delegating Phase 2 scoring and Phase 3 rendering to Java backend...");
            AnalysisResponse response = null;
            try {
                // job_store is inside the project root (classroom-anticheat/job_store)
                Path jobDir = Paths.get(System.getProperty("user.dir"))
                        .getParent().resolve("job_store").resolve(jobId)
                        .toAbsolutePath().normalize();
                
                JavaPostCvAllRunner javaRunner = new JavaPostCvAllRunner();
                response = javaRunner.run(jobDir, request.getExamId());
            } catch (Exception e) {
                reporter.printError("Failed to run Java backend: " + e.getMessage());
                response = pythonResponse;
            }

            reporter.printReport(response);

            try {
                NotificationConfig notifConfig = NotificationConfig.load();
                if (notifConfig.enabled) {
                    NotificationService notifier = new NotificationService(notifConfig, "http://localhost:8000");
                    if ("immediate".equalsIgnoreCase(notifConfig.deliveryMode)) {
                        notifier.sendImmediateAlerts(jobId, request.getExamId(), response);
                    } else {
                        reporter.printStatus("Notification delivery_mode=digest; deferred to scheduled digest job.");
                    }
                }
            } catch (Exception notificationError) {
                reporter.printStatus("Notification skipped due to error: " + notificationError.getMessage());
            }
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
        boolean renderAnnotated = true;

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
        System.out.println("  --java-phase2 --job-dir <path> [--exam-id <id>]  Run Java Phase 2 from persisted Phase 1 artifacts");
        System.out.println("  --java-phase2-parity --job-dir <path> [--exam-id <id>]  Run Java Phase 2 and print parity diff vs python results");
        System.out.println("  --java-postcv-all --job-dir <path> [--exam-id <id>]  Run Java Phase2+Phase3+snapshots from persisted artifacts");
        System.out.println("  --web [--port <port>] [--cv-url <url>]  Start the web server (default port: 7070)");
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
        System.out.println("  java -jar anticheat.jar --java-phase2 --job-dir ./job_store/<job_id> --exam-id demo_001");
        System.out.println("  java -jar anticheat.jar --java-phase2-parity --job-dir ./job_store/<job_id> --exam-id demo_001");
        System.out.println("  java -jar anticheat.jar --java-postcv-all --job-dir ./job_store/<job_id> --exam-id demo_001");
        System.out.println();
    }

    private static boolean hasFlag(String[] args, String flag) {
        for (String arg : args) {
            if (flag.equals(arg)) {
                return true;
            }
        }
        return false;
    }

    private static String valueAfter(String[] args, String key) {
        for (int i = 0; i < args.length - 1; i++) {
            if (key.equals(args[i])) {
                return args[i + 1];
            }
        }
        return null;
    }
}
