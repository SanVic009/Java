# Classroom Anti-Cheat System — Complete Rebuild Documentation (Same-to-Same)

This document is a **code-faithful reconstruction guide** for the current repository state.
If your friend follows this document exactly, they can rebuild the project behaviorally the same.

---

## 1) What this project is (current state)

This is an **offline, post-exam video analysis system** with three layers:

1. **Python CV service** (core intelligence):
   - Runs detection, tracking, pose/gaze estimation, phase-wise scoring, interval generation, optional annotated rendering.
   - Exposes HTTP API with async job model.

2. **Java orchestrator** (CLI client):
   - Sends job request to Python API.
   - Polls until completion.
   - Prints terminal report.

3. **React frontend** (UI shell):
   - Upload-style UI for initiating analysis.
   - Displays intervals/annotated video if payload already has results.
   - Note: current frontend does not fully implement async polling loop used by backend job API.

---

## 2) Exact frameworks, libraries, tools, and why each is used

## 2.1 Python CV service stack

From requirements:

- `fastapi==0.109.0`
  - API framework for `/analyze`, `/status/{job_id}`, `/result/{job_id}`, `/health`.
- `uvicorn[standard]==0.27.0`
  - ASGI server to run FastAPI.
- `pydantic==2.5.3`
  - Request/response validation and schema serialization.
- `opencv-python==4.9.0.80`
  - Video read/write, image processing, pose math, rendering.
- `numpy==1.26.3`
  - Numeric operations across CV pipeline.
- `ultralytics==8.1.0`
  - YOLOv8 person detector (`PersonDetector`).
- `mediapipe==0.10.9`
  - Face mesh + iris landmarks for pose/gaze.
- `lap==0.5.13`, `scipy==1.12.0`, `filterpy==1.4.5`
  - Tracking utilities (Hungarian match + tracking support libs).
- `python-multipart==0.0.6`
  - Multipart utility dependency (kept available, though current `/analyze` uses JSON).

Why this stack:
- FastAPI + Pydantic provides strict contracts quickly.
- YOLOv8n gives low-latency person detection.
- ByteTrack-like identity continuity is needed for per-person timeline scoring.
- MediaPipe gives dense face landmarks/iris without custom training.
- OpenCV and NumPy handle full pipeline and rendering operations.

## 2.2 Java orchestrator stack

From Maven:

- Java 17
- Maven build plugins (`compiler`, `jar`, `shade`)
- `gson 2.10.1`

Why:
- Java orchestrator is lightweight and stable for institutional CLI operations.
- `gson` handles JSON request/response conversion.
- `shade` produces self-contained runnable JAR.

## 2.3 Frontend stack

From frontend package:

- React 19
- React Router DOM 7
- Vite 7
- Tailwind CSS 3 + PostCSS + Autoprefixer

Why:
- Quick modern UI scaffolding and utility styling.
- Meant as convenience layer over Python API.

---

## 3) ML / model assets used (and where)

## 3.1 YOLO model

- Runtime detector class uses `YOLO("yolov8n.pt")` by default.
- There are multiple `.pt` files present in workspace (`yolov8n.pt`, `yolov8m.pt`) but current detector default is **yolov8n**.

Used in:
- `python-cv-service/detection/detector.py`

Purpose:
- Detect person bounding boxes per sampled frame.

## 3.2 Face model(s)

Pose estimator attempts face detection in this order:

1. **YuNet ONNX** if file exists:
   - `python-cv-service/models/face_detection_yunet_2023mar.onnx` (or fallback search paths)
2. Haar Cascade fallback (`haarcascade_frontalface_default.xml`) from OpenCV data
3. MediaPipe FaceMesh over face crop
4. Coarse fallback modes if FaceMesh unavailable/failed

Used in:
- `python-cv-service/analysis/pose_estimator.py`

Purpose:
- Robust pose and gaze extraction under real footage issues.

---

## 4) High-level architecture and flow

## 4.1 Runtime sequence (actual)

1. Java CLI (or frontend) sends `POST /analyze`.
2. Python API creates `job_id`, persists request, marks status `queued`.
3. Background thread executes `VideoProcessor.run(job_dir)`.
4. `VideoProcessor` executes:
   - Phase 1 feature extraction -> JSONL + track meta + phase1 stats
   - Phase 2 scoring/aggregation -> results JSON + phase2 stats + frame scores
   - Phase 3 optional annotated video rendering (async additive)
5. Client polls `/status/{job_id}`.
6. Client fetches `/result/{job_id}` once completed.

## 4.2 Why two-phase design

- Phase 1 is **feature persistence** only (no final decisions): replayable and auditable.
- Phase 2 can be rerun from persisted features with changed thresholds/rules without decoding video again.
- Supports observability and resume behavior via job files.

---

## 5) Repository modules and what each does

## 5.1 Python CV service

