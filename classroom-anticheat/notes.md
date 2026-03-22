# Classroom Anti-Cheat System - Implementation Notes

## Scope

This project runs offline classroom video analysis and outputs suspicious intervals from track-centric signals.

## Current Runtime

- Java orchestrator submits and polls analysis jobs.
- Python service processes frames and writes per-job artifacts.
- Optional annotated video rendering is artifact-driven.

## Core Processing

1. Detect and track persons.
2. Estimate pose/gaze features.
3. Build rolling baselines.
4. Compute weighted frame scores.
5. Smooth with EMA and build intervals.

## Output Artifacts

- `phase1_features.jsonl`
- `phase1_track_meta.json`
- `phase1_stats.json`
- `phase2_frame_scores.jsonl`
- `phase2_results.json`
- `phase2_stats.json`

## Notes

- Results are indicators and require human review.
- The pipeline is optimized for post-exam batch analysis.
