from pathlib import Path
from datetime import datetime

from models.schemas import AnalysisRequest
from pipeline.processor import VideoProcessor

job_id = f"fix_verify_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
job_dir = Path('/home/sanvict/Documents/Code/Java/job_store') / job_id

req = AnalysisRequest(
    exam_id='runtime_model_check_20260321_fixverify',
    video_path='106705-673786412_small.mp4',
    fps_sampling=5,
    render_annotated_video=False,
)

payload = VideoProcessor(req).run(job_dir=job_dir)
print('JOB_ID', job_id)
print('RESULT_PATH', str(job_dir / 'phase2_results.json'))
print('FRAME_SCORES_PATH', str(job_dir / 'phase2_frame_scores.jsonl'))
print('TRACKS', len(payload.get('results', [])))
