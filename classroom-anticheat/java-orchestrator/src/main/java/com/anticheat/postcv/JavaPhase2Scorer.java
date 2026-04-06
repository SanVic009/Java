package com.anticheat.postcv;

import com.anticheat.model.AnalysisResponse;
import com.anticheat.model.SuspiciousInterval;
import com.anticheat.model.TrackResult;
import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.Deque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * Initial Java port for post-CV Phase 2 scoring.
 *
 * <p>
 * Consumes persisted Phase 1 artifacts and emits:
 * <ul>
 * <li>phase2_results.json</li>
 * <li>phase2_stats.json</li>
 * <li>phase2_frame_scores.jsonl</li>
 * </ul>
 */
public class JavaPhase2Scorer {
    private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();

    // Mirrors python-cv-service/config.py values
    private static final double HEAD_WEIGHT = 0.45;
    private static final double GAZE_WEIGHT = 0.28;
    private static final double PROX_WEIGHT = 0.17;
    private static final double DRIFT_WEIGHT = 0.10;

    private static final double TRACK_STABILITY_MIN_SCORE = 0.30;
    private static final double MIN_TRACK_LIFESPAN_SEC = 10.0;
    private static final double BASELINE_WINDOW_SEC = 30.0;
    private static final int MIN_BASELINE_SAMPLES = 5;
    private static final int BASELINE_MIN_ABSOLUTE_SAMPLES = 10;

    private static final double MIN_POSE_CONFIDENCE = 0.45;
    private static final double HEAD_DEV_NORM_DEG = 25.0;
    private static final double GAZE_DEV_NORM = 0.4;
    private static final double PROXIMITY_DISTANCE_RATIO_THRESHOLD = 0.7;
    private static final double SIGNAL_FLAG_THRESHOLD = 0.6;

    private static final double SOFT_GATE_MIN_WEIGHT = 0.15;
    private static final double SOFT_GATE_FLOOR = 0.20;
    private static final double MIN_CONFIDENCE_WEIGHT_FLOOR = 0.35;

    private static final double EMA_ALPHA_BASE = 0.2;
    private static final double EMA_ALPHA_FAST = 0.35;
    private static final double SUSPICION_ENTER_THRESHOLD = 0.28;
    private static final double SUSPICION_EXIT_THRESHOLD = 0.18;
    private static final int INTERVAL_GRACE_FRAMES = 8;
    private static final double MIN_INTERVAL_DURATION_SEC = 3.0;
    private static final double MIN_INTERVAL_AVG_CONFIDENCE = 0.33;
    private static final double MERGE_GAP_SEC = 5.0;
    private static final double BASELINE_LOCK_SEC = 60.0;
    private static final double BASELINE_LOCK_MIN_SEC = 15.0;

    private static final double TEACHER_MIN_CUMULATIVE_TRAVEL_PX = 800.0;
    private static final double TEACHER_MIN_SPATIAL_VARIANCE = 15000.0;
    private static final double TEACHER_MIN_TRACK_AGE_SEC = 30.0;
    private static final double TEACHER_POSITION_TOP_FRACTION = 0.20;
    private static final double TEACHER_POSITION_MIN_TRAVEL_FALLBACK_PX = 300.0;
    private static final double TEACHER_PROXIMITY_SUPPRESSION_RADIUS = 120.0;

    private static final double SIMULTANEOUS_SUPPRESSION_SCORE_THRESHOLD = 0.50;
    private static final int SIMULTANEOUS_SUPPRESSION_MIN_TRACKS = 3;
    private static final double SIMULTANEOUS_SUPPRESSION_FRACTION = 0.60;

    public AnalysisResponse run(Path jobDir, String examId) throws IOException {
        return run(
                jobDir,
                examId,
                "phase2_results.json",
                "phase2_stats.json",
                "phase2_frame_scores.jsonl");
    }

