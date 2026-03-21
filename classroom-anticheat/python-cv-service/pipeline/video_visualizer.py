"""
Phase 3: annotated video rendering (pure visualization).

Constraints:
- No CV inference. Uses only persisted Phase 1/Phase 2 artifacts.
- Reads:
  - Phase 1 features JSONL (bounding boxes + pose confidence metrics)
  - Phase 2 results (intervals + dominant signals)
  - Phase 2 frame scores JSONL (final_score + confidence_weight per sampled frame)
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, DefaultDict, Dict, List, Optional, Tuple

import cv2
import numpy as np


@dataclass
class FrameAnn:
    bbox: List[int]  # [x1,y1,x2,y2]
    ema_score: float  # 0..1
    active: bool
    dominant_signals: List[str]
    confidence_weight: float  # 0..1
    interval_peak_score: float


class VideoVisualizer:
    def __init__(self):
        # BGR colors for OpenCV drawing.
        self.color_green = (0, 200, 0)
        self.color_amber = (0, 165, 255)
        self.color_red = (0, 0, 255)

        self.signal_labels = ["HeadDeviation", "GazeDeviation", "ProximityAnomaly"]

    def _clamp(self, x: float, lo: float = 0.0, hi: float = 1.0) -> float:
        return float(max(lo, min(hi, x)))

    def _blend_rect(self, frame: np.ndarray, x1: int, y1: int, x2: int, y2: int, bg_color, alpha: float):
        """
        Semi-transparent rectangle overlay for panel backgrounds.
        """
        x1 = max(0, min(frame.shape[1] - 1, x1))
        y1 = max(0, min(frame.shape[0] - 1, y1))
        x2 = max(0, min(frame.shape[1] - 1, x2))
        y2 = max(0, min(frame.shape[0] - 1, y2))
        if x2 <= x1 or y2 <= y1:
            return
        roi = frame[y1:y2, x1:x2]
        overlay = roi.copy()
        overlay[:, :] = bg_color
        blended = cv2.addWeighted(overlay, alpha, roi, 1.0 - alpha, 0)
        frame[y1:y2, x1:x2] = blended

    def render(
        self,
        job_id: str,
        source_video_path: str,
        phase2_results: Dict[str, Any],
        phase1_features_path: Path,
        out_video_path: Path,
        cfg,
    ) -> Dict[str, Any]:
        """
        Render an annotated video from persisted Phase 1/2 artifacts.

        Returns annotated_video info dict suitable for placing into API results.
        """
        job_dir = phase1_features_path.parent
        phase2_frame_scores_path = job_dir / "phase2_frame_scores.jsonl"

        cap = cv2.VideoCapture(source_video_path)
        if not cap.isOpened():
            raise RuntimeError(f"Failed to open source video: {source_video_path}")

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        if fps <= 0:
            fps = 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration_sec = float(total_frames) / float(fps) if total_frames > 0 else 0.0

        if total_frames <= 0:
            raise RuntimeError("Source video has zero frames")

        # ---- Phase 2: intervals_by_track (for active status + dominant signals) ----
        intervals_by_track: Dict[int, List[Dict[str, Any]]] = {}
        for tr in phase2_results.get("results", []):
            tid = int(tr["track_id"])
            intervals_by_track[tid] = tr.get("intervals", []) or []

        # We'll draw bboxes for all tracks present in Phase 1 features.
        # Phase 2 only provides intervals for the subset that passed quality gates.
        track_ids_sorted = sorted(intervals_by_track.keys())

        # ---- Build sample score/EMA/confidence lookups from phase2_frame_scores.jsonl ----
        # sample_conf[(tid, frame_idx)] = {final_score, confidence_weight, ema}
        alpha = float(cfg.EMA_ALPHA)
        sample_scores: DefaultDict[int, Dict[int, Tuple[float, float]]] = defaultdict(dict)
        # frame_idx estimates must be consistent with Phase 1/2 timestamp usage.
        if phase2_frame_scores_path.exists():
            with phase2_frame_scores_path.open("r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    rec = json.loads(line)
                    tid = int(rec["track_id"])
                    ts = float(rec["timestamp"])
                    frame_idx = int(round(ts * fps))
                    final_score = float(rec.get("final_score", 0.0))
                    conf_w = float(rec.get("confidence_weight", 0.0))
                    sample_scores[tid][frame_idx] = (final_score, conf_w)

        # Compute EMA at sampled frames
        sample_ema: DefaultDict[int, Dict[int, float]] = defaultdict(dict)
        for tid, frame_map in sample_scores.items():
            ema = 0.0
            for frame_idx in sorted(frame_map.keys()):
                score = float(frame_map[frame_idx][0])
                ema = alpha * score + (1.0 - alpha) * ema
                sample_ema[tid][frame_idx] = float(ema)

        # ---- Build sample bbox lookup from phase1_features.jsonl ----
        sample_bbox: DefaultDict[int, Dict[int, List[int]]] = defaultdict(dict)
        with phase1_features_path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                rec = json.loads(line)
                tid = int(rec["track_id"])
                ts = float(rec["timestamp"])
                frame_idx = int(round(ts * fps))
                bbox = rec.get("bbox")
                if not bbox:
                    continue
                sample_bbox[tid][frame_idx] = [int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])]

        # Now that we have all tracks from Phase 1, update the timeline/annotation universe.
        all_track_ids_sorted = sorted(sample_bbox.keys())

        # ---- Visual lookup: annotation per (track_id, frame_idx) with carry-forward ----
        carry_forward_max = int(cfg.CARRY_FORWARD_MAX_NON_SAMPLED_FRAMES)
        timeline_h = int(cfg.TIMELINE_HEIGHT_PX)
        row_h = int(cfg.TIMELINE_ROW_HEIGHT_PX)

        # Fit all tracks into the fixed-height timeline by shrinking row height if necessary.
        num_tracks = max(1, len(all_track_ids_sorted))
        if num_tracks * row_h > timeline_h:
            row_h = max(3, timeline_h // num_tracks)

        display_tracks = all_track_ids_sorted
        display_set = set(display_tracks)

        # ann_lookup[(tid, frame_idx)] = FrameAnn
        ann_lookup: Dict[Tuple[int, int], FrameAnn] = {}
        # for faster drawing: ann_by_frame[frame_idx] -> list[(tid, FrameAnn)]
        ann_by_frame: DefaultDict[int, List[Tuple[int, FrameAnn]]] = defaultdict(list)

        # Helper for active interval check.
        def _active_interval(tid: int, ts: float) -> Optional[Dict[str, Any]]:
            for interval in intervals_by_track.get(tid, []):
                if float(interval["start"]) <= ts <= float(interval["end"]):
                    return interval
            return None

        for tid in all_track_ids_sorted:
            frames_sorted = sorted(sample_bbox[tid].keys())
            if not frames_sorted:
                continue

            for i, fi in enumerate(frames_sorted):
                if fi < 0 or fi >= total_frames:
                    continue
                next_fi = frames_sorted[i + 1] if i + 1 < len(frames_sorted) else total_frames
                end_fill = min(total_frames - 1, next_fi - 1, fi + carry_forward_max)

                bbox = sample_bbox[tid][fi]
                score, conf_w = sample_scores.get(tid, {}).get(fi, (0.0, 0.0))
                ema = sample_ema.get(tid, {}).get(fi, 0.0)

                for f in range(fi, end_fill + 1):
                    ts = float(f) / fps
                    interval = _active_interval(tid, ts)
                    active = interval is not None
                    dominant = interval.get("dominant_signals", []) if active else []
                    peak = float(interval.get("peak_score", 0.0)) if active else 0.0
                    ann = FrameAnn(
                        bbox=bbox,
                        ema_score=self._clamp(float(ema), 0.0, 1.0),
                        active=bool(active),
                        dominant_signals=[str(x) for x in dominant],
                        confidence_weight=self._clamp(float(conf_w), 0.0, 1.0),
                        interval_peak_score=float(peak),
                    )
                    key = (tid, f)
                    ann_lookup[key] = ann
                    ann_by_frame[f].append((tid, ann))

        # ---- Output video writer ----
        out_video_path.parent.mkdir(parents=True, exist_ok=True)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(out_video_path), fourcc, fps, (width, height))
        if not writer.isOpened():
            raise RuntimeError(f"Failed to open video writer: {out_video_path}")

        # ---- Pre-render timeline background (segments) ----
        timeline_y0 = height - timeline_h
        timeline_bg = np.zeros((timeline_h, width, 3), dtype=np.uint8)

        for row_idx, tid in enumerate(display_tracks):
            y0 = row_idx * row_h
            y1 = min(timeline_h - 1, y0 + row_h - 1)
            # base row line
            cv2.rectangle(timeline_bg, (0, y0), (width - 1, y1), (30, 30, 30), thickness=-1)
            for interval in intervals_by_track.get(tid, []):
                start_s = float(interval["start"])
                end_s = float(interval["end"])
                if duration_sec <= 1e-6:
                    continue
                x_start = int((start_s / duration_sec) * width)
                x_end = int((end_s / duration_sec) * width)
                x_start = max(0, min(width - 1, x_start))
                x_end = max(0, min(width - 1, x_end))
                if x_end <= x_start:
                    continue
                peak = float(interval.get("peak_score", 0.0))
                color = self.color_red if peak >= float(cfg.HIGH_SUSPICION_PEAK_THRESHOLD) else self.color_amber
                cv2.rectangle(timeline_bg, (x_start, y0), (x_end, y1), color, thickness=-1)

        # Cursor line is dynamic.

        # ---- Frame drawing helpers ----
        def _draw_bbox_and_labels(frame: np.ndarray, tid: int, ann: FrameAnn):
            x1, y1, x2, y2 = ann.bbox
            # Choose color based on status.
            if not ann.active:
                color = self.color_green
            else:
                color = self.color_red if ann.interval_peak_score >= float(cfg.HIGH_SUSPICION_PEAK_THRESHOLD) else self.color_amber

            thickness = int(cfg.ANNOT_LINE_THICKNESS)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)

            # Track label above bbox.
            label = f"ID {tid}"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, float(cfg.ANNOT_FONT_SCALE), 1)
            lx1 = x1
            ly1 = max(0, y1 - th - 6)
            cv2.rectangle(frame, (lx1, ly1), (lx1 + tw + 6, ly1 + th + 6), color, thickness=-1)
            cv2.putText(frame, label, (lx1 + 3, ly1 + th + 2), cv2.FONT_HERSHEY_SIMPLEX, float(cfg.ANNOT_FONT_SCALE), (0, 0, 0), 1, cv2.LINE_AA)

            # Score bar and confidence indicator.
            self._draw_score_bar_and_confidence(frame, ann, x1, y2, color, cfg)

            # Checkbox panel when active.
            if ann.active:
                self._draw_signal_checkbox_panel(frame, x1, y1, ann.dominant_signals, cfg)

        def _draw_timeline_strip(frame: np.ndarray, cursor_x: int):
            # Blend timeline background into bottom area.
            roi = frame[timeline_y0:timeline_y0 + timeline_h, 0:width]
            blended = cv2.addWeighted(roi, 0.35, timeline_bg, 0.65, 0)
            frame[timeline_y0:timeline_y0 + timeline_h, 0:width] = blended

            cursor_x = max(0, min(width - 1, cursor_x))
            cv2.line(frame, (cursor_x, timeline_y0), (cursor_x, timeline_y0 + timeline_h - 1), (255, 255, 255), 1)

        # ---- Draw per frame ----
        frame_idx = 0
        while frame_idx < total_frames:
            ret, frame = cap.read()
            if not ret:
                break

            ts = float(frame_idx) / fps if fps > 0 else 0.0
            cursor_x = int((ts / duration_sec) * width) if duration_sec > 1e-6 else 0
            _draw_timeline_strip(frame, cursor_x)

            # Draw annotations for this frame.
            for tid, ann in ann_by_frame.get(frame_idx, []):
                _draw_bbox_and_labels(frame, tid, ann)

            writer.write(frame)
            frame_idx += 1

        cap.release()
        writer.release()

        return {
            "file_path": str(out_video_path),
            "status": "ready",
            "resolution": {"width": width, "height": height},
            "frame_rate": float(fps),
            "duration_sec": float(duration_sec),
        }

    def _draw_score_bar_and_confidence(self, frame: np.ndarray, ann: FrameAnn, x1: int, y2: int, color, cfg):
        """
        Draw a small horizontal score bar and numeric confidence weight.
        """
        bar_w = int(cfg.SCORE_BAR_WIDTH_PX)
        bar_h = int(cfg.SCORE_BAR_HEIGHT_PX)
        # Put bar just under bbox, but keep within frame excluding timeline area.
        timeline_top = frame.shape[0] - int(cfg.TIMELINE_HEIGHT_PX)
        y_bar = min(max(0, y2 + 2), max(0, timeline_top - bar_h - 1))
        x_bar = max(0, min(frame.shape[1] - bar_w - 1, x1))

        ema = self._clamp(float(ann.ema_score), 0.0, 1.0)
        fill_w = int(round(bar_w * ema))

        # Background bar
        cv2.rectangle(frame, (x_bar, y_bar), (x_bar + bar_w, y_bar + bar_h), (60, 60, 60), thickness=-1)
        if fill_w > 0:
            cv2.rectangle(frame, (x_bar, y_bar), (x_bar + fill_w, y_bar + bar_h), color, thickness=-1)

        # Confidence text near bar.
        cw = float(ann.confidence_weight)
        txt = f"cw:{cw:.2f}"
        (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, float(cfg.ANNOT_FONT_SCALE), 1)
        cv2.putText(frame, txt, (x_bar, max(0, y_bar - 4)), cv2.FONT_HERSHEY_SIMPLEX, float(cfg.ANNOT_FONT_SCALE), color, 1, cv2.LINE_AA)

    def _draw_signal_checkbox_panel(self, frame: np.ndarray, x1: int, y1: int, dominant_signals: List[str], cfg):
        """
        Semi-transparent panel with 3 labeled checkboxes.
        """
        box_w = 170
        box_h = 45
        timeline_top = frame.shape[0] - int(cfg.TIMELINE_HEIGHT_PX)

        px1 = max(0, min(frame.shape[1] - box_w - 1, x1))
        px2 = px1 + box_w
        py2 = min(timeline_top - 1, y1 + 5 + box_h)
        py1 = max(0, py2 - box_h)

        # Semi-transparent background
        self._blend_rect(frame, px1, py1, px2, py2, (20, 20, 20), alpha=0.45)
        cv2.rectangle(frame, (px1, py1), (px2, py2), (220, 220, 220), thickness=1)

        dom = set(dominant_signals or [])
        labels = self.signal_labels

        # checkbox geometry
        cb_size = 10
        pad = 8
        start_y = py1 + 14
        line_gap = 10

        for idx, lab in enumerate(labels):
            cy = start_y + idx * line_gap
            cx = px1 + pad
            # checkbox
            cv2.rectangle(frame, (cx, cy), (cx + cb_size, cy + cb_size), (230, 230, 230), thickness=1)
            if lab in dom:
                # check mark
                cv2.line(frame, (cx + 2, cy + 7), (cx + 5, cy + 10), (230, 230, 230), 2)
                cv2.line(frame, (cx + 5, cy + 10), (cx + 12, cy + 2), (230, 230, 230), 2)
            # label text
            text_x = cx + cb_size + 6
            cv2.putText(
                frame,
                lab,
                (text_x, cy + 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.35,
                (230, 230, 230),
                1,
                cv2.LINE_AA,
            )

