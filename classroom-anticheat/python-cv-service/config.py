"""
Configuration settings for the CV service.
"""
from dataclasses import dataclass


@dataclass
class Config:
    # Frame sampling
    FPS_SAMPLING: int = 5
    
    # Baseline calibration
    BASELINE_DURATION_SEC: int = 60
    
    # Signal thresholds
    HEAD_YAW_MIN_THRESHOLD: float = 25.0  # degrees
    HEAD_YAW_STD_MULTIPLIER: float = 2.0
    GAZE_THRESHOLD: float = 0.4
    PROXIMITY_RATIO: float = 0.7
    
    # Signal weights
    WEIGHT_HEAD: float = 0.35
    WEIGHT_GAZE: float = 0.25
    WEIGHT_PROXIMITY: float = 0.55
    
    # Scoring
    SUSPICIOUS_THRESHOLD: float = 0.75
    
    # Temporal aggregation
    WINDOW_SIZE_SEC: int = 30
    SUSPICIOUS_FRAME_RATIO: float = 0.20  # 20%
    
    # Interval merging
    MERGE_GAP_SEC: float = 5.0
    
    # Seat assignment stabilization
    STABILIZATION_FRAMES: int = 10
    
    # Detection confidence
    YOLO_CONFIDENCE: float = 0.5
    
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000


config = Config()
