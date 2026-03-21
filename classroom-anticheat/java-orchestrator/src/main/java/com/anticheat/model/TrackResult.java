package com.anticheat.model;

import java.util.List;

/**
 * Analysis result for a single track (ByteTrack track_id).
 */
public class TrackResult {
    private int track_id;
    private double total_duration;
    private double stability_score;
    private List<SuspicionInterval> intervals;

    public TrackResult() {}

    public TrackResult(int track_id, double total_duration, double stability_score, List<SuspicionInterval> intervals) {
        this.track_id = track_id;
        this.total_duration = total_duration;
        this.stability_score = stability_score;
        this.intervals = intervals;
    }

    public int getTrackId() {
        return track_id;
    }

    public void setTrackId(int track_id) {
        this.track_id = track_id;
    }

    public double getTotalDuration() {
        return total_duration;
    }

    public void setTotalDuration(double total_duration) {
        this.total_duration = total_duration;
    }

    public double getStabilityScore() {
        return stability_score;
    }

    public void setStabilityScore(double stability_score) {
        this.stability_score = stability_score;
    }

    public List<SuspicionInterval> getIntervals() {
        return intervals;
    }

    public void setIntervals(List<SuspicionInterval> intervals) {
        this.intervals = intervals;
    }

    public boolean hasSuspiciousIntervals() {
        return intervals != null && !intervals.isEmpty();
    }
}