    public AnalysisResponse run(
            Path jobDir,
            String examId,
            String resultsFileName,
            String statsFileName,
            String frameScoresFileName) throws IOException {
        Path featuresPath = jobDir.resolve("phase1_features.jsonl");
        Path trackMetaPath = jobDir.resolve("phase1_track_meta.json");
        Path outResultsPath = jobDir.resolve(resultsFileName);
        Path outStatsPath = jobDir.resolve(statsFileName);
        Path outFrameScoresPath = jobDir.resolve(frameScoresFileName);

        if (!Files.exists(featuresPath) || !Files.exists(trackMetaPath)) {
            throw new IOException("Missing Phase 1 artifacts in " + jobDir);
        }

        Map<Integer, TrackMeta> trackMeta = loadTrackMeta(trackMetaPath);
        List<FeatureRecord> records = loadFeatureRecords(featuresPath);

        JsonObject phase1Stats = readJsonObjectIfExists(jobDir.resolve("phase1_stats.json"));
        double durationSec = getDouble(phase1Stats, "duration_sec", 3600.0);
        int fpsSampling = (int) getDouble(phase1Stats, "fps_sampling", 5.0);
        double actualSamplingRate = getDouble(phase1Stats, "actual_sampling_rate", fpsSampling);
        double durationRatio = clamp(durationSec / 3600.0, 0.1, 1.0);

        double effectiveAlpha = actualSamplingRate >= 10.0 ? EMA_ALPHA_FAST : EMA_ALPHA_BASE;
        double effectiveMinLifespanSec = Math.max(Math.max(1.0, durationSec * 0.10),
                MIN_TRACK_LIFESPAN_SEC * durationRatio);
        double effectiveBaselineWindowSec = Math.max(3.0, BASELINE_WINDOW_SEC * durationRatio);
        int effectiveMinBaselineSamples = Math.max(3, (int) Math.round(MIN_BASELINE_SAMPLES * durationRatio));
        double effectiveTeacherMinAgeSec = Math.max(5.0, TEACHER_MIN_TRACK_AGE_SEC * durationRatio);
        double effectiveMinIntervalDurationSec = clamp(Math.max(0.5, durationSec * 0.05), 0.5,
                MIN_INTERVAL_DURATION_SEC);
        double effectiveBaselineLockSec = Math.max(Math.min(BASELINE_LOCK_MIN_SEC, durationSec * 0.20),
                BASELINE_LOCK_SEC * durationRatio);

        Map<Integer, List<FeatureRecord>> byTrack = new HashMap<>();
        for (FeatureRecord rec : records) {
            byTrack.computeIfAbsent(rec.trackId, ignored -> new ArrayList<>()).add(rec);
        }
        byTrack.values().forEach(list -> list.sort(Comparator.comparingDouble(r -> r.timestamp)));

        Integer teacherTrackId = detectTeacherTrack(
                byTrack,
                trackMeta,
                effectiveTeacherMinAgeSec,
                effectiveMinLifespanSec);

        List<TrackResult> outputTracks = new ArrayList<>();
        Map<String, Object> stats = new LinkedHashMap<>();
        stats.put("total_feature_records", records.size());
        stats.put("discarded_tracks", 0);
        stats.put("kept_tracks", 0);
        stats.put("track_discard_reasons", new LinkedHashMap<String, String>());
        stats.put("teacher_track_id", teacherTrackId);
        stats.put("frames_pose_unavailable", 0);
        stats.put("frames_baseline_not_ready", 0);
        stats.put("intervals_created", 0);
        stats.put("intervals_discarded_duration", 0);
        stats.put("intervals_discarded_confidence", 0);
        stats.put("phase2_scaled", Map.of(
                "duration_sec", durationSec,
                "duration_ratio", durationRatio,
                "effective_alpha", effectiveAlpha,
                "effective_min_lifespan_sec", effectiveMinLifespanSec,
                "effective_baseline_window_sec", effectiveBaselineWindowSec,
                "effective_min_baseline_samples", effectiveMinBaselineSamples,
                "effective_teacher_min_age_sec", effectiveTeacherMinAgeSec,
                "effective_min_interval_duration_sec", effectiveMinIntervalDurationSec,
                "effective_baseline_lock_sec", effectiveBaselineLockSec));

        int idSwitchTotal = 0;
        Set<Integer> keptTrackIds = new HashSet<>();

        Map<Double, Point> teacherCentroidByTs = teacherTrackId == null
                ? new HashMap<>()
                : centroidByTimestamp(byTrack.getOrDefault(teacherTrackId, List.of()));

        Map<Integer, List<FrameEval>> evalsByTrack = new HashMap<>();
        Map<Double, List<FrameEval>> evalsByTs = new HashMap<>();

        Files.createDirectories(outFrameScoresPath.getParent());
        for (Map.Entry<Integer, List<FeatureRecord>> entry : byTrack.entrySet()) {
            int trackId = entry.getKey();
            TrackMeta meta = trackMeta.get(trackId);
            if (meta == null) {
                continue;
            }

            if (teacherTrackId != null && teacherTrackId == trackId) {
                increment(stats, "discarded_tracks");
                putDiscardReason(stats, trackId, "teacher_track_excluded");
                continue;
            }

            if (meta.stabilityScore < TRACK_STABILITY_MIN_SCORE
                    || meta.totalVisibleDurationSec < effectiveMinLifespanSec) {
                increment(stats, "discarded_tracks");
                if (meta.stabilityScore < TRACK_STABILITY_MIN_SCORE) {
                    putDiscardReason(stats, trackId, "stability_score<" + TRACK_STABILITY_MIN_SCORE);
                } else {
                    putDiscardReason(stats, trackId,
                            "total_visible_duration<" + String.format("%.2f", effectiveMinLifespanSec));
                }
                continue;
            }
            increment(stats, "kept_tracks");
            keptTrackIds.add(trackId);
            idSwitchTotal += meta.idSwitchCount;

            TrackState state = new TrackState();
            List<FeatureRecord> trackRecords = entry.getValue();
            List<FrameEval> trackEvals = new ArrayList<>();

            for (FeatureRecord rec : trackRecords) {
                Double baselineYaw = median(state.baselineYaw, effectiveMinBaselineSamples);
                Double baselineGaze = median(state.baselineGaze, effectiveMinBaselineSamples);
                Double baselineDist = median(state.baselineDist, effectiveMinBaselineSamples);
                Double baselineYawLong = median(state.baselineYawLong, effectiveMinBaselineSamples);
                boolean baselineReady = baselineYaw != null
                        && baselineGaze != null
                        && state.baselineYaw.size() >= BASELINE_MIN_ABSOLUTE_SAMPLES;

                double headSignal = 0.0;
                double gazeSignal = 0.0;
                double proxSignal = 0.0;
                double driftSignal = 0.0;
                double confidenceWeight = 0.0;
                double rawSignalScore = 0.0;
                int headDevFlag = 0;
                int gazeDevFlag = 0;
                boolean poseAvailable = rec.pose != null;

                if (rec.pose == null) {
                    increment(stats, "frames_pose_unavailable");
                } else {
                    double rawConf = Math.min(rec.quality.visibilityScore, rec.pose.headPoseConfidence);

                    // baseline update
                    boolean baselineCalibrationOk = rec.timestamp <= effectiveBaselineLockSec;
                    if (baselineCalibrationOk && rawConf >= SOFT_GATE_FLOOR) {
                        state.baselineYaw.addLast(new TimedValue(rec.timestamp, rec.pose.yaw));
                        state.baselineGaze.addLast(new TimedValue(rec.timestamp, rec.pose.gazeX));
                        state.baselineYawLong.addLast(new TimedValue(rec.timestamp, rec.pose.yaw));
                        if (rec.proximity.nearestNeighborDistance != null) {
                            state.baselineDist
                                    .addLast(new TimedValue(rec.timestamp, rec.proximity.nearestNeighborDistance));
                        }
                    }

                    pruneWindow(state.baselineYaw, rec.timestamp, effectiveBaselineWindowSec);
                    pruneWindow(state.baselineGaze, rec.timestamp, effectiveBaselineWindowSec);
                    pruneWindow(state.baselineDist, rec.timestamp, effectiveBaselineWindowSec);
                    pruneWindow(state.baselineYawLong, rec.timestamp, 300.0);

                    baselineYaw = median(state.baselineYaw, effectiveMinBaselineSamples);
                    baselineGaze = median(state.baselineGaze, effectiveMinBaselineSamples);
                    baselineDist = median(state.baselineDist, effectiveMinBaselineSamples);
                    baselineYawLong = median(state.baselineYawLong, effectiveMinBaselineSamples);
                    baselineReady = baselineYaw != null
                            && baselineGaze != null
                            && state.baselineYaw.size() >= BASELINE_MIN_ABSOLUTE_SAMPLES;

                    if (baselineReady) {
                        if (rec.pose.headPoseConfidence >= MIN_POSE_CONFIDENCE) {
                            headSignal = clamp(Math.abs(rec.pose.yaw - baselineYaw) / HEAD_DEV_NORM_DEG);
                        }
                        if (rec.pose.gazeReliability >= MIN_POSE_CONFIDENCE) {
                            gazeSignal = clamp(Math.abs(rec.pose.gazeX - baselineGaze) / GAZE_DEV_NORM);
                        }
                        if (baselineDist != null && rec.proximity.nearestNeighborDistance != null
                                && baselineDist > 0.0) {
                            double threshold = baselineDist * PROXIMITY_DISTANCE_RATIO_THRESHOLD;
                            if (threshold > 1e-6 && rec.proximity.nearestNeighborDistance <= threshold) {
                                proxSignal = clamp((threshold - rec.proximity.nearestNeighborDistance) / threshold);
                            }
                        }
                        if (baselineYawLong != null) {
                            driftSignal = clamp(Math.abs(baselineYaw - baselineYawLong) / HEAD_DEV_NORM_DEG);
                        }

                        double effectiveHeadWeight = HEAD_WEIGHT;
                        double effectiveGazeWeight = GAZE_WEIGHT;
                        if ("body_pose_landmarks".equals(rec.estimationMode)) {
                            effectiveHeadWeight += effectiveGazeWeight;
                            effectiveGazeWeight = 0.0;
                        }

                        rawSignalScore = clamp(
                                effectiveHeadWeight * headSignal
                                        + effectiveGazeWeight * gazeSignal
                                        + PROX_WEIGHT * proxSignal
                                        + DRIFT_WEIGHT * driftSignal);
                        if ("bbox_proxy_face_not_visible".equals(rec.estimationMode)) {
                            rawSignalScore = clamp(rawSignalScore * 0.5);
                        }

                        headDevFlag = headSignal >= SIGNAL_FLAG_THRESHOLD ? 1 : 0;
                        gazeDevFlag = gazeSignal >= SIGNAL_FLAG_THRESHOLD ? 1 : 0;

                        if (rawConf <= SOFT_GATE_FLOOR) {
                            confidenceWeight = SOFT_GATE_MIN_WEIGHT;
                        } else {
                            double t = (rawConf - SOFT_GATE_FLOOR) / (1.0 - SOFT_GATE_FLOOR);
                            confidenceWeight = SOFT_GATE_MIN_WEIGHT + t * (1.0 - SOFT_GATE_MIN_WEIGHT);
                        }
                        confidenceWeight = clamp(Math.max(confidenceWeight, MIN_CONFIDENCE_WEIGHT_FLOOR));
                    } else {
                        increment(stats, "frames_baseline_not_ready");
                    }
                }

                FrameEval eval = new FrameEval();
                eval.trackId = trackId;
                eval.timestamp = rec.timestamp;
                eval.rawSignalScore = rawSignalScore;
                eval.confidenceWeight = confidenceWeight;
                eval.headSignal = headSignal;
                eval.gazeSignal = gazeSignal;
                eval.proxSignal = proxSignal;
                eval.driftSignal = driftSignal;
                eval.baselineReady = baselineReady;
                eval.baselineYawLen = state.baselineYaw.size();
                eval.headDevFlag = headDevFlag;
                eval.gazeDevFlag = gazeDevFlag;
                eval.poseAvailable = poseAvailable;
                eval.nearestDistance = rec.proximity.nearestNeighborDistance;
                eval.estimationMode = rec.estimationMode;
                eval.visibilityScore = rec.quality.visibilityScore;
                eval.occlusionScore = rec.quality.occlusionScore;
                eval.gazeReliability = rec.pose == null ? 0.0 : rec.pose.gazeReliability;
                eval.centroid = rec.bbox == null ? null
                        : new Point((rec.bbox[0] + rec.bbox[2]) * 0.5, (rec.bbox[1] + rec.bbox[3]) * 0.5);

                trackEvals.add(eval);
                evalsByTs.computeIfAbsent(eval.timestamp, ignored -> new ArrayList<>()).add(eval);
            }

            evalsByTrack.put(trackId, trackEvals);
        }

        stats.put("frames_suppressed_whole_class_event", 0);
        stats.put("frames_suppressed_teacher_proximity", 0);

        for (Map.Entry<Double, List<FrameEval>> e : evalsByTs.entrySet()) {
            List<FrameEval> items = e.getValue();
            int activeTrackCount = items.size();
            int flaggedCount = (int) items.stream()
                    .filter(item -> item.rawSignalScore > SIMULTANEOUS_SUPPRESSION_SCORE_THRESHOLD).count();
            int matureCount = (int) items.stream().filter(item -> item.baselineReady && item.baselineYawLen >= 8)
                    .count();
            double matureFraction = activeTrackCount > 0 ? (double) matureCount / activeTrackCount : 0.0;

            boolean wholeClassEvent = activeTrackCount >= SIMULTANEOUS_SUPPRESSION_MIN_TRACKS
                    && activeTrackCount > 0
                    && ((double) flaggedCount / activeTrackCount) >= SIMULTANEOUS_SUPPRESSION_FRACTION
                    && matureFraction >= 0.5;
            if (wholeClassEvent) {
                for (FrameEval item : items) {
                    item.suppressedWholeClassEvent = true;
                    increment(stats, "frames_suppressed_whole_class_event");
                }
            }

            Point teacherCentroid = teacherCentroidByTs.get(e.getKey());
            if (teacherCentroid != null) {
                for (FrameEval item : items) {
                    if (item.centroid == null) {
                        continue;
                    }
                    double dx = item.centroid.x - teacherCentroid.x;
                    double dy = item.centroid.y - teacherCentroid.y;
                    double dist = Math.sqrt(dx * dx + dy * dy);
                    if (dist < TEACHER_PROXIMITY_SUPPRESSION_RADIUS) {
                        item.suppressedTeacherProximity = true;
                        increment(stats, "frames_suppressed_teacher_proximity");
                    }
                }
            }
        }

        try (BufferedWriter frameWriter = Files.newBufferedWriter(outFrameScoresPath, StandardCharsets.UTF_8)) {
            for (int trackId : keptTrackIds) {
                TrackMeta meta = trackMeta.get(trackId);
                if (meta == null) {
                    continue;
                }
                List<FrameEval> trackEvals = evalsByTrack.getOrDefault(trackId, List.of());
                trackEvals.sort(Comparator.comparingDouble(f -> f.timestamp));

                TrackState state = new TrackState();
                List<SuspiciousInterval> intervals = new ArrayList<>();
                for (FrameEval eval : trackEvals) {
                    boolean suppressed = eval.suppressedWholeClassEvent || eval.suppressedTeacherProximity;
                    double finalScore = suppressed ? 0.0 : (eval.rawSignalScore * eval.confidenceWeight);
                    state.ema = effectiveAlpha * finalScore + (1.0 - effectiveAlpha) * state.ema;

                    JsonObject frame = new JsonObject();
                    frame.addProperty("timestamp", eval.timestamp);
                    frame.addProperty("track_id", eval.trackId);
                    frame.addProperty("final_score", finalScore);
                    frame.addProperty("raw_signal_score", eval.rawSignalScore);
                    frame.addProperty("confidence_weight", eval.confidenceWeight);
                    frame.addProperty("head_signal", eval.headSignal);
                    frame.addProperty("gaze_signal", eval.gazeSignal);
                    frame.addProperty("proximity_signal", eval.proxSignal);
                    frame.addProperty("drift_signal", eval.driftSignal);
                    frame.addProperty("baseline_ready", eval.baselineReady);
                    frame.addProperty("head_dev_flag", eval.headDevFlag == 1);
                    frame.addProperty("gaze_dev_flag", eval.gazeDevFlag == 1);
                    frame.addProperty("suppressed_whole_class_event", eval.suppressedWholeClassEvent);
                    frame.addProperty("suppressed_teacher_proximity", eval.suppressedTeacherProximity);
                    frame.addProperty("visibility_score", eval.visibilityScore);
                    frame.addProperty("occlusion_score", eval.occlusionScore);
                    frame.addProperty("gaze_reliability", eval.gazeReliability);
                    if (eval.estimationMode != null) {
                        frame.addProperty("estimation_mode", eval.estimationMode);
                    }
                    frameWriter.write(GSON.toJson(frame));
                    frameWriter.write("\n");

                    if (state.intervalOpen && state.interval != null) {
                        state.interval.end = eval.timestamp;
                        if (!suppressed) {
                            state.interval.frameCount += 1;
                            state.interval.sumScore += finalScore;
                            state.interval.peakScore = Math.max(state.interval.peakScore, finalScore);
                            state.interval.sumConfidence += eval.confidenceWeight;
                            if (eval.baselineReady && eval.poseAvailable && eval.confidenceWeight > 0.0) {
                                state.interval.headSignalSum += eval.headSignal;
                                state.interval.gazeSignalSum += eval.gazeSignal;
                                state.interval.proxSignalSum += eval.proxSignal;
                                state.interval.driftSignalSum += eval.driftSignal;
                                state.interval.componentFrames += 1;
                                state.interval.headDeviationFlags += eval.headDevFlag;
                                state.interval.gazeDeviationFlags += eval.gazeDevFlag;
                                if (eval.nearestDistance != null) {
                                    state.interval.proximityDistanceSum += eval.nearestDistance;
                                    state.interval.proximityDistanceCount += 1;
                                    if (state.interval.proximityDistanceMin == null) {
                                        state.interval.proximityDistanceMin = eval.nearestDistance;
                                    } else {
                                        state.interval.proximityDistanceMin = Math
                                                .min(state.interval.proximityDistanceMin, eval.nearestDistance);
                                    }
                                }
                            }
                        }

                        if (state.ema <= SUSPICION_EXIT_THRESHOLD) {
                            if (state.graceFrames <= 0) {
                                state.graceFrames = INTERVAL_GRACE_FRAMES;
                                state.intervalExitTs = eval.timestamp;
                            } else {
                                state.graceFrames -= 1;
                                if (state.graceFrames <= 0) {
                                    state.interval.end = state.intervalExitTs;
                                    maybeFinalizeInterval(state.interval, intervals, stats,
                                            effectiveMinIntervalDurationSec);
                                    state.intervalOpen = false;
                                    state.interval = null;
                                }
                            }
                        } else {
                            state.graceFrames = 0;
                        }
                    }

                    if (!state.intervalOpen && state.ema >= SUSPICION_ENTER_THRESHOLD) {
                        state.intervalOpen = true;
                        state.graceFrames = 0;
                        state.interval = new IntervalAcc();
                        state.interval.start = eval.timestamp;
                        state.interval.end = eval.timestamp;
                        if (!suppressed) {
                            state.interval.frameCount = 1;
                            state.interval.sumScore = finalScore;
                            state.interval.peakScore = finalScore;
                            state.interval.sumConfidence = eval.confidenceWeight;
                            if (eval.baselineReady && eval.poseAvailable && eval.confidenceWeight > 0.0) {
                                state.interval.headSignalSum = eval.headSignal;
                                state.interval.gazeSignalSum = eval.gazeSignal;
                                state.interval.proxSignalSum = eval.proxSignal;
                                state.interval.driftSignalSum = eval.driftSignal;
                                state.interval.componentFrames = 1;
                                state.interval.headDeviationFlags = eval.headDevFlag;
                                state.interval.gazeDeviationFlags = eval.gazeDevFlag;
                                if (eval.nearestDistance != null) {
                                    state.interval.proximityDistanceSum = eval.nearestDistance;
                                    state.interval.proximityDistanceCount = 1;
                                    state.interval.proximityDistanceMin = eval.nearestDistance;
                                }
                            }
                        }
                    }
                }

                if (state.intervalOpen && state.interval != null) {
                    maybeFinalizeInterval(state.interval, intervals, stats, effectiveMinIntervalDurationSec);
                }

                intervals = mergeIntervals(intervals);
                outputTracks
                        .add(new TrackResult(trackId, meta.totalVisibleDurationSec, meta.stabilityScore, intervals));
            }
        }

        outputTracks.sort(Comparator.comparingInt(TrackResult::getTrackId));
        stats.put("tracking_id_switch_count_total", idSwitchTotal);

        AnalysisResponse response = new AnalysisResponse();
        response.setExamId(examId);
        response.setResults(outputTracks);
        response.setObservability(stats);

        Files.writeString(outResultsPath, GSON.toJson(response), StandardCharsets.UTF_8);
        Files.writeString(outStatsPath, GSON.toJson(stats), StandardCharsets.UTF_8);
        return response;
    }

