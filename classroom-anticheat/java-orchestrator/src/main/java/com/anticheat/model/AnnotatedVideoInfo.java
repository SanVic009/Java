package com.anticheat.model;

import com.google.gson.annotations.SerializedName;
import java.util.Map;

/**
 * Phase 3 annotated video rendering info.
 */
public class AnnotatedVideoInfo {
    @SerializedName("file_path")
    private String filePath;

    private String status; // rendering | ready | failed | not_requested

    // resolution: { width, height }
    private Map<String, Object> resolution;

    @SerializedName("frame_rate")
    private Double frameRate;

    @SerializedName("duration_sec")
    private Double durationSec;

    private String error;

    public AnnotatedVideoInfo() {}

    public String getFilePath() {
        return filePath;
    }

    public String getStatus() {
        return status;
    }

    public Map<String, Object> getResolution() {
        return resolution;
    }

    public Double getFrameRate() {
        return frameRate;
    }

    public Double getDurationSec() {
        return durationSec;
    }

    public String getError() {
        return error;
    }
}

