"""
Temporal aggregation and interval generation.
Applies sliding window analysis and merges nearby intervals.
"""
from typing import Dict, List, Tuple
from dataclasses import dataclass
from collections import defaultdict
from analysis.scorer import FrameScore, Scorer
from config import config


@dataclass
class SuspiciousInterval:
    """A suspicious time interval for a student."""
    start: float  # Start time in seconds
    end: float  # End time in seconds
    peak_score: float
    reasons: List[str]
    frame_count: int = 0


class TemporalAggregator:
    """
    Aggregates frame scores into suspicious intervals.
    
    Uses sliding window of 30 seconds (150 frames at 5 FPS).
    Window is suspicious if >= 20% of frames are suspicious.
    Merges intervals separated by < 5 seconds.
    """
    
    def __init__(self, fps: int):
        self.fps = fps
        self.window_size = config.WINDOW_SIZE_SEC * fps  # frames
        self.suspicious_ratio = config.SUSPICIOUS_FRAME_RATIO
        self.merge_gap = config.MERGE_GAP_SEC
        
        # Storage for frame scores per student
        self.student_scores: Dict[int, List[FrameScore]] = defaultdict(list)
        
        print(f"[TemporalAggregator] Window: {config.WINDOW_SIZE_SEC}s "
              f"({self.window_size} frames)")
        print(f"[TemporalAggregator] Suspicious ratio: {self.suspicious_ratio}")
        print(f"[TemporalAggregator] Merge gap: {self.merge_gap}s")
    
    def add_score(self, frame_score: FrameScore):
        """Add a frame score for a student."""
        self.student_scores[frame_score.student_id].append(frame_score)
    
    def aggregate(self) -> Dict[int, List[SuspiciousInterval]]:
        """
        Aggregate all scores into suspicious intervals per student.
        
        Returns:
            Dict mapping student_id -> list of SuspiciousInterval
        """
        results = {}
        
        for student_id, scores in self.student_scores.items():
            if not scores:
                continue
            
            # Sort by frame index
            scores.sort(key=lambda x: x.frame_idx)
            
            # Find suspicious windows
            suspicious_windows = self._find_suspicious_windows(scores)
            
            # Merge nearby windows into intervals
            intervals = self._merge_windows(suspicious_windows, scores)
            
            if intervals:
                results[student_id] = intervals
                print(f"[TemporalAggregator] Student {student_id}: "
                      f"{len(intervals)} suspicious intervals")
        
        return results
    
    def _find_suspicious_windows(
        self, 
        scores: List[FrameScore]
    ) -> List[Tuple[int, int]]:
        """
        Find windows where suspicious frame ratio exceeds threshold.
        
        Returns:
            List of (start_frame_idx, end_frame_idx) tuples
        """
        if len(scores) < self.window_size:
            # Not enough frames for a full window
            # Check if the whole video is suspicious
            suspicious_count = sum(1 for s in scores if s.is_suspicious)
            if suspicious_count / len(scores) >= self.suspicious_ratio:
                return [(scores[0].frame_idx, scores[-1].frame_idx)]
            return []
        
        suspicious_windows = []
        suspicious_count = 0
        
        # Initialize first window
        for i in range(min(self.window_size, len(scores))):
            if scores[i].is_suspicious:
                suspicious_count += 1
        
        # Slide window
        for i in range(len(scores) - self.window_size + 1):
            ratio = suspicious_count / self.window_size
            
            if ratio >= self.suspicious_ratio:
                start_idx = scores[i].frame_idx
                end_idx = scores[i + self.window_size - 1].frame_idx
                suspicious_windows.append((start_idx, end_idx))
            
            # Slide: remove leaving frame, add entering frame
            if i + self.window_size < len(scores):
                if scores[i].is_suspicious:
                    suspicious_count -= 1
                if scores[i + self.window_size].is_suspicious:
                    suspicious_count += 1
        
        return suspicious_windows
    
    def _merge_windows(
        self,
        windows: List[Tuple[int, int]],
        scores: List[FrameScore]
    ) -> List[SuspiciousInterval]:
        """
        Merge overlapping or nearby windows into intervals.
        """
        if not windows:
            return []
        
        # Sort by start frame
        windows.sort(key=lambda x: x[0])
        
        # Merge overlapping/nearby windows
        merged = []
        current_start, current_end = windows[0]
        
        merge_gap_frames = self.merge_gap * self.fps
        
        for start, end in windows[1:]:
            if start <= current_end + merge_gap_frames:
                # Extend current interval
                current_end = max(current_end, end)
            else:
                # Save current and start new
                merged.append((current_start, current_end))
                current_start, current_end = start, end
        
        merged.append((current_start, current_end))
        
        # Convert to SuspiciousInterval with metadata
        scorer = Scorer()
        frame_lookup = {s.frame_idx: s for s in scores}
        
        intervals = []
        for start_frame, end_frame in merged:
            # Find scores in this interval
            interval_scores = [
                s for s in scores 
                if start_frame <= s.frame_idx <= end_frame
            ]
            
            if not interval_scores:
                continue
            
            # Compute peak score and collect reasons
            peak_score = max(s.score for s in interval_scores)
            
            # Aggregate reasons across suspicious frames
            reason_counts = defaultdict(int)
            for s in interval_scores:
                if s.is_suspicious:
                    for reason in scorer.get_active_reasons(s):
                        reason_counts[reason] += 1
            
            # Sort reasons by frequency
            reasons = sorted(reason_counts.keys(), 
                           key=lambda r: reason_counts[r], 
                           reverse=True)
            
            # Convert frame indices to timestamps
            start_time = start_frame / self.fps
            end_time = end_frame / self.fps
            
            intervals.append(SuspiciousInterval(
                start=start_time,
                end=end_time,
                peak_score=peak_score,
                reasons=reasons,
                frame_count=len(interval_scores)
            ))
        
        return intervals
    
    def reset(self):
        """Reset aggregator state."""
        self.student_scores.clear()
