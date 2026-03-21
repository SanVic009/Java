"""
ByteTrack multi-object tracker implementation.
Simplified version for classroom tracking scenario.
"""
import numpy as np
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field
from scipy.optimize import linear_sum_assignment
from filterpy.kalman import KalmanFilter


@dataclass
class Track:
    """Single tracked object."""
    track_id: int
    bbox: Tuple[int, int, int, int]
    centroid: Tuple[int, int]
    age: int = 0  # counts total frames (visible + missed)
    hits: int = 0  # counts visible updates
    time_since_update: int = 0

    # Detection confidence history for this track (used as "track confidence").
    last_detection_confidence: float = 0.0
    detection_confidence_sum: float = 0.0
    detection_confidence_count: int = 0

    # Track lifecycle metadata (in tracker frames, not wall-clock).
    start_frame_idx: int = 0
    end_frame_idx: int = 0
    visible_frames: int = 0

    # Heuristic approximation: without ground truth, ID-switches are detected as
    # track fragmentation near recently-ended tracks.
    id_switch_count: int = 0
    
    def update(self, bbox: Tuple[int, int, int, int], confidence: float, frame_idx: int):
        """Update track with a new detection."""
        self.bbox = bbox
        x1, y1, x2, y2 = bbox
        self.centroid = ((x1 + x2) // 2, (y1 + y2) // 2)
        self.hits += 1
        self.visible_frames += 1
        self.time_since_update = 0
        self.age += 1

        self.last_detection_confidence = float(confidence)
        self.detection_confidence_sum += float(confidence)
        self.detection_confidence_count += 1
        self.end_frame_idx = frame_idx
    
    def mark_missed(self, frame_idx: int):
        """Mark track as missed in current frame."""
        self.time_since_update += 1
        self.age += 1
        self.end_frame_idx = frame_idx

    def mean_detection_confidence(self) -> float:
        if self.detection_confidence_count <= 0:
            return 0.0
        return float(self.detection_confidence_sum / self.detection_confidence_count)

    def stability_score(self) -> float:
        """
        Track stability score in [0,1].

        This is heuristic: combines presence ratio with ID fragmentation penalty.
        """
        if self.age <= 0:
            return 0.0
        presence = float(self.hits) / float(self.age)
        id_factor = 1.0 / (1.0 + float(self.id_switch_count))
        return float(np.clip(presence * id_factor, 0.0, 1.0))


class ByteTracker:
    """
    Simplified ByteTrack implementation for classroom tracking.
    Uses IoU-based association with high/low confidence detection handling.
    """
    
    def __init__(
        self,
        track_thresh: float = 0.5,
        track_buffer: int = 10,
        match_thresh: float = 0.35,
        fps_sampling: float = 5.0,
        id_switch_distance_px: float = 60.0,
        id_switch_lookback_sec: float = 15.0
    ):
        """
        Initialize ByteTracker.
        
        Args:
            track_thresh: Threshold to separate high/low confidence detections
            track_buffer: Frames to keep lost tracks
            match_thresh: IoU threshold for matching
        """
        self.track_thresh = track_thresh
        self.track_buffer = track_buffer
        self.match_thresh = match_thresh

        self.fps_sampling = fps_sampling
        self.id_switch_distance_px = id_switch_distance_px
        self.id_switch_lookback_frames = max(1, int(id_switch_lookback_sec * fps_sampling))
        
        self.tracks: List[Track] = []
        self.lost_tracks: List[Track] = []
        self.next_id = 1

        self._ended_track_events: List[Tuple[int, Tuple[int, int]]] = []  # (end_frame_idx, centroid)
        self.id_switch_events: int = 0

        self._frame_idx: int = 0
        
        print(f"[Tracker] Initialized ByteTracker with buffer={track_buffer}")
    
    def update(self, detections: List['Detection'], frame_idx: Optional[int] = None) -> List[Track]:
        """
        Update tracker with new detections.
        
        Args:
            detections: List of Detection objects from detector
            
        Returns:
            List of active tracks
        """
        if frame_idx is None:
            self._frame_idx += 1
            frame_idx = self._frame_idx
        else:
            self._frame_idx = frame_idx

        if not detections:
            # Mark all tracks as missed
            for track in self.tracks:
                track.mark_missed(frame_idx)
            self._handle_lost_tracks()
            return self.tracks
        
        # Separate high and low confidence detections
        high_dets = [d for d in detections if d.confidence >= self.track_thresh]
        low_dets = [d for d in detections if d.confidence < self.track_thresh]
        
        # First association: high confidence detections with active tracks
        unmatched_tracks, unmatched_dets = self._associate(
            self.tracks, high_dets
        )
        
        # Second association: unmatched tracks with low confidence detections
        if unmatched_tracks and low_dets:
            remaining_tracks = [self.tracks[i] for i in unmatched_tracks]
            still_unmatched, _ = self._associate(remaining_tracks, low_dets)
            unmatched_tracks = [unmatched_tracks[i] for i in still_unmatched]
        
        # Handle unmatched tracks
        for idx in unmatched_tracks:
            self.tracks[idx].mark_missed(frame_idx)
        
        # Create new tracks for unmatched high confidence detections
        for idx in unmatched_dets:
            det = high_dets[idx]
            # Approximate ID-switch detection by proximity to recently-ended tracks.
            id_switches = 0
            for ended_frame, ended_centroid in self._ended_track_events:
                if ended_frame < frame_idx - self.id_switch_lookback_frames:
                    continue
                dx = ended_centroid[0] - det.centroid[0]
                dy = ended_centroid[1] - det.centroid[1]
                dist = float(np.sqrt(dx * dx + dy * dy))
                if dist <= self.id_switch_distance_px:
                    id_switches += 1
                    break

            new_track = Track(
                track_id=self.next_id,
                bbox=det.bbox,
                centroid=det.centroid
            )
            new_track.start_frame_idx = frame_idx
            new_track.end_frame_idx = frame_idx
            # Initialize stats based on this first detection.
            new_track.update(det.bbox, det.confidence, frame_idx)
            new_track.id_switch_count = id_switches
            self.id_switch_events += id_switches
            self.tracks.append(new_track)
            self.next_id += 1
        
        self._handle_lost_tracks()
        
        return self.tracks
    
    def _associate(
        self,
        tracks: List[Track],
        detections: List['Detection']
    ) -> Tuple[List[int], List[int]]:
        """
        Associate tracks with detections using IoU.
        
        Returns:
            Tuple of (unmatched_track_indices, unmatched_detection_indices)
        """
        if not tracks or not detections:
            return list(range(len(tracks))), list(range(len(detections)))
        
        # Compute IoU matrix
        iou_matrix = np.zeros((len(tracks), len(detections)))
        for t, track in enumerate(tracks):
            for d, det in enumerate(detections):
                iou_matrix[t, d] = self._compute_iou(track.bbox, det.bbox)
        
        # Use Hungarian algorithm for optimal assignment
        row_indices, col_indices = linear_sum_assignment(-iou_matrix)
        
        matched_tracks = set()
        matched_dets = set()
        
        # Note: we update track state after association, but actual frame_idx is
        # available from ByteTracker.update().
        frame_idx = self._frame_idx

        for row, col in zip(row_indices, col_indices):
            iou_ok = iou_matrix[row, col] >= self.match_thresh
            if not iou_ok:
                cx1, cy1 = tracks[row].centroid
                cx2, cy2 = detections[col].centroid[0], detections[col].centroid[1]
                dist = float(np.sqrt((cx1 - cx2) ** 2 + (cy1 - cy2) ** 2))
                x1, y1, x2, y2 = tracks[row].bbox
                diag = float(np.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2))
                centroid_ok = dist <= (diag * 0.15)
            else:
                centroid_ok = False

            if iou_ok or centroid_ok:
                tracks[row].update(detections[col].bbox, detections[col].confidence, frame_idx)
                matched_tracks.add(row)
                matched_dets.add(col)
        
        unmatched_tracks = [i for i in range(len(tracks)) if i not in matched_tracks]
        unmatched_dets = [i for i in range(len(detections)) if i not in matched_dets]
        
        return unmatched_tracks, unmatched_dets
    
    def _compute_iou(
        self,
        bbox1: Tuple[int, int, int, int],
        bbox2: Tuple[int, int, int, int]
    ) -> float:
        """Compute IoU between two bounding boxes."""
        x1 = max(bbox1[0], bbox2[0])
        y1 = max(bbox1[1], bbox2[1])
        x2 = min(bbox1[2], bbox2[2])
        y2 = min(bbox1[3], bbox2[3])
        
        inter_area = max(0, x2 - x1) * max(0, y2 - y1)
        
        area1 = (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1])
        area2 = (bbox2[2] - bbox2[0]) * (bbox2[3] - bbox2[1])
        
        union_area = area1 + area2 - inter_area
        
        return inter_area / union_area if union_area > 0 else 0
    
    def _handle_lost_tracks(self):
        """Move lost tracks and remove old ones."""
        active_tracks = []
        
        for track in self.tracks:
            if track.time_since_update > self.track_buffer:
                self.lost_tracks.append(track)
                # Record ended identity event for ID-switch approximation.
                self._ended_track_events.append((track.end_frame_idx, track.centroid))
            else:
                active_tracks.append(track)
        
        self.tracks = active_tracks
        
        # Clean up very old lost tracks
        self.lost_tracks = [
            t for t in self.lost_tracks 
            if t.time_since_update <= self.track_buffer * 2
        ]

        # Keep ended events bounded.
        if len(self._ended_track_events) > 5000:
            self._ended_track_events = self._ended_track_events[-2000:]
    
    def reset(self):
        """Reset tracker state."""
        self.tracks = []
        self.lost_tracks = []
        self.next_id = 1
        self._ended_track_events = []
        self.id_switch_events = 0
        self._frame_idx = 0
