package com.anticheat.report;

import com.anticheat.model.AnalysisResponse;
import com.anticheat.model.DiscoveredSeat;
import com.anticheat.model.StudentResult;
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
        
        // Show auto-discovery info if applicable
        if (response.isAutoDiscovered()) {
            printDiscoveredSeats(response);
        }
        
        printStudentResults(response);
        printSummary(response);
    }

    private void printHeader(AnalysisResponse response) {
        System.out.println();
        System.out.println(SEPARATOR);
        System.out.println("        CLASSROOM ANTI-CHEAT ANALYSIS REPORT");
        System.out.println(SEPARATOR);
        System.out.println("Exam ID: " + response.getExamId());
        System.out.println("Mode: " + (response.isAutoDiscovered() ? "AUTO-DISCOVERY" : "PREDEFINED SEATS"));
        System.out.println(THIN_SEPARATOR);
    }

    private void printDiscoveredSeats(AnalysisResponse response) {
        if (response.getDiscoveredSeats() == null || response.getDiscoveredSeats().isEmpty()) {
            System.out.println("\nNo seats were discovered.");
            return;
        }

        System.out.println("\nDISCOVERED SEATS:");
        System.out.println(THIN_SEPARATOR);
        
        for (DiscoveredSeat seat : response.getDiscoveredSeats()) {
            System.out.printf("  Seat %d → Student ID %d (stability: %.2f)%n",
                    seat.getSeatId(),
                    seat.getStudentId(),
                    seat.getStabilityScore());
        }
        
        System.out.println(THIN_SEPARATOR);
    }

    private void printStudentResults(AnalysisResponse response) {
        if (response.getResults() == null || response.getResults().isEmpty()) {
            System.out.println("\nNo students analyzed.");
            return;
        }

        boolean anyFlagged = false;

        for (StudentResult student : response.getResults()) {
            if (student.hasSuspiciousActivity()) {
                anyFlagged = true;
                printStudentSuspiciousActivity(student);
            }
        }

        if (!anyFlagged) {
            System.out.println("\n✓ No suspicious patterns detected for any student.");
        }
    }

    private void printStudentSuspiciousActivity(StudentResult student) {
        System.out.println();
        System.out.println("Student " + student.getStudentId());

        for (SuspiciousInterval interval : student.getIntervals()) {
            System.out.printf("  [%s – %s] Suspicious pattern (Peak Score: %.2f)%n",
                    interval.getFormattedStart(),
                    interval.getFormattedEnd(),
                    interval.getPeakScore());

            // Print reasons indented
            if (interval.getReasons() != null && !interval.getReasons().isEmpty()) {
                System.out.print("    Reasons: ");
                System.out.println(String.join(", ", interval.getReasons()));
            }
        }
    }

    private void printSummary(AnalysisResponse response) {
        System.out.println();
        System.out.println(THIN_SEPARATOR);
        System.out.println("SUMMARY");
        System.out.println(THIN_SEPARATOR);
        
        if (response.isAutoDiscovered()) {
            System.out.println("Seats discovered: " + response.getDiscoveredSeatCount());
        }
        
        int totalStudents = response.getResults() != null ? response.getResults().size() : 0;
        int flaggedStudents = response.getSuspiciousStudentCount();
        int totalIntervals = response.getTotalSuspiciousIntervals();

        System.out.println("Total students analyzed: " + totalStudents);
        System.out.println("Students flagged: " + flaggedStudents);
        System.out.println("Total suspicious intervals: " + totalIntervals);
        System.out.println(SEPARATOR);
        System.out.println();
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
