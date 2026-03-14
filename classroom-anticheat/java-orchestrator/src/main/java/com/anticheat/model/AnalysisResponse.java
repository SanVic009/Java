package com.anticheat.model;

import com.google.gson.annotations.SerializedName;
import java.util.List;

/**
 * Response from Python CV service containing analysis results.
 */
public class AnalysisResponse {
    @SerializedName("exam_id")
    private String examId;

    private List<StudentResult> results;

    @SerializedName("auto_discovered")
    private boolean autoDiscovered;

    @SerializedName("discovered_seats")
    private List<DiscoveredSeat> discoveredSeats;

    public AnalysisResponse() {}

    public AnalysisResponse(String examId, List<StudentResult> results) {
        this.examId = examId;
        this.results = results;
    }

    // Getters and Setters
    public String getExamId() {
        return examId;
    }

    public void setExamId(String examId) {
        this.examId = examId;
    }

    public List<StudentResult> getResults() {
        return results;
    }

    public void setResults(List<StudentResult> results) {
        this.results = results;
    }

    public boolean isAutoDiscovered() {
        return autoDiscovered;
    }

    public void setAutoDiscovered(boolean autoDiscovered) {
        this.autoDiscovered = autoDiscovered;
    }

    public List<DiscoveredSeat> getDiscoveredSeats() {
        return discoveredSeats;
    }

    public void setDiscoveredSeats(List<DiscoveredSeat> discoveredSeats) {
        this.discoveredSeats = discoveredSeats;
    }

    /**
     * Get count of students with suspicious activity.
     */
    public int getSuspiciousStudentCount() {
        if (results == null) return 0;
        return (int) results.stream()
                .filter(StudentResult::hasSuspiciousActivity)
                .count();
    }

    /**
     * Get total number of suspicious intervals across all students.
     */
    public int getTotalSuspiciousIntervals() {
        if (results == null) return 0;
        return results.stream()
                .mapToInt(StudentResult::getSuspiciousCount)
                .sum();
    }

    /**
     * Get count of discovered seats (if auto-discovery was used).
     */
    public int getDiscoveredSeatCount() {
        return discoveredSeats != null ? discoveredSeats.size() : 0;
    }
}
