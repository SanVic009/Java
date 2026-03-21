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

import json
from pathlib import Path
from typing import Any, Dict, Optional

from config import config
from models.schemas import AnalysisRequest

from pipeline.feature_extractor import FeatureExtractorPhase1
from pipeline.phase2_scoring import Phase2Scoring
from pipeline.video_visualizer import VideoVisualizer


def validate_video_path(raw_path: str, project_root: Path) -> Path:
    # Block traversal/absolute paths immediately.
    if ".." in raw_path or raw_path.startswith("/"):
        raise ValueError(
            "Invalid video_path: absolute paths and directory traversal are not allowed. "
            "Place video files under the 'videos/' directory and use filenames only."
        )

    for base in config.ALLOWED_VIDEO_BASE_DIRS:
        candidate = (project_root / base / raw_path).resolve()
        allowed_root = (project_root / base).resolve()
        if str(candidate).startswith(str(allowed_root)) and candidate.exists() and candidate.is_file():
            return candidate

    raise FileNotFoundError(
        f"Video file '{raw_path}' not found in any allowed directory: "
        f"{config.ALLOWED_VIDEO_BASE_DIRS}. Ensure the file exists and path has no traversal."
    )


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
        """Resolve request video path to an existing absolute path under allowed roots."""
        service_root = Path(__file__).resolve().parents[1]  # python-cv-service
        project_root = service_root.parent

        return str(validate_video_path(self.request.video_path, project_root))

    @staticmethod
    def _update_job_status_details(status_path: Optional[Path], **fields: Any) -> None:
        if status_path is None:
            return
        payload: Dict[str, Any] = {}
        if status_path.exists():
            payload = json.loads(status_path.read_text(encoding="utf-8"))
        payload.update(fields)
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def run(self, job_dir: Path, status_path: Optional[Path] = None) -> Dict[str, Any]:
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

        phase1_complete = False

        # Phase 1
        try:
            phase1 = FeatureExtractorPhase1()
            phase1.extract(
                exam_id=self.request.exam_id,
                video_path=resolved_video_path,
                fps_sampling=self.fps_sampling,
                out_features_path=features_jsonl_path,
                out_track_meta_path=track_meta_path,
                out_phase1_stats_path=phase1_stats_path,
            )
            phase1_complete = True
        except Exception as exc:
            VideoProcessor._update_job_status_details(
                status_path,
                status="failed",
                failed_phase="phase1",
                error=str(exc),
                phase1_complete=False,
                phase2_complete=False,
                annotated_video_status="not_requested",
            )
            raise

        # Phase 2
        try:
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
                payload = json.loads(results_path.read_text(encoding="utf-8"))
        except Exception as exc:
            VideoProcessor._update_job_status_details(
                status_path,
                status="failed",
                failed_phase="phase2",
                error=str(exc),
                phase1_complete=phase1_complete,
                phase2_complete=False,
                annotated_video_status="not_requested",
            )
            raise

        # Merge observability from phase1+phase2.
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
        VideoProcessor._update_job_status_details(
            status_path,
            phase1_complete=phase1_complete,
            phase2_complete=True,
            failed_phase=None,
            error=None,
            annotated_video_status="rendering" if render_enabled else "not_requested",
        )

        if render_enabled:
            annotated_video_path = job_dir / "phase2_annotated.mp4"
            payload["annotated_video"] = {
                "file_path": str(annotated_video_path),
                "status": "rendering",
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
                    VideoProcessor._update_job_status_details(status_path, annotated_video_status="ready")
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
                    VideoProcessor._update_job_status_details(status_path, annotated_video_status="failed")

            import threading
            threading.Thread(target=_render_bg, daemon=True).start()

        return payload

    @staticmethod
    def _read_results_json(results_path: Path) -> Dict[str, Any]:
        import json
        if not results_path.exists():
            return {}
        return json.loads(results_path.read_text(encoding="utf-8"))