    private static void maybeFinalizeInterval(
            IntervalAcc acc,
            List<SuspiciousInterval> out,
            Map<String, Object> stats,
            double effectiveMinIntervalDurationSec) {
        double duration = acc.end - acc.start;
        if (duration < effectiveMinIntervalDurationSec) {
            increment(stats, "intervals_discarded_duration");
            return;
        }
        if (acc.frameCount <= 0) {
            increment(stats, "intervals_discarded_duration");
            return;
        }

        double avgConfidence = acc.sumConfidence / acc.frameCount;
        if (avgConfidence < MIN_INTERVAL_AVG_CONFIDENCE) {
            increment(stats, "intervals_discarded_confidence");
            return;
        }

        SuspiciousInterval it = new SuspiciousInterval();
        it.setStart(acc.start);
        it.setEnd(acc.end);
        it.setDuration(duration);
        it.setPeakScore(acc.peakScore);
        it.setAvgScore(acc.sumScore / acc.frameCount);
        it.setConfidence(avgConfidence);

        double headAvg = acc.componentFrames > 0 ? acc.headSignalSum / acc.componentFrames : 0.0;
        double gazeAvg = acc.componentFrames > 0 ? acc.gazeSignalSum / acc.componentFrames : 0.0;
        double proxAvg = acc.componentFrames > 0 ? acc.proxSignalSum / acc.componentFrames : 0.0;
        double driftAvg = acc.componentFrames > 0 ? acc.driftSignalSum / acc.componentFrames : 0.0;
        List<Map.Entry<String, Double>> components = new ArrayList<>();
        components.add(Map.entry("HeadDeviation", headAvg));
        components.add(Map.entry("GazeDeviation", gazeAvg));
        components.add(Map.entry("ProximityAnomaly", proxAvg));
        components.add(Map.entry("SustainedDrift", driftAvg));
        components.sort((a, b) -> Double.compare(b.getValue(), a.getValue()));
        List<String> dominant = components.stream()
                .limit(3)
                .filter(x -> x.getValue() > 0.0)
                .map(Map.Entry::getKey)
                .collect(Collectors.toList());
        if (dominant.isEmpty() && !components.isEmpty()) {
            dominant = List.of(components.get(0).getKey());
        }
        it.setDominantSignals(dominant);

        JsonObject ss = new JsonObject();
        ss.addProperty("head_deviation_pct",
                acc.frameCount > 0 ? (double) acc.headDeviationFlags / acc.frameCount : 0.0);
        ss.addProperty("gaze_deviation_pct",
                acc.frameCount > 0 ? (double) acc.gazeDeviationFlags / acc.frameCount : 0.0);
        if (acc.proximityDistanceCount > 0) {
            ss.addProperty("proximity_avg_distance", acc.proximityDistanceSum / acc.proximityDistanceCount);
        } else {
            ss.add("proximity_avg_distance", null);
        }
        if (acc.proximityDistanceMin != null) {
            ss.addProperty("proximity_min_distance", acc.proximityDistanceMin);
        } else {
            ss.add("proximity_min_distance", null);
        }
        it.setSupportingStats(GSON.fromJson(ss, SuspiciousInterval.SupportingStats.class));

        out.add(it);
        increment(stats, "intervals_created");
    }

