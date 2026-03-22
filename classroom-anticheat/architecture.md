# Classroom Anti-Cheat System - Architecture

## System Overview

- Java orchestrator invokes Python service.
- Python service runs the full two-phase track-centric pipeline.
- Outputs are persisted per job in `job_store`.

## Runtime Flow

1. Request accepted by API.
2. Phase 1 extracts per-frame/per-track features.
3. Phase 2 computes confidence-weighted scores and intervals.
4. Optional renderer produces annotated video from persisted artifacts.

## Active Core Modules

- `python-cv-service/pipeline/feature_extractor.py`
- `python-cv-service/pipeline/phase2_scoring.py`
- `python-cv-service/pipeline/video_visualizer.py`
- `python-cv-service/pipeline/processor.py`
- `python-cv-service/main.py`

## API Surface

- `GET /health`
- `POST /analyze`
- `GET /status/{job_id}`
- `GET /result/{job_id}`
