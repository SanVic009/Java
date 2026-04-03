package com.anticheat.model;

import java.util.List;

public class ViolationEvent {
    public String examId;
    public String jobId;
    public int trackId;
    public double startSec;
    public double endSec;
    public double durationSec;
    public double peakScore;
    public List<String> dominantSignals;
    public String clipPath;
    public String clipUrl;
    public String detectedAt;

    public ViolationEvent() {
    }

    public ViolationEvent(
            String examId,
            String jobId,
            int trackId,
            double startSec,
            double endSec,
            double durationSec,
            double peakScore,
            List<String> dominantSignals,
            String clipPath,
            String clipUrl,
            String detectedAt
    ) {
        this.examId = examId;
        this.jobId = jobId;
        this.trackId = trackId;
        this.startSec = startSec;
        this.endSec = endSec;
        this.durationSec = durationSec;
        this.peakScore = peakScore;
        this.dominantSignals = dominantSignals;
        this.clipPath = clipPath;
        this.clipUrl = clipUrl;
        this.detectedAt = detectedAt;
    }
}