    private static List<SuspiciousInterval> mergeIntervals(List<SuspiciousInterval> intervals) {
        if (intervals.size() <= 1) {
            return intervals;
        }
        List<SuspiciousInterval> sorted = new ArrayList<>(intervals);
        sorted.sort(Comparator.comparingDouble(SuspiciousInterval::getStart));

        List<SuspiciousInterval> merged = new ArrayList<>();
        for (SuspiciousInterval curr : sorted) {
            if (merged.isEmpty()) {
                merged.add(curr);
                continue;
            }
            SuspiciousInterval prev = merged.get(merged.size() - 1);
            double gap = curr.getStart() - prev.getEnd();
            if (gap <= MERGE_GAP_SEC) {
                SuspiciousInterval m = new SuspiciousInterval();
                m.setStart(prev.getStart());
                m.setEnd(curr.getEnd());
                m.setDuration(curr.getEnd() - prev.getStart());
                m.setPeakScore(Math.max(prev.getPeakScore(), curr.getPeakScore()));
                double prevDur = Math.max(1e-6, prev.getDuration());
                double currDur = Math.max(1e-6, curr.getDuration());
                double totalDur = prevDur + currDur;
                m.setAvgScore(((prev.getAvgScore() * prevDur) + (curr.getAvgScore() * currDur)) / totalDur);
                m.setConfidence(((prev.getConfidence() * prevDur) + (curr.getConfidence() * currDur)) / totalDur);

                LinkedHashSet<String> dom = new LinkedHashSet<>();
                if (prev.getDominantSignals() != null)
                    dom.addAll(prev.getDominantSignals());
                if (curr.getDominantSignals() != null)
                    dom.addAll(curr.getDominantSignals());
                m.setDominantSignals(new ArrayList<>(dom));
                if (prev.getSupportingStats() != null && curr.getSupportingStats() != null) {
                    JsonObject ss = new JsonObject();
                    ss.addProperty(
                            "head_deviation_pct",
                            ((prev.getSupportingStats().getHeadDeviationPct() * prevDur)
                                    + (curr.getSupportingStats().getHeadDeviationPct() * currDur)) / totalDur);
                    ss.addProperty(
                            "gaze_deviation_pct",
                            ((prev.getSupportingStats().getGazeDeviationPct() * prevDur)
                                    + (curr.getSupportingStats().getGazeDeviationPct() * currDur)) / totalDur);
                    Double pAvgA = prev.getSupportingStats().getProximityAvgDistance();
                    Double pAvgB = curr.getSupportingStats().getProximityAvgDistance();
                    if (pAvgA == null && pAvgB == null) {
                        ss.add("proximity_avg_distance", null);
                    } else if (pAvgA == null) {
                        ss.addProperty("proximity_avg_distance", pAvgB);
                    } else if (pAvgB == null) {
                        ss.addProperty("proximity_avg_distance", pAvgA);
                    } else {
                        ss.addProperty("proximity_avg_distance", ((pAvgA * prevDur) + (pAvgB * currDur)) / totalDur);
                    }
                    Double pMinA = prev.getSupportingStats().getProximityMinDistance();
                    Double pMinB = curr.getSupportingStats().getProximityMinDistance();
                    if (pMinA == null && pMinB == null) {
                        ss.add("proximity_min_distance", null);
                    } else if (pMinA == null) {
                        ss.addProperty("proximity_min_distance", pMinB);
                    } else if (pMinB == null) {
                        ss.addProperty("proximity_min_distance", pMinA);
                    } else {
                        ss.addProperty("proximity_min_distance", Math.min(pMinA, pMinB));
                    }
                    m.setSupportingStats(GSON.fromJson(ss, SuspiciousInterval.SupportingStats.class));
                } else {
                    m.setSupportingStats(
                            prev.getSupportingStats() != null ? prev.getSupportingStats() : curr.getSupportingStats());
                }
                merged.set(merged.size() - 1, m);
            } else {
                merged.add(curr);
            }
        }
        return merged;
    }

