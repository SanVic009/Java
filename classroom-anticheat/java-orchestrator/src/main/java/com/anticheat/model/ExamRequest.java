package com.anticheat.model;

import com.google.gson.annotations.SerializedName;
import java.util.List;

/**
 * Request payload sent to Python CV service for analysis.
 * If seatMap is null or empty, auto-discovery mode will be used.
 */
public class ExamRequest {
    @SerializedName("exam_id")
    private String examId;

    @SerializedName("video_path")
    private String videoPath;

    @SerializedName("fps_sampling")
    private int fpsSampling;

    @SerializedName("baseline_duration_sec")
    private int baselineDurationSec;

    @SerializedName("seat_map")
    private List<SeatMapping> seatMap;  // Optional - null triggers auto-discovery

    @SerializedName("discovery_duration_sec")
    private int discoveryDurationSec;  // Duration for auto-discovery phase

    public ExamRequest() {}

    public ExamRequest(String examId, String videoPath, int fpsSampling, 
                       int baselineDurationSec, List<SeatMapping> seatMap,
                       int discoveryDurationSec) {
        this.examId = examId;
        this.videoPath = videoPath;
        this.fpsSampling = fpsSampling;
        this.baselineDurationSec = baselineDurationSec;
        this.seatMap = seatMap;
        this.discoveryDurationSec = discoveryDurationSec;
    }

    // Builder pattern for cleaner construction
    public static Builder builder() {
        return new Builder();
    }

    public static class Builder {
        private String examId;
        private String videoPath;
        private int fpsSampling = 5; // Default
        private int baselineDurationSec = 60; // Default 1 minute
        private int discoveryDurationSec = 120; // Default 2 minutes for auto-discovery
        private List<SeatMapping> seatMap = null; // Default: auto-discovery

        public Builder examId(String examId) {
            this.examId = examId;
            return this;
        }

        public Builder videoPath(String videoPath) {
            this.videoPath = videoPath;
            return this;
        }

        public Builder fpsSampling(int fpsSampling) {
            this.fpsSampling = fpsSampling;
            return this;
        }

        public Builder baselineDurationSec(int baselineDurationSec) {
            this.baselineDurationSec = baselineDurationSec;
            return this;
        }

        public Builder discoveryDurationSec(int discoveryDurationSec) {
            this.discoveryDurationSec = discoveryDurationSec;
            return this;
        }

        public Builder seatMap(List<SeatMapping> seatMap) {
            this.seatMap = seatMap;
            return this;
        }

        public ExamRequest build() {
            return new ExamRequest(examId, videoPath, fpsSampling, 
                    baselineDurationSec, seatMap, discoveryDurationSec);
        }
    }

    /**
     * Check if auto-discovery mode should be used.
     */
    public boolean isAutoDiscoveryMode() {
        return seatMap == null || seatMap.isEmpty();
    }

    // Getters and Setters
    public String getExamId() {
        return examId;
    }

    public void setExamId(String examId) {
        this.examId = examId;
    }

    public String getVideoPath() {
        return videoPath;
    }

    public void setVideoPath(String videoPath) {
        this.videoPath = videoPath;
    }

    public int getFpsSampling() {
        return fpsSampling;
    }

    public void setFpsSampling(int fpsSampling) {
        this.fpsSampling = fpsSampling;
    }

    public int getBaselineDurationSec() {
        return baselineDurationSec;
    }

    public void setBaselineDurationSec(int baselineDurationSec) {
        this.baselineDurationSec = baselineDurationSec;
    }

    public int getDiscoveryDurationSec() {
        return discoveryDurationSec;
    }

    public void setDiscoveryDurationSec(int discoveryDurationSec) {
        this.discoveryDurationSec = discoveryDurationSec;
    }

    public List<SeatMapping> getSeatMap() {
        return seatMap;
    }

    public void setSeatMap(List<SeatMapping> seatMap) {
        this.seatMap = seatMap;
    }
}
