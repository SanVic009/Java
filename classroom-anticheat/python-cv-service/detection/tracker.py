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
    age: int = 0
    hits: int = 1
    time_since_update: int = 0
    
    def update(self, bbox: Tuple[int, int, int, int]):
        """Update track with new detection."""
        self.bbox = bbox
        x1, y1, x2, y2 = bbox
        self.centroid = ((x1 + x2) // 2, (y1 + y2) // 2)
        self.hits += 1
        self.time_since_update = 0
        self.age += 1
    
    def mark_missed(self):
        """Mark track as missed in current frame."""
        self.time_since_update += 1
        self.age += 1


class ByteTracker:
    """
    Simplified ByteTrack implementation for classroom tracking.
    Uses IoU-based association with high/low confidence detection handling.
    """
    
    def __init__(
        self,
        track_thresh: float = 0.5,
        track_buffer: int = 30,
        match_thresh: float = 0.8
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
        
        self.tracks: List[Track] = []
        self.lost_tracks: List[Track] = []
        self.next_id = 1
        
        print(f"[Tracker] Initialized ByteTracker with buffer={track_buffer}")
    
    def update(self, detections: List['Detection']) -> List[Track]:
        """
        Update tracker with new detections.
        
        Args:
            detections: List of Detection objects from detector
            
        Returns:
            List of active tracks
        """
        if not detections:
            # Mark all tracks as missed
            for track in self.tracks:
                track.mark_missed()
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
            self.tracks[idx].mark_missed()
        
        # Create new tracks for unmatched high confidence detections
        for idx in unmatched_dets:
            det = high_dets[idx]
            new_track = Track(
                track_id=self.next_id,
                bbox=det.bbox,
                centroid=det.centroid
            )
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
        
        for row, col in zip(row_indices, col_indices):
            if iou_matrix[row, col] >= self.match_thresh:
                tracks[row].update(detections[col].bbox)
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
            else:
                active_tracks.append(track)
        
        self.tracks = active_tracks
        
        # Clean up very old lost tracks
        self.lost_tracks = [
            t for t in self.lost_tracks 
            if t.time_since_update <= self.track_buffer * 2
        ]
    
    def reset(self):
        """Reset tracker state."""
        self.tracks = []
        self.lost_tracks = []
        self.next_id = 1
