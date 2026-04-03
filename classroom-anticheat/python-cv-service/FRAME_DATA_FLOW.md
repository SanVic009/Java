# Per-Frame Data Flow in Python CV Service

This document explains exactly what happens to each sampled frame, which model handles it, why that step exists, and what data is emitted for downstream phases.

## 0) Big picture (one sampled frame)

For each sampled frame, the pipeline does this in order:

1. Read frame from video.
2. Estimate camera/global motion between previous sampled frame and current sampled frame.
3. Run YOLOv8 person detection.
4. Run ByteTrack update (with Kalman prediction + global motion compensation).
5. Run YOLOv8-pose once on the full frame (cache result for all tracks).
6. For each active track in this frame:
   - compute quality signals (occlusion, blur)
   - run pose/gaze estimation chain
   - compute nearest-neighbor proximity
   - write one Phase 1 JSON record
7. Repeat for next sampled frame.

Why this order: identity must be stabilized (`track_id`) before pose/proximity features are meaningful over time.

---

## 1) Frame sampling and timing

- The video is not processed at full native FPS.
- `frame_skip = max(1, int(original_fps / fps_sampling))`
- A frame is processed only when `frame_idx % frame_skip == 0`.

Why: this reduces compute cost while preserving enough temporal signal for interval-level behavior detection.

Output fields established here:
- `timestamp`
- `frame_sample_idx`

---

## 2) Global Motion Compensation (GMC)

### Model/algorithm
- Sparse Lucas-Kanade optical flow on grayscale keypoints.

### Why it runs
If camera pans slightly, all people shift together. Without compensation, tracker matching (IoU/centroid) would break and create fake ID switches.

### What it outputs
- Frame-level translation `(gmc_dx, gmc_dy)`.
- This shift is applied to predicted track boxes before association.

---

## 3) Person detection (YOLOv8)

### Model
- YOLOv8 detector (`yolov8n.pt` by default in this module).

### Why it runs
It provides candidate person boxes for tracking and all later per-person analysis.

### Inputs
- Full BGR frame.

### Core thresholds
- Detection confidence threshold: `YOLO_CONFIDENCE` (default 0.5)
- NMS IoU threshold: `NMS_IOU_THRESHOLD` (default 0.45)
- Class filter: person class only (COCO class 0)
- Post-filters:
  - minimum area
  - min/max aspect ratio

### Outputs
Per detection:
- `bbox` (`x1,y1,x2,y2`)
- `confidence`
- `centroid`

---

## 4) Tracking (ByteTrack + Kalman)

### Model/algorithm
- ByteTrack-style association with Hungarian matching.
- Constant-velocity Kalman filter per track.

### Why it runs
Downstream scoring is track-centric. We need persistent identity over time (`track_id`) to build rolling baselines and intervals.

### Inputs
- Current frame detections.
- Existing active/lost tracks.
- Global motion offset `(gmc_dx, gmc_dy)`.

### Association logic
1. Predict each track state (`Kalman.predict`).
2. Shift predicted boxes by GMC.
3. Match active tracks with high-confidence detections.
4. Match remaining with low-confidence detections.
5. Optional re-ID from recently lost tracks by centroid distance/time window.
6. Mark misses and age tracks.

### Important thresholds
- `track_thresh` (high vs low detection split, default 0.5)
- `match_thresh` (IoU match threshold, default 0.35)
- `track_buffer` (how long to retain unmatched tracks)

### Track object after update
Each `track` now has:
- persistent `track_id`
- current `bbox`, `centroid`
- lifecycle (`age`, `hits`, `time_since_update`)
- detection confidence history
- `id_switch_count`
- stability proxy (`stability_score()`)

---

## 5) YOLOv8-pose (frame cache)

### Model
- YOLOv8 pose model (`yolov8m-pose.pt`).

### Why it runs
It provides a body-landmark fallback when face-based pose methods fail (e.g., head down, face not visible).

### Key point
It is run **once per sampled frame** and cached, then reused for all tracks in that frame. This avoids repeated full-frame pose inference per track.

Output:
- Cached pose result object used by the per-track pose estimator chain.

---

## 6) Per-track pose/gaze estimation chain

For each visible track, the system calls `PoseEstimator.estimate(frame, track_bbox, detection_confidence, pose_result_cache)`.

### Chain order and reason
1. **YuNet face detection**
2. **MediaPipe Face Mesh** (if face found and large enough)
3. **Haar frontal fallback**
4. **Haar profile fallback**
5. **YOLOv8-pose body landmarks fallback**
6. **BBox proxy fallback** (always available last)

Reason: preserve the best available signal first, but never return empty pose data if weaker proxies can still provide low-confidence directional evidence.

### Per-track pose output fields
- orientation: `yaw`, `pitch`, `roll`
- gaze: `gaze_x`, `gaze_y`
- uncertainty/quality: `landmark_visibility`, `head_pose_confidence`, `gaze_reliability`, `confidence`
- metadata: `face_visible`, `estimation_mode`, `face_detect_confidence`, keypoints

---

## 7) Additional per-track quality signals in the same frame

These are computed after tracking/pose for each track record:

1. **Occlusion score**
   - Max IoU against other visible track boxes in the same frame.
   - Why: high overlap means visibility ambiguity.

2. **Blur quality**
   - Laplacian variance on the track crop, normalized to `[0,1]`.
   - Why: blur lowers trust in fine pose/gaze cues.

3. **Tracking confidence/stability**
   - Mean detection confidence over track history.
   - `stability_score` from track continuity/fragmentation.

4. **Visibility score**
   - Derived from pose landmark visibility when available.

---

## 8) Proximity computation per track

### How
For each visible track, compute Euclidean centroid distance to all other visible tracks and keep the nearest one.

### Why
Proximity is a separate behavioral cue not captured by head/gaze alone.

### Output fields
- `nearest_neighbor_track_id`
- `nearest_neighbor_distance`
- `proximity_confidence` (currently tied to visibility proxy)

---

## 9) What exactly gets persisted per sampled frame

One JSON record per (`timestamp`, `track_id`) containing:

- identity/timing: `exam_id`, `timestamp`, `frame_sample_idx`, `track_id`
- geometry: `bbox`
- detection: confidence
- pose block (or `null` if unavailable)
- quality block (`blur_quality`, `occlusion_score`, `visibility_score`)
- tracking block (`tracking_confidence`, `tracking_stability_score`, `id_switch_count`)
- proximity block (`nearest_neighbor_track_id`, `nearest_neighbor_distance`, `proximity_confidence`)

This file is the Phase 1 feature stream consumed by Phase 2.

---

## 10) Why downstream depends on this exact data

Phase 2 does no heavy vision inference. It trusts and reuses Phase 1 outputs to:
- build per-track rolling baselines (yaw/gaze/proximity)
- compute confidence-weighted frame suspicion scores
- apply quality gates/suppressions
- aggregate intervals

So, if Phase 1 identity continuity or pose quality is wrong, Phase 2 interval decisions shift accordingly.

---

## 11) Quick mental model

Think of Phase 1 as converting raw video into a time-indexed table of person-centric evidence. Detection/tracking answer "who is who"; pose chain answers "where are they oriented/looking" with confidence; quality/proximity answer "how trustworthy and contextually risky is this frame". That table is the sole factual substrate for all scoring decisions later.
