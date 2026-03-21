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
    component_sum_frames: int = 0

    head_deviation_flag_count: int = 0
    gaze_deviation_flag_count: int = 0

    proximity_distance_sum: float = 0.0
    proximity_distance_count: int = 0
    proximity_distance_min: Optional[float] = None


class Phase2Scoring:
    def __init__(self):
        self.alpha = float(config.EMA_ALPHA)
        self.enter_th = float(config.SUSPICION_ENTER_THRESHOLD)
        self.exit_th = float(config.SUSPICION_EXIT_THRESHOLD)

        self.min_interval_duration_sec = float(config.MIN_INTERVAL_DURATION_SEC)
        self.min_interval_avg_confidence = float(config.MIN_INTERVAL_AVG_CONFIDENCE)
        self.merge_gap_sec = float(config.MERGE_GAP_SEC)

        self.weight_head = float(config.WEIGHT_HEAD)
        self.weight_gaze = float(config.WEIGHT_GAZE)
        self.weight_proximity = float(config.WEIGHT_PROXIMITY)

    def run(
        self,
        out_results_path: Path,
        out_phase2_stats_path: Path,
        features_jsonl_path: Path,
        track_meta_path: Path,
        exam_id: Optional[str] = None,
        out_frame_scores_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
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
            if duration < float(config.MIN_TRACK_LIFESPAN_SEC):
                discarded_tracks += 1
                track_discard_reasons[tid] = f"total_visible_duration<{config.MIN_TRACK_LIFESPAN_SEC}"
                continue
            kept_tracks.add(tid)

        # Rolling baseline per track (timestamp, value)
        window_sec = float(config.BASELINE_ROLLING_WINDOW_SEC)
        min_samples = int(config.MIN_BASELINE_SAMPLES)

        @dataclass
        class TrackState:
            ema: float = 0.0
            baseline_yaw: Deque[Tuple[float, float]] = None
            baseline_gaze: Deque[Tuple[float, float]] = None
            baseline_dist: Deque[Tuple[float, float]] = None
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

        results_by_track: Dict[int, List[Dict[str, Any]]] = defaultdict(list)

        stats: Dict[str, Any] = {
            "total_feature_records": 0,
            "discarded_tracks": discarded_tracks,
            "kept_tracks": len(kept_tracks),
            "track_discard_reasons": {str(k): v for k, v in track_discard_reasons.items()},
            "frames_pose_unavailable": 0,
            "frames_low_visibility": 0,
            "frames_baseline_not_ready": 0,
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
            if duration < self.min_interval_duration_sec:
                stats["intervals_discarded_duration"] += 1
                return
            if interval.frame_count <= 0:
                stats["intervals_discarded_empty"] += 1
                return

            avg_conf = float(interval.sum_confidence_weight / float(interval.frame_count))
            if avg_conf < self.min_interval_avg_confidence:
                stats["intervals_discarded_confidence"] += 1
                return

            avg_score = float(interval.sum_score / float(interval.frame_count))

            if interval.component_sum_frames > 0:
                head_avg = interval.head_signal_sum / float(interval.component_sum_frames)
                gaze_avg = interval.gaze_signal_sum / float(interval.component_sum_frames)
                prox_avg = interval.proximity_signal_sum / float(interval.component_sum_frames)
            else:
                head_avg = gaze_avg = prox_avg = 0.0

            comp_sorted = sorted(
                [
                    ("HeadDeviation", head_avg),
                    ("GazeDeviation", gaze_avg),
                    ("ProximityAnomaly", prox_avg),
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
            with features_jsonl_path.open("r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    stats["total_feature_records"] += 1
                    rec = json.loads(line)

                    tid = int(rec["track_id"])
                    if tid not in kept_tracks:
                        continue

                    state = _ensure_state(tid)
                    timestamp = float(rec["timestamp"])

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
                    final_score = 0.0
                    head_signal = 0.0
                    gaze_signal = 0.0
                    proximity_signal = 0.0
                    head_dev_flag = 0
                    gaze_dev_flag = 0

                    # 1) Update rolling baselines if pose quality is sufficient.
                    if pose is None:
                        stats["frames_pose_unavailable"] += 1
                    else:
                        pose_conf = float(pose.get("confidence", 0.0))
                        head_pose_conf = float(pose.get("head_pose_confidence", 0.0))
                        gaze_reliability = float(pose.get("gaze_reliability", 0.0))

                    baseline_ok = (
                        visibility_score >= float(config.MIN_FRAME_VISIBILITY_SCORE)
                        and pose_conf >= float(config.MIN_POSE_CONFIDENCE)
                        and head_pose_conf >= float(config.MIN_POSE_CONFIDENCE)
                        and gaze_reliability >= float(config.MIN_POSE_CONFIDENCE)
                    )

                    if not baseline_ok:
                        stats["frames_low_visibility"] += 1
                    else:
                        state.baseline_yaw.append((timestamp, float(pose["yaw"])))
                        state.baseline_gaze.append((timestamp, float(pose["gaze_x"])))
                        if nearest_distance is not None:
                            state.baseline_dist.append((timestamp, nearest_distance))

                # Prune rolling baselines.
                _prune(state.baseline_yaw, timestamp)
                _prune(state.baseline_gaze, timestamp)
                _prune(state.baseline_dist, timestamp)

                baseline_yaw, baseline_gaze, baseline_dist = _baseline_values(state)
                baseline_ready = baseline_yaw is not None and baseline_gaze is not None

                # 2) Compute signals and confidence-weighted score when possible.
                # (If baseline isn't ready or pose missing, score stays 0, but EMA still updates.)
                if pose is not None and baseline_ready:
                    # Use the same quality gates as baseline update to avoid over-scoring.
                    pose_conf = float(pose.get("confidence", 0.0))
                    head_pose_conf = float(pose.get("head_pose_confidence", 0.0))
                    gaze_reliability = float(pose.get("gaze_reliability", 0.0))
                    quality_ok = (
                        visibility_score >= float(config.MIN_FRAME_VISIBILITY_SCORE)
                        and pose_conf >= float(config.MIN_POSE_CONFIDENCE)
                        and head_pose_conf >= float(config.MIN_POSE_CONFIDENCE)
                        and gaze_reliability >= float(config.MIN_POSE_CONFIDENCE)
                    )

                    if not quality_ok:
                        stats["frames_low_visibility"] += 1
                    else:
                        yaw = float(pose["yaw"])
                        gaze_x = float(pose["gaze_x"])

                        head_dev = abs(yaw - float(baseline_yaw))
                        gaze_dev = abs(gaze_x - float(baseline_gaze))

                        head_signal = _clamp(head_dev / float(config.HEAD_DEV_NORM_DEG), 0.0, 1.0)
                        gaze_signal = _clamp(gaze_dev / float(config.GAZE_DEV_NORM), 0.0, 1.0)

                        proximity_signal = 0.0
                        if baseline_dist is not None and nearest_distance is not None and baseline_dist > 0:
                            threshold = float(baseline_dist) * float(config.PROXIMITY_DISTANCE_RATIO_THRESHOLD)
                            if threshold > 1e-6 and nearest_distance <= threshold:
                                proximity_signal = _clamp((threshold - nearest_distance) / threshold, 0.0, 1.0)

                        raw_signal_score = (
                            self.weight_head * head_signal
                            + self.weight_gaze * gaze_signal
                            + self.weight_proximity * proximity_signal
                        )

                        occlusion_clarity = float(1.0 - occlusion_score)
                        confidence_weight = _clamp(
                            pose_conf
                            * visibility_score
                            * tracking_stability_score
                            * occlusion_clarity,
                            0.0,
                            1.0,
                        )
                        final_score = raw_signal_score * confidence_weight

                        head_dev_flag = 1 if head_signal >= 1.0 else 0
                        gaze_dev_flag = 1 if gaze_signal >= 1.0 else 0
                        stats["frames_pose_unavailable"] += 0  # no-op for explicitness
                else:
                    stats["frames_baseline_not_ready"] += 1

                # 3) Update EMA always.
                state.ema = self.alpha * float(final_score) + (1.0 - self.alpha) * float(state.ema)

                # Persist per-frame scoring for audit/debugging.
                if frame_scores_fp is not None:
                    frame_scores_fp.write(
                        json.dumps(
                            {
                                "timestamp": float(timestamp),
                                "track_id": int(tid),
                                "final_score": float(final_score),
                                "raw_signal_score": float(raw_signal_score),
                                "confidence_weight": float(confidence_weight),
                                "head_signal": float(head_signal),
                                "gaze_signal": float(gaze_signal),
                                "proximity_signal": float(proximity_signal),
                                "baseline_ready": bool(baseline_ready),
                                "visibility_score": float(visibility_score),
                                "occlusion_score": float(occlusion_score),
                            }
                        )
                        + "\n"
                    )

                # 4) Interval transitions + accumulation.
                if state.interval_open and state.interval is not None:
                    interval = state.interval
                    interval.end_time = timestamp
                    interval.frame_count += 1
                    interval.sum_score += float(final_score)
                    interval.peak_score = max(float(interval.peak_score), float(final_score))
                    interval.sum_confidence_weight += float(confidence_weight)

                    # Components/support only if we computed signals this frame.
                    if pose is not None and baseline_ready and confidence_weight > 0.0:
                        interval.head_signal_sum += float(head_signal)
                        interval.gaze_signal_sum += float(gaze_signal)
                        interval.proximity_signal_sum += float(proximity_signal)
                        interval.component_sum_frames += 1

                        interval.head_deviation_flag_count += int(head_dev_flag)
                        interval.gaze_deviation_flag_count += int(gaze_dev_flag)

                        if nearest_distance is not None:
                            interval.proximity_distance_sum += float(nearest_distance)
                            interval.proximity_distance_count += 1
                            if interval.proximity_distance_min is None:
                                interval.proximity_distance_min = float(nearest_distance)
                            else:
                                interval.proximity_distance_min = min(float(interval.proximity_distance_min), float(nearest_distance))

                    if state.ema <= self.exit_th:
                        _finalize_interval(tid, interval)
                        state.interval_open = False
                        state.interval = None

                # Start new interval if not open.
                if not state.interval_open and state.ema >= self.enter_th:
                    state.interval_open = True
                    state.interval = IntervalAcc(start_time=timestamp, end_time=timestamp)
                    # Accumulate this frame as part of the interval.
                    interval = state.interval
                    interval.frame_count = 1
                    interval.sum_score = float(final_score)
                    interval.peak_score = max(float(interval.peak_score), float(final_score))
                    interval.sum_confidence_weight = float(confidence_weight)

                    if pose is not None and baseline_ready and confidence_weight > 0.0:
                        interval.head_signal_sum = float(head_signal)
                        interval.gaze_signal_sum = float(gaze_signal)
                        interval.proximity_signal_sum = float(proximity_signal)
                        interval.component_sum_frames = 1
                        interval.head_deviation_flag_count = int(head_dev_flag)
                        interval.gaze_deviation_flag_count = int(gaze_dev_flag)
                        if nearest_distance is not None:
                            interval.proximity_distance_sum = float(nearest_distance)
                            interval.proximity_distance_count = 1
                            interval.proximity_distance_min = float(nearest_distance)

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
                    "duration": float(a["end"] - a["start"] + (b["end"] - b["start"])) if (a["end"] and b["end"]) else float(total_dur),
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

