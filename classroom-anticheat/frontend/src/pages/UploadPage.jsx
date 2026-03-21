import { useEffect, useMemo, useRef, useState } from 'react';
import PageContainer from '../components/PageContainer';
import TopBar from '../components/TopBar';
import GlassCard from '../components/GlassCard';
import {
  API_BASE_URL,
  EMPTY_RESULT,
  formatPercent,
  formatSeconds,
  normalizeSignal,
  normalizeResult,
  parseBackendPayload,
  resolveVideoPath,
  signalPillTone,
} from '../lib/analysisUtils';

export default function UploadPage() {
  const [dragOver, setDragOver] = useState(false);
  const [file, setFile] = useState(null);
  const [examId, setExamId] = useState('');
  const [renderAnnotatedVideo, setRenderAnnotatedVideo] = useState(true);
  const [status, setStatus] = useState('idle'); // idle | processing | results | error
  const [error, setError] = useState('');
  const [result, setResult] = useState(EMPTY_RESULT);
  const [jobId, setJobId] = useState('');
  const [jobStatusMessage, setJobStatusMessage] = useState('Queued...');
  const [jobProgress, setJobProgress] = useState(0);

  const pollingTimeoutRef = useRef(null);
  const pollingTickRef = useRef(null);

  const flaggedTracks = useMemo(
    () => result.results.filter((track) => track.intervals.length > 0),
    [result.results],
  );

  const resetStatus = () => {
    setStatus('idle');
    setError('');
    setResult(EMPTY_RESULT);
    setJobId('');
    setJobStatusMessage('Queued...');
    setJobProgress(0);
  };

  const setSelectedFile = (selected) => {
    if (!selected) return;
    setFile(selected);
    resetStatus();
  };

  const handleDrop = (event) => {
    event.preventDefault();
    setDragOver(false);
    setSelectedFile(event.dataTransfer.files?.[0]);
  };

  const runAnalysis = async () => {
    if (!file) return;

    if (!examId.trim()) {
      setStatus('error');
      setError('Please provide an Exam ID before running analysis.');
      return;
    }

    setStatus('processing');
    setError('');

    try {
      const response = await fetch(`${API_BASE_URL}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          exam_id: examId.trim(),
          video_path: file.name,
          render_annotated_video: renderAnnotatedVideo,
        }),
      });

      const payload = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(
          payload?.message ||
            payload?.detail ||
            'Something went wrong. Check that the analysis server is running.',
        );
      }

      const submittedJobId = payload?.job_id;
      if (!submittedJobId) {
        throw new Error('Job submission succeeded but no job_id was returned.');
      }

      setJobId(submittedJobId);
      setJobStatusMessage('Queued...');
      setJobProgress(0);
      setStatus('processing');
    } catch (e) {
      setStatus('error');
      setError(
        e instanceof Error
          ? e.message
          : 'Something went wrong. Check that the analysis server is running.',
      );
    }
  };

  useEffect(() => {
    if (status !== 'processing' || !jobId) return undefined;

    let cancelled = false;

    const pollStatus = async () => {
      if (cancelled) return;
      try {
        const response = await fetch(`${API_BASE_URL}/status/${jobId}`);
        const payload = await response.json().catch(() => ({}));

        if (!response.ok) {
          throw new Error(payload?.detail || payload?.message || 'Failed to fetch job status.');
        }

        const nextStatus = String(payload?.status || 'queued').toLowerCase();
        const nextMessage = payload?.message || 'Processing...';
        const nextProgress = Number(payload?.progress || 0);

        if (!cancelled) {
          setJobStatusMessage(nextMessage);
          setJobProgress(Number.isFinite(nextProgress) ? nextProgress : 0);
        }

        if (nextStatus === 'failed') {
          let failureMessage = nextMessage || 'Analysis failed.';
          try {
            const failedResultResp = await fetch(`${API_BASE_URL}/result/${jobId}`);
            const failedPayload = await failedResultResp.json().catch(() => ({}));
            const apiMessage = failedPayload?.error?.message;
            const phase1Available = failedPayload?.error?.phase1_artifacts_available;
            if (apiMessage) {
              failureMessage = phase1Available
                ? `${apiMessage} Phase 1 artifacts are available in job_store/${jobId}/.`
                : apiMessage;
            }
          } catch {
            // fallback to status message
          }
          if (!cancelled) {
            setStatus('error');
            setError(failureMessage);
          }
          return;
        }

        if (nextStatus === 'completed') {
          const resultResponse = await fetch(`${API_BASE_URL}/result/${jobId}`);
          const resultPayload = await resultResponse.json().catch(() => ({}));
          if (!resultResponse.ok) {
            throw new Error(resultPayload?.detail || resultPayload?.message || 'Failed to fetch analysis result.');
          }

          if (resultPayload?.status === 'failed') {
            const message =
              resultPayload?.error?.message ||
              'Analysis failed while preparing the final result payload.';
            if (!cancelled) {
              setStatus('error');
              setError(message);
            }
            return;
          }

          const parsed = parseBackendPayload(resultPayload);
          const normalizedTracks = normalizeResult(resultPayload);
          if (!cancelled) {
            setResult({ ...parsed, results: normalizedTracks });
            setStatus('results');
          }
          return;
        }

        pollingTickRef.current = setTimeout(pollStatus, 3000);
      } catch (e) {
        if (!cancelled) {
          setStatus('error');
          setError(e instanceof Error ? e.message : 'Failed while polling job status.');
        }
      }
    };

    pollStatus();

    pollingTimeoutRef.current = setTimeout(() => {
      if (!cancelled) {
        setStatus('error');
        setError('Timed out after 10 minutes waiting for analysis completion.');
      }
    }, 600000);

    return () => {
      cancelled = true;
      if (pollingTickRef.current) clearTimeout(pollingTickRef.current);
      if (pollingTimeoutRef.current) clearTimeout(pollingTimeoutRef.current);
    };
  }, [jobId, status]);

  useEffect(() => {
    if (status !== 'results' || !jobId || result.annotated_video_status !== 'rendering') {
      return undefined;
    }

    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/result/${jobId}`);
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || cancelled) return;
        const parsed = parseBackendPayload(payload);
        const normalizedTracks = normalizeResult(payload);
        if (!cancelled) setResult({ ...parsed, results: normalizedTracks });
      } catch {
        // best-effort refresh only
      }
    }, 5000);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [jobId, result.annotated_video_status, status]);

  return (
    <PageContainer>
      <TopBar
        backToHome
        right={<div className="text-sm font-medium text-slate-500">Upload & Analysis</div>}
      />

      <section className="mx-auto max-w-5xl px-6 pb-14 pt-10">
        <GlassCard className="p-7 md:p-10">
          <h2 className="text-2xl font-semibold text-slate-900">Upload Exam Footage</h2>
          <p className="mt-2 text-[16px] leading-relaxed text-slate-600">
            Supported format: MP4. Processing happens locally via your analysis server.
          </p>

          {status === 'processing' ? (
            <div className="mt-10 rounded-2xl border border-indigo-100 bg-gradient-to-b from-indigo-50 to-white py-16 text-center">
              <div className="mx-auto h-16 w-16 rounded-full border-4 border-indigo-200 border-t-[#6366f1] animate-spin shadow-[0_0_0_10px_rgba(99,102,241,0.08)]" />
              <p className="mt-6 text-xl font-medium text-slate-900">Analyzing footage…</p>
              <p className="mt-2 text-[16px] leading-relaxed text-slate-600">
                This may take several minutes depending on video length.
              </p>
              <p className="mt-2 text-sm text-slate-600">Job ID: {jobId}</p>
              <p className="mt-2 text-sm text-slate-600">{jobStatusMessage}</p>
              <p className="mt-1 text-sm text-slate-500">Progress: {Math.round((jobProgress || 0) * 100)}%</p>
              <button
                type="button"
                onClick={resetStatus}
                className="mt-8 text-slate-500 underline underline-offset-4 hover:text-slate-700"
              >
                Cancel
              </button>
            </div>
          ) : status === 'results' ? (
            <div className="mt-10">
              {flaggedTracks.length === 0 ? (
                <div className="rounded-xl border border-emerald-200 bg-gradient-to-b from-emerald-50 to-white p-8 text-center">
                  <div className="text-3xl">✓</div>
                  <p className="mt-3 text-lg font-medium text-emerald-700">No suspicious patterns detected</p>
                </div>
              ) : (
                <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                  <div className="rounded-xl border border-indigo-100 bg-gradient-to-b from-indigo-50/70 to-white p-3">
                    {result.annotated_video_status === 'rendering' ? (
                      <div className="rounded-lg p-8 text-center text-slate-600">
                        Annotated video still rendering...
                      </div>
                    ) : result.annotated_video_path ? (
                      <video
                        controls
                        className="w-full rounded-lg"
                        src={resolveVideoPath(result.annotated_video_path)}
                      />
                    ) : (
                      <div className="rounded-lg p-8 text-center text-slate-600">
                        Annotated video path not returned by server.
                      </div>
                    )}
                  </div>

                  <div className="max-h-[520px] overflow-y-auto rounded-xl border border-indigo-100 bg-gradient-to-b from-indigo-50/55 to-white p-4">
                    <div className="space-y-4">
                      {flaggedTracks.map((track) => (
                        <article key={track.track_id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                          <h3 className="text-lg font-bold text-slate-900">Track {track.track_id}</h3>

                          <div className="mt-3 space-y-3">
                            {track.intervals.map((interval, index) => (
                              <div
                                key={`${track.track_id}-${index}`}
                                className="rounded-lg border border-slate-200 bg-slate-50 p-3"
                              >
                                <p className="text-sm text-slate-700">
                                  {formatSeconds(interval.start)} – {formatSeconds(interval.end)}
                                </p>
                                <p className="mt-1 text-sm text-slate-600">
                                  Peak score: {formatPercent(interval.peak_score)}
                                </p>
                                <p className="text-sm text-slate-600">
                                  Confidence: {formatPercent(interval.confidence)}
                                </p>

                                <div className="mt-2 flex flex-wrap gap-2">
                                  {interval.dominant_signals.map((signalRaw, i) => {
                                    const signal = normalizeSignal(signalRaw);
                                    return (
                                      <span
                                        key={`${signalRaw}-${i}`}
                                        className={`rounded-full border px-2.5 py-1 text-xs ${signalPillTone(signal)}`}
                                      >
                                        {signal}
                                      </span>
                                    );
                                  })}
                                </div>
                              </div>
                            ))}
                          </div>
                        </article>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              <p className="mt-6 text-sm leading-relaxed text-slate-500">
                Results are flagged for human review only. This system does not confirm cheating.
              </p>
              {result?.error?.message && (
                <p className="mt-2 text-sm leading-relaxed text-red-600">{result.error.message}</p>
              )}
            </div>
          ) : (
            <>
              <label
                className="mt-8 block cursor-pointer rounded-xl border-2 border-dashed p-12 text-center transition-colors"
                style={{
                  borderColor: dragOver ? '#6366f1' : 'rgba(99,102,241,0.5)',
                  backgroundColor: dragOver ? 'rgba(99,102,241,0.1)' : 'rgba(99,102,241,0.04)',
                }}
                onDrop={handleDrop}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragOver(true);
                }}
                onDragLeave={() => setDragOver(false)}
              >
                <input
                  type="file"
                  accept="video/mp4"
                  className="hidden"
                  onChange={(e) => setSelectedFile(e.target.files?.[0])}
                />
                <p className="text-[18px] text-slate-800">Drag and drop your video file here</p>
                <p className="mt-2 text-[16px] text-slate-600">or click to browse</p>
                {file && <p className="mt-4 text-sm text-indigo-600">Selected: {file.name}</p>}
              </label>

              <div className="mt-8">
                <label className="mb-2 block text-sm text-slate-700">Exam ID</label>
                <input
                  type="text"
                  value={examId}
                  onChange={(e) => setExamId(e.target.value)}
                  placeholder="e.g. exam_room_a_2026"
                  className="w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-base text-slate-900 outline-none transition focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
                />
              </div>

              <div className="mt-7 flex items-start gap-4">
                <button
                  type="button"
                  role="switch"
                  aria-checked={renderAnnotatedVideo}
                  onClick={() => setRenderAnnotatedVideo((prev) => !prev)}
                  className={`relative h-7 w-14 rounded-full transition-colors ${renderAnnotatedVideo ? 'bg-gradient-to-r from-[#6366f1] to-[#7c5cff]' : 'bg-slate-300'}`}
                >
                  <span
                    className={`absolute top-1 h-5 w-5 rounded-full bg-white shadow transition-all ${renderAnnotatedVideo ? 'left-[34px]' : 'left-1'}`}
                  />
                </button>
                <div>
                  <p className="text-base font-medium text-slate-800">Generate annotated video</p>
                  <p className="text-sm leading-relaxed text-slate-600">
                    Renders bounding boxes and signals on output
                  </p>
                </div>
              </div>

              {status === 'error' && (
                <div className="mt-6 rounded-lg border border-red-200 bg-red-50 p-4 text-sm leading-relaxed text-red-700">
                  {error || 'Something went wrong. Check that the analysis server is running.'}
                  {jobId && <div className="mt-2 text-xs text-red-600">Job ID: {jobId}</div>}
                </div>
              )}

              <button
                type="button"
                disabled={!file}
                onClick={runAnalysis}
                className={`mt-8 w-full rounded-xl py-4 text-base font-semibold transition-colors ${
                  file
                    ? 'bg-gradient-to-r from-[#6366f1] to-[#7c5cff] text-white shadow-[0_8px_20px_rgba(99,102,241,0.3)] hover:from-[#5558e8] hover:to-[#6f4cf8]'
                    : 'cursor-not-allowed bg-slate-300 text-slate-500'
                }`}
              >
                Run Analysis
              </button>
            </>
          )}
        </GlassCard>
      </section>
    </PageContainer>
  );
}
