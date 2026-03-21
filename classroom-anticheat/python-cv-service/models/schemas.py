"""
Pydantic models for API request/response schemas.

Note: This service is track-centric (per ByteTrack track_id) and uncertainty-aware.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    exam_id: str
    video_path: str

    # Frames are sampled at this effective FPS for analysis and persistence.
    fps_sampling: int = 5

    # Phase 3 rendering (pure visualization; no CV inference). Default off.
    render_annotated_video: bool = False


class AnalyzeJobCreateResponse(BaseModel):
    job_id: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str  # queued | running | completed | failed
    progress: float = 0.0
    message: Optional[str] = None


class SupportingStats(BaseModel):
    head_deviation_pct: float
    gaze_deviation_pct: float
    proximity_avg_distance: Optional[float] = None
    proximity_min_distance: Optional[float] = None


class SuspicionInterval(BaseModel):
    start: float
    end: float

    duration: float
    peak_score: float
    avg_score: float

    # Avg confidence_weight across the interval frames (0..1).
    confidence: float

    # Ranked list by average component contribution.
    dominant_signals: List[str]

    supporting_stats: SupportingStats


class TrackResult(BaseModel):
    track_id: int
    total_duration: float
    stability_score: float
    intervals: List[SuspicionInterval]


class AnalysisResponse(BaseModel):
    exam_id: str
    results: List[TrackResult]

    # Observability / debug info to support audits.
    observability: Dict[str, Any] = {}

    annotated_video: Optional[Dict[str, Any]] = None


class JobResultResponse(BaseModel):
    job_id: str
    status: str
    result: Optional[AnalysisResponse] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    version: str = "1.0.0"
