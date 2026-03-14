package com.anticheat;

import com.anticheat.model.AnalysisResponse;
import com.anticheat.model.ExamRequest;
import com.anticheat.model.SeatMapping;
import com.anticheat.report.TerminalReporter;
import com.anticheat.service.AnalysisClient;
import com.google.gson.Gson;
import com.google.gson.GsonBuilder;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.List;

/**
 * Main entry point for the Classroom Anti-Cheat Orchestrator.
 * 
 * Usage:
 *   java -jar anticheat.jar <config.json>
 *   java -jar anticheat.jar --video <path> --exam-id <id>
 *   java -jar anticheat.jar --video <path> --exam-id <id> --seat-map <path>
 * 
 * If --seat-map is not provided, auto-discovery mode is used.
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
            runAnalysis(request);

        } catch (Exception e) {
            reporter.printError(e.getMessage());
            System.exit(1);
        }
    }

    private static void runAnalysis(ExamRequest request) {
        AnalysisClient client = new AnalysisClient();

        reporter.printStatus("Checking Python CV service availability...");

        if (!client.healthCheck()) {
            reporter.printError("Python CV service is not available at localhost:8000");
            reporter.printStatus("Please start the Python service first:");
            System.out.println("  cd python-cv-service && python main.py");
            System.exit(1);
        }

        reporter.printStatus("Service is available. Starting analysis...");
        
        if (request.isAutoDiscoveryMode()) {
            reporter.printStatus("Mode: AUTO-DISCOVERY (no seat map provided)");
        } else {
            reporter.printStatus("Mode: PREDEFINED SEATS (" + request.getSeatMap().size() + " seats)");
        }

        try {
            AnalysisResponse response = client.analyze(request);
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
        String seatMapPath = null;  // Optional - null triggers auto-discovery
        int fps = 5;
        int baselineSec = 60;
        int discoverySec = 120;

        for (int i = 0; i < args.length; i++) {
            switch (args[i]) {
                case "--exam-id":
                    examId = args[++i];
                    break;
                case "--video":
                    videoPath = args[++i];
                    break;
                case "--seat-map":
                    seatMapPath = args[++i];
                    break;
                case "--fps":
                    fps = Integer.parseInt(args[++i]);
                    break;
                case "--baseline":
                    baselineSec = Integer.parseInt(args[++i]);
                    break;
                case "--discovery":
                    discoverySec = Integer.parseInt(args[++i]);
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
                .baselineDurationSec(baselineSec)
                .discoveryDurationSec(discoverySec);

        // Load seat map if provided, otherwise auto-discovery will be used
        if (seatMapPath != null) {
            String seatMapContent = Files.readString(Paths.get(seatMapPath));
            SeatMapping[] seatMappings = gson.fromJson(seatMapContent, SeatMapping[].class);
            builder.seatMap(Arrays.asList(seatMappings));
        }
        // If seatMapPath is null, seatMap remains null → auto-discovery mode

        return builder.build();
    }

    private static void printUsage() {
        System.out.println();
        System.out.println("Classroom Anti-Cheat Analysis System");
        System.out.println("=====================================");
        System.out.println();
        System.out.println("Usage:");
        System.out.println("  java -jar anticheat.jar <config.json>");
        System.out.println("  java -jar anticheat.jar --video <path> --exam-id <id>");
        System.out.println("  java -jar anticheat.jar --video <path> --exam-id <id> --seat-map <path>");
        System.out.println();
        System.out.println("Options:");
        System.out.println("  --exam-id <id>      Unique identifier for the exam (required)");
        System.out.println("  --video <path>      Path to the CCTV video file (required)");
        System.out.println("  --seat-map <path>   Path to seat mapping JSON file (optional)");
        System.out.println("                      If not provided, auto-discovery mode is used");
        System.out.println("  --fps <number>      Frame sampling rate (default: 5)");
        System.out.println("  --baseline <sec>    Baseline calibration duration (default: 60)");
        System.out.println("  --discovery <sec>   Auto-discovery duration (default: 120)");
        System.out.println("  --help, -h          Show this help message");
        System.out.println();
        System.out.println("Examples:");
        System.out.println();
        System.out.println("  # Auto-discovery mode (simplest):");
        System.out.println("  java -jar anticheat.jar --exam-id exam_001 --video /path/to/video.mp4");
        System.out.println();
        System.out.println("  # With predefined seat map:");
        System.out.println("  java -jar anticheat.jar --exam-id exam_001 --video /path/to/video.mp4 --seat-map seats.json");
        System.out.println();
        System.out.println("  # Using config file:");
        System.out.println("  java -jar anticheat.jar exam_config.json");
        System.out.println();
    }

    /**
     * Demo mode with sample data for testing.
     */
    private static void runDemo() {
        reporter.printStatus("Running in DEMO mode...");
        System.out.println();
        
        System.out.println("AUTO-DISCOVERY MODE (Default):");
        System.out.println("  No seat map required! Just provide video and exam ID.");
        System.out.println("  The system will automatically detect student positions.");
        System.out.println();

        // Demo with auto-discovery (no seat map)
        ExamRequest autoDiscoveryRequest = ExamRequest.builder()
                .examId("demo_auto_discovery")
                .videoPath("/path/to/demo_video.mp4")
                .fpsSampling(5)
                .baselineDurationSec(60)
                .discoveryDurationSec(120)
                // No seatMap → auto-discovery mode
                .build();

        System.out.println("Auto-discovery config:");
        System.out.println(gson.toJson(autoDiscoveryRequest));
        System.out.println();
        
        System.out.println("PREDEFINED SEATS MODE:");
        System.out.println("  Provide a seat map JSON file for more accurate tracking.");
        System.out.println();

        // Demo with predefined seats
        List<SeatMapping> seatMap = Arrays.asList(
                new SeatMapping(1, 101, new int[]{100, 100, 250, 300}, Arrays.asList(2, 4)),
                new SeatMapping(2, 102, new int[]{260, 100, 410, 300}, Arrays.asList(1, 3, 5)),
                new SeatMapping(3, 103, new int[]{420, 100, 570, 300}, Arrays.asList(2, 6))
        );

        ExamRequest predefinedRequest = ExamRequest.builder()
                .examId("demo_predefined")
                .videoPath("/path/to/demo_video.mp4")
                .fpsSampling(5)
                .baselineDurationSec(60)
                .seatMap(seatMap)
                .build();

        System.out.println("Predefined seats config:");
        System.out.println(gson.toJson(predefinedRequest));
        System.out.println();
        
        reporter.printStatus("To run actual analysis, start the Python CV service and provide a real video.");
    }
}
        System.out.println(gson.toJson(demoRequest));
        System.out.println();
        reporter.printStatus("To run actual analysis, start the Python CV service and provide a real video.");
    }
}
