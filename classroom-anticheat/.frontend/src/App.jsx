import { useMemo, useRef, useState } from 'react';

const API_BASE_URL = 'http://localhost:8000';

const INITIAL_RESULT = {
  exam_id: '',
  results: [],
  annotated_video_path: '',
};

function signalPillClass(signal) {
  if (signal === 'HeadDeviation') {
    return 'text-indigo-100 border-indigo-400/40 bg-indigo-500/20';
  }
  if (signal === 'GazeDeviation') {
    return 'text-violet-100 border-violet-400/40 bg-violet-500/20';
  }
  if (signal === 'ProximityAnomaly') {
    return 'text-teal-100 border-teal-400/40 bg-teal-500/20';
  }
  return 'text-indigo-100 border-indigo-400/30 bg-indigo-500/15';
}

function toDisplaySignal(signal) {
  if (!signal) return 'UnknownSignal';
  const direct = signal.replace(/[_\s]+/g, '');
  if (/^headdeviation$/i.test(direct)) return 'HeadDeviation';
  if (/^gazedeviation$/i.test(direct)) return 'GazeDeviation';
  if (/^proximityanomaly$/i.test(direct)) return 'ProximityAnomaly';
  return signal;
}

function toPercent(value) {
  return `${Math.round((Number(value) || 0) * 100)}%`;
}

function toSeconds(value) {
  return `${(Number(value) || 0).toFixed(2)}s`;
}

