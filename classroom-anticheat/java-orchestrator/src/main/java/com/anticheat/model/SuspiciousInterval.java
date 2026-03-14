package com.anticheat.model;

import com.google.gson.annotations.SerializedName;
import java.util.List;

/**
 * Represents a suspicious time interval detected for a student.
 */
public class SuspiciousInterval {
    private double start;
    private double end;

    @SerializedName("peak_score")
    private double peakScore;

    private List<String> reasons;

    public SuspiciousInterval() {}

    public SuspiciousInterval(double start, double end, double peakScore, List<String> reasons) {
        this.start = start;
        this.end = end;
        this.peakScore = peakScore;
        this.reasons = reasons;
    }

    // Getters and Setters
    public double getStart() {
        return start;
    }

    public void setStart(double start) {
        this.start = start;
    }

    public double getEnd() {
        return end;
    }

    public void setEnd(double end) {
        this.end = end;
    }

    public double getPeakScore() {
        return peakScore;
    }

    public void setPeakScore(double peakScore) {
        this.peakScore = peakScore;
    }

    public List<String> getReasons() {
        return reasons;
    }

    public void setReasons(List<String> reasons) {
        this.reasons = reasons;
    }

    /**
     * Format start time as HH:MM:SS
     */
    public String getFormattedStart() {
        return formatTimestamp(start);
    }

    /**
     * Format end time as HH:MM:SS
     */
    public String getFormattedEnd() {
        return formatTimestamp(end);
    }

    private String formatTimestamp(double seconds) {
        int totalSeconds = (int) seconds;
        int hours = totalSeconds / 3600;
        int minutes = (totalSeconds % 3600) / 60;
        int secs = totalSeconds % 60;
        return String.format("%02d:%02d:%02d", hours, minutes, secs);
    }

    @Override
    public String toString() {
        return String.format("[%s – %s] Peak Score: %.2f, Reasons: %s",
                getFormattedStart(), getFormattedEnd(), peakScore, reasons);
    }
}
