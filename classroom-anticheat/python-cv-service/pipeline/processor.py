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
    Two-phase processor:
    - Phase 1 always runs fresh for each invocation.
    - If phase2 outputs exist, Phase 2 is skipped.
    """

    def __init__(self, request: AnalysisRequest):
        self.request = request
        self.fps_sampling = int(request.fps_sampling)

    def _resolve_video_path(self) -> str:
        """
        Resolve request video path to an existing absolute path.

        Supports:
        - absolute paths
        - paths relative to current working directory
        - paths relative to python-cv-service root
        - paths relative to repository root
        - bare filenames placed in java-orchestrator/videos
        """
        raw = Path(self.request.video_path).expanduser()
        service_root = Path(__file__).resolve().parents[1]  # python-cv-service
        project_root = service_root.parent

        candidates = []
        if raw.is_absolute():
            candidates.append(raw)
        else:
            candidates.extend(
                [
                    raw,
                    Path.cwd() / raw,
                    service_root / raw,
                    project_root / raw,
                    project_root / "java-orchestrator" / "videos" / raw,
                    project_root / "java-orchestrator" / "videos" / raw.name,
                    project_root / "videos" / raw,
                    project_root / "videos" / raw.name,
                ]
            )

        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return str(candidate.resolve())

        checked = "\n".join(f"- {str(p)}" for p in candidates)
        raise FileNotFoundError(
            f"Video not found: {self.request.video_path}. Checked:\n{checked}"
        )

    def run(self, job_dir: Path) -> Dict[str, Any]:
        job_dir.mkdir(parents=True, exist_ok=True)
        resolved_video_path = self._resolve_video_path()

        features_jsonl_path = job_dir / "phase1_features.jsonl"
        track_meta_path = job_dir / "phase1_track_meta.json"
        phase1_stats_path = job_dir / "phase1_stats.json"

        results_path = job_dir / "phase2_results.json"
        phase2_stats_path = job_dir / "phase2_stats.json"
        frame_scores_path = job_dir / "phase2_frame_scores.jsonl"

        print(
            "[Phase1PathCheck] "
            f"job_dir={job_dir} "
            f"features_path={features_jsonl_path} exists={features_jsonl_path.exists()} "
            f"track_meta_path={track_meta_path} exists={track_meta_path.exists()}"
        )

        # Phase 1
        phase1 = FeatureExtractorPhase1()
        phase1.extract(
            exam_id=self.request.exam_id,
            video_path=resolved_video_path,
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
                        source_video_path=resolved_video_path,
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
