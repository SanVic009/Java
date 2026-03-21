package com.anticheat.model;

import com.google.gson.annotations.SerializedName;
import java.util.List;
import java.util.Map;

/**
 * Response from Python CV service containing analysis results.
 */
public class AnalysisResponse {
    @SerializedName("exam_id")
    private String examId;

    private List<TrackResult> results;

    private Map<String, Object> observability;

    @SerializedName("annotated_video")
    private AnnotatedVideoInfo annotatedVideo;

    public AnalysisResponse() {}

    public AnalysisResponse(String examId, List<TrackResult> results) {
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

    public List<TrackResult> getResults() {
        return results;
    }

    public void setResults(List<TrackResult> results) {
        this.results = results;
    }

    public Map<String, Object> getObservability() {
        return observability;
    }

    public void setObservability(Map<String, Object> observability) {
        this.observability = observability;
    }

    public AnnotatedVideoInfo getAnnotatedVideo() {
        return annotatedVideo;
    }

    public void setAnnotatedVideo(AnnotatedVideoInfo annotatedVideo) {
        this.annotatedVideo = annotatedVideo;
    }

    /**
     * Get count of students with suspicious activity.
     */
    public int getSuspiciousStudentCount() {
        if (results == null) return 0;
        return (int) results.stream()
                .filter(TrackResult::hasSuspiciousIntervals)
                .count();
    }

    /**
     * Get total number of suspicious intervals across all students.
     */
    public int getTotalSuspiciousIntervals() {
        if (results == null) return 0;
        return results.stream()
                .mapToInt(r -> r.getIntervals() != null ? r.getIntervals().size() : 0)
                .sum();
    }
}