- `main.py`
  - FastAPI app, async job lifecycle, lock file logic, static mounting for job outputs.
- `config.py`
  - Central thresholds, weights, heuristics, rendering settings.
- `models/schemas.py`
  - API contracts.
- `detection/detector.py`
  - YOLO person detection.
- `detection/tracker.py`
  - ByteTrack-style association, track lifecycle, ID-switch heuristic.
- `analysis/pose_estimator.py`
  - Face-first pose/gaze with confidence and fallback modes.
- `pipeline/feature_extractor.py`
  - Phase 1 writer (`phase1_features.jsonl`, `phase1_track_meta.json`, `phase1_stats.json`).
- `pipeline/phase2_scoring.py`
  - Rolling baselines, confidence-weighted scoring, EMA+hysteresis, suppression rules, intervals.
- `pipeline/video_visualizer.py`
  - Annotated MP4 rendering using persisted artifacts only.
- `pipeline/processor.py`
  - Orchestrates all phases.

## 5.2 Java orchestrator

- `Main.java`
  - CLI parser + workflow controller.
- `service/AnalysisClient.java`
  - Submit/poll/fetch API calls.
- `report/TerminalReporter.java`
  - Human-readable report printing.
- `model/*.java`
  - JSON contract models for response rendering.

## 5.3 Frontend

- `src/pages/UploadPage.jsx`
  - Video selection, exam ID input, POST request.
- `src/lib/analysisUtils.js`
  - Response normalization and helper formatting.
- Router/pages/components for UI only.

---

## 6) API contracts (current authoritative behavior)

## 6.1 Submit

`POST /analyze`

Request:

```json
{
  "exam_id": "exam_001",
  "video_path": "video.mp4",
  "fps_sampling": 5,
  "render_annotated_video": false
}
```

Response (immediate):

```json
{
  "job_id": "<uuid-hex>"
}
```

## 6.2 Poll

`GET /status/{job_id}`

Returns status in: `queued | running | completed | failed` + progress/message.

## 6.3 Result

`GET /result/{job_id}`

Returns:

```json
{
  "job_id": "...",
  "status": "completed",
  "result": {
    "exam_id": "...",
    "results": [
      {
        "track_id": 1,
        "total_duration": 321.4,
        "stability_score": 0.89,
        "intervals": [
          {
            "start": 31.2,
            "end": 41.0,
            "duration": 9.8,
            "peak_score": 0.71,
            "avg_score": 0.63,
            "confidence": 0.57,
            "dominant_signals": ["HeadDeviation", "GazeDeviation"],
            "supporting_stats": {
              "head_deviation_pct": 0.44,
              "gaze_deviation_pct": 0.39,
              "proximity_avg_distance": 90.2,
              "proximity_min_distance": 54.8
            }
          }
        ]
      }
    ],
    "observability": { "...": "..." },
    "annotated_video": {
      "file_path": "job_store/<job_id>/phase2_annotated.mp4",
      "status": "ready"
    }
  },
  "error": null
}
```

---

## 7) Core rules, formulas, and thresholds (actual scoring logic)

All values here are from `config.py` + `phase2_scoring.py` behavior.

## 7.1 Detection and track quality gates

- YOLO confidence (`YOLO_CONFIDENCE`): `0.5`
- Track stability minimum (`TRACK_STABILITY_MIN_SCORE`): `0.45`
- Track minimum lifespan (`MIN_TRACK_LIFESPAN_SEC`): `10s` (duration-scaled for short videos)

Why:
- Remove unstable identities and transient detections before behavior decisions.

## 7.2 Pose quality gates for baseline/scoring

Frame considered quality-usable when all satisfy:
- `visibility_score >= 0.45`
- `pose.confidence >= 0.45`
- `head_pose_confidence >= 0.45`
- `gaze_reliability >= 0.45`

Why:
- Avoid scoring from noisy face estimates.

## 7.3 Rolling baseline (track-centric)

Per track rolling windows:
- baseline window: `30s` (scaled by duration ratio)
- min baseline samples: `5` (scaled by duration ratio)

Baselines computed as medians over accepted frames:
- baseline yaw
- baseline gaze_x
- baseline nearest-neighbor distance (if available)

Why:
- Dynamic adaptation per person, robust to start-time assumptions.

## 7.4 Continuous signal computation

Signals are continuous in $[0,1]$ (not binary in Phase 2):

- Head deviation:
  $$head\_signal = \text{clamp}\left(\frac{|yaw - baseline\_yaw|}{25.0}, 0, 1\right)$$

- Gaze deviation:
  $$gaze\_signal = \text{clamp}\left(\frac{|gaze\_x - baseline\_gaze|}{0.4}, 0, 1\right)$$

- Proximity anomaly (if below threshold):
  $$threshold = baseline\_dist \times 0.7$$
  $$proximity\_signal = \text{clamp}\left(\frac{threshold - current\_dist}{threshold}, 0, 1\right)$$

