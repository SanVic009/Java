package com.anticheat.model;

import java.util.List;

/**
 * Represents a seat in the classroom with its bounding box and neighbor relationships.
 * Bounding box coordinates are in pixels relative to video resolution.
 */
public class SeatMapping {
    private int seatId;
    private int studentId;
    private int[] bbox; // [x1, y1, x2, y2]
    private List<Integer> neighbors;

    public SeatMapping() {}

    public SeatMapping(int seatId, int studentId, int[] bbox, List<Integer> neighbors) {
        this.seatId = seatId;
        this.studentId = studentId;
        this.bbox = bbox;
        this.neighbors = neighbors;
    }

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

    public int[] getBbox() {
        return bbox;
    }

    public void setBbox(int[] bbox) {
        this.bbox = bbox;
    }

    public List<Integer> getNeighbors() {
        return neighbors;
    }

    public void setNeighbors(List<Integer> neighbors) {
        this.neighbors = neighbors;
    }

    @Override
    public String toString() {
        return String.format("SeatMapping{seatId=%d, studentId=%d, bbox=[%d,%d,%d,%d], neighbors=%s}",
                seatId, studentId, bbox[0], bbox[1], bbox[2], bbox[3], neighbors);
    }
}
