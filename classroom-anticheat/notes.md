# Classroom Anti-Cheat System - Implementation Notes

## Project Overview
Offline classroom anti-cheat analysis system that processes CCTV video after exams and outputs per-student suspicious timestamp intervals.

---

## Architecture

| Layer | Technology | Responsibility |
|-------|------------|----------------|
| Orchestration | Java | Accept metadata, call Python service, receive results, print terminal report |
| ML/CV Processing | Python (FastAPI) | Video processing, detection, tracking, pose estimation, suspicion scoring |

---

## Detection Stack (V1)
- **YOLOv8n** → Person detection
- **ByteTrack** → Multi-object tracking
- **MediaPipe Face Mesh** → Head pose + gaze estimation

---

## Processing Pipeline

### Phase 1 — Baseline Calibration (First 1 Minute)
| Metric | Computation |
|--------|-------------|
| `baseline_yaw` | median(yaw) during first 60s |
| `baseline_gaze` | median(gaze_x) during first 60s |
| `yaw_std` | std(yaw) during baseline |
| `baseline_neighbor_distance` | median neighbor distance |

### Phase 2 — Signal Detection (Per Frame)
| Signal | Condition | Weight |
|--------|-----------|--------|
| HeadSignal | `|adj_yaw| > max(25°, 2 × yaw_std)` | 0.35 |
| GazeSignal | `|adj_gaze| > 0.4` | 0.25 |
| ProximitySignal | `neighbor_dist < baseline_dist × 0.7` | 0.55 |

**Per-frame score formula:**
```
S(t) = 0.35 × HeadSignal + 0.25 × GazeSignal + 0.55 × ProximitySignal
```

**Suspicious frame:** S(t) ≥ 0.75

---

## Temporal Aggregation
| Parameter | Value |
|-----------|-------|
| Frame rate | 5 FPS |
| Window size | 30 seconds (150 frames) |
| Trigger threshold | ≥ 20% suspicious frames in window |
| Merge gap | < 5 seconds between intervals |

---

## Output Format

### Python → Java (JSON)
```json
[
  {
    "student_id": 12,
    "start": 750.0,
    "end": 765.0,
    "peak_score": 0.92,
    "reasons": [
      "Prolonged head deviation",
      "Repeated proximity"
    ]
  }
]
```

### Java Terminal Output
```
Student 12
  [00:12:30 – 00:12:45] Suspicious pattern (Peak Score: 0.92)
```

---

## Implementation Status

### Java Layer
- [ ] Project setup (Maven)
- [ ] ExamMetadata model
- [ ] SuspiciousInterval model
- [ ] REST client for Python service
- [ ] Terminal report generator
- [ ] Main orchestrator

### Python Layer
- [ ] FastAPI project setup
- [ ] Video frame sampler (5 FPS)
- [ ] YOLOv8n person detection
- [ ] ByteTrack integration
- [ ] MediaPipe Face Mesh integration
- [ ] Baseline calibration module
- [ ] Signal computation module
- [ ] Scoring engine
- [ ] Temporal aggregation
- [ ] Interval merging
- [ ] REST API endpoint

---

## Locked Architectural Decisions

### 1. Seat Mapping — Two Modes

#### A. Auto-Discovery Mode (Default)
No seat map required. The system automatically:
1. Tracks all persons during first 2 minutes (configurable)
2. Identifies stable positions (>50% presence ratio)
3. Generates seat bounding boxes from observed track sizes
4. Auto-assigns track_id as student_id
5. Computes neighbors using Delaunay triangulation or distance threshold

**Usage:**
```bash
java -jar anticheat.jar --exam-id exam_001 --video /path/to/video.mp4
```

#### B. Predefined Seats Mode
```json
{
  "seat_id": 1,
  "student_id": 12,
  "bbox": [x1, y1, x2, y2],
  "neighbors": [2, 5]
}
```
- Bounding boxes in pixel coordinates relative to video resolution
- Handles perspective distortion
- Provides deterministic spatial constraints

**Usage:**
```bash
java -jar anticheat.jar --exam-id exam_001 --video /path/to/video.mp4 --seat-map seats.json
```

### 2. Student ID Assignment
- Compute centroid of tracked person's bounding box
- Find seat whose bbox contains centroid
- Map: track_id → seat_id → student_id
- **Stabilization**: Track must remain inside seat bbox for ≥ 10 consecutive frames before confirming assignment
- If multiple tracks overlap one seat → choose highest IOU
- If track leaves seat for > N seconds → temporarily unassigned

### 3. Neighbor Definition (For ProximitySignal)
- Predefined adjacency list in seat configuration
- Only check against students in neighbor seat list
- Proximity triggers when:
  1. Distance between centroids < baseline_dist × 0.7
  2. AND both have yaw pointing toward each other

### 4. Build Preferences
| Component | Choice | Reason |
|-----------|--------|--------|
| Java | Maven | Standard, stable, clean dependency locking |
| Python | pip + requirements.txt | Simple, no overhead for POC |
| FastAPI Port | 8000 | Default, no complication |

### 5. API Contract

**Request:** `POST /analyze`

Auto-discovery mode (no seat_map):
```json
{
  "exam_id": "exam_2026_01",
  "video_path": "/path/to/video.mp4",
  "fps_sampling": 5,
  "baseline_duration_sec": 60,
  "discovery_duration_sec": 120
}
```

Predefined seats mode:
```json
{
  "exam_id": "exam_2026_01",
  "video_path": "/path/to/video.mp4",
  "fps_sampling": 5,
  "baseline_duration_sec": 60,
  "seat_map": [
    {
      "seat_id": 1,
      "student_id": 12,
      "bbox": [100, 200, 300, 450],
      "neighbors": [2, 5]
    }
  ]
}
```

**Response:**
```json
{
  "exam_id": "exam_2026_01",
  "auto_discovered": true,
  "discovered_seats": [
    {
      "seat_id": 1,
      "student_id": 1,
      "bbox": [105, 195, 295, 445],
      "neighbor_seat_ids": [2, 4],
      "stability_score": 0.95
    }
  ],
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

---

## Implementation Status

### Java Layer
- [x] Project setup (Maven pom.xml)
- [x] Models: ExamRequest, SeatMapping, AnalysisResponse, SuspiciousInterval
- [x] REST client (HttpClient for Python service)
- [x] Terminal report generator (timestamp formatting)
- [x] Main orchestrator

### Python Layer
- [x] FastAPI project setup
- [x] Video frame sampler (5 FPS)
- [x] YOLOv8n person detection
- [x] ByteTrack multi-object tracking
- [x] Seat assignment with stabilization
- [x] MediaPipe Face Mesh (head pose + gaze)
- [x] Baseline calibration module
- [x] Signal computation (Head, Gaze, Proximity)
- [x] Per-frame scoring engine
- [x] Temporal aggregation (30s sliding window, 20% threshold)
- [x] Interval merging (< 5s gap)
- [x] REST API endpoint `/analyze`
- [x] Auto-discovery mode (default, no seat map required)

---

## File Structure
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
│       │   ├── SuspiciousInterval.java
│       │   └── DiscoveredSeat.java
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
│   │   ├── auto_discovery.py
│   │   ├── seat_assigner.py
│   │   ├── pose_estimator.py
│   │   ├── baseline.py
│   │   ├── signals.py
│   │   ├── scorer.py
│   │   └── aggregator.py
│   └── pipeline/
│       └── processor.py
├── examples/
│   ├── auto_discovery_config.json
│   └── predefined_seats_config.json
└── notes.md
```
