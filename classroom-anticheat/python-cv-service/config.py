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

    # Track-centric identity & quality gates
    MIN_TRACK_LIFESPAN_SEC: float = 10.0
    TRACK_STABILITY_MIN_SCORE: float = 0.45  # 0..1
    MIN_FRAME_VISIBILITY_SCORE: float = 0.45  # derived from pose landmark visibility and occlusion
    MIN_POSE_CONFIDENCE: float = 0.45
    MIN_TRACK_CONFIDENCE: float = 0.35

    # Rolling baseline (track-specific, uncertainty-aware)
    BASELINE_ROLLING_WINDOW_SEC: float = 30.0
    MIN_BASELINE_SAMPLES: int = 5  # number of accepted samples per rolling baseline

    # Signal normalization / thresholds for continuous scoring
    HEAD_DEV_NORM_DEG: float = 25.0
    GAZE_DEV_NORM: float = 0.4
    PROXIMITY_DISTANCE_RATIO_THRESHOLD: float = 0.7  # current_dist < baseline_dist * ratio triggers proximity anomaly

    # Temporal aggregation (robust hysteresis + smoothing)
    EMA_ALPHA: float = 0.2
    SUSPICION_ENTER_THRESHOLD: float = 0.6
    SUSPICION_EXIT_THRESHOLD: float = 0.45
    MIN_INTERVAL_DURATION_SEC: float = 3.0
    MIN_INTERVAL_AVG_CONFIDENCE: float = 0.45

    # ID switch observability (heuristic; without ground truth it is an approximation)
    ID_SWITCH_DISTANCE_PX: float = 60.0
    ID_SWITCH_LOOKBACK_SEC: float = 15.0

    # Async job-based API storage
    JOB_STORAGE_DIR: str = "job_store"

    # Phase 3: annotated video rendering (pure visualization; no CV inference)
    RENDER_ANNOTATED_VIDEO_DEFAULT: bool = False
    HIGH_SUSPICION_PEAK_THRESHOLD: float = 0.8

    ANNOT_FONT_SCALE: float = 0.5
    ANNOT_LINE_THICKNESS: int = 2

    # Timeline rendering (bottom overlay)
    TIMELINE_HEIGHT_PX: int = 80
    TIMELINE_ROW_HEIGHT_PX: int = 10

    # Carry-forward rendering: max number of non-sampled frames to reuse stale annotation
    CARRY_FORWARD_MAX_NON_SAMPLED_FRAMES: int = 8

    # Score bar sizing
    SCORE_BAR_WIDTH_PX: int = 120
    SCORE_BAR_HEIGHT_PX: int = 8


config = Config()
