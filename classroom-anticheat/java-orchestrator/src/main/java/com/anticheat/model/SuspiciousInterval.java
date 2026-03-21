package com.anticheat.model;

import com.google.gson.annotations.SerializedName;
import java.util.List;

/**
 * Represents a track-centric suspicious time interval.
 */
public class SuspiciousInterval {
    private double start;
    private double end;
    private double duration;

    @SerializedName("peak_score")
    private double peakScore;

    @SerializedName("avg_score")
    private double avgScore;

    // Avg confidence_weight over frames in the interval (0..1).
    private double confidence;

    @SerializedName("dominant_signals")
    private List<String> dominantSignals;

    @SerializedName("supporting_stats")
    private SupportingStats supportingStats;

    public SuspiciousInterval() {}

    public SuspiciousInterval(double start, double end, double duration, double peakScore, double avgScore, double confidence,
                              List<String> dominantSignals, SupportingStats supportingStats) {
        this.start = start;
        this.end = end;
        this.duration = duration;
        this.peakScore = peakScore;
        this.avgScore = avgScore;
        this.confidence = confidence;
        this.dominantSignals = dominantSignals;
        this.supportingStats = supportingStats;
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

    public double getAvgScore() {
        return avgScore;
    }

    public void setAvgScore(double avgScore) {
        this.avgScore = avgScore;
    }

    public double getConfidence() {
        return confidence;
    }

    public void setConfidence(double confidence) {
        this.confidence = confidence;
    }

    public List<String> getDominantSignals() {
        return dominantSignals;
    }

    public void setDominantSignals(List<String> dominantSignals) {
        this.dominantSignals = dominantSignals;
    }

    public SupportingStats getSupportingStats() {
        return supportingStats;
    }

    public void setSupportingStats(SupportingStats supportingStats) {
        this.supportingStats = supportingStats;
    }

    public double getDuration() {
        return duration;
    }

    public void setDuration(double duration) {
        this.duration = duration;
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
        String dom = dominantSignals == null ? "" : String.join(", ", dominantSignals);
        return String.format("[%s – %s] Peak: %.2f, Avg: %.2f, Conf: %.2f, Dominant: %s",
                getFormattedStart(), getFormattedEnd(), peakScore, avgScore, confidence, dom);
    }

    public static class SupportingStats {
        @SerializedName("head_deviation_pct")
        private double headDeviationPct;

        @SerializedName("gaze_deviation_pct")
        private double gazeDeviationPct;

        @SerializedName("proximity_avg_distance")
        private Double proximityAvgDistance;

        @SerializedName("proximity_min_distance")
        private Double proximityMinDistance;

        public SupportingStats() {}

        public double getHeadDeviationPct() {
            return headDeviationPct;
        }

        public double getGazeDeviationPct() {
            return gazeDeviationPct;
        }

        public Double getProximityAvgDistance() {
            return proximityAvgDistance;
        }

        public Double getProximityMinDistance() {
            return proximityMinDistance;
        }
    }
}