    private static JsonObject readJsonObjectIfExists(Path path) throws IOException {
        if (!Files.exists(path)) {
            return new JsonObject();
        }
        return JsonParser.parseString(Files.readString(path, StandardCharsets.UTF_8)).getAsJsonObject();
    }

    private static Map<Integer, TrackMeta> loadTrackMeta(Path path) throws IOException {
        JsonArray arr = JsonParser.parseString(Files.readString(path, StandardCharsets.UTF_8)).getAsJsonArray();
        Map<Integer, TrackMeta> out = new HashMap<>();
        for (JsonElement el : arr) {
            JsonObject o = el.getAsJsonObject();
            TrackMeta m = new TrackMeta();
            m.trackId = getInt(o, "track_id", -1);
            m.totalVisibleDurationSec = getDouble(o, "total_visible_duration_sec", 0.0);
            m.stabilityScore = getDouble(o, "stability_score", 0.0);
            m.idSwitchCount = getInt(o, "id_switch_count", 0);
            out.put(m.trackId, m);
        }
        return out;
    }

    private static List<FeatureRecord> loadFeatureRecords(Path path) throws IOException {
        List<FeatureRecord> out = new ArrayList<>();
        try (BufferedReader br = Files.newBufferedReader(path, StandardCharsets.UTF_8)) {
            String line;
            while ((line = br.readLine()) != null) {
                if (line.isBlank()) {
                    continue;
                }
                JsonObject o = JsonParser.parseString(line).getAsJsonObject();
                FeatureRecord r = new FeatureRecord();
                r.timestamp = getDouble(o, "timestamp", 0.0);
                r.trackId = getInt(o, "track_id", -1);
                r.estimationMode = getString(o, "estimation_mode", "");
                JsonArray bbox = o.has("bbox") && o.get("bbox").isJsonArray() ? o.getAsJsonArray("bbox") : null;
                if (bbox != null && bbox.size() == 4) {
                    r.bbox = new double[] {
                            bbox.get(0).getAsDouble(),
                            bbox.get(1).getAsDouble(),
                            bbox.get(2).getAsDouble(),
                            bbox.get(3).getAsDouble(),
                    };
                }

                JsonObject poseObj = getObj(o, "pose");
                if (poseObj != null) {
                    r.pose = new Pose();
                    r.pose.yaw = getDouble(poseObj, "yaw", 0.0);
                    r.pose.gazeX = getDouble(poseObj, "gaze_x", 0.0);
                    r.pose.headPoseConfidence = getDouble(poseObj, "head_pose_confidence", 0.0);
                    r.pose.gazeReliability = getDouble(poseObj, "gaze_reliability", 0.0);
                }

                JsonObject qualityObj = getObj(o, "quality");
                r.quality = new Quality();
                r.quality.visibilityScore = qualityObj == null ? 0.0 : getDouble(qualityObj, "visibility_score", 0.0);
                r.quality.occlusionScore = qualityObj == null ? 0.0 : getDouble(qualityObj, "occlusion_score", 0.0);

                JsonObject proxObj = getObj(o, "proximity");
                r.proximity = new Proximity();
                r.proximity.nearestNeighborDistance = proxObj == null ? null
                        : getNullableDouble(proxObj, "nearest_neighbor_distance");

                out.add(r);
            }
        }
        return out;
    }