function resolveVideoSrc(path) {
  if (!path) return '';
  if (/^https?:\/\//i.test(path)) return path;
  if (path.startsWith('/')) return `${API_BASE_URL}${path}`;
  return `${API_BASE_URL}/${path}`;
}

function parseResponse(payload) {
  const body = payload?.result ?? payload ?? {};
  const tracks = Array.isArray(body.results)
    ? body.results
    : Array.isArray(body.tracks)
      ? body.tracks
      : [];

  const mappedResults = tracks.map((track) => ({
    track_id: track.track_id ?? track.id ?? 'N/A',
    intervals: Array.isArray(track.intervals)
      ? track.intervals.map((interval) => ({
          start: interval.start,
          end: interval.end,
          peak_score: interval.peak_score,
          confidence: interval.confidence,
          dominant_signals: Array.isArray(interval.dominant_signals)
            ? interval.dominant_signals
            : [],
        }))
      : [],
  }));

  const annotatedPath =
    body.annotated_video_path ||
    body.annotated_video ||
    body.annotated_video_url ||
    body.annotatedVideoPath ||
    body?.annotated_video?.file_path ||
    '';

  return {
    exam_id: body.exam_id || body.examId || '',
    results: mappedResults,
    annotated_video_path: annotatedPath,
  };
}

export default function App() {
  const uploadRef = useRef(null);
  const [showUpload, setShowUpload] = useState(false);
  const [isDragOver, setIsDragOver] = useState(false);
  const [file, setFile] = useState(null);
  const [examId, setExamId] = useState('');
  const [renderAnnotated, setRenderAnnotated] = useState(true);
  const [status, setStatus] = useState('idle'); // idle | processing | done | error
  const [result, setResult] = useState(INITIAL_RESULT);
  const [errorMessage, setErrorMessage] = useState('');

  const flaggedTracks = useMemo(
    () => result.results.filter((track) => track.intervals.length > 0),
    [result.results],
  );

  const revealUpload = () => {
    setShowUpload(true);
    setTimeout(() => {
      uploadRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 120);
  };

  const resetState = () => {
    setStatus('idle');
    setErrorMessage('');
    setResult(INITIAL_RESULT);
  };

  const onDrop = (event) => {
    event.preventDefault();
    setIsDragOver(false);
    const selected = event.dataTransfer.files?.[0];
    if (selected) {
      setFile(selected);
      resetState();
    }
  };

  const runAnalysis = async () => {
    if (!file) return;
    if (!examId.trim()) {
      setStatus('error');
      setErrorMessage('Please provide an Exam ID before running analysis.');
      return;
    }

    setStatus('processing');
    setErrorMessage('');

    try {
      const response = await fetch(`${API_BASE_URL}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          exam_id: examId.trim(),
          video_path: file.name,
          render_annotated_video: renderAnnotated,
        }),
      });

      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(
          data?.message ||
            data?.detail ||
            'Something went wrong. Check that the analysis server is running.',
        );
      }

      setResult(parseResponse(data));
      setStatus('done');
    } catch (error) {
      setStatus('error');
      setErrorMessage(
        error instanceof Error
          ? error.message
          : 'Something went wrong. Check that the analysis server is running.',
      );
    }
  };

  return (
    <div
      className="min-h-screen"
      style={{ backgroundColor: '#0a0f1e', color: '#f0f4ff' }}
    >
      <section className="min-h-screen flex items-center justify-center px-6">
        <div className="max-w-6xl mx-auto text-center py-20">
          <span
            className="inline-flex items-center rounded-full border px-4 py-2 text-sm tracking-wide"
            style={{
              color: '#6366f1',
              borderColor: 'rgba(99,102,241,0.45)',
              backgroundColor: 'rgba(99,102,241,0.09)',
            }}
          >
            AI-Powered Exam Monitoring
          </span>

          <h1 className="mt-8 text-5xl md:text-7xl lg:text-[72px] font-extrabold leading-[1.1] tracking-tight">
            Catch Dishonesty. Protect Integrity.
          </h1>

          <p className="mt-8 max-w-4xl mx-auto text-base md:text-lg leading-relaxed font-light tracking-wide text-blue-100/80">
            Upload your exam footage and let the system automatically surface suspicious behavior for human review — privately, offline, and without bias.
          </p>

          <div className="mt-12 flex flex-col sm:flex-row items-center justify-center gap-4">
            <button
              type="button"
              onClick={revealUpload}
              className="rounded-xl px-8 py-4 text-base font-semibold transition-colors"
              style={{ backgroundColor: '#6366f1' }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = '#7c7ff4';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = '#6366f1';
              }}
            >
              Analyze Video
            </button>

            <button
              type="button"
              onClick={() => {
                setShowUpload(true);
                uploadRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
              }}
              className="rounded-xl px-8 py-4 text-base font-semibold border transition-colors text-blue-100/90"
              style={{ borderColor: 'rgba(255,255,255,0.24)' }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = 'rgba(99,102,241,0.65)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = 'rgba(255,255,255,0.24)';
              }}
            >
              See How It Works
            </button>
          </div>

          <div className="mt-16 flex items-center justify-center gap-3">
            <span className="h-2 w-2 rounded-full bg-indigo-400/70 shadow-[0_0_10px_rgba(99,102,241,0.8)]" />
            <span className="h-2 w-2 rounded-full bg-indigo-400/50 shadow-[0_0_10px_rgba(99,102,241,0.6)]" />
            <span className="h-2 w-2 rounded-full bg-indigo-400/35 shadow-[0_0_10px_rgba(99,102,241,0.5)]" />
          </div>
        </div>
      </section>

      <section
        ref={uploadRef}
        className={`px-6 pb-24 transition-all duration-500 ${showUpload ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4 pointer-events-none'}`}
      >
        <div
          className="max-w-5xl mx-auto rounded-2xl p-6 md:p-10"
          style={{
            backgroundColor: '#111827',
            border: '1px solid rgba(255,255,255,0.07)',
          }}
        >
          <h2 className="text-2xl font-medium">Upload Exam Footage</h2>
          <p className="mt-2 text-blue-100/75 text-base leading-relaxed">
            Supported format: MP4. Processing happens locally via your analysis server.
          </p>

          {status === 'processing' ? (
            <div className="mt-10 text-center py-16 transition-opacity duration-500">
              <div className="mx-auto h-16 w-16 rounded-full border-4 border-indigo-400/20 border-t-indigo-400 animate-spin" />
              <p className="mt-6 text-xl font-medium">Analyzing footage…</p>
              <p className="mt-2 text-blue-100/75 text-base leading-relaxed">
                This may take several minutes depending on video length.
              </p>
              <button
                type="button"
                onClick={() => setStatus('idle')}
                className="mt-8 text-blue-100/75 underline underline-offset-4 hover:text-blue-100"
              >
                Cancel
              </button>
            </div>
          ) : status === 'done' ? (
            <div className="mt-10 transition-opacity duration-500">
              {flaggedTracks.length === 0 ? (
                <div
                  className="rounded-xl border p-8 text-center"
                  style={{ borderColor: 'rgba(52,211,153,0.35)', backgroundColor: 'rgba(16,185,129,0.08)' }}
                >
                  <div className="text-4xl">✓</div>
                  <p className="mt-3 text-lg font-medium text-emerald-300">
                    No suspicious patterns detected
                  </p>
                </div>
              ) : (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  <div
                    className="rounded-xl p-3"
                    style={{
                      backgroundColor: 'rgba(10,15,30,0.55)',
                      border: '1px solid rgba(255,255,255,0.07)',
                    }}
                  >
                    {result.annotated_video_path ? (
                      <video
                        controls
                        className="w-full rounded-lg"
                        src={resolveVideoSrc(result.annotated_video_path)}
                      />
                    ) : (
                      <div className="rounded-lg p-8 text-center text-blue-100/80">
                        Annotated video path not returned by server.
                      </div>
                    )}
                  </div>

                  <div
                    className="rounded-xl p-4 max-h-[500px] overflow-y-auto"
                    style={{
                      backgroundColor: 'rgba(10,15,30,0.55)',
                      border: '1px solid rgba(255,255,255,0.07)',
                    }}
                  >
                    <div className="space-y-4">
                      {flaggedTracks.map((track) => (
                        <article
                          key={track.track_id}
                          className="rounded-xl p-4"
                          style={{
                            backgroundColor: '#111827',
                            border: '1px solid rgba(255,255,255,0.07)',
                          }}
                        >
                          <h3 className="text-lg font-bold">Track {track.track_id}</h3>

                          <div className="mt-3 space-y-3">
                            {track.intervals.map((interval, index) => (
                              <div
                                key={`${track.track_id}-${index}`}
                                className="rounded-lg p-3"
                                style={{ border: '1px solid rgba(255,255,255,0.07)' }}
                              >
                                <p className="text-sm text-blue-100/90 leading-relaxed">
                                  {toSeconds(interval.start)} – {toSeconds(interval.end)}
                                </p>
                                <p className="mt-1 text-sm text-blue-100/80 leading-relaxed">
                                  Peak score: {toPercent(interval.peak_score)}
                                </p>
                                <p className="text-sm text-blue-100/80 leading-relaxed">
                                  Confidence: {toPercent(interval.confidence)}
                                </p>

                                <div className="mt-2 flex flex-wrap gap-2">
                                  {interval.dominant_signals.map((signal, idx) => {
                                    const normalized = toDisplaySignal(signal);
                                    return (
                                      <span
                                        key={`${signal}-${idx}`}
                                        className={`rounded-full border px-2.5 py-1 text-xs ${signalPillClass(normalized)}`}
                                      >
                                        {normalized}
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

              <p className="mt-6 text-sm leading-relaxed text-blue-100/70">
                Results are flagged for human review only. This system does not confirm cheating.
              </p>
            </div>
          ) : (
            <>
              <label
                onDrop={onDrop}
                onDragOver={(event) => {
                  event.preventDefault();
                  setIsDragOver(true);
                }}
                onDragLeave={() => setIsDragOver(false)}
                className="mt-8 block rounded-xl border-2 border-dashed p-12 text-center cursor-pointer transition-colors"
                style={{
                  borderColor: isDragOver ? '#6366f1' : 'rgba(99,102,241,0.5)',
                  backgroundColor: isDragOver ? 'rgba(99,102,241,0.08)' : 'rgba(99,102,241,0.03)',
                }}
              >
                <input
                  type="file"
                  accept="video/mp4"
                  className="hidden"
                  onChange={(event) => {
                    const selected = event.target.files?.[0];
                    if (selected) {
                      setFile(selected);
                      resetState();
                    }
                  }}
                />
                <p className="text-lg leading-relaxed">Drag and drop your video file here</p>
                <p className="mt-2 text-base text-blue-100/75 leading-relaxed">or click to browse</p>
                {file && <p className="mt-4 text-sm text-indigo-300/95">Selected: {file.name}</p>}
              </label>

              <div className="mt-8">
                <label className="block text-sm mb-2 text-blue-100/90">Exam ID</label>
                <input
                  type="text"
                  value={examId}
                  onChange={(event) => setExamId(event.target.value)}
                  placeholder="e.g. exam_room_a_2026"
                  className="w-full rounded-lg px-4 py-3 text-base outline-none transition-colors"
                  style={{
                    backgroundColor: '#0a0f1e',
                    border: '1px solid rgba(255,255,255,0.13)',
                    color: '#f0f4ff',
                  }}
                  onFocus={(e) => {
                    e.currentTarget.style.borderColor = 'rgba(99,102,241,0.85)';
                  }}
                  onBlur={(e) => {
                    e.currentTarget.style.borderColor = 'rgba(255,255,255,0.13)';
                  }}
                />
              </div>

              <div className="mt-7 flex items-start gap-4">
                <button
                  type="button"
                  role="switch"
                  aria-checked={renderAnnotated}
                  onClick={() => setRenderAnnotated((prev) => !prev)}
                  className="relative h-7 w-14 rounded-full transition-colors"
                  style={{ backgroundColor: renderAnnotated ? '#6366f1' : 'rgba(255,255,255,0.22)' }}
                >
                  <span
                    className="absolute top-1 h-5 w-5 rounded-full bg-white transition-all"
                    style={{ left: renderAnnotated ? '34px' : '4px' }}
                  />
                </button>
                <div>
                  <p className="text-base font-medium text-blue-100/90">Generate annotated video</p>
                  <p className="text-sm text-blue-100/75 leading-relaxed">
                    Renders bounding boxes and signals on output
                  </p>
                </div>
              </div>

              {status === 'error' && (
                <div
                  className="mt-6 rounded-lg p-4 text-sm leading-relaxed text-red-100"
                  style={{
                    border: '1px solid rgba(248,113,113,0.55)',
                    backgroundColor: 'rgba(127,29,29,0.28)',
                  }}
                >
                  {errorMessage ||
                    'Something went wrong. Check that the analysis server is running.'}
                </div>
              )}

              <button
                type="button"
                disabled={!file}
                onClick={runAnalysis}
                className="mt-8 w-full rounded-xl py-4 text-base font-semibold transition-colors disabled:cursor-not-allowed"
                style={{
                  backgroundColor: file ? '#6366f1' : 'rgba(255,255,255,0.18)',
                  color: file ? '#f0f4ff' : 'rgba(240,244,255,0.75)',
                }}
              >
                Run Analysis
              </button>
            </>
          )}
        </div>
      </section>
    </div>
  );
}
