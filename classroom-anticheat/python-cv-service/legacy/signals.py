"""
Signal computation module.
Computes binary signals (Head, Gaze, Proximity) from raw features.
"""
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from analysis.baseline import StudentBaseline
from config import config
import math


@dataclass
class SignalResult:
    """Binary signals for a single frame."""
    head_signal: int  # 0 or 1
    gaze_signal: int  # 0 or 1
    proximity_signal: int  # 0 or 1
    
    # Raw adjusted values for debugging
    adj_yaw: float = 0.0
    adj_gaze: float = 0.0
    current_distance: float = 0.0


class SignalComputer:
    """
    Computes binary signals from pose estimates and baseline.
    """
    
    def __init__(self):
        print("[SignalComputer] Initialized with thresholds:")
        print(f"  Head: max({config.HEAD_YAW_MIN_THRESHOLD}°, "
              f"{config.HEAD_YAW_STD_MULTIPLIER} × yaw_std)")
        print(f"  Gaze: |adj_gaze| > {config.GAZE_THRESHOLD}")
        print(f"  Proximity: dist < baseline × {config.PROXIMITY_RATIO}")
    
    def compute(
        self,
        student_id: int,
        baseline: StudentBaseline,
        yaw: float,
        gaze_x: float,
        neighbor_distance: Optional[float] = None,
        neighbor_yaw: Optional[float] = None
    ) -> SignalResult:
        """
        Compute signals for a frame.
        
        Args:
            student_id: Student identifier
            baseline: Student's baseline metrics
            yaw: Current head yaw
            gaze_x: Current gaze direction
            neighbor_distance: Current distance to neighbor
            neighbor_yaw: Neighbor's yaw (for mutual facing check)
            
        Returns:
            SignalResult with binary signals
        """
        # Compute adjusted values
        adj_yaw = yaw - baseline.baseline_yaw
        adj_gaze = gaze_x - baseline.baseline_gaze
        
        # Head signal
        yaw_threshold = max(
            config.HEAD_YAW_MIN_THRESHOLD,
            config.HEAD_YAW_STD_MULTIPLIER * baseline.yaw_std
        )
        head_signal = 1 if abs(adj_yaw) > yaw_threshold else 0
        
        # Gaze signal
        gaze_signal = 1 if abs(adj_gaze) > config.GAZE_THRESHOLD else 0
        
        # Proximity signal
        proximity_signal = 0
        current_distance = neighbor_distance if neighbor_distance else float('inf')
        
        if neighbor_distance is not None:
            distance_threshold = baseline.baseline_neighbor_distance * config.PROXIMITY_RATIO
            
            if neighbor_distance < distance_threshold:
                # Check if both students are facing each other
                # This prevents random proximity triggers
                if neighbor_yaw is not None:
                    # Both looking towards each other (opposite yaw directions)
                    # Simplified: just check if they're both deviating significantly
                    if abs(adj_yaw) > 15 or abs(neighbor_yaw) > 15:
                        proximity_signal = 1
                else:
                    # No neighbor yaw info, just use distance
                    proximity_signal = 1
        
        return SignalResult(
            head_signal=head_signal,
            gaze_signal=gaze_signal,
            proximity_signal=proximity_signal,
            adj_yaw=adj_yaw,
            adj_gaze=adj_gaze,
            current_distance=current_distance
        )


def compute_distance(
    centroid1: Tuple[int, int],
    centroid2: Tuple[int, int]
) -> float:
    """Compute Euclidean distance between two centroids."""
    dx = centroid1[0] - centroid2[0]
    dy = centroid1[1] - centroid2[1]
    return math.sqrt(dx * dx + dy * dy)