    private static JsonObject getObj(JsonObject o, String key) {
        if (!o.has(key) || o.get(key).isJsonNull() || !o.get(key).isJsonObject()) {
            return null;
        }
        return o.getAsJsonObject(key);
    }

    private static void pruneWindow(Deque<TimedValue> deque, double ts, double windowSec) {
        while (!deque.isEmpty() && (ts - deque.peekFirst().timestamp) > windowSec) {
            deque.removeFirst();
        }
    }

    private static Double median(Deque<TimedValue> deque, int minSamples) {
        if (deque.size() < minSamples) {
            return null;
        }
        List<Double> vals = deque.stream().map(tv -> tv.value).sorted().collect(Collectors.toList());
        int n = vals.size();
        if (n == 0) {
            return null;
        }
        if (n % 2 == 1) {
            return vals.get(n / 2);
        }
        return (vals.get(n / 2 - 1) + vals.get(n / 2)) * 0.5;
    }

    private static double clamp(double v) {
        return Math.max(0.0, Math.min(1.0, v));
    }

    private static double clamp(double v, double lo, double hi) {
        return Math.max(lo, Math.min(hi, v));
    }

    private static void increment(Map<String, Object> stats, String key) {
        Number n = (Number) stats.getOrDefault(key, 0);
        stats.put(key, n.intValue() + 1);
    }

