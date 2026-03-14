package com.anticheat.model;

import com.google.gson.annotations.SerializedName;
import java.util.List;

/**
 * Information about an auto-discovered seat.
 */
public class DiscoveredSeat {
    @SerializedName("seat_id")
    private int seatId;

    @SerializedName("student_id")
    private int studentId;

    private List<Integer> bbox;

    private List<Integer> neighbors;

    @SerializedName("stability_score")
    private double stabilityScore;

    public DiscoveredSeat() {}

    // Getters and Setters
    public int getSeatId() {
        return seatId;
    }

    public void setSeatId(int seatId) {
        this.seatId = seatId;
    }

    public int getStudentId() {
        return studentId;
    }

    public void setStudentId(int studentId) {
        this.studentId = studentId;
    }

    public List<Integer> getBbox() {
        return bbox;
    }

    public void setBbox(List<Integer> bbox) {
        this.bbox = bbox;
    }

    public List<Integer> getNeighbors() {
        return neighbors;
    }

    public void setNeighbors(List<Integer> neighbors) {
        this.neighbors = neighbors;
    }

    public double getStabilityScore() {
        return stabilityScore;
    }

    public void setStabilityScore(double stabilityScore) {
        this.stabilityScore = stabilityScore;
    }

    @Override
    public String toString() {
        return String.format("Seat %d (Student %d): stability=%.2f, neighbors=%s",
                seatId, studentId, stabilityScore, neighbors);
    }
}
