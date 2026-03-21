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

    public ExamRequest() {}

    public ExamRequest(String examId, String videoPath, int fpsSampling, boolean renderAnnotatedVideo) {
        this.examId = examId;
        this.videoPath = videoPath;
        this.fpsSampling = fpsSampling;
        this.renderAnnotatedVideo = renderAnnotatedVideo;
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

        public ExamRequest build() {
            return new ExamRequest(examId, videoPath, fpsSampling, renderAnnotatedVideo);
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

    public boolean isRenderAnnotatedVideo() {
        return renderAnnotatedVideo;
    }

    public void setRenderAnnotatedVideo(boolean renderAnnotatedVideo) {
        this.renderAnnotatedVideo = renderAnnotatedVideo;
    }

}
