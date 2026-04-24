const RAW_API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:7070').trim();
export const API_BASE_URL = RAW_API_BASE_URL.replace(/\/+$/, '');

export function buildApiUrl(path) {
  let normalizedPath = path.startsWith('/') ? path : `/${path}`;

  // If base already includes /api, avoid accidentally creating /api/api/* URLs.
  if (API_BASE_URL.endsWith('/api') && normalizedPath.startsWith('/api/')) {
    normalizedPath = normalizedPath.slice(4);
  }

  return `${API_BASE_URL}${normalizedPath}`;
}

export const EMPTY_RESULT = {
  exam_id: '',
  results: [],
  annotated_video_path: '',
  annotated_video_status: 'not_requested',
};

export function normalizeResult(resultPayload) {
  const root = resultPayload?.result ?? resultPayload ?? {};
  return Array.isArray(root?.result?.results)
    ? root.result.results
    : Array.isArray(root?.results)
      ? root.results
      : [];
}

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

/**
 * Build a playable URL for the annotated video.
 * The Java backend serves annotated videos via GET /api/video/{jobId}.
 */
export function resolveVideoUrl(jobId) {
  if (!jobId) return '';
  return buildApiUrl(`/api/video/${jobId}`);
}

// Keep the old helper for backward compat but prefer resolveVideoUrl
export function resolveVideoPath(path) {
  if (!path) return '';
  if (/^https?:\/\//i.test(path)) return path;
  if (path.startsWith('/')) return buildApiUrl(path);
  return buildApiUrl(path);
}

export function parseBackendPayload(payload) {
  const root = payload?.result ?? payload ?? {};
  const tracks = Array.isArray(normalizeResult(payload))
    ? normalizeResult(payload)
    : Array.isArray(root.tracks)
      ? root.tracks
      : [];

  const annotatedVideo =
    root?.annotated_video && typeof root.annotated_video === 'object'
      ? root.annotated_video
      : null;

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
      (typeof root.annotated_video === 'string' ? root.annotated_video : null) ||
      root.annotated_video_url ||
      annotatedVideo?.file_path ||
      '',
    annotated_video_status: annotatedVideo?.status || 'not_requested',
    error: payload?.error || null,
  };
}
