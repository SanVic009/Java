"""
Classroom Anti-Cheat CV Service
FastAPI application for video analysis.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import torch
# Allow loading YOLO models in PyTorch 2.6+ by adding safe globals
try:
    from ultralytics.nn.tasks import DetectionModel
    if hasattr(torch.serialization, 'add_safe_globals'):
        torch.serialization.add_safe_globals([DetectionModel])
except ImportError:
    pass

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from models import (
    AnalysisRequest,
    HealthResponse,
    AnalyzeJobCreateResponse,
    JobStatusResponse,
    JobResultResponse,
    AnalysisResponse,
)
from pipeline import VideoProcessor
from config import config

app = FastAPI(
    title="Classroom Anti-Cheat CV Service",
    description="Computer Vision service for detecting suspicious behavior in classroom videos",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount job storage for static access to annotated videos
JOB_ROOT = Path(config.JOB_STORAGE_DIR)
JOB_ROOT.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=config.JOB_STORAGE_DIR), name="static")


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(status="healthy", version="1.0.0")


def _job_dir(job_id: str) -> Path:
    return JOB_ROOT / job_id


def _status_path(job_id: str) -> Path:
    return _job_dir(job_id) / "status.json"


def _request_path(job_id: str) -> Path:
    return _job_dir(job_id) / "request.json"


def _phase2_results_path(job_id: str) -> Path:
    return _job_dir(job_id) / "phase2_results.json"


def _lock_path(job_id: str) -> Path:
    return _job_dir(job_id) / "job.lock"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _try_acquire_lock(job_id: str) -> bool:
    """
    Best-effort lock to avoid duplicate background runs.
    """
    lock_path = _lock_path(job_id)
    try:
        # O_EXCL gives us atomic creation.
        fd = lock_path.open("x", encoding="utf-8")
        fd.write(str(time.time()))
        fd.close()
        return True
    except FileExistsError:
        return False


def _release_lock(job_id: str) -> None:
    lock_path = _lock_path(job_id)
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


def _update_status(job_id: str, status: str, progress: float = 0.0, message: Optional[str] = None) -> None:
    path = _status_path(job_id)
    payload: Dict[str, Any] = {}
    if path.exists():
        payload = _read_json(path)
    payload.update(
        {
            "job_id": job_id,
            "status": status,
            "progress": float(progress),
            "message": message,
            "updated_at": _now_iso(),
        }
    )
    _write_json(path, payload)


def _run_job(job_id: str, request_dict: Dict[str, Any]) -> None:
    acquired = _try_acquire_lock(job_id)
    if not acquired:
        return

    try:
        _update_status(job_id, status="running", progress=0.05, message="Starting pipeline")
        request = AnalysisRequest.model_validate(request_dict)

        # Resume-friendly progress hints.
        job_dir = _job_dir(job_id)
        features_path = job_dir / "phase1_features.jsonl"
        track_meta_path = job_dir / "phase1_track_meta.json"
        results_path = _phase2_results_path(job_id)

        had_phase1 = features_path.exists() and track_meta_path.exists()
        had_phase2 = results_path.exists()

        processor = VideoProcessor(request)
        payload = processor.run(job_dir)

        # Post-process: ensure result JSON exists where GET /result expects.
        if results_path.exists():
            _update_status(job_id, status="completed", progress=1.0, message="Completed")
        else:
            _update_status(job_id, status="failed", progress=0.0, message="Results missing after run")
    except Exception as e:
        _update_status(job_id, status="failed", progress=0.0, message=str(e))
    finally:
        _release_lock(job_id)


@app.post("/analyze", response_model=AnalyzeJobCreateResponse)
async def analyze_video(request: AnalysisRequest):
    """
    Submit an analysis job.

    This endpoint is non-blocking and returns a `job_id` immediately.
    Results can be fetched with:
    - GET /status/{job_id}
    - GET /result/{job_id}
    """
    JOB_ROOT.mkdir(parents=True, exist_ok=True)

    job_id = uuid.uuid4().hex
    job_dir = _job_dir(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)

    # Persist request for resume/audit.
    _write_json(_request_path(job_id), request.model_dump())

    _update_status(job_id, status="queued", progress=0.0, message="Queued")

    # Start background worker thread.
    thread = threading.Thread(target=_run_job, args=(job_id, request.model_dump()), daemon=True)
    thread.start()

    return AnalyzeJobCreateResponse(job_id=job_id)


@app.get("/status/{job_id}", response_model=JobStatusResponse)
async def get_status(job_id: str):
    path = _status_path(job_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Job not found")
    payload = _read_json(path)
    return JobStatusResponse(
        job_id=job_id,
        status=payload.get("status", "queued"),
        progress=float(payload.get("progress", 0.0)),
        message=payload.get("message"),
    )


@app.get("/result/{job_id}", response_model=JobResultResponse)
async def get_result(job_id: str):
    results_path = _phase2_results_path(job_id)
    status_path = _status_path(job_id)
    if not status_path.exists():
        raise HTTPException(status_code=404, detail="Job not found")

    status_payload = _read_json(status_path)
    status = status_payload.get("status", "queued")

    if results_path.exists():
        result_payload = json.loads(results_path.read_text(encoding="utf-8"))
        # Patch exam_id if VideoProcessor didn't set it.
        if not result_payload.get("exam_id"):
            req_path = _request_path(job_id)
            if req_path.exists():
                req = json.loads(req_path.read_text(encoding="utf-8"))
                result_payload["exam_id"] = req.get("exam_id")

        return JobResultResponse(
            job_id=job_id,
            status="completed",
            result=AnalysisResponse.model_validate(result_payload),
            error=None,
        )

    # If results aren't ready, attempt resume if the job isn't actively running.
    if status in ("failed", "queued"):
        req_path = _request_path(job_id)
        if not req_path.exists():
            raise HTTPException(status_code=500, detail="Request missing; cannot resume")
        request_dict = json.loads(req_path.read_text(encoding="utf-8"))
        thread = threading.Thread(target=_run_job, args=(job_id, request_dict), daemon=True)
        thread.start()
        _update_status(job_id, status="running", progress=float(status_payload.get("progress", 0.0)), message="Resumed")

    return JobResultResponse(job_id=job_id, status=status, result=None, error=None)


@app.get("/")
async def root():
    """Root endpoint with service info."""
    return {
        "service": "Classroom Anti-Cheat CV Service",
        "version": "1.0.0",
        "features": [
            "Track-centric identity (per track_id; no fixed seat mapping)",
            "YOLOv8 person detection",
            "ByteTrack multi-object tracking",
            "MediaPipe head pose and gaze estimation",
            "Uncertainty-aware confidence-weighted suspicious intervals",
            "Async job-based API with persisted intermediate results",
        ],
        "endpoints": {
            "health": "/health",
            "analyze": "/analyze (POST -> job_id)",
            "status": "/status/{job_id}",
            "result": "/result/{job_id}",
        }
    }


if __name__ == "__main__":
    print("\n" + "="*60)
    print("CLASSROOM ANTI-CHEAT CV SERVICE")
    print("="*60)
    print(f"Starting server on {config.HOST}:{config.PORT}")
    print("="*60 + "\n")
    
    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=config.PORT,
        reload=False,
        log_level="info"
    )