    private static int getInt(JsonObject o, String key, int def) {
        if (o == null || !o.has(key) || o.get(key).isJsonNull())
            return def;
        try {
            return o.get(key).getAsInt();
        } catch (Exception ignored) {
            return def;
        }
    }

    private static double getDouble(JsonObject o, String key, double def) {
        if (o == null || !o.has(key) || o.get(key).isJsonNull())
            return def;
        try {
            return o.get(key).getAsDouble();
        } catch (Exception ignored) {
            return def;
        }
    }

    private static Double getNullableDouble(JsonObject o, String key) {
        if (o == null || !o.has(key) || o.get(key).isJsonNull())
            return null;
        try {
            return o.get(key).getAsDouble();
        } catch (Exception ignored) {
            return null;
        }
    }

    private static String getString(JsonObject o, String key, String def) {
        if (o == null || !o.has(key) || o.get(key).isJsonNull())
            return def;
        try {
            return o.get(key).getAsString();
        } catch (Exception ignored) {
            return def;
        }
    }

    private static class TrackMeta {
        int trackId;
        double totalVisibleDurationSec;
        double stabilityScore;
        int idSwitchCount;
    }

    private static class FeatureRecord {
        double timestamp;
        int trackId;
        String estimationMode;
        double[] bbox;
        Pose pose;
        Quality quality;
        Proximity proximity;
    }

    private static class Pose {
        double yaw;
        double gazeX;
        double headPoseConfidence;
        double gazeReliability;
    }

    private static class Quality {
        double visibilityScore;
        double occlusionScore;
    }

    private static class Proximity {
        Double nearestNeighborDistance;
    }

    private static class TimedValue {
        final double timestamp;
        final double value;

        private TimedValue(double timestamp, double value) {
            this.timestamp = timestamp;
            this.value = value;
        }
    }

    private static class IntervalAcc {
        double start;
        double end;
        int frameCount;
        double sumScore;
        double peakScore;
        double sumConfidence;
        double headSignalSum;
        double gazeSignalSum;
        double proxSignalSum;
        double driftSignalSum;
        int componentFrames;
        int headDeviationFlags;
        int gazeDeviationFlags;
        double proximityDistanceSum;
        int proximityDistanceCount;
        Double proximityDistanceMin;
    }

    private static class TrackState {
        final Deque<TimedValue> baselineYaw = new ArrayDeque<>();
        final Deque<TimedValue> baselineGaze = new ArrayDeque<>();
        final Deque<TimedValue> baselineDist = new ArrayDeque<>();
        final Deque<TimedValue> baselineYawLong = new ArrayDeque<>();

        double ema = 0.0;
        boolean intervalOpen = false;
        int graceFrames = 0;
        double intervalExitTs = 0.0;
        IntervalAcc interval;
    }

    private static class FrameEval {
        int trackId;
        double timestamp;
        double rawSignalScore;
        double confidenceWeight;
        double headSignal;
        double gazeSignal;
        double proxSignal;
        double driftSignal;
        boolean baselineReady;
        int baselineYawLen;
        int headDevFlag;
        int gazeDevFlag;
        boolean poseAvailable;
        Double nearestDistance;
        String estimationMode;
        double visibilityScore;
        double occlusionScore;
        double gazeReliability;
        Point centroid;
        boolean suppressedWholeClassEvent;
        boolean suppressedTeacherProximity;
    }

