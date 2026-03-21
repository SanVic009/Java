"""
Uncertainty-aware, track-centric two-phase pipeline orchestrator.

Phase 1 (Feature Extraction):
- Persist per-frame/per-track features to disk (JSONL + track_meta.json)
- No decisions, no suspicious interval computation

Phase 2 (Scoring + Aggregation):
- Read persisted features
- Compute confidence-weighted suspicion scores using a rolling baseline per track
- Apply EMA + hysteresis + robust interval merging
- Apply quality gates and return uncertainty-aware intervals
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from config import config
from models.schemas import AnalysisRequest

from pipeline.feature_extractor import FeatureExtractorPhase1
from pipeline.phase2_scoring import Phase2Scoring
from pipeline.video_visualizer import VideoVisualizer


class VideoProcessor:
    """
    Two-phase processor that is resume-friendly:
    - If phase1 outputs exist, Phase 1 is skipped.
    - If phase2 outputs exist, Phase 2 is skipped.
    """

    def __init__(self, request: AnalysisRequest):
        self.request = request
        self.fps_sampling = int(request.fps_sampling)

    def run(self, job_dir: Path) -> Dict[str, Any]:
        job_dir.mkdir(parents=True, exist_ok=True)

        features_jsonl_path = job_dir / "phase1_features.jsonl"
        track_meta_path = job_dir / "phase1_track_meta.json"
        phase1_stats_path = job_dir / "phase1_stats.json"

        results_path = job_dir / "phase2_results.json"
        phase2_stats_path = job_dir / "phase2_stats.json"
        frame_scores_path = job_dir / "phase2_frame_scores.jsonl"

        # Phase 1
        if not (features_jsonl_path.exists() and track_meta_path.exists()):
            phase1 = FeatureExtractorPhase1()
            phase1.extract(
                exam_id=self.request.exam_id,
                video_path=self.request.video_path,
                fps_sampling=self.fps_sampling,
                out_features_path=features_jsonl_path,
                out_track_meta_path=track_meta_path,
                out_phase1_stats_path=phase1_stats_path,
            )

        # Phase 2
        if not results_path.exists():
            phase2 = Phase2Scoring()
            payload = phase2.run(
                out_results_path=results_path,
                out_phase2_stats_path=phase2_stats_path,
                features_jsonl_path=features_jsonl_path,
                track_meta_path=track_meta_path,
                exam_id=self.request.exam_id,
                out_frame_scores_path=frame_scores_path,
            )
        else:
            import json

            payload = json.loads(results_path.read_text(encoding="utf-8"))

        # Merge observability from phase1+phase2.
        import json

        observability: Dict[str, Any] = {}
        if phase1_stats_path.exists():
            observability["phase1"] = json.loads(phase1_stats_path.read_text(encoding="utf-8"))
        if phase2_stats_path.exists():
            observability["phase2"] = json.loads(phase2_stats_path.read_text(encoding="utf-8"))

        if "observability" in payload and payload["observability"]:
            payload["observability"] = {**payload["observability"], **observability}
        else:
            payload["observability"] = observability

        # Phase 3: optional annotated video rendering (background).
        # Must be additive and must not re-run any CV models.
        render_enabled = bool(getattr(self.request, "render_annotated_video", False)) or bool(
            getattr(config, "RENDER_ANNOTATED_VIDEO_DEFAULT", False)
        )
        if render_enabled:
            annotated_video_path = job_dir / "phase2_annotated.mp4"
            payload["annotated_video"] = {
                "file_path": str(annotated_video_path),
                "status": "processing",
                "resolution": None,
                "frame_rate": None,
                "duration_sec": None,
            }

            # Persist initial placeholder so clients polling /result can see progress.
            import json
            results_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

            def _render_bg():
                try:
                    visualizer = VideoVisualizer()
                    final_info = visualizer.render(
                        job_id=str(job_dir.name),
                        source_video_path=self.request.video_path,
                        phase2_results=payload,
                        phase1_features_path=features_jsonl_path,
                        out_video_path=annotated_video_path,
                        cfg=config,
                    )
                    payload_final = VideoProcessor._read_results_json(results_path)
                    payload_final["annotated_video"] = final_info
                    results_path.write_text(json.dumps(payload_final, indent=2), encoding="utf-8")
                except Exception as e:
                    payload_err = VideoProcessor._read_results_json(results_path)
                    payload_err["annotated_video"] = {
                        "file_path": str(annotated_video_path),
                        "status": "failed",
                        "error": str(e),
                        "resolution": None,
                        "frame_rate": None,
                        "duration_sec": None,
                    }
                    results_path.write_text(json.dumps(payload_err, indent=2), encoding="utf-8")

            import threading
            threading.Thread(target=_render_bg, daemon=True).start()

        return payload

    @staticmethod
    def _read_results_json(results_path: Path) -> Dict[str, Any]:
        import json
        if not results_path.exists():
            return {}
        return json.loads(results_path.read_text(encoding="utf-8"))
