package com.anticheat.model;

import com.google.gson.annotations.SerializedName;

/**
 * Request payload sent to Python CV service for analysis.
 */
public class ExamRequest {
    @SerializedName("exam_id")
    private String examId;

    @SerializedName("video_path")
    private String videoPath;

    @SerializedName("fps_sampling")
    private int fpsSampling = 5;

    @SerializedName("render_annotated_video")
    private boolean renderAnnotatedVideo = false;

    @SerializedName("phase1_only")
    private boolean phase1Only = false;

    public ExamRequest() {}

    public ExamRequest(String examId, String videoPath, int fpsSampling, boolean renderAnnotatedVideo, boolean phase1Only) {
        this.examId = examId;
        this.videoPath = videoPath;
        this.fpsSampling = fpsSampling;
        this.renderAnnotatedVideo = renderAnnotatedVideo;
        this.phase1Only = phase1Only;
    }

    // Builder pattern for cleaner construction
    public static Builder builder() {
        return new Builder();
    }

    public static class Builder {
        private String examId;
        private String videoPath;
        private int fpsSampling = 5; // Default
        private boolean renderAnnotatedVideo = false;
        private boolean phase1Only = false;

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

        public Builder renderAnnotatedVideo(boolean renderAnnotatedVideo) {
            this.renderAnnotatedVideo = renderAnnotatedVideo;
            return this;
        }

        public Builder phase1Only(boolean phase1Only) {
            this.phase1Only = phase1Only;
            return this;
        }

        public ExamRequest build() {
            return new ExamRequest(examId, videoPath, fpsSampling, renderAnnotatedVideo, phase1Only);
        }
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

    public boolean isPhase1Only() {
        return phase1Only;
    }

    public void setPhase1Only(boolean phase1Only) {
        this.phase1Only = phase1Only;
    }
}
