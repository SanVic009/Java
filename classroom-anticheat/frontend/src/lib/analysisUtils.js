export const API_BASE_URL = 'http://localhost:8000';

export const EMPTY_RESULT = {
  exam_id: '',
  results: [],
  annotated_video_path: '',
};

export function normalizeSignal(raw) {
  const value = String(raw || '').replace(/[_\s]+/g, '').toLowerCase();
  if (value === 'headdeviation') return 'HeadDeviation';
  if (value === 'gazedeviation') return 'GazeDeviation';
  if (value === 'proximityanomaly') return 'ProximityAnomaly';
  return raw || 'UnknownSignal';
}

export function signalPillTone(signal) {
  if (signal === 'HeadDeviation') return 'bg-indigo-100 text-indigo-700 border-indigo-300';
  if (signal === 'GazeDeviation') return 'bg-violet-100 text-violet-700 border-violet-300';
  if (signal === 'ProximityAnomaly') return 'bg-teal-100 text-teal-700 border-teal-300';
  return 'bg-slate-100 text-slate-700 border-slate-300';
}

export function formatSeconds(value) {
  return `${(Number(value) || 0).toFixed(2)}s`;
}

export function formatPercent(value) {
  return `${Math.round((Number(value) || 0) * 100)}%`;
}

export function resolveVideoPath(path) {
  if (!path) return '';
  if (/^https?:\/\//i.test(path)) return path;
  if (path.startsWith('/')) return `${API_BASE_URL}${path}`;
  return `${API_BASE_URL}/${path}`;
}

export function parseBackendPayload(payload) {
  const root = payload?.result ?? payload ?? {};
  const tracks = Array.isArray(root.results)
    ? root.results
    : Array.isArray(root.tracks)
      ? root.tracks
      : [];

  return {
    exam_id: root.exam_id || root.examId || '',
    results: tracks.map((track) => ({
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
    })),
    annotated_video_path:
      root.annotated_video_path ||
      root.annotated_video ||
      root.annotated_video_url ||
      root?.annotated_video?.file_path ||
      '',
  };
}