    private static Integer detectTeacherTrack(
            Map<Integer, List<FeatureRecord>> byTrack,
            Map<Integer, TrackMeta> trackMeta,
            double effectiveTeacherMinAgeSec,
            double effectiveMinLifespanSec) {
        List<TeacherCandidate> candidates = new ArrayList<>();
        double frameHeight = 1080.0;

        for (Map.Entry<Integer, List<FeatureRecord>> entry : byTrack.entrySet()) {
            int tid = entry.getKey();
            TrackMeta preGateMeta = trackMeta.get(tid);
            if (preGateMeta == null) {
                continue;
            }
            if (preGateMeta.stabilityScore < TRACK_STABILITY_MIN_SCORE
                    || preGateMeta.totalVisibleDurationSec < effectiveMinLifespanSec) {
                continue;
            }

            List<Point> points = toCentroids(entry.getValue());
            if (points.size() < 2) {
                continue;
            }

            double travel = cumulativeTravel(points);
            double spatialVar = spatialVariance(points);
            TrackMeta meta = trackMeta.get(tid);
            double age = meta == null ? 0.0 : meta.totalVisibleDurationSec;

            if (age >= effectiveTeacherMinAgeSec
                    && travel >= TEACHER_MIN_CUMULATIVE_TRAVEL_PX
                    && spatialVar >= TEACHER_MIN_SPATIAL_VARIANCE) {
                candidates.add(new TeacherCandidate(tid, travel, spatialVar));
            }

            for (FeatureRecord r : entry.getValue()) {
                if (r.bbox != null && r.bbox.length == 4) {
                    frameHeight = Math.max(frameHeight, r.bbox[3]);
                }
            }
        }

        if (candidates.isEmpty()) {
            double topThreshold = frameHeight * TEACHER_POSITION_TOP_FRACTION;
            double bottomThreshold = frameHeight * (1.0 - TEACHER_POSITION_TOP_FRACTION);
            for (Map.Entry<Integer, List<FeatureRecord>> entry : byTrack.entrySet()) {
                int tid = entry.getKey();
                TrackMeta preGateMeta = trackMeta.get(tid);
                if (preGateMeta == null) {
                    continue;
                }
                if (preGateMeta.stabilityScore < TRACK_STABILITY_MIN_SCORE
                        || preGateMeta.totalVisibleDurationSec < effectiveMinLifespanSec) {
                    continue;
                }

                List<Point> points = toCentroids(entry.getValue());
                if (points.size() < 2) {
                    continue;
                }
                double medianY = medianList(points.stream().map(p -> p.y).collect(Collectors.toList()));
                boolean edgeBand = medianY < topThreshold || medianY > bottomThreshold;
                TrackMeta meta = trackMeta.get(tid);
                double age = meta == null ? 0.0 : meta.totalVisibleDurationSec;
                double travel = cumulativeTravel(points);
                if (edgeBand && age >= effectiveTeacherMinAgeSec && travel >= TEACHER_POSITION_MIN_TRAVEL_FALLBACK_PX) {
                    candidates.add(new TeacherCandidate(tid, travel, spatialVariance(points)));
                }
            }
        }

        if (candidates.isEmpty()) {
            return null;
        }
        TeacherCandidate max = Collections.max(candidates,
                Comparator.comparingDouble(c -> c.travel + c.spatialVariance));
        return max.trackId;
    }

    private static List<Point> toCentroids(List<FeatureRecord> records) {
        List<Point> out = new ArrayList<>();
        for (FeatureRecord r : records) {
            if (r.bbox == null || r.bbox.length != 4) {
                continue;
            }
            out.add(new Point((r.bbox[0] + r.bbox[2]) * 0.5, (r.bbox[1] + r.bbox[3]) * 0.5));
        }
        return out;
    }

    private static Map<Double, Point> centroidByTimestamp(List<FeatureRecord> records) {
        Map<Double, Point> out = new HashMap<>();
        for (FeatureRecord r : records) {
            if (r.bbox == null || r.bbox.length != 4) {
                continue;
            }
            out.put(r.timestamp, new Point((r.bbox[0] + r.bbox[2]) * 0.5, (r.bbox[1] + r.bbox[3]) * 0.5));
        }
        return out;
    }

    private static double cumulativeTravel(List<Point> points) {
        double sum = 0.0;
        for (int i = 1; i < points.size(); i++) {
            double dx = points.get(i).x - points.get(i - 1).x;
            double dy = points.get(i).y - points.get(i - 1).y;
            sum += Math.sqrt(dx * dx + dy * dy);
        }
        return sum;
    }

    private static double spatialVariance(List<Point> points) {
        if (points.isEmpty()) {
            return 0.0;
        }
        double meanX = points.stream().mapToDouble(p -> p.x).average().orElse(0.0);
        double meanY = points.stream().mapToDouble(p -> p.y).average().orElse(0.0);
        double varX = 0.0;
        double varY = 0.0;
        for (Point p : points) {
            varX += (p.x - meanX) * (p.x - meanX);
            varY += (p.y - meanY) * (p.y - meanY);
        }
        varX /= points.size();
        varY /= points.size();
        return varX + varY;
    }

    private static double medianList(List<Double> values) {
        if (values == null || values.isEmpty()) {
            return 0.0;
        }
        List<Double> copy = new ArrayList<>(values);
        copy.sort(Double::compareTo);
        int n = copy.size();
        if (n % 2 == 1) {
            return copy.get(n / 2);
        }
        return (copy.get(n / 2 - 1) + copy.get(n / 2)) * 0.5;
    }

    @SuppressWarnings("unchecked")
    private static void putDiscardReason(Map<String, Object> stats, int trackId, String reason) {
        Object mapObj = stats.get("track_discard_reasons");
        if (!(mapObj instanceof Map<?, ?>)) {
            mapObj = new LinkedHashMap<String, String>();
            stats.put("track_discard_reasons", mapObj);
        }
        ((Map<String, String>) mapObj).put(String.valueOf(trackId), reason);
    }

    private static class TeacherCandidate {
        final int trackId;
        final double travel;
        final double spatialVariance;

        private TeacherCandidate(int trackId, double travel, double spatialVariance) {
            this.trackId = trackId;
            this.travel = travel;
            this.spatialVariance = spatialVariance;
        }
    }

    private static class Point {
        final double x;
        final double y;

        private Point(double x, double y) {
            this.x = x;
            this.y = y;
        }
    }
}