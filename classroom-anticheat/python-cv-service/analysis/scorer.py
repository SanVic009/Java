"""
Per-frame scoring engine.
Computes suspicion score from binary signals.
"""
from dataclasses import dataclass
from typing import List
from analysis.signals import SignalResult
from config import config


@dataclass 
class FrameScore:
    """Score result for a single frame."""
    timestamp: float  # Seconds
    frame_idx: int
    student_id: int
    score: float
    is_suspicious: bool
    signals: SignalResult
    
    # Which signals contributed
    head_active: bool = False
    gaze_active: bool = False
    proximity_active: bool = False


class Scorer:
    """
    Computes per-frame suspicion scores from signals.
    
    Score formula:
    S(t) = 0.35 × HeadSignal + 0.25 × GazeSignal + 0.55 × ProximitySignal
    
    Suspicious if S(t) >= 0.75
    """
    
    def __init__(self):
        self.weight_head = config.WEIGHT_HEAD
        self.weight_gaze = config.WEIGHT_GAZE
        self.weight_proximity = config.WEIGHT_PROXIMITY
        self.threshold = config.SUSPICIOUS_THRESHOLD
        
        print(f"[Scorer] Weights: Head={self.weight_head}, "
              f"Gaze={self.weight_gaze}, Proximity={self.weight_proximity}")
        print(f"[Scorer] Suspicious threshold: {self.threshold}")
    
    def score_frame(
        self,
        frame_idx: int,
        timestamp: float,
        student_id: int,
        signals: SignalResult
    ) -> FrameScore:
        """
        Compute suspicion score for a frame.
        
        Args:
            frame_idx: Frame index
            timestamp: Time in seconds
            student_id: Student identifier
            signals: Binary signals for this frame
            
        Returns:
            FrameScore with computed score
        """
        score = (
            self.weight_head * signals.head_signal +
            self.weight_gaze * signals.gaze_signal +
            self.weight_proximity * signals.proximity_signal
        )
        
        is_suspicious = score >= self.threshold
        
        return FrameScore(
            timestamp=timestamp,
            frame_idx=frame_idx,
            student_id=student_id,
            score=score,
            is_suspicious=is_suspicious,
            signals=signals,
            head_active=signals.head_signal == 1,
            gaze_active=signals.gaze_signal == 1,
            proximity_active=signals.proximity_signal == 1
        )
    
    def get_active_reasons(self, frame_score: FrameScore) -> List[str]:
        """Get list of active signal reasons for a frame."""
        reasons = []
        if frame_score.head_active:
            reasons.append("HeadDeviation")
        if frame_score.gaze_active:
            reasons.append("GazeDeviation")
        if frame_score.proximity_active:
            reasons.append("ProximityPattern")
        return reasons
