"""
Phase 2: scoring + robust aggregation.

This phase reads Phase 1 JSONL features and produces track-centric suspicious intervals
using:
- Rolling baseline per track (sliding window; ignore low-confidence frames)
- Confidence-weighted scoring (final = raw * confidence_weight)
- EMA smoothing + hysteresis thresholds
- Gap-based interval merging
- Failure/quality gates (discard low-stability tracks; discard low-confidence intervals)
"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np

from config import config


assert abs(
    config.HEAD_WEIGHT + config.GAZE_WEIGHT + config.PROXIMITY_WEIGHT + config.DRIFT_WEIGHT - 1.0
) < 1e-9, (
    "Signal weights must sum to 1.0"
)


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return float(max(lo, min(hi, x)))


def _median(d: Deque[float]) -> Optional[float]:
    if not d:
        return None
    return float(np.median(np.array(list(d), dtype=np.float64)))


@dataclass
class IntervalAcc:
    start_time: float
    end_time: float

    frame_count: int = 0
    sum_score: float = 0.0
    peak_score: float = 0.0
    sum_confidence_weight: float = 0.0

    # Component sums (accumulate only when baseline-ready + pose-quality).
    head_signal_sum: float = 0.0
    gaze_signal_sum: float = 0.0
    proximity_signal_sum: float = 0.0
    drift_signal_sum: float = 0.0
    component_sum_frames: int = 0

    head_deviation_flag_count: int = 0
    gaze_deviation_flag_count: int = 0

    proximity_distance_sum: float = 0.0
    proximity_distance_count: int = 0
    proximity_distance_min: Optional[float] = None


class Phase2Scoring:
    def __init__(self):
        self.alpha = float(config.EMA_ALPHA_BASE)
        self.enter_th = float(config.SUSPICION_ENTER_THRESHOLD)
        self.exit_th = float(config.SUSPICION_EXIT_THRESHOLD)

        self.min_interval_duration_sec = float(config.MIN_INTERVAL_DURATION_SEC)
        self.min_interval_avg_confidence = float(config.MIN_INTERVAL_AVG_CONFIDENCE)
        self.merge_gap_sec = float(config.MERGE_GAP_SEC)

        self.weight_head = float(config.HEAD_WEIGHT)
        self.weight_gaze = float(config.GAZE_WEIGHT)
        self.weight_proximity = float(config.PROXIMITY_WEIGHT)
        self.weight_drift = float(config.DRIFT_WEIGHT)

    @staticmethod
    def _load_video_duration_sec(features_jsonl_path: Path) -> float:
        """
        Load video duration from sibling Phase 1 stats file.
        Returns 3600.0 when unavailable (reference exam duration).
        """
        phase1_stats_path = features_jsonl_path.parent / "phase1_stats.json"
        try:
            payload = json.loads(phase1_stats_path.read_text(encoding="utf-8"))
            dur = float(payload.get("duration_sec", 0.0))
            return dur if dur > 0.0 else 3600.0
        except Exception:
            return 3600.0

    @staticmethod
    def _load_phase1_stats(features_jsonl_path: Path) -> Dict[str, Any]:
        phase1_stats_path = features_jsonl_path.parent / "phase1_stats.json"
        try:
            return json.loads(phase1_stats_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def run(
        self,
        out_results_path: Path,
        out_phase2_stats_path: Path,
        features_jsonl_path: Path,
        track_meta_path: Path,
        exam_id: Optional[str] = None,
        out_frame_scores_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        # Duration-aware scaling for short clips.
        phase1_stats = self._load_phase1_stats(features_jsonl_path)
        duration_sec = float(phase1_stats.get("duration_sec", self._load_video_duration_sec(features_jsonl_path)))
        fps_sampling = int(phase1_stats.get("fps_sampling", config.FPS_SAMPLING))
        actual_sampling_rate = float(phase1_stats.get("actual_sampling_rate", fps_sampling))
        duration_ratio = float(np.clip(duration_sec / 3600.0, 0.1, 1.0))

        alpha = float(config.EMA_ALPHA_FAST if actual_sampling_rate >= 10 else config.EMA_ALPHA_BASE)

        effective_min_lifespan_sec = max(
            max(1.0, duration_sec * 0.10),
            float(config.MIN_TRACK_LIFESPAN_SEC) * duration_ratio,
        )
        effective_baseline_window_sec = max(
            3.0, float(config.BASELINE_ROLLING_WINDOW_SEC) * duration_ratio
        )
        effective_min_baseline_samples = int(
            max(3, round(float(config.MIN_BASELINE_SAMPLES) * duration_ratio))
        )
        effective_teacher_min_age_sec = max(
            5.0,
            float(config.TEACHER_MIN_TRACK_AGE_SEC) * duration_ratio,
        )
        effective_min_interval_duration_sec = float(np.clip(
            max(0.5, duration_sec * 0.05),
            0.5,
            float(config.MIN_INTERVAL_DURATION_SEC),
        ))
        effective_baseline_lock_sec = max(
            min(float(config.BASELINE_LOCK_MIN_SEC), duration_sec * 0.20),
            float(config.BASELINE_LOCK_SEC) * duration_ratio,
        )
        effective_alpha = float(alpha)

        adjusted_enter_th = float(config.SUSPICION_ENTER_THRESHOLD)
        adjusted_exit_th = float(config.SUSPICION_EXIT_THRESHOLD)

        print(
            "[Phase2] Using scaled parameters "
            f"for duration={duration_sec:.2f}s (ratio={duration_ratio:.4f}): "
            f"effective_min_lifespan={effective_min_lifespan_sec:.2f}s, "
            f"effective_baseline_window={effective_baseline_window_sec:.2f}s, "
            f"effective_min_baseline_samples={effective_min_baseline_samples}, "
            f"effective_teacher_min_age={effective_teacher_min_age_sec:.2f}s, "
            f"effective_min_interval_duration={effective_min_interval_duration_sec:.2f}s, "
            f"effective_baseline_lock={effective_baseline_lock_sec:.2f}s, "
            f"fps_sampling={fps_sampling}, actual_sampling_rate={actual_sampling_rate:.3f}, alpha={alpha:.3f}, "
            f"effective_alpha={effective_alpha:.3f}, "
            f"raw_enter_th={self.enter_th:.3f}, raw_exit_th={self.exit_th:.3f}, "
            f"adjusted_enter_th={adjusted_enter_th:.3f}, adjusted_exit_th={adjusted_exit_th:.3f}"
        )

        track_meta_list = json.loads(track_meta_path.read_text(encoding="utf-8"))
        track_meta: Dict[int, Dict[str, Any]] = {int(t["track_id"]): t for t in track_meta_list}

        kept_tracks: set[int] = set()
        discarded_tracks = 0
        track_discard_reasons: Dict[int, str] = {}
        for tid, meta in track_meta.items():
            duration = float(meta.get("total_visible_duration_sec", 0.0))
            stability = float(meta.get("stability_score", 0.0))
            if stability < float(config.TRACK_STABILITY_MIN_SCORE):
                discarded_tracks += 1
                track_discard_reasons[tid] = f"stability_score<{config.TRACK_STABILITY_MIN_SCORE}"
                continue
            if duration < float(effective_min_lifespan_sec):
                discarded_tracks += 1
                track_discard_reasons[tid] = f"total_visible_duration<{effective_min_lifespan_sec:.2f}"
                continue
            kept_tracks.add(tid)

        def _centroid_from_bbox(bbox: List[float]) -> Tuple[float, float]:
            x1, y1, x2, y2 = bbox
            return (0.5 * (float(x1) + float(x2)), 0.5 * (float(y1) + float(y2)))

        # Read Phase 1 features once (needed for teacher detection + timestamp-level suppressions).
        with features_jsonl_path.open("r", encoding="utf-8") as f:
            feature_records: List[Dict[str, Any]] = [json.loads(line) for line in f if line.strip()]

        # Teacher detection among already kept tracks.
        centroids_by_track: Dict[int, List[Tuple[float, float]]] = defaultdict(list)
        for rec in feature_records:
            tid = int(rec["track_id"])
            if tid not in kept_tracks:
                continue
            bbox = rec.get("bbox")
            if not bbox or len(bbox) != 4:
                continue
            centroids_by_track[tid].append(_centroid_from_bbox(bbox))

        teacher_candidates: List[Tuple[int, float, float]] = []
        for tid, pts in centroids_by_track.items():
            if len(pts) < 2:
                continue
            travel = float(
                sum(
                    np.sqrt((pts[i][0] - pts[i - 1][0]) ** 2 + (pts[i][1] - pts[i - 1][1]) ** 2)
                    for i in range(1, len(pts))
                )
            )
            xs = np.array([p[0] for p in pts], dtype=np.float64)
            ys = np.array([p[1] for p in pts], dtype=np.float64)
            spatial_var = float(np.var(xs) + np.var(ys))
            if (
                float(track_meta.get(tid, {}).get("total_visible_duration_sec", 0.0)) >= effective_teacher_min_age_sec
                and travel >= float(config.TEACHER_MIN_CUMULATIVE_TRAVEL_PX)
                and spatial_var >= float(config.TEACHER_MIN_SPATIAL_VARIANCE)
            ):
                teacher_candidates.append((tid, travel, spatial_var))

        # Position-based teacher detection fallback.
        frame_height = 0.0
        for rec in feature_records[:20]:
            bbox = rec.get("bbox")
            if bbox and len(bbox) == 4:
                frame_height = max(frame_height, float(bbox[3]))
        if frame_height <= 0.0:
            frame_height = 1080.0

        if not teacher_candidates and frame_height > 0.0:
            top_threshold = frame_height * float(config.TEACHER_POSITION_TOP_FRACTION)
            bottom_threshold = frame_height * (1.0 - float(config.TEACHER_POSITION_TOP_FRACTION))

            for tid, pts in centroids_by_track.items():
                if len(pts) < 2:
                    continue
                median_y = float(np.median([p[1] for p in pts]))
                is_front_or_back = (median_y < top_threshold or median_y > bottom_threshold)

                travel = float(
                    sum(
                        np.sqrt((pts[i][0] - pts[i - 1][0]) ** 2 + (pts[i][1] - pts[i - 1][1]) ** 2)
                        for i in range(1, len(pts))
                    )
                )
                track_age = float(track_meta.get(tid, {}).get("total_visible_duration_sec", 0.0))

                if (
                    is_front_or_back
                    and travel >= float(config.TEACHER_POSITION_MIN_TRAVEL_FALLBACK_PX)
                    and track_age >= effective_teacher_min_age_sec
                ):
                    xs = np.array([p[0] for p in pts], dtype=np.float64)
                    ys = np.array([p[1] for p in pts], dtype=np.float64)
                    spatial_var = float(np.var(xs) + np.var(ys))
                    teacher_candidates.append((tid, travel, spatial_var))
                    print(
                        f"[Phase2] Teacher candidate (position-based): "
                        f"track_id={tid}, median_y={median_y:.1f}, "
                        f"top_thresh={top_threshold:.1f}, travel={travel:.1f}"
                    )

            # Secondary fallback for perspective-heavy frames where the invigilator
            # may sit just outside the strict top/bottom 20% band.
            if not teacher_candidates:
                relaxed_top = top_threshold * 1.5
                relaxed_bottom = frame_height - relaxed_top
                for tid, pts in centroids_by_track.items():
                    if len(pts) < 2:
                        continue
                    median_y = float(np.median([p[1] for p in pts]))
                    is_edge_band = (median_y < relaxed_top or median_y > relaxed_bottom)
                    if not is_edge_band:
                        continue

                    travel = float(
                        sum(
                            np.sqrt((pts[i][0] - pts[i - 1][0]) ** 2 + (pts[i][1] - pts[i - 1][1]) ** 2)
                            for i in range(1, len(pts))
                        )
                    )
                    track_age = float(track_meta.get(tid, {}).get("total_visible_duration_sec", 0.0))
                    if (
                        travel >= float(config.TEACHER_POSITION_MIN_TRAVEL_FALLBACK_PX)
                        and track_age >= effective_teacher_min_age_sec
                    ):
                        xs = np.array([p[0] for p in pts], dtype=np.float64)
                        ys = np.array([p[1] for p in pts], dtype=np.float64)
                        spatial_var = float(np.var(xs) + np.var(ys))
                        teacher_candidates.append((tid, travel, spatial_var))
                        print(
                            f"[Phase2] Teacher candidate (position-relaxed): "
                            f"track_id={tid}, median_y={median_y:.1f}, "
                            f"relaxed_top={relaxed_top:.1f}, travel={travel:.1f}"
                        )

        teacher_track_id: Optional[int] = None
        teacher_travel = 0.0
        teacher_spatial_variance = 0.0
        if teacher_candidates:
            teacher_track_id, teacher_travel, teacher_spatial_variance = max(
                teacher_candidates,
                key=lambda x: x[1] + x[2],
            )
            kept_tracks.discard(int(teacher_track_id))
            track_discard_reasons[int(teacher_track_id)] = "teacher_track_excluded"
            discarded_tracks += 1
            print(
                "[Phase2] Excluding teacher track: "
                f"track_id={teacher_track_id}, cumulative_travel={teacher_travel:.2f}, "
                f"spatial_variance={teacher_spatial_variance:.2f}"
            )

        # Teacher centroid by timestamp for proximity suppression.
        teacher_centroid_by_ts: Dict[float, Tuple[float, float]] = {}
        if teacher_track_id is not None:
            for rec in feature_records:
                if int(rec["track_id"]) != int(teacher_track_id):
                    continue
                bbox = rec.get("bbox")
                if not bbox or len(bbox) != 4:
                    continue
                ts = float(rec["timestamp"])
                teacher_centroid_by_ts[ts] = _centroid_from_bbox(bbox)

        # Keep only non-teacher kept tracks; bucket by sampled timestamp.
        records_by_ts: Dict[float, List[Dict[str, Any]]] = defaultdict(list)
        for rec in feature_records:
            tid = int(rec["track_id"])
            if tid not in kept_tracks:
                continue
            ts = float(rec["timestamp"])
            records_by_ts[ts].append(rec)

        # Rolling baseline per track (timestamp, value)
        window_sec = float(effective_baseline_window_sec)
        long_window_sec = 300.0
        min_samples = int(effective_min_baseline_samples)

        @dataclass
        class TrackState:
            ema: float = 0.0
            baseline_yaw: Deque[Tuple[float, float]] = None
            baseline_gaze: Deque[Tuple[float, float]] = None
            baseline_dist: Deque[Tuple[float, float]] = None
            baseline_yaw_long: Deque[Tuple[float, float]] = None
            baseline_gaze_long: Deque[Tuple[float, float]] = None
            interval_open: bool = False
            interval: Optional[IntervalAcc] = None

        track_states: Dict[int, TrackState] = {}

        def _ensure_state(tid: int) -> TrackState:
            if tid not in track_states:
                track_states[tid] = TrackState(
                    ema=0.0,
                    baseline_yaw=deque(),
                    baseline_gaze=deque(),
                    baseline_dist=deque(),
                    baseline_yaw_long=deque(),
                    baseline_gaze_long=deque(),
                    interval_open=False,
                    interval=None,
                )
            return track_states[tid]

        def _prune(d: Deque[Tuple[float, float]], current_ts: float) -> None:
            while d and (current_ts - d[0][0]) > window_sec:
                d.popleft()

        def _baseline_values(state: TrackState) -> Tuple[Optional[float], Optional[float], Optional[float]]:
            # Compute medians only if enough samples exist.
            yaw_vals = deque([v for _, v in state.baseline_yaw])
            gaze_vals = deque([v for _, v in state.baseline_gaze])
            dist_vals = deque([v for _, v in state.baseline_dist])

            yaw_med = _median(yaw_vals) if len(yaw_vals) >= min_samples else None
            gaze_med = _median(gaze_vals) if len(gaze_vals) >= min_samples else None
            dist_med = _median(dist_vals) if len(dist_vals) >= min_samples else None
            return yaw_med, gaze_med, dist_med

        def _long_baseline_values(state: TrackState) -> Tuple[Optional[float], Optional[float]]:
            yaw_vals = deque([v for _, v in state.baseline_yaw_long])
            gaze_vals = deque([v for _, v in state.baseline_gaze_long])
            yaw_med = _median(yaw_vals) if len(yaw_vals) >= min_samples else None
            gaze_med = _median(gaze_vals) if len(gaze_vals) >= min_samples else None
            return yaw_med, gaze_med

        results_by_track: Dict[int, List[Dict[str, Any]]] = defaultdict(list)

        stats: Dict[str, Any] = {
            "total_feature_records": len(feature_records),
            "discarded_tracks": discarded_tracks,
            "kept_tracks": len(kept_tracks),
            "track_discard_reasons": {str(k): v for k, v in track_discard_reasons.items()},
            "teacher_track_id": int(teacher_track_id) if teacher_track_id is not None else None,
            "teacher_track_cumulative_travel": float(teacher_travel),
            "teacher_track_spatial_variance": float(teacher_spatial_variance),
            "frames_pose_unavailable": 0,
            "frames_low_visibility": 0,
            "frames_baseline_not_ready": 0,
            "frames_suppressed_whole_class_event": 0,
            "frames_suppressed_teacher_proximity": 0,
            "intervals_created": 0,
            "intervals_discarded_confidence": 0,
            "intervals_discarded_duration": 0,
            "intervals_discarded_empty": 0,
            "tracking_id_switch_count_total": int(
                sum(int(track_meta[t].get("id_switch_count", 0)) for t in kept_tracks)
            ) if kept_tracks else 0,
        }

        def _finalize_interval(tid: int, interval: IntervalAcc) -> None:
            duration = float(interval.end_time - interval.start_time)
            if duration < float(effective_min_interval_duration_sec):
                stats["intervals_discarded_duration"] += 1
                return
            if interval.frame_count <= 0:
                stats["intervals_discarded_empty"] += 1
                return

            avg_conf = float(interval.sum_confidence_weight / float(interval.frame_count))
            if avg_conf < self.min_interval_avg_confidence:
                stats["intervals_discarded_confidence"] += 1
                if "intervals_discarded_confidence_by_track" not in stats:
                    stats["intervals_discarded_confidence_by_track"] = {}
                stats["intervals_discarded_confidence_by_track"][str(tid)] = (
                    stats["intervals_discarded_confidence_by_track"].get(str(tid), 0) + 1
                )
                return

            avg_score = float(interval.sum_score / float(interval.frame_count))

            if interval.component_sum_frames > 0:
                head_avg = interval.head_signal_sum / float(interval.component_sum_frames)
                gaze_avg = interval.gaze_signal_sum / float(interval.component_sum_frames)
                prox_avg = interval.proximity_signal_sum / float(interval.component_sum_frames)
                drift_avg = interval.drift_signal_sum / float(interval.component_sum_frames)
            else:
                head_avg = gaze_avg = prox_avg = drift_avg = 0.0

            comp_sorted = sorted(
                [
                    ("HeadDeviation", head_avg),
                    ("GazeDeviation", gaze_avg),
                    ("ProximityAnomaly", prox_avg),
                    ("SustainedDrift", drift_avg),
                ],
                key=lambda x: x[1],
                reverse=True,
            )
            dominant = [name for name, v in comp_sorted[:3] if v > 0.0]
            if not dominant and comp_sorted:
                dominant = [comp_sorted[0][0]]

            head_dev_pct = float(interval.head_deviation_flag_count / float(interval.frame_count))
            gaze_dev_pct = float(interval.gaze_deviation_flag_count / float(interval.frame_count))
            prox_avg_dist = (
                float(interval.proximity_distance_sum / float(interval.proximity_distance_count))
                if interval.proximity_distance_count > 0
                else None
            )

            payload = {
                "start": float(interval.start_time),
                "end": float(interval.end_time),
                "duration": duration,
                "peak_score": float(interval.peak_score),
                "avg_score": avg_score,
                "confidence": avg_conf,
                "dominant_signals": dominant,
                "supporting_stats": {
                    "head_deviation_pct": head_dev_pct,
                    "gaze_deviation_pct": gaze_dev_pct,
                    "proximity_avg_distance": prox_avg_dist,
                    "proximity_min_distance": interval.proximity_distance_min,
                },
                # Internal fields for merging.
                "_frame_count": interval.frame_count,
                "_sum_score": interval.sum_score,
                "_sum_conf": interval.sum_confidence_weight,
                "_component_sum_frames": interval.component_sum_frames,
                "_component_sums": {
                    "head": interval.head_signal_sum,
                    "gaze": interval.gaze_signal_sum,
                    "prox": interval.proximity_signal_sum,
                    "drift": interval.drift_signal_sum,
                },
                "_support": {
                    "head_dev_count": interval.head_deviation_flag_count,
                    "gaze_dev_count": interval.gaze_deviation_flag_count,
                    "prox_sum": interval.proximity_distance_sum,
                    "prox_count": interval.proximity_distance_count,
                },
            }
            results_by_track[tid].append(payload)
            stats["intervals_created"] += 1

        frame_scores_fp = None
        if out_frame_scores_path is not None:
            out_frame_scores_path.parent.mkdir(parents=True, exist_ok=True)
            frame_scores_fp = out_frame_scores_path.open("w", encoding="utf-8")

        try:
            sim_signal_th = float(config.SIMULTANEOUS_SUPPRESSION_SCORE_THRESHOLD)
            sim_min_tracks = int(config.SIMULTANEOUS_SUPPRESSION_MIN_TRACKS)
            sim_fraction = float(config.SIMULTANEOUS_SUPPRESSION_FRACTION)
            teacher_radius = float(config.TEACHER_PROXIMITY_SUPPRESSION_RADIUS)
            ema_baseline_freeze_threshold = float(config.SUSPICION_ENTER_THRESHOLD) * 0.6

            for timestamp in sorted(records_by_ts.keys()):
                frame_items: List[Dict[str, Any]] = []
                recs = records_by_ts[timestamp]

                # First pass for this timestamp: baseline/scoring per track (pre-suppression).
                for rec in recs:
                    tid = int(rec["track_id"])
                    state = _ensure_state(tid)

                    pose = rec.get("pose")
                    quality = rec.get("quality", {})
                    visibility_score = float(quality.get("visibility_score", 0.0))
                    occlusion_score = float(quality.get("occlusion_score", 0.0))

                    tracking = rec.get("tracking", {})
                    tracking_stability_score = float(tracking.get("tracking_stability_score", 0.0))

                    nearest_distance = rec.get("proximity", {}).get("nearest_neighbor_distance")
                    nearest_distance = float(nearest_distance) if nearest_distance is not None else None

                    # Defaults for this frame (used everywhere, so keep defined).
                    raw_signal_score = 0.0
                    confidence_weight = 0.0
                    final_score_pre = 0.0
                    head_signal = 0.0
                    gaze_signal = 0.0
                    proximity_signal = 0.0
                    drift_signal = 0.0
                    head_dev_flag = 0
                    gaze_dev_flag = 0
                    quality_gate_status = "ok"

                    pose_conf = 0.0
                    head_pose_conf = 0.0
                    gaze_reliability = 0.0

                    # 1) Update rolling baselines if pose quality is sufficient.
                    if pose is None:
                        stats["frames_pose_unavailable"] += 1
                    else:
                        pose_conf = float(pose.get("confidence", 0.0))
                        head_pose_conf = float(pose.get("head_pose_confidence", 0.0))
                        gaze_reliability = float(pose.get("gaze_reliability", 0.0))

                    frame_usable = (
                        visibility_score >= float(config.MIN_FRAME_VISIBILITY_SCORE)
                        and head_pose_conf >= float(config.MIN_POSE_CONFIDENCE)
                    )
                    head_signal_reliable = head_pose_conf >= float(config.MIN_POSE_CONFIDENCE)
                    gaze_signal_reliable = gaze_reliability >= float(config.MIN_POSE_CONFIDENCE)

                    if not frame_usable:
                        stats["frames_low_visibility"] += 1
                    else:
                        baseline_calibration_ok = bool(config.BASELINE_UPDATE_DURING_SUSPICION) or (
                            float(timestamp) <= float(effective_baseline_lock_sec)
                            or float(state.ema) < float(ema_baseline_freeze_threshold)
                        )
                        if baseline_calibration_ok:
                            state.baseline_yaw.append((timestamp, float(pose["yaw"])))
                            state.baseline_gaze.append((timestamp, float(pose["gaze_x"])))
                            state.baseline_yaw_long.append((timestamp, float(pose["yaw"])))
                            state.baseline_gaze_long.append((timestamp, float(pose["gaze_x"])))
                            if nearest_distance is not None:
                                state.baseline_dist.append((timestamp, nearest_distance))

                    # Prune rolling baselines.
                    _prune(state.baseline_yaw, timestamp)
                    _prune(state.baseline_gaze, timestamp)
                    _prune(state.baseline_dist, timestamp)
                    while state.baseline_yaw_long and (timestamp - state.baseline_yaw_long[0][0]) > long_window_sec:
                        state.baseline_yaw_long.popleft()
                    while state.baseline_gaze_long and (timestamp - state.baseline_gaze_long[0][0]) > long_window_sec:
                        state.baseline_gaze_long.popleft()

                    baseline_yaw, baseline_gaze, baseline_dist = _baseline_values(state)
                    baseline_yaw_long, _ = _long_baseline_values(state)
                    abs_min = int(config.BASELINE_MIN_ABSOLUTE_SAMPLES)
                    baseline_ready = (
                        baseline_yaw is not None
                        and baseline_gaze is not None
                        and len(state.baseline_yaw) >= abs_min
                    )

                    # 2) Compute signals and confidence-weighted score when possible.
                    if pose is not None and baseline_ready:
                        if not frame_usable:
                            quality_gate_status = f"fail:vis={visibility_score:.2f},head={head_pose_conf:.2f}"
                        else:
                            quality_gate_status = "ok"
                            yaw = float(pose["yaw"])
                            gaze_x = float(pose["gaze_x"])

                            head_dev = abs(yaw - float(baseline_yaw))
                            gaze_dev = abs(gaze_x - float(baseline_gaze))

                            if head_signal_reliable:
                                head_signal = _clamp(head_dev / float(config.HEAD_DEV_NORM_DEG), 0.0, 1.0)
                            else:
                                head_signal = 0.0

                            if gaze_signal_reliable:
                                gaze_signal = _clamp(gaze_dev / float(config.GAZE_DEV_NORM), 0.0, 1.0)
                            else:
                                gaze_signal = 0.0

                            if baseline_dist is not None and nearest_distance is not None and baseline_dist > 0:
                                threshold = float(baseline_dist) * float(config.PROXIMITY_DISTANCE_RATIO_THRESHOLD)
                                if threshold > 1e-6 and nearest_distance <= threshold:
                                    proximity_signal = _clamp((threshold - nearest_distance) / threshold, 0.0, 1.0)

                            if baseline_yaw is not None and baseline_yaw_long is not None:
                                drift_signal = _clamp(
                                    abs(float(baseline_yaw) - float(baseline_yaw_long))
                                    / float(config.HEAD_DEV_NORM_DEG),
                                    0.0,
                                    1.0,
                                )

                            raw_signal_score = (
                                self.weight_head * head_signal
                                + self.weight_gaze * gaze_signal
                                + self.weight_proximity * proximity_signal
                                + self.weight_drift * drift_signal
                            )
                            raw_signal_score = _clamp(raw_signal_score, 0.0, 1.0)

                            estimation_mode = rec.get("estimation_mode")
                            if estimation_mode == "bbox_proxy_face_not_visible":
                                raw_signal_score = _clamp(raw_signal_score * 0.5, 0.0, 1.0)
                            elif estimation_mode == "body_pose_landmarks":
                                pass
                            elif estimation_mode == "profile_face_detected":
                                pass

                            occlusion_clarity = float(1.0 - occlusion_score)
                            confidence_weight_mean = (
                                0.4 * pose_conf
                                + 0.3 * visibility_score
                                + 0.2 * tracking_stability_score
                                + 0.1 * occlusion_clarity
                            )
                            confidence_weight = _clamp(
                                max(float(confidence_weight_mean), float(config.MIN_CONFIDENCE_WEIGHT_FLOOR)),
                                0.0,
                                1.0,
                            )

                            active_signals = sum(
                                [
                                    1 if head_signal >= 0.5 else 0,
                                    1 if gaze_signal >= 0.5 else 0,
                                    1 if proximity_signal >= 0.5 else 0,
                                ]
                            )
                            if active_signals >= 2:
                                confidence_weight = _clamp(confidence_weight * 1.15, 0.0, 1.0)

                            final_score_pre = raw_signal_score * confidence_weight

                            head_dev_flag = 1 if head_signal >= float(config.SIGNAL_FLAG_THRESHOLD) else 0
                            gaze_dev_flag = 1 if gaze_signal >= float(config.SIGNAL_FLAG_THRESHOLD) else 0
                    else:
                        if not frame_usable:
                            quality_gate_status = f"fail:vis={visibility_score:.2f},head={head_pose_conf:.2f}"
                        elif not baseline_ready:
                            quality_gate_status = "fail:baseline_not_ready"
                        stats["frames_baseline_not_ready"] += 1

                    bbox = rec.get("bbox")
                    centroid = _centroid_from_bbox(bbox) if bbox and len(bbox) == 4 else None

                    frame_items.append(
                        {
                            "tid": tid,
                            "state": state,
                            "timestamp": float(timestamp),
                            "pose": pose,
                            "nearest_distance": nearest_distance,
                            "baseline_ready": bool(baseline_ready),
                            "visibility_score": float(visibility_score),
                            "occlusion_score": float(occlusion_score),
                            "gaze_reliability": float(gaze_reliability),
                            "quality_gate_status": str(quality_gate_status),
                            "raw_signal_score": float(raw_signal_score),
                            "confidence_weight": float(confidence_weight),
                            "final_score_pre": float(final_score_pre),
                            "head_signal": float(head_signal),
                            "gaze_signal": float(gaze_signal),
                            "proximity_signal": float(proximity_signal),
                            "drift_signal": float(drift_signal),
                            "head_dev_flag": int(head_dev_flag),
                            "gaze_dev_flag": int(gaze_dev_flag),
                            "centroid": centroid,
                            "baseline_yaw_len": len(state.baseline_yaw),
                            "suppressed_whole_class_event": False,
                            "suppressed_teacher_proximity": False,
                            "estimation_mode": rec.get("estimation_mode"),
                        }
                    )

                # Whole-class simultaneous event suppression.
                active_track_count = len(frame_items)
                flagged_count = sum(
                    1 for item in frame_items if float(item["raw_signal_score"]) > sim_signal_th
                )
                tracks_with_mature_baseline = sum(
                    1 for item in frame_items
                    if bool(item["baseline_ready"]) and int(item.get("baseline_yaw_len", 0)) >= 8
                )
                baseline_mature_fraction = (
                    float(tracks_with_mature_baseline) / float(active_track_count)
                    if active_track_count > 0
                    else 0.0
                )
                whole_class_event = (
                    active_track_count >= sim_min_tracks
                    and active_track_count > 0
                    and (float(flagged_count) / float(active_track_count)) >= sim_fraction
                    and baseline_mature_fraction >= 0.5
                )
                if whole_class_event:
                    for item in frame_items:
                        item["suppressed_whole_class_event"] = True
                        stats["frames_suppressed_whole_class_event"] += 1

                # Teacher proximity suppression.
                teacher_centroid = teacher_centroid_by_ts.get(float(timestamp))
                if teacher_centroid is not None:
                    for item in frame_items:
                        c = item.get("centroid")
                        if c is None:
                            continue
                        d = float(np.sqrt((c[0] - teacher_centroid[0]) ** 2 + (c[1] - teacher_centroid[1]) ** 2))
                        if d < teacher_radius:
                            item["suppressed_teacher_proximity"] = True
                            stats["frames_suppressed_teacher_proximity"] += 1

                # Second pass for this timestamp: EMA + interval state machine using suppressed final score.
                for item in frame_items:
                    tid = int(item["tid"])
                    state = item["state"]
                    suppressed = bool(item["suppressed_whole_class_event"] or item["suppressed_teacher_proximity"])
                    final_score = 0.0 if suppressed else float(item["final_score_pre"])

                    # 3) Update EMA always.
                    state.ema = effective_alpha * float(final_score) + (1.0 - effective_alpha) * float(state.ema)

                    if frame_scores_fp is not None:
                        frame_scores_fp.write(
                            json.dumps(
                                {
                                    "timestamp": float(item["timestamp"]),
                                    "track_id": int(tid),
                                    "final_score": float(final_score),
                                    "raw_signal_score": float(item["raw_signal_score"]),
                                    "confidence_weight": float(item["confidence_weight"]),
                                    "head_signal": float(item["head_signal"]),
                                    "gaze_signal": float(item["gaze_signal"]),
                                    "proximity_signal": float(item["proximity_signal"]),
                                    "drift_signal": float(item["drift_signal"]),
                                    "baseline_ready": bool(item["baseline_ready"]),
                                    "visibility_score": float(item["visibility_score"]),
                                    "occlusion_score": float(item["occlusion_score"]),
                                    "gaze_reliability": float(item["gaze_reliability"]),
                                    "quality_gate_status": str(item.get("quality_gate_status", "ok")),
                                    "estimation_mode": item.get("estimation_mode"),
                                    "suppressed_whole_class_event": bool(item["suppressed_whole_class_event"]),
                                    "suppressed_teacher_proximity": bool(item["suppressed_teacher_proximity"]),
                                }
                            )
                            + "\n"
                        )

                    include_for_interval = not suppressed

                    # 4) Interval transitions + accumulation.
                    if state.interval_open and state.interval is not None:
                        interval = state.interval
                        interval.end_time = float(item["timestamp"])

                        if include_for_interval:
                            interval.frame_count += 1
                            interval.sum_score += float(final_score)
                            interval.peak_score = max(float(interval.peak_score), float(final_score))
                            interval.sum_confidence_weight += float(item["confidence_weight"])

                            if item["pose"] is not None and bool(item["baseline_ready"]) and float(item["confidence_weight"]) > 0.0:
                                interval.head_signal_sum += float(item["head_signal"])
                                interval.gaze_signal_sum += float(item["gaze_signal"])
                                interval.proximity_signal_sum += float(item["proximity_signal"])
                                interval.drift_signal_sum += float(item["drift_signal"])
                                interval.component_sum_frames += 1

                                interval.head_deviation_flag_count += int(item["head_dev_flag"])
                                interval.gaze_deviation_flag_count += int(item["gaze_dev_flag"])

                                if item["nearest_distance"] is not None:
                                    interval.proximity_distance_sum += float(item["nearest_distance"])
                                    interval.proximity_distance_count += 1
                                    if interval.proximity_distance_min is None:
                                        interval.proximity_distance_min = float(item["nearest_distance"])
                                    else:
                                        interval.proximity_distance_min = min(float(interval.proximity_distance_min), float(item["nearest_distance"]))

                        if state.ema <= adjusted_exit_th:
                            _finalize_interval(tid, interval)
                            state.interval_open = False
                            state.interval = None

                    if not state.interval_open and state.ema >= adjusted_enter_th:
                        state.interval_open = True
                        state.interval = IntervalAcc(start_time=float(item["timestamp"]), end_time=float(item["timestamp"]))
                        interval = state.interval
                        if include_for_interval:
                            interval.frame_count = 1
                            interval.sum_score = float(final_score)
                            interval.peak_score = max(float(interval.peak_score), float(final_score))
                            interval.sum_confidence_weight = float(item["confidence_weight"])

                            if item["pose"] is not None and bool(item["baseline_ready"]) and float(item["confidence_weight"]) > 0.0:
                                interval.head_signal_sum = float(item["head_signal"])
                                interval.gaze_signal_sum = float(item["gaze_signal"])
                                interval.proximity_signal_sum = float(item["proximity_signal"])
                                interval.drift_signal_sum = float(item["drift_signal"])
                                interval.component_sum_frames = 1
                                interval.head_deviation_flag_count = int(item["head_dev_flag"])
                                interval.gaze_deviation_flag_count = int(item["gaze_dev_flag"])
                                if item["nearest_distance"] is not None:
                                    interval.proximity_distance_sum = float(item["nearest_distance"])
                                    interval.proximity_distance_count = 1
                                    interval.proximity_distance_min = float(item["nearest_distance"])

        finally:
            if frame_scores_fp is not None:
                frame_scores_fp.close()

        # Finalize any open intervals at EOF.
        for tid, state in track_states.items():
            if state.interval_open and state.interval is not None:
                _finalize_interval(tid, state.interval)

        # Merge intervals by gap per track.
        merged_results: Dict[int, List[Dict[str, Any]]] = {}
        for tid, intervals in results_by_track.items():
            if not intervals:
                continue
            intervals_sorted = sorted(intervals, key=lambda x: x["start"])
            merged: List[Dict[str, Any]] = []

            def _merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
                dur_a = float(a["duration"])
                dur_b = float(b["duration"])
                total_dur = dur_a + dur_b if dur_a + dur_b > 0 else 1.0

                # Weighted by frame_count (more robust than duration).
                fa = int(a["_frame_count"])
                fb = int(b["_frame_count"])
                ftotal = fa + fb if fa + fb > 0 else 1

                merged_interval = {
                    "start": float(a["start"]),
                    "end": float(b["end"]),
                    "duration": float(b["end"]) - float(a["start"]),
                    "peak_score": float(max(a["peak_score"], b["peak_score"])),
                    "avg_score": float((float(a["avg_score"]) * fa + float(b["avg_score"]) * fb) / ftotal),
                    "confidence": float((float(a["confidence"]) * fa + float(b["confidence"]) * fb) / ftotal),
                    "dominant_signals": list({*(a.get("dominant_signals") or []), *(b.get("dominant_signals") or [])}),
                    "supporting_stats": {
                        "head_deviation_pct": float((float(a["supporting_stats"]["head_deviation_pct"]) * fa + float(b["supporting_stats"]["head_deviation_pct"]) * fb) / ftotal),
                        "gaze_deviation_pct": float((float(a["supporting_stats"]["gaze_deviation_pct"]) * fa + float(b["supporting_stats"]["gaze_deviation_pct"]) * fb) / ftotal),
                        "proximity_avg_distance": None,
                        "proximity_min_distance": (
                            min(
                                x
                                for x in [a["supporting_stats"].get("proximity_min_distance"), b["supporting_stats"].get("proximity_min_distance")]
                                if x is not None
                            )
                            if (a["supporting_stats"].get("proximity_min_distance") is not None or b["supporting_stats"].get("proximity_min_distance") is not None)
                            else None
                        ),
                    },
                    # Internal fields for possible future merges.
                    "_frame_count": ftotal,
                    "_sum_score": float(a["_sum_score"] + b["_sum_score"]),
                    "_sum_conf": float(a["_sum_conf"] + b["_sum_conf"]),
                    "_component_sum_frames": int(a["_component_sum_frames"] + b["_component_sum_frames"]),
                    "_component_sums": {
                        "head": float(a["_component_sums"]["head"] + b["_component_sums"]["head"]),
                        "gaze": float(a["_component_sums"]["gaze"] + b["_component_sums"]["gaze"]),
                        "prox": float(a["_component_sums"]["prox"] + b["_component_sums"]["prox"]),
                        "drift": float(a["_component_sums"]["drift"] + b["_component_sums"]["drift"]),
                    },
                    "_support": {
                        "head_dev_count": int(a["_support"]["head_dev_count"] + b["_support"]["head_dev_count"]),
                        "gaze_dev_count": int(a["_support"]["gaze_dev_count"] + b["_support"]["gaze_dev_count"]),
                        "prox_sum": float(a["_support"]["prox_sum"] + b["_support"]["prox_sum"]),
                        "prox_count": int(a["_support"]["prox_count"] + b["_support"]["prox_count"]),
                    },
                }

                # Recompute proximity average if we have counts.
                prox_count = merged_interval["_support"]["prox_count"]
                if prox_count > 0:
                    merged_interval["supporting_stats"]["proximity_avg_distance"] = float(
                        merged_interval["_support"]["prox_sum"] / float(prox_count)
                    )
                return merged_interval

            for interval in intervals_sorted:
                if not merged:
                    merged.append(interval)
                    continue
                gap = float(interval["start"]) - float(merged[-1]["end"])
                if gap <= self.merge_gap_sec:
                    merged[-1] = _merge(merged[-1], interval)
                else:
                    merged.append(interval)

            # Strip internal fields before output.
            for it in merged:
                it.pop("_frame_count", None)
                it.pop("_sum_score", None)
                it.pop("_sum_conf", None)
                it.pop("_component_sum_frames", None)
                it.pop("_component_sums", None)
                it.pop("_support", None)

            merged_results[tid] = merged

        output_results: List[Dict[str, Any]] = []
        for tid in sorted(kept_tracks):
            meta = track_meta.get(tid)
            if meta is None:
                continue
            intervals = merged_results.get(tid, [])
            output_results.append(
                {
                    "track_id": int(tid),
                    "total_duration": float(meta.get("total_visible_duration_sec", 0.0)),
                    "stability_score": float(meta.get("stability_score", 0.0)),
                    "intervals": intervals,
                }
            )

        payload = {
            "exam_id": exam_id,
            "results": output_results,
            "observability": stats,
        }

        out_results_path.parent.mkdir(parents=True, exist_ok=True)
        out_results_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        out_phase2_stats_path.parent.mkdir(parents=True, exist_ok=True)
        out_phase2_stats_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")

        print("\n[Phase2 Summary]")
        print(f"  kept_tracks={stats.get('kept_tracks', 0)}, discarded_tracks={stats.get('discarded_tracks', 0)}")
        print(f"  intervals_created={stats.get('intervals_created', 0)}")
        print(f"  intervals_discarded_confidence={stats.get('intervals_discarded_confidence', 0)}")
        print(f"  intervals_discarded_duration={stats.get('intervals_discarded_duration', 0)}")
        print(f"  intervals_discarded_empty={stats.get('intervals_discarded_empty', 0)}")
        print(f"  tracking_id_switch_count_total={stats.get('tracking_id_switch_count_total', 0)}")

        return payload