## 7.5 Raw weighted score

Weights from config:
- head: `0.35`
- gaze: `0.25`
- proximity: `0.55`

Raw signal score:
$$raw = 0.35 \cdot head + 0.25 \cdot gaze + 0.55 \cdot proximity$$

## 7.6 Confidence weighting

Confidence blend:
$$cw\_mean = 0.4\cdot pose\_conf + 0.3\cdot visibility + 0.2\cdot tracking\_stability + 0.1\cdot(1-occlusion)$$

Then floor and clamp:
- `MIN_CONFIDENCE_WEIGHT_FLOOR = 0.35`
- `cw = clamp(max(cw_mean, 0.35), 0, 1)`

Final per-frame score before suppression:
$$final\_pre = raw \cdot cw$$

Why:
- High anomaly with poor confidence is down-weighted, not dropped.

## 7.7 Suppression rules

### A) Whole-class simultaneous event suppression

If at a timestamp:
- number of tracks with `raw_signal_score > 0.25` is `>= 4`

Then all track scores at that timestamp are suppressed to zero.

Why:
- Reduce false positives from global disturbances (camera shake, collective movement).

### B) Teacher proximity suppression

A track can be automatically labeled as teacher if:
- cumulative travel >= `2000 px`
- spatial variance >= `15000`

That teacher track is excluded from normal analysis.

For remaining tracks, if centroid distance to teacher at timestamp < `120 px`, score is suppressed.

Why:
- Invigilator movement near students should not be interpreted as cheating.

## 7.8 Temporal smoothing and interval state machine

EMA:
$$ema_t = \alpha \cdot final_t + (1-\alpha)\cdot ema_{t-1}$$
with base `alpha=0.2` and duration scaling.

Hysteresis thresholds:
- Enter interval if `ema >= enter_threshold` (base 0.6, adjusted by score ceiling)
- Exit interval if `ema <= exit_threshold` (base 0.45, adjusted)

Why:
- Stable interval boundaries, less flicker.

## 7.9 Interval-level filters

Discard interval if any:
- duration too short (`MIN_INTERVAL_DURATION_SEC`, duration-scaled)
- no included frames
- average confidence < `0.45`

Merge intervals when gap <= `5.0s`.

Why:
- Keep output concise and meaningful.

---

## 8) Phase artifacts and job folder contract

Each job is persisted under `job_store/<job_id>/`:

- `request.json` — original request
- `status.json` — lifecycle status
- `job.lock` — run lock
- `phase1_features.jsonl` — per-track sampled features (core audit file)
- `phase1_track_meta.json` — durations/stability/id-switch summaries
- `phase1_stats.json` — phase-1 observability
- `phase2_frame_scores.jsonl` — per-frame final and supporting signals
- `phase2_results.json` — final API result payload
- `phase2_stats.json` — phase-2 observability
- `phase2_annotated.mp4` — optional renderer output

---

## 9) Build and run instructions (same-to-same)

## 9.1 Prerequisites

- Python 3.10+
- Java 17+
- Maven 3.8+
- Linux/macOS shell (or adapt to Windows)

## 9.2 Python CV service

From project root:

1. `cd python-cv-service`
2. Create env and install requirements
3. Ensure `yolov8n.pt` available in runtime lookup path
4. Run `python main.py`
5. Verify `GET http://localhost:8000/health`
# Rebuild Guide (Current Runtime)

## Java Orchestrator

1. `cd java-orchestrator`
2. `mvn clean package`
3. Run:
   - `java -jar target/classroom-anticheat-orchestrator-1.0.0-shaded.jar --exam-id exam_001 --video video.mp4 --fps 5`
4. Optional:
   - add `--render-annotated-video`

## Frontend (optional)

1. `cd frontend`
2. Install Node dependencies
3. Start Vite
4. Open upload page

## Path resolution

Supported resolution includes absolute path, CWD-relative, service-root-relative, project-root-relative, and common `videos/` locations.

## Active modules

- `pipeline/feature_extractor.py`
- `pipeline/phase2_scoring.py`
- `pipeline/video_visualizer.py`
- `pipeline/processor.py`

## Rebuild checklist

- [ ] Recreate `python-cv-service`, `java-orchestrator`, `frontend`
- [ ] Pin Python dependencies from `requirements.txt`
- [ ] Configure Java 17 + Maven
- [ ] Implement async API: `/analyze`, `/status`, `/result`
- [ ] Implement feature extraction, scoring, interval aggregation, and rendering
- [ ] Validate artifact outputs under `job_store`

## Quick reference

- backend API: `python-cv-service/main.py`
- pipeline orchestrator: `python-cv-service/pipeline/processor.py`
- scoring engine: `python-cv-service/pipeline/phase2_scoring.py`
- Java entrypoint: `java-orchestrator/src/main/java/com/anticheat/Main.java`