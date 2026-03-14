"""
Pydantic models for API request/response schemas.
"""
from pydantic import BaseModel
from typing import List, Optional


class SeatMapping(BaseModel):
    seat_id: int
    student_id: int
    bbox: List[int]  # [x1, y1, x2, y2]
    neighbors: List[int]


class AnalysisRequest(BaseModel):
    exam_id: str
    video_path: str
    fps_sampling: int = 5
    baseline_duration_sec: int = 60
    seat_map: Optional[List[SeatMapping]] = None  # Optional - auto-discovery if not provided
    discovery_duration_sec: int = 120  # Auto-discovery period (2 minutes)


class SuspiciousInterval(BaseModel):
    start: float
    end: float
    peak_score: float
    reasons: List[str]


class StudentResult(BaseModel):
    student_id: int
    intervals: List[SuspiciousInterval]


class DiscoveredSeatInfo(BaseModel):
    """Info about an auto-discovered seat."""
    seat_id: int
    student_id: int
    bbox: List[int]
    neighbors: List[int]
    stability_score: float


class AnalysisResponse(BaseModel):
    exam_id: str
    results: List[StudentResult]
    auto_discovered: bool = False  # Whether seats were auto-discovered
    discovered_seats: Optional[List[DiscoveredSeatInfo]] = None  # Discovered seat info


class HealthResponse(BaseModel):
    status: str
    version: str = "1.0.0"
