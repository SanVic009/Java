import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import PageContainer from '../components/PageContainer';
import TopBar from '../components/TopBar';
import GlassCard from '../components/GlassCard';
import { API_BASE_URL } from '../lib/analysisUtils';

function toHex(buffer) {
  const bytes = new Uint8Array(buffer);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

async function computeSha256(file) {
  const data = await file.arrayBuffer();
  const digest = await crypto.subtle.digest('SHA-256', data);
  return toHex(digest);
}

export default function CheckIntegrityPage() {
  const [jobId, setJobId] = useState('');
  const [file, setFile] = useState(null);
  const [status, setStatus] = useState('idle'); // idle | hashing | checking | done | error
  const [error, setError] = useState('');
  const [localSha256, setLocalSha256] = useState('');
  const [result, setResult] = useState(null);

  const statusTone = useMemo(() => {
    if (!result?.integrityStatus) return 'border-slate-200 bg-slate-50 text-slate-700';
    return result.integrityStatus === 'untampered'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
      : 'border-red-200 bg-red-50 text-red-700';
  }, [result]);

  const runCheck = async () => {
    if (!jobId.trim()) {
      setStatus('error');
      setError('Please provide a Job ID.');
      return;
    }
    if (!file) {
      setStatus('error');
      setError('Please select a file to verify.');
      return;
    }

    if (!window.crypto?.subtle) {
      setStatus('error');
      setError('SHA-256 is not available in this browser.');
      return;
    }

    setStatus('hashing');
    setError('');
    setResult(null);

    try {
      const computed = await computeSha256(file);
      setLocalSha256(computed);
      setStatus('checking');

      const formData = new FormData();
      formData.append('jobId', jobId.trim());
      formData.append('file', file);
      formData.append('clientSha256', computed);

      const response = await fetch(`${API_BASE_URL}/api/integrity/check`, {
        method: 'POST',
        body: formData,
      });

      const rawText = await response.text();
      let payload;
      try {
        payload = JSON.parse(rawText);
      } catch {
        throw new Error(`Server returned non-JSON response (HTTP ${response.status}).`);
      }

      if (!response.ok) {
        throw new Error(payload?.error || payload?.message || `Integrity check failed (HTTP ${response.status}).`);
      }

      setResult(payload);
      setStatus('done');
    } catch (e) {
      setStatus('error');
      setError(e instanceof Error ? e.message : 'Integrity check failed.');
    }
  };

  return (
    <PageContainer>
      <TopBar
        backToHome
        right={
          <Link
            to="/upload"
            className="rounded-lg border border-indigo-200 bg-white px-4 py-2 text-sm font-semibold text-indigo-700 transition-colors hover:bg-indigo-50"
          >
            Open Upload
          </Link>
        }
      />

      <section className="mx-auto max-w-5xl px-6 pb-14 pt-10">
        <GlassCard className="p-7 md:p-10">
          <h2 className="text-2xl font-semibold text-slate-900">Check Integrity</h2>
          <p className="mt-2 text-[16px] leading-relaxed text-slate-600">
            This page computes SHA-256 in-browser, then compares it against the phase-3 SHA-256 stored for the provided job ID.
          </p>

          <div className="mt-8">
            <label className="mb-2 block text-sm text-slate-700">Job ID</label>
            <input
              type="text"
              value={jobId}
              onChange={(e) => setJobId(e.target.value)}
              placeholder="Enter generated or user-provided job ID"
              className="w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-base text-slate-900 outline-none transition focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
            />
          </div>

          <label className="mt-6 block cursor-pointer rounded-xl border-2 border-dashed border-indigo-200 bg-indigo-50/30 p-8 text-center transition-colors hover:bg-indigo-50/60">
            <input
              type="file"
              accept="video/mp4"
              className="hidden"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
            <p className="text-[18px] text-slate-800">Click to select file for integrity verification</p>
            {file && <p className="mt-2 text-sm text-indigo-700">Selected: {file.name}</p>}
          </label>

          <button
            type="button"
            onClick={runCheck}
            disabled={status === 'hashing' || status === 'checking'}
            className="mt-8 w-full rounded-xl bg-gradient-to-r from-[#6366f1] to-[#7c5cff] py-4 text-base font-semibold text-white shadow-[0_8px_20px_rgba(99,102,241,0.3)] transition-colors hover:from-[#5558e8] hover:to-[#6f4cf8] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {status === 'hashing' ? 'Computing SHA-256...' : status === 'checking' ? 'Checking Integrity...' : 'Check Integrity'}
          </button>

          {localSha256 && (
            <div className="mt-6 rounded-lg border border-slate-200 bg-slate-50 p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Client SHA-256</div>
              <div className="mt-2 break-all font-mono text-xs text-slate-700">{localSha256}</div>
            </div>
          )}

          {status === 'error' && (
            <div className="mt-6 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
              {error}
            </div>
          )}

          {result && (
            <div className="mt-6 space-y-4">
              <div className={`rounded-lg border p-4 text-sm font-semibold ${statusTone}`}>
                {String(result.integrityStatus || '').toLowerCase() === 'untampered'
                  ? 'Untampered file: hashes match.'
                  : 'Tampered file: hashes do not match.'}
              </div>

              <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Stored SHA-256 (job-store)</div>
                <div className="mt-2 break-all font-mono text-xs text-slate-700">{result.storedSha256}</div>
              </div>

              <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Uploaded File SHA-256</div>
                <div className="mt-2 break-all font-mono text-xs text-slate-700">{result.uploadedSha256}</div>
              </div>

              <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-700">
                <div>Provided Job ID: {result.providedJobId}</div>
                <div className="mt-1">Resolved Job ID: {result.resolvedJobId}</div>
              </div>
            </div>
          )}
        </GlassCard>
      </section>
    </PageContainer>
  );
}
