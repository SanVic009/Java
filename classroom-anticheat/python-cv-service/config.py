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
    
    # Signal weights (must sum to 1.0)
    # Rebalanced so head+gaze-only behavior can still exceed suspicion thresholds.
    HEAD_WEIGHT: float = 0.45
    GAZE_WEIGHT: float = 0.28
    PROXIMITY_WEIGHT: float = 0.17
    DRIFT_WEIGHT: float = 0.10

    # Backward-compatible aliases
    WEIGHT_HEAD: float = HEAD_WEIGHT
    WEIGHT_GAZE: float = GAZE_WEIGHT
    WEIGHT_PROXIMITY: float = PROXIMITY_WEIGHT
    
    # Scoring
    SUSPICIOUS_THRESHOLD: float = 0.75
    
    # Temporal aggregation
    WINDOW_SIZE_SEC: int = 30
    SUSPICIOUS_FRAME_RATIO: float = 0.20  # 20%
    
    # Interval merging
    MERGE_GAP_SEC: float = 5.0
    
    # Assignment stabilization
    STABILIZATION_FRAMES: int = 10
    
    # Detection confidence
    YOLO_CONFIDENCE: float = 0.5
    MIN_DETECTION_CONFIDENCE: float = 0.60
    NMS_IOU_THRESHOLD: float = 0.45
    MIN_PERSON_BOX_AREA: float = 1600.0
    MIN_PERSON_ASPECT_RATIO: float = 0.75
    MAX_PERSON_ASPECT_RATIO: float = 4.5

    # Pose estimator pre-gate (do not run face landmarks for tiny faces)
    MIN_FACE_CROP_PX: int = 35
    
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Track-centric identity & quality gates
    MIN_TRACK_LIFESPAN_SEC: float = 10.0
    TRACK_STABILITY_MIN_SCORE: float = 0.30  # 0..1
    MIN_FRAME_VISIBILITY_SCORE: float = 0.45  # derived from pose landmark visibility and occlusion
    MIN_POSE_CONFIDENCE: float = 0.45
    MIN_TRACK_CONFIDENCE: float = 0.35

    # Rolling baseline (track-specific, uncertainty-aware)
    BASELINE_ROLLING_WINDOW_SEC: float = 30.0
    BASELINE_LOCK_SEC: float = 60.0
    BASELINE_LOCK_MIN_SEC: float = 15.0
    BASELINE_MIN_ABSOLUTE_SAMPLES: int = 10
    BASELINE_UPDATE_DURING_SUSPICION: bool = False
    MIN_BASELINE_SAMPLES: int = 5  # number of accepted samples per rolling baseline

    # Signal normalization / thresholds for continuous scoring
    HEAD_DEV_NORM_DEG: float = 25.0
    GAZE_DEV_NORM: float = 0.4
    SIGNAL_FLAG_THRESHOLD: float = 0.6
    GAZE_X_SCALE_FACTOR: float = 2.0
    PROXIMITY_DISTANCE_RATIO_THRESHOLD: float = 0.7  # current_dist < baseline_dist * ratio triggers proximity anomaly
    BODY_POSE_YAW_SCALE_DEG: float = 35.0

    # Temporal aggregation (robust hysteresis + smoothing)
    EMA_ALPHA_BASE: float = 0.2
    # NOTE: With alpha=0.2 and enter_threshold=0.6, the minimum detectable
    # suspicious event duration is approximately ceil(log(1-0.6) / log(1-0.2))
    # frames = ~4-5 frames. At FPS_SAMPLING=5, this is ~1 second.
    # Increase alpha (e.g. 0.35) to detect shorter events at the cost of more flicker.
    # Decrease alpha (e.g. 0.1) for smoother, slower-responding detection.
    EMA_ALPHA_FAST: float = 0.35  # used when fps_sampling >= 10 (higher temporal resolution)

    # Backward-compatible alias
    EMA_ALPHA: float = EMA_ALPHA_BASE
    SUSPICION_ENTER_THRESHOLD: float = 0.45
    SUSPICION_EXIT_THRESHOLD: float = 0.30
    MIN_INTERVAL_DURATION_SEC: float = 3.0
    MIN_INTERVAL_AVG_CONFIDENCE: float = 0.33

    # Phase 2 runtime weighting/threshold adaptation for real classroom footage
    MIN_CONFIDENCE_WEIGHT_FLOOR: float = 0.35
    EFFECTIVE_SCORE_CEILING: float = 0.5
    # NOTE: This value documents the practical maximum observed score in real classroom footage.
    # It is NOT used to scale detection thresholds. Thresholds are defined directly via
    # SUSPICION_ENTER_THRESHOLD and SUSPICION_EXIT_THRESHOLD.

    # Phase 2 teacher/event suppression heuristics
    TEACHER_MIN_CUMULATIVE_TRAVEL_PX: float = 800.0   # must satisfy BOTH conditions
    TEACHER_MIN_SPATIAL_VARIANCE: float = 15000.0      # must satisfy BOTH conditions
    TEACHER_MIN_TRACK_AGE_SEC: float = 30.0            # track must be old enough before classification
    TEACHER_POSITION_TOP_FRACTION: float = 0.20
    TEACHER_POSITION_MIN_TRAVEL_FALLBACK_PX: float = 300.0

    # Backward-compatible aliases
    TEACHER_CUMULATIVE_TRAVEL_THRESHOLD: float = TEACHER_MIN_CUMULATIVE_TRAVEL_PX
    TEACHER_SPATIAL_VARIANCE_THRESHOLD: float = TEACHER_MIN_SPATIAL_VARIANCE

    SIMULTANEOUS_SUPPRESSION_FRACTION: float = 0.60
    SIMULTANEOUS_SUPPRESSION_MIN_TRACKS: int = 3
    SIMULTANEOUS_SUPPRESSION_SCORE_THRESHOLD: float = 0.50

    # Backward-compatible aliases
    SIMULTANEOUS_EVENT_SIGNAL_THRESHOLD: float = SIMULTANEOUS_SUPPRESSION_SCORE_THRESHOLD
    SIMULTANEOUS_EVENT_MIN_TRACKS: int = SIMULTANEOUS_SUPPRESSION_MIN_TRACKS
    TEACHER_PROXIMITY_SUPPRESSION_RADIUS: float = 120.0

    # ID switch observability (heuristic; without ground truth it is an approximation)
    ID_SWITCH_DISTANCE_PX: float = 60.0
    ID_SWITCH_LOOKBACK_SEC: float = 15.0
    TRACKER_TRACK_BUFFER: int = 20
    TRACKER_REID_MAX_DISTANCE_PX: float = 180.0

    # Async job-based API storage
    JOB_STORAGE_DIR: str = "job_store"
    ALLOWED_VIDEO_BASE_DIRS: list[str] = None

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

# Allowed request video paths (relative to project root).
if config.ALLOWED_VIDEO_BASE_DIRS is None:
    config.ALLOWED_VIDEO_BASE_DIRS = [
        "videos/",
        "java-orchestrator/videos/",
    ]
