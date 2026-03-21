package com.anticheat.report;

import com.anticheat.model.AnalysisResponse;
import com.anticheat.model.TrackResult;
import com.anticheat.model.SuspiciousInterval;

/**
 * Generates terminal-based reports for analysis results.
 */
public class TerminalReporter {
    private static final String SEPARATOR = "=".repeat(60);
    private static final String THIN_SEPARATOR = "-".repeat(60);

    /**
     * Print the full analysis report to terminal.
     *
     * @param response The analysis response from CV service
     */
    public void printReport(AnalysisResponse response) {
        printHeader(response);

        printTrackResults(response);
        printSummary(response);
    }

    private void printHeader(AnalysisResponse response) {
        System.out.println();
        System.out.println(SEPARATOR);
        System.out.println("        CLASSROOM ANTI-CHEAT ANALYSIS REPORT");
        System.out.println(SEPARATOR);
        System.out.println("Exam ID: " + response.getExamId());
        System.out.println(THIN_SEPARATOR);
    }

    private void printTrackResults(AnalysisResponse response) {
        if (response.getResults() == null || response.getResults().isEmpty()) {
            System.out.println("\nNo tracks analyzed.");
            return;
        }

        boolean anyFlagged = false;

        for (TrackResult track : response.getResults()) {
            if (track.hasSuspiciousIntervals()) {
                anyFlagged = true;
                printTrackSuspiciousActivity(track);
            }
        }

        if (!anyFlagged) {
            System.out.println("\n✓ No suspicious patterns detected (confidence-weighted signals).");
        }
    }

    private void printTrackSuspiciousActivity(TrackResult track) {
        System.out.println();
        System.out.printf("Track %d (stability: %.2f)%n", track.getTrackId(), track.getStabilityScore());

        if (track.getIntervals() == null || track.getIntervals().isEmpty()) {
            return;
        }

        for (SuspiciousInterval interval : track.getIntervals()) {
            System.out.printf("  [%s – %s] Suspicion signal (Peak: %.2f, Avg: %.2f, Conf: %.2f)%n",
                    interval.getFormattedStart(),
                    interval.getFormattedEnd(),
                    interval.getPeakScore(),
                    interval.getAvgScore(),
                    interval.getConfidence());

            if (interval.getDominantSignals() != null && !interval.getDominantSignals().isEmpty()) {
                System.out.println("    Dominant signals: " + String.join(", ", interval.getDominantSignals()));
            }

            if (interval.getSupportingStats() != null) {
                System.out.printf("    Supporting stats: head_dev=%.2f%%, gaze_dev=%.2f%%%n",
                        interval.getSupportingStats().getHeadDeviationPct() * 100.0,
                        interval.getSupportingStats().getGazeDeviationPct() * 100.0
                );
            }
        }
    }

    private void printSummary(AnalysisResponse response) {
        System.out.println();
        System.out.println(THIN_SEPARATOR);
        System.out.println("SUMMARY");
        System.out.println(THIN_SEPARATOR);
        int totalTracks = response.getResults() != null ? response.getResults().size() : 0;
        int flaggedTracks = response.getSuspiciousStudentCount(); // legacy method name, but counts tracks
        int totalIntervals = response.getTotalSuspiciousIntervals();

        System.out.println("Total tracks analyzed: " + totalTracks);
        System.out.println("Tracks flagged: " + flaggedTracks);
        System.out.println("Total suspicious intervals: " + totalIntervals);
        System.out.println(SEPARATOR);
        System.out.println();

        if (response.getAnnotatedVideo() != null) {
            System.out.println("Annotated video:");
            System.out.println("  status: " + response.getAnnotatedVideo().getStatus());
            System.out.println("  path: " + response.getAnnotatedVideo().getFilePath());
            if (response.getAnnotatedVideo().getResolution() != null) {
                System.out.println("  resolution: " + response.getAnnotatedVideo().getResolution());
            }
            if (response.getAnnotatedVideo().getFrameRate() != null) {
                System.out.println("  frame_rate: " + response.getAnnotatedVideo().getFrameRate());
            }
        }
    }

    /**
     * Print a simple error message.
     *
     * @param message The error message
     */
    public void printError(String message) {
        System.out.println();
        System.out.println(SEPARATOR);
        System.out.println("ERROR: " + message);
        System.out.println(SEPARATOR);
        System.out.println();
    }

    /**
     * Print processing status.
     *
     * @param message The status message
     */
    public void printStatus(String message) {
        System.out.println("[STATUS] " + message);
    }
}
