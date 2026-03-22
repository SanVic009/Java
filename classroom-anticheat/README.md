# Classroom Anti-Cheat Analysis System

Offline classroom anti-cheat analysis system that processes CCTV video after exams and outputs suspicious timestamp intervals.

## Architecture

- Java Orchestrator
  - accepts exam metadata
  - submits async jobs to Python service
  - polls status and prints report
- Python CV Service
  - YOLOv8 person detection
  - ByteTrack tracking
  - MediaPipe pose/gaze estimation
  - uncertainty-aware track-centric scoring

## Quick Start

### 1) Start Python CV Service

```bash
cd python-cv-service
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd .. && ./download_models.sh && cd python-cv-service
python main.py
```

Service runs on http://localhost:8000

### 2) Build and run Java Orchestrator

```bash
cd java-orchestrator
mvn clean package

# Config file mode
java -jar target/classroom-anticheat-orchestrator-1.0.0-shaded.jar ../sample-config/exam_config.json

# CLI mode
java -jar target/classroom-anticheat-orchestrator-1.0.0-shaded.jar \
  --exam-id "exam_2026_01" \
  --video "video.mp4"
```

## Sample Config

```json
{
  "exam_id": "exam_2026_01",
  "video_path": "video.mp4",
  "fps_sampling": 5,
  "render_annotated_video": true
}
```

## API Endpoints

- GET /health
- POST /analyze
- GET /status/{job_id}
- GET /result/{job_id}

## Notes

- The system flags suspicious patterns, not final misconduct verdicts.
- The pipeline is batch/offline.
- Review results with human proctors.
