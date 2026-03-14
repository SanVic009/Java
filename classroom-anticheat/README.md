# Classroom Anti-Cheat Analysis System

Offline classroom anti-cheat analysis system that processes CCTV video after exams and outputs per-student suspicious timestamp intervals.

## Architecture

```
┌─────────────────────┐         ┌─────────────────────────────────┐
│   Java Orchestrator │  REST   │      Python CV Service          │
│                     │ ──────► │                                 │
│  • Accept metadata  │         │  • YOLOv8n detection           │
│  • Call Python API  │         │  • ByteTrack tracking          │
│  • Print report     │ ◄────── │  • MediaPipe pose/gaze         │
│                     │  JSON   │  • Baseline calibration        │
└─────────────────────┘         │  • Signal computation          │
                                │  • Suspicion scoring           │
                                │  • Temporal aggregation        │
                                └─────────────────────────────────┘
```

## Quick Start

### 1. Start Python CV Service

```bash
cd python-cv-service

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Start service
python main.py
```

Service runs on `http://localhost:8000`

### 2. Build and Run Java Orchestrator

```bash
cd java-orchestrator

# Build with Maven
mvn clean package

# Run with config file
java -jar target/classroom-anticheat-orchestrator-1.0.0-shaded.jar ../sample-config/exam_config.json

# Or run with command-line arguments
java -jar target/classroom-anticheat-orchestrator-1.0.0-shaded.jar \
  --exam-id "exam_2026_01" \
  --video "/path/to/video.mp4" \
  --seat-map "../sample-config/seat_map.json"
```

## Configuration

### Seat Mapping Format

Each seat requires:
- `seat_id`: Unique seat identifier
- `student_id`: Student assigned to this seat
- `bbox`: Bounding box in pixel coordinates `[x1, y1, x2, y2]`
- `neighbors`: List of adjacent seat IDs

```json
{
  "seat_id": 1,
  "student_id": 101,
  "bbox": [50, 100, 200, 350],
  "neighbors": [2, 4]
}
```

### Full Exam Configuration

```json
{
  "exam_id": "exam_2026_01",
  "video_path": "/path/to/video.mp4",
  "fps_sampling": 5,
  "baseline_duration_sec": 60,
  "seat_map": [...]
}
```

## Detection Pipeline

### Phase 1: Baseline Calibration (First 60 seconds)

For each student, computes:
- `baseline_yaw`: median head yaw
- `baseline_gaze`: median gaze direction
- `yaw_std`: standard deviation of yaw
- `baseline_neighbor_distance`: median distance to neighbors

### Phase 2: Signal Detection

| Signal | Condition | Weight |
|--------|-----------|--------|
| HeadSignal | `\|adj_yaw\| > max(25°, 2 × yaw_std)` | 0.35 |
| GazeSignal | `\|adj_gaze\| > 0.4` | 0.25 |
| ProximitySignal | `neighbor_dist < baseline × 0.7` | 0.55 |

### Scoring

Per-frame score:
```
S(t) = 0.35 × HeadSignal + 0.25 × GazeSignal + 0.55 × ProximitySignal
```

Frame is suspicious if `S(t) >= 0.75`

### Temporal Aggregation

- **Window**: 30 seconds (150 frames at 5 FPS)
- **Threshold**: Window is suspicious if ≥ 20% frames are suspicious
- **Merging**: Intervals within 5 seconds are merged

## Output

### Terminal Report

```
============================================================
        CLASSROOM ANTI-CHEAT ANALYSIS REPORT
============================================================
Exam ID: exam_2026_01
------------------------------------------------------------

Student 12
  [00:12:30 – 00:12:45] Suspicious pattern (Peak Score: 0.92)
    Reasons: HeadDeviation, ProximityPattern

Student 15
  [00:08:15 – 00:08:35] Suspicious pattern (Peak Score: 0.85)
    Reasons: HeadDeviation

------------------------------------------------------------
SUMMARY
------------------------------------------------------------
Total students analyzed: 24
Students flagged: 2
Total suspicious intervals: 2
============================================================
```

### API Response (JSON)

```json
{
  "exam_id": "exam_2026_01",
  "results": [
    {
      "student_id": 12,
      "intervals": [
        {
          "start": 750.0,
          "end": 765.0,
          "peak_score": 0.92,
          "reasons": ["HeadDeviation", "ProximityPattern"]
        }
      ]
    }
  ]
}
```

## Project Structure

```
classroom-anticheat/
├── java-orchestrator/
│   ├── pom.xml
│   └── src/main/java/com/anticheat/
│       ├── Main.java
│       ├── model/
│       │   ├── ExamRequest.java
│       │   ├── SeatMapping.java
│       │   ├── AnalysisResponse.java
│       │   ├── StudentResult.java
│       │   └── SuspiciousInterval.java
│       ├── service/
│       │   └── AnalysisClient.java
│       └── report/
│           └── TerminalReporter.java
├── python-cv-service/
│   ├── requirements.txt
│   ├── main.py
│   ├── config.py
│   ├── models/
│   │   └── schemas.py
│   ├── detection/
│   │   ├── detector.py
│   │   └── tracker.py
│   ├── analysis/
│   │   ├── seat_assigner.py
│   │   ├── pose_estimator.py
│   │   ├── baseline.py
│   │   ├── signals.py
│   │   ├── scorer.py
│   │   └── aggregator.py
│   └── pipeline/
│       └── processor.py
├── sample-config/
│   ├── seat_map.json
│   └── exam_config.json
├── notes.md
└── README.md
```

## Requirements

### Java
- Java 17+
- Maven 3.8+

### Python
- Python 3.10+
- CUDA (optional, for GPU acceleration)

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/analyze` | POST | Analyze video |

## Notes

- System flags **suspicious patterns**, not confirmed cheating
- Baseline calibration assumes first 60 seconds are normal behavior
- Processing is offline (batch), not real-time
- Results should be reviewed by human proctors
