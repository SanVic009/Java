"""
Phase 1: Uncertainty-aware feature extraction (no decisions).

For each sampled frame and each active track_id, we persist:
- bbox
- detection confidence
- pose/gaze (with confidence metrics)
- tracking confidence/stability
- frame quality (blur/occlusion/visibility)
- proximity features (nearest neighbor distances)

The output is persisted to JSONL so Phase 2 can be re-run independently.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from analysis.pose_estimator import PoseEstimator
from config import config
from detection import ByteTracker, Detection, PersonDetector, Track


def _iou_xyxy(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> float:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = max(0, a[2] - a[0]) * max(0, a[3] - a[1])
    area_b = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    union = area_a + area_b - inter
    return float(inter / union) if union > 0 else 0.0


def _laplacian_blur_quality(gray: np.ndarray) -> float:
    """
    Map blur sharpness to a 0..1 quality score.

    Higher Laplacian variance => sharper image.
    """
    if gray.size == 0:
        return 0.0
    var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    # Heuristic normalization; tuned later using real data.
    # Typical Laplacian variances vary widely, so we use a soft clip.
    return float(np.clip(var / 500.0, 0.0, 1.0))


class FeatureExtractorPhase1:
    def __init__(self):
        self.detector = PersonDetector(confidence=config.YOLO_CONFIDENCE)
        self.tracker: Optional[ByteTracker] = None
        self.pose_estimator = PoseEstimator()

    def extract(
        self,
        exam_id: str,
        video_path: str,
        fps_sampling: int,
        out_features_path: Path,
        out_track_meta_path: Path,
        out_phase1_stats_path: Path,
    ) -> Dict[str, Any]:
        """
        Run Phase 1 feature extraction and persist results to disk.
        """
        video = self._resolve_video_path(video_path)
        if not video.exists():
            raise FileNotFoundError(f"Video not found: {video}")

        cap = cv2.VideoCapture(str(video))
        if not cap.isOpened():
            raise RuntimeError(f"Failed to open video: {video}")

        original_fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration_sec = total_frames / original_fps if original_fps and original_fps > 0 else 0.0

        frame_skip = max(1, int(original_fps / float(fps_sampling))) if original_fps else 1
        sampled_frames = total_frames // frame_skip if frame_skip else 0

        # Tracker stores identity & stability. We give it fps_sampling to reason about ID-switch lookback.
        self.tracker = ByteTracker(
            fps_sampling=float(fps_sampling),
            id_switch_distance_px=config.ID_SWITCH_DISTANCE_PX,
            id_switch_lookback_sec=config.ID_SWITCH_LOOKBACK_SEC,
        )

        # Track meta built online from persisted features.
        track_meta: Dict[int, Dict[str, Any]] = {}

        # Observability
        stats: Dict[str, Any] = {
            "exam_id": exam_id,
            "video_path": str(video),
            "original_fps": original_fps,
            "total_frames": total_frames,
            "duration_sec": duration_sec,
            "fps_sampling": fps_sampling,
            "frame_skip": frame_skip,
            "sampled_frames_estimate": sampled_frames,
            "frames_read": 0,
            "frames_sampled": 0,
            "frames_skipped": 0,
            "frames_with_any_detection": 0,
            "detections_per_sample_frame_sum": 0,
            "pose_frames_attempted": 0,
            "pose_frames_succeeded": 0,
            "avg_pose_confidence_sum": 0.0,
            "avg_pose_landmark_visibility_sum": 0.0,
            "avg_detection_confidence_sum": 0.0,
            "avg_tracking_confidence_sum": 0.0,
            "tracking_id_switch_events": 0,
            "records_written": 0,
        }

        # Ensure output directory exists.
        out_features_path.parent.mkdir(parents=True, exist_ok=True)

        with out_features_path.open("w", encoding="utf-8") as f:
            frame_idx = 0
            sample_idx = 0
            try:
                while True:
                    ret, frame = cap.read()
                    if not ret:
                        break

                    stats["frames_read"] += 1

                    if frame_idx % frame_skip == 0:
                        timestamp = float(frame_idx) / float(original_fps) if original_fps else 0.0
                        stats["frames_sampled"] += 1

                        detections: List[Detection] = self.detector.detect(frame)
                        if detections:
                            stats["frames_with_any_detection"] += 1
                        stats["detections_per_sample_frame_sum"] += float(len(detections))
                        stats["avg_detection_confidence_sum"] += (
                            float(np.mean([d.confidence for d in detections])) if detections else 0.0
                        )

                        tracks: List[Track] = self.tracker.update(detections, frame_idx=sample_idx)

                        visible_tracks = [t for t in tracks if t.time_since_update == 0]

                        # Precompute visible bboxes list for occlusion and proximity.
                        visible_bboxes = [(t.track_id, t.bbox) for t in visible_tracks]

                        for track in tracks:
                            track_id = int(track.track_id)
                            is_visible = (track.time_since_update == 0)

                            # Detection confidence
                            det_conf = float(track.last_detection_confidence) if is_visible else 0.0

                            # Occlusion estimate: max IoU with other visible tracks.
                            occlusion_score = 0.0
                            if is_visible and len(visible_bboxes) > 1:
                                for other_id, other_bbox in visible_bboxes:
                                    if other_id == track_id:
                                        continue
                                    occlusion_score = max(occlusion_score, _iou_xyxy(track.bbox, other_bbox))

                            # Blur quality
                            x1, y1, x2, y2 = track.bbox
                            x1 = max(0, x1)
                            y1 = max(0, y1)
                            x2 = min(frame.shape[1] - 1, x2)
                            y2 = min(frame.shape[0] - 1, y2)
                            crop = frame[y1:y2, x1:x2]
                            blur_quality = _laplacian_blur_quality(
                                cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.size > 0 else np.zeros((1, 1), dtype=np.uint8)
                            )

                            # Pose / gaze estimation (only when visible).
                            pose_payload: Optional[Dict[str, Any]] = None
                            visibility_score = 0.0
                            if is_visible:
                                stats["pose_frames_attempted"] += 1
                                pose = self.pose_estimator.estimate(
                                    frame,
                                    track.bbox,
                                    detection_confidence=det_conf,
                                )
                                if pose is not None:
                                    stats["pose_frames_succeeded"] += 1
                                    stats["avg_pose_confidence_sum"] += float(pose.confidence)
                                    stats["avg_pose_landmark_visibility_sum"] += float(pose.landmark_visibility)
                                    visibility_score = float(np.clip(pose.landmark_visibility * (1.0 - occlusion_score), 0.0, 1.0))

                                    pose_payload = {
                                        "yaw": pose.yaw,
                                        "pitch": pose.pitch,
                                        "roll": pose.roll,
                                        "gaze_x": pose.gaze_x,
                                        "gaze_y": pose.gaze_y,
                                        "landmark_visibility": pose.landmark_visibility,
                                        "head_pose_confidence": pose.head_pose_confidence,
                                        "gaze_reliability": pose.gaze_reliability,
                                        "confidence": pose.confidence,
                                        "pose_keypoints_2d": pose.pose_keypoints_2d,
                                        "face_visible": pose.face_visible,
                                        "estimation_mode": pose.estimation_mode,
                                        "face_detect_confidence": pose.face_detect_confidence,
                                        "bbox_aspect_ratio": pose.bbox_aspect_ratio,
                                        "bbox_orientation_deg": pose.bbox_orientation_deg,
                                    }

                            # Proximity features: nearest visible neighbor distance.
                            nearest_neighbor_track_id: Optional[int] = None
                            nearest_neighbor_distance: Optional[float] = None
                            if visible_tracks and len(visible_tracks) > 1:
                                min_d = None
                                for other in visible_tracks:
                                    if other.track_id == track.track_id:
                                        continue
                                    dx = float(track.centroid[0] - other.centroid[0])
                                    dy = float(track.centroid[1] - other.centroid[1])
                                    d = float(np.sqrt(dx * dx + dy * dy))
                                    if min_d is None or d < min_d:
                                        min_d = d
                                        nearest_neighbor_distance = d
                                        nearest_neighbor_track_id = int(other.track_id)

                            proximity_confidence = float(visibility_score)

                            # Tracking confidence / stability
                            tracking_confidence = float(track.mean_detection_confidence())
                            tracking_stability = float(track.stability_score())

                            # Persist one record.
                            record = {
                                "exam_id": exam_id,
                                "timestamp": timestamp,
                                "frame_sample_idx": int(sample_idx),
                                "track_id": track_id,
                                "estimation_mode": (
                                    pose_payload.get("estimation_mode")
                                    if pose_payload is not None
                                    else None
                                ),

                                "bbox": list(track.bbox),
                                "detection": {
                                    "confidence": det_conf,
                                },

                                "pose": pose_payload,  # None if pose failed/unavailable

                                "quality": {
                                    "blur_quality": blur_quality,
                                    "occlusion_score": occlusion_score,
                                    "visibility_score": visibility_score,
                                },

                                "tracking": {
                                    "tracking_confidence": tracking_confidence,
                                    "tracking_stability_score": tracking_stability,
                                    "id_switch_count": int(track.id_switch_count),
                                },

                                "proximity": {
                                    "nearest_neighbor_track_id": nearest_neighbor_track_id,
                                    "nearest_neighbor_distance": nearest_neighbor_distance,
                                    "proximity_confidence": proximity_confidence,
                                },
                            }

                            f.write(json.dumps(record) + "\n")
                            stats["records_written"] += 1

                            # Update meta (online; used in Phase 2 gates).
                            meta = track_meta.get(track_id)
                            if meta is None:
                                meta = {
                                    "track_id": track_id,
                                    "start_time": None,
                                    "end_time": None,
                                    "total_visible_frames": 0,
                                    "total_visible_duration_sec": 0.0,
                                    "id_switch_count": int(track.id_switch_count),
                                    "avg_tracking_confidence_sum": 0.0,
                                    "visible_frames_for_conf_avg": 0,
                                    "stability_score": tracking_stability,
                                }
                                track_meta[track_id] = meta

                            if is_visible:
                                if meta["start_time"] is None:
                                    meta["start_time"] = timestamp
                                meta["end_time"] = timestamp
                                meta["total_visible_frames"] += 1
                                meta["avg_tracking_confidence_sum"] += tracking_confidence
                                meta["visible_frames_for_conf_avg"] += 1
                                meta["stability_score"] = tracking_stability
                                meta["id_switch_count"] = int(track.id_switch_count)

                        sample_idx += 1

                    frame_idx += 1
            finally:
                cap.release()
                self.pose_estimator.close()

        # Finalize meta and stats.
        stats["frames_skipped"] = max(0, stats["frames_read"] - stats["frames_sampled"])
        stats["tracking_id_switch_events"] = int(self.tracker.id_switch_events) if self.tracker else 0
        stats["detections_per_sample_frame_avg"] = (
            stats["detections_per_sample_frame_sum"] / stats["frames_sampled"]
            if stats["frames_sampled"] > 0
            else 0.0
        )
        stats["pose_success_rate"] = (
            stats["pose_frames_succeeded"] / stats["pose_frames_attempted"]
            if stats["pose_frames_attempted"] > 0
            else 0.0
        )
        stats["avg_pose_confidence"] = (
            stats["avg_pose_confidence_sum"] / stats["pose_frames_succeeded"]
            if stats["pose_frames_succeeded"] > 0
            else 0.0
        )
        stats["avg_pose_landmark_visibility"] = (
            stats["avg_pose_landmark_visibility_sum"] / stats["pose_frames_succeeded"]
            if stats["pose_frames_succeeded"] > 0
            else 0.0
        )

        # Convert visible frames to duration seconds.
        for _, meta in track_meta.items():
            meta["total_visible_duration_sec"] = float(meta["total_visible_frames"]) / float(fps_sampling)
            denom = meta["visible_frames_for_conf_avg"]
            meta["avg_tracking_confidence"] = (
                float(meta["avg_tracking_confidence_sum"]) / float(denom) if denom > 0 else 0.0
            )
            # Remove internal fields.
            meta.pop("avg_tracking_confidence_sum", None)
            meta.pop("visible_frames_for_conf_avg", None)
            meta.pop("total_visible_frames", None)

        # Log an audit-friendly summary.
        print("\n[Phase1 Summary]")
        print(f"  frames_read={stats['frames_read']}, frames_sampled={stats['frames_sampled']}, frames_skipped={stats['frames_skipped']}")
        print(f"  detections_per_sample_frame_avg={stats.get('detections_per_sample_frame_avg', 0.0):.3f}")
        print(f"  pose_success_rate={stats.get('pose_success_rate', 0.0):.3f}")
        print(f"  avg_pose_confidence={stats.get('avg_pose_confidence', 0.0):.3f}")
        print(f"  tracking_id_switch_events={stats.get('tracking_id_switch_events', 0)}")
        print(f"  tracks_persisted={len(track_meta)}")

        out_track_meta_path.parent.mkdir(parents=True, exist_ok=True)
        out_track_meta_path.write_text(json.dumps(list(track_meta.values()), indent=2), encoding="utf-8")
        out_phase1_stats_path.parent.mkdir(parents=True, exist_ok=True)
        out_phase1_stats_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")

        return stats

    @staticmethod
    def _resolve_video_path(video_path: str) -> Path:
        """
        Resolve a video path from common locations used by this workspace.
        """
        raw = Path(video_path).expanduser()
        service_root = Path(__file__).resolve().parents[1]  # python-cv-service
        project_root = service_root.parent

        candidates: List[Path] = []
        if raw.is_absolute():
            candidates.append(raw)
        else:
            candidates.extend(
                [
                    raw,
                    Path.cwd() / raw,
                    service_root / raw,
                    project_root / raw,
                    project_root / "java-orchestrator" / "videos" / raw,
                    project_root / "java-orchestrator" / "videos" / raw.name,
                    project_root / "videos" / raw,
                    project_root / "videos" / raw.name,
                ]
            )

        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate.resolve()

        checked = "\n".join(f"- {str(p)}" for p in candidates)
        raise FileNotFoundError(f"Video not found: {video_path}. Checked:\n{checked}")

