package com.anticheat.model;

import com.google.gson.annotations.SerializedName;
import java.util.List;

/**
 * Analysis result for a single student.
 */
public class StudentResult {
    @SerializedName("student_id")
    private int studentId;

    private List<SuspiciousInterval> intervals;

    public StudentResult() {}

    public StudentResult(int studentId, List<SuspiciousInterval> intervals) {
        this.studentId = studentId;
        this.intervals = intervals;
    }

    // Getters and Setters
    public int getStudentId() {
        return studentId;
    }

    public void setStudentId(int studentId) {
        this.studentId = studentId;
    }

    public List<SuspiciousInterval> getIntervals() {
        return intervals;
    }

    public void setIntervals(List<SuspiciousInterval> intervals) {
        this.intervals = intervals;
    }

    /**
     * Check if this student has any suspicious intervals.
     */
    public boolean hasSuspiciousActivity() {
        return intervals != null && !intervals.isEmpty();
    }

    /**
     * Get total number of suspicious intervals.
     */
    public int getSuspiciousCount() {
        return intervals != null ? intervals.size() : 0;
    }
}
