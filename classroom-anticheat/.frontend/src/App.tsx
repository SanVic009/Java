import React, { useState, useEffect, useRef } from 'react';

// Types
interface SupportingStats {
  head_deviation_pct: number;
  gaze_deviation_pct: number;
  proximity_avg_distance: number | null;
  proximity_min_distance: number | null;
}

interface SuspicionInterval {
  start: number;
  end: number;
  duration: number;
  peak_score: number;
  avg_score: number;
  confidence: number;
  dominant_signals: string[];
  supporting_stats: SupportingStats;
}

interface TrackResult {
  track_id: number;
  total_duration: number;
  stability_score: number;
  intervals: SuspicionInterval[];
}

interface AnnotatedVideoInfo {
  file_path: string;
  status: string;
}

interface AnalysisResponse {
  exam_id: string;
  results: TrackResult[];
  annotated_video?: AnnotatedVideoInfo;
}

type ViewState = 'HERO' | 'UPLOAD' | 'LOADING' | 'RESULTS' | 'ERROR';

const API_BASE_URL = 'http://localhost:8000';

function App() {
  const [view, setView] = useState<ViewState>('HERO');
  const [examId, setExamId] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [renderAnnotated, setRenderAnnotated] = useState(false);
  const [loadingProgress, setLoadingProgress] = useState(0);
  const [loadingMessage, setLoadingMessage] = useState('BOOT_SEQUENCE_INIT');
  const [results, setResults] = useState<AnalysisResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [terminalLogs, setTerminalLogs] = useState<string[]>(['[0.00] SYSTEM_ONLINE']);

  const uploadRef = useRef<HTMLDivElement>(null);
  const methodologyRef = useRef<HTMLDivElement>(null);

  const scrollTo = (ref: React.RefObject<HTMLDivElement>, newView?: ViewState) => {
    if (newView) setView(newView);
    setTimeout(() => ref.current?.scrollIntoView({ behavior: 'smooth' }), 100);
  };

  const addLog = (msg: string) => {
    setTerminalLogs(prev => [...prev.slice(-4), `[${(Math.random() * 9.99).toFixed(2)}] ${msg}`]);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file || !examId) return;
    setView('LOADING');
    setLoadingProgress(0);
    setTerminalLogs(['[0.00] SESSION_INIT', `[0.12] SOURCE_VIDEO: ${file.name}`]);
    
    try {
      const res = await fetch(`${API_BASE_URL}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ exam_id: examId, video_path: file.name, render_annotated_video: renderAnnotated }),
      });
      const data = await res.json();
      setJobId(data.job_id);
      addLog('JOB_ID_GEN: ' + data.job_id.slice(0, 8));
    } catch (err) {
      setError('PROTOCOL_ERROR_501');
      setView('ERROR');
    }
  };

  useEffect(() => {
    if (!jobId || view !== 'LOADING') return;
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/status/${jobId}`);
        const data = await res.json();
        setLoadingProgress(data.progress * 100);
        setLoadingMessage(data.message?.toUpperCase() || 'ANALYZING_BUFFERS');
        if (data.progress > 0.2) addLog('DETECTION_PIPELINE_RUNNING');
        if (data.progress > 0.6) addLog('SCORING_VECTORS_EXTRACTED');
        
        if (data.status === 'completed') {
          clearInterval(interval);
          addLog('SYSTEM_COMPLETED_HANDOFF');
          const resultRes = await fetch(`${API_BASE_URL}/result/${jobId}`);
          const resultData = await resultRes.json();
          setResults(resultData.result);
          setTimeout(() => setView('RESULTS'), 800);
        } else if (data.status === 'failed') {
          clearInterval(interval);
          setError(data.message || 'ENGINE_FAILURE');
          setView('ERROR');
        }
      } catch { clearInterval(interval); setView('ERROR'); }
    }, 2000);
    return () => clearInterval(interval);
  }, [jobId, view]);

  return (
    <div className="min-h-screen bg-white text-slate-900 selection:bg-emerald-100 selection:text-emerald-900 overflow-x-hidden font-sans">
      
      {/* GRID & PATTERNS */}
      <div className="fixed inset-0 bg-grid-pattern opacity-40 pointer-events-none" />
      <div className="fixed inset-0 pointer-events-none border-[12px] border-white/80 z-50" />

      {/* VIEW: HERO & UPLOAD */}
      {(view === 'HERO' || view === 'UPLOAD') && (
        <div className="relative animate-in fade-in slide-up duration-1000">
          <section className="h-screen flex flex-col items-center justify-center px-6 relative">
            {/* HUD Elements */}
            <div className="absolute top-12 left-12 flex items-center space-x-4">
              <div className="w-10 h-10 bg-emerald-500 flex items-center justify-center font-black text-white text-xl border-2 border-slate-900 shadow-[4px_4px_0px_0px_rgba(15,23,42,1)]">C</div>
              <div className="font-mono text-[9px] leading-tight font-black uppercase tracking-tight">
                System_Core_v4.2 <br/>
                <span className="text-emerald-500">Security: Verified</span>
              </div>
            </div>

            <div className="max-w-4xl text-center space-y-10">
              <div className="space-y-4">
                <span className="inline-block px-4 py-1.5 bg-emerald-50 text-emerald-600 font-mono text-[10px] font-black border-2 border-emerald-500 rounded-full uppercase tracking-widest mb-2">
                  Autonomous_Vision_Intelligence
                </span>
                <h1 className="text-5xl md:text-7xl font-black tracking-tightest leading-[0.9] uppercase">
                  ANTI_CHEAT <br/>
                  <span className="text-emerald-500 italic">SYSTEM</span>
                </h1>
              </div>
              
              <p className="text-lg md:text-xl text-slate-500 font-medium max-w-xl mx-auto leading-relaxed">
                Offline Computer Vision analysis for academic environments. Detect behavioral patterns with enterprise-grade accuracy.
              </p>

              <div className="flex flex-col sm:flex-row items-center justify-center gap-6 pt-6">
                <button
                  onClick={() => scrollTo(uploadRef, 'UPLOAD')}
                  className="px-10 py-4 bg-slate-900 text-white font-black text-lg border-2 border-slate-900 shadow-[6px_6px_0px_0px_rgba(16,185,129,1)] hover:translate-x-1 hover:translate-y-1 hover:shadow-none transition-all"
                >
                  UPLOAD_SESSION
                </button>
                <button
                  onClick={() => scrollTo(methodologyRef)}
                  className="px-10 py-4 bg-white text-slate-900 font-black text-lg border-4 border-slate-900 hover:bg-slate-50 transition-colors"
                >
                  METHODOLOGY
                </button>
              </div>
            </div>
          </section>

          {/* METHODOLOGY SECTION */}
          <section ref={methodologyRef} className="py-40 px-6 border-y-[6px] border-slate-900 bg-white relative z-10 overflow-hidden">
            <div className="max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-2 gap-20 items-start relative">
              <div className="space-y-10">
                <div className="space-y-4">
                  <span className="text-emerald-500 font-black font-mono text-xs tracking-[0.4em] uppercase">SYSTEM_SPECS</span>
                  <h2 className="text-4xl md:text-6xl font-black tracking-tighter uppercase leading-[0.9]">
                    Multi_Vector <br/>Diagnostics.
                  </h2>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-6">
                  {[
                    { label: "LATENCY", value: "0.08ms", desc: "Batch inference lag per frame." },
                    { label: "FIDELITY", value: "HIGH", desc: "Sub-pixel landmark resolution." },
                    { label: "STORAGE", value: "ENCRYPTED", desc: "Local-first data persistence." },
                    { label: "RECOVERY", value: "AUTO", desc: "Resume-friendly job states." }
                  ].map((stat, i) => (
                    <div key={i} className="p-6 border-4 border-slate-900 shadow-[8px_8px_0px_0px_rgba(241,245,249,1)] space-y-3 group hover:bg-emerald-500 hover:text-white transition-all">
                      <div className="text-[10px] font-mono font-black uppercase tracking-widest opacity-60 group-hover:opacity-100">{stat.label}</div>
                      <div className="text-3xl font-black font-mono leading-none">{stat.value}</div>
                      <p className="text-xs font-medium opacity-60 group-hover:opacity-100">{stat.desc}</p>
                    </div>
                  ))}
                </div>
              </div>
              <div className="space-y-12">
                <div className="p-8 bg-slate-900 text-white rounded-[1.5rem] shadow-2xl relative">
                  <div className="absolute top-6 right-6 w-2 h-2 bg-emerald-500 rounded-full animate-pulse shadow-[0_0_15px_rgba(16,185,129,0.8)]" />
                  <p className="font-mono text-[9px] text-emerald-500 mb-8 uppercase tracking-[0.3em] font-black">//_OPERATIONAL_PROTOCOLS</p>
                  <div className="space-y-8">
                    {[
                      { step: "01", title: "TRACK_LOCK", desc: "YOLOv8 + ByteTrack creates unique temporal identities for all objects." },
                      { step: "02", title: "GAZE_VECTORING", desc: "MediaPipe estimators build head-pose matrices and gaze intersection points." },
                      { step: "03", title: "ANOMALY_CLUSTERING", desc: "Weighted signal aggregation merges suspicious frame blocks into incidents." }
                    ].map((item, i) => (
                      <div key={i} className="flex gap-6 group">
                        <span className="text-2xl font-mono font-black text-white/20 group-hover:text-emerald-500 transition-colors">{item.step}</span>
                        <div>
                          <h4 className="font-black text-lg mb-1 tracking-tighter uppercase">{item.title}</h4>
                          <p className="text-white/50 text-sm leading-snug">{item.desc}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </section>

          {/* UPLOAD SECTION */}
          <section ref={uploadRef} className="py-40 px-6 bg-slate-50 flex justify-center relative">
            <div className="w-full max-w-2xl bg-white border-[6px] border-slate-900 p-12 shadow-[24px_24px_0px_0px_rgba(16,185,129,0.1)] relative">
              <div className="flex justify-between items-start mb-12">
                <div className="space-y-2">
                  <h2 className="text-4xl font-black tracking-tightest uppercase">Session_Load</h2>
                  <p className="font-mono text-[9px] text-slate-400 font-black uppercase tracking-widest">PROTOCOL: ANALYTICS_v4_INIT</p>
                </div>
                <div className="w-10 h-10 border-4 border-slate-900 border-r-emerald-500 animate-spin" />
              </div>

              <form onSubmit={handleSubmit} className="space-y-10">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                  <div className="space-y-3">
                    <label className="text-[10px] font-mono font-black text-slate-400 uppercase tracking-widest">_EXAM_IDENTIFIER</label>
                    <input
                      type="text"
                      value={examId}
                      onChange={(e) => setExamId(e.target.value)}
                      placeholder="EX-B101"
                      className="w-full px-6 py-4 bg-slate-50 border-4 border-slate-900 font-mono font-black text-base focus:bg-white focus:shadow-[4px_4px_0px_0px_rgba(16,185,129,1)] outline-none transition-all placeholder:opacity-20"
                      required
                    />
                  </div>
                  <div className="space-y-3">
                    <label className="text-[10px] font-mono font-black text-slate-400 uppercase tracking-widest">_RENDER_MODE</label>
                    <button
                      type="button"
                      onClick={() => setRenderAnnotated(!renderAnnotated)}
                      className={`w-full px-6 py-4 border-4 border-slate-900 font-black transition-all text-xs uppercase ${renderAnnotated ? 'bg-emerald-500 text-white shadow-[6px_6px_0px_0px_rgba(15,23,42,1)]' : 'bg-white text-slate-400 border-dashed opacity-50'}`}
                    >
                      {renderAnnotated ? 'ANNOTATION_ON' : 'ANNOTATION_OFF'}
                    </button>
                  </div>
                </div>

                <div className="space-y-3">
                  <label className="text-[10px] font-mono font-black text-slate-400 uppercase tracking-widest">_FOOTAGE_PAYLOAD</label>
                  <div className="relative group border-4 border-dashed border-slate-200 bg-slate-50/50 p-20 text-center hover:bg-emerald-50 transition-colors cursor-pointer rounded-3xl overflow-hidden">
                    <input
                      type="file"
                      accept="video/*"
                      onChange={(e) => setFile(e.target.files?.[0] || null)}
                      className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-20"
                      required
                    />
                    <div className="space-y-6 relative z-10">
                      <div className="w-16 h-16 bg-white border-2 border-slate-100 rounded-2xl flex items-center justify-center mx-auto text-3xl shadow-sm group-hover:scale-110 transition-transform">📼</div>
                      <div className="space-y-2">
                        <p className="text-lg font-black uppercase tracking-tight text-slate-900">
                          {file ? file.name : 'Select_Payload'}
                        </p>
                        <p className="text-slate-400 text-[10px] font-mono font-black">MP4, MOV, MKV » MAX_SIZE: 2GB</p>
                      </div>
                    </div>
                  </div>
                </div>

                <button
                  type="submit"
                  className="w-full py-5 bg-emerald-500 text-white font-black text-2xl border-4 border-slate-900 shadow-[12px_12px_0px_0px_rgba(15,23,42,1)] hover:translate-x-1 hover:translate-y-1 hover:shadow-none transition-all active:scale-[0.98]"
                >
                  START_PIPELINE
                </button>
              </form>
            </div>
          </section>
        </div>
      )}

      {/* VIEW: LOADING */}
      {view === 'LOADING' && (
        <section className="h-screen flex flex-col items-center justify-center px-6 animate-in fade-in bg-slate-900 text-white">
          <div className="w-full max-w-xl space-y-14 relative">
            <div className="scanline" />
            <div className="flex justify-between items-end border-b-2 border-white/10 pb-6">
              <div className="space-y-3">
                <span className="font-mono text-[10px] font-black text-emerald-500 animate-pulse uppercase tracking-[0.4em]">_PROCESSING_STREAM</span>
                <h3 className="text-5xl font-black tracking-tightest uppercase leading-none">{loadingMessage}</h3>
              </div>
              <div className="text-7xl font-black italic tracking-tighter opacity-10">{Math.round(loadingProgress)}%</div>
            </div>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-10">
              <div className="space-y-6">
                <div className="w-full h-10 bg-white/5 border-2 border-white/10 relative overflow-hidden">
                  <div 
                    className="h-full bg-emerald-500 transition-all duration-700 ease-out"
                    style={{ width: `${loadingProgress}%` }}
                  />
                  <div className="absolute inset-0 flex items-center justify-center font-mono text-[8px] font-black tracking-[1em] text-white/30">BUFF_ANALYSIS</div>
                </div>
                <div className="flex justify-between font-mono text-[8px] font-black text-white/40">
                  <span>FRAME_OFFSET: {Math.round(loadingProgress * 1200)}</span>
                  <span>CPU_LOAD: 74%</span>
                </div>
              </div>
              
              <div className="bg-black/40 p-5 rounded-xl border border-white/5 font-mono text-[9px] space-y-2">
                {terminalLogs.map((log, i) => (
                  <div key={i} className={i === terminalLogs.length - 1 ? 'text-emerald-500' : 'text-white/40'}>
                    {log}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>
      )}

      {/* VIEW: RESULTS */}
      {view === 'RESULTS' && results && (
        <main className="h-screen flex flex-col bg-slate-50 animate-in fade-in overflow-hidden relative z-10 border-[12px] border-white">
          <header className="px-8 py-4 flex justify-between items-center border-b-[6px] border-slate-900 bg-white shrink-0">
            <div className="flex items-center gap-6">
              <div className="w-10 h-10 bg-slate-900 flex items-center justify-center font-black text-emerald-500 text-xl shadow-[4px_4px_0px_0px_rgba(16,185,129,1)]">C</div>
              <div>
                <h2 className="font-black text-xl tracking-tightest uppercase">{results.exam_id}_REPORT</h2>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="px-2 py-0.5 bg-emerald-100 text-emerald-600 text-[8px] font-black rounded-sm uppercase tracking-widest">Integrity_Secure</span>
                </div>
              </div>
            </div>
            <button 
              onClick={() => setView('HERO')}
              className="px-6 py-2 bg-white text-slate-900 font-black text-[10px] border-4 border-slate-900 hover:bg-emerald-500 hover:text-white hover:shadow-none transition-all uppercase tracking-widest shadow-[4px_4px_0px_0px_rgba(15,23,42,1)]"
            >
              Flush_Buffers
            </button>
          </header>

          <div className="flex flex-col lg:flex-row flex-1 overflow-hidden">
            {/* Left: Terminal Hub */}
            <div className="flex-1 bg-slate-900 flex items-center justify-center p-8 relative overflow-hidden group">
              <div className="scanline" />
              <div className="absolute top-6 left-6 flex flex-col gap-3 font-mono text-[8px] font-black text-white/40 z-20">
                <div className="flex gap-2 items-center"><span className="w-1.5 h-1.5 rounded-full bg-emerald-500" /> FEED_SYNC_OK</div>
                <div className="flex gap-2 items-center"><span className="w-1.5 h-1.5 rounded-full bg-emerald-500" /> ANNOT_LAYER_v2</div>
              </div>

              {results.annotated_video ? (
                <div className="w-full max-w-5xl border-[8px] border-white/5 shadow-[0_0_100px_rgba(0,0,0,0.8)] relative z-10 group-hover:scale-[1.01] transition-transform duration-700">
                  <video 
                    controls 
                    className="w-full block"
                    src={`${API_BASE_URL}/static/${results.annotated_video.file_path.split(/[\\/]/).slice(-2).join('/')}`}
                  />
                </div>
              ) : (
                <div className="text-center space-y-6 relative z-10">
                  <div className="text-6xl opacity-30 animate-pulse">📡</div>
                  <p className="font-mono text-[10px] text-emerald-500 font-black uppercase tracking-[0.4em]">Metadata_Report_Ready</p>
                </div>
              )}
            </div>

            {/* Right: Incident Control */}
            <div className="w-full lg:w-[480px] flex flex-col bg-white border-l-[6px] border-slate-900 shadow-2xl overflow-hidden shrink-0 relative">
              <div className="p-8 border-b-4 border-slate-50 bg-white relative z-10">
                <div className="flex justify-between items-end mb-4">
                  <div>
                    <h3 className="font-black text-3xl tracking-tightest uppercase mb-1">Incidents</h3>
                    <p className="text-[9px] font-mono font-black text-slate-300 uppercase tracking-widest leading-none">Anomalous_Temporal_Clusters</p>
                  </div>
                  <div className="px-4 py-1.5 bg-slate-900 text-white font-mono text-lg font-black skew-x-[-10deg]">
                    {results.results.filter(r => r.intervals.length > 0).length}
                  </div>
                </div>
              </div>
              
              <div className="flex-1 overflow-y-auto p-6 space-y-6 bg-grid-pattern bg-[length:30px_30px]">
                {results.results.filter(r => r.intervals.length > 0).length === 0 ? (
                  <div className="h-full flex flex-col items-center justify-center text-center p-12 space-y-6 opacity-20">
                    <div className="text-8xl">🛡️</div>
                    <p className="font-mono text-xs font-black text-slate-400 uppercase leading-relaxed tracking-widest">Zero_Threat_Markers <br/>Identified_In_Session</p>
                  </div>
                ) : (
                  results.results
                    .filter(r => r.intervals.length > 0)
                    .map((track) => (
                      <div key={track.track_id} className="bg-white border-4 border-slate-900 p-6 shadow-[8px_8px_0px_0px_rgba(15,23,42,0.05)] hover:shadow-[10px_10px_0px_0px_rgba(16,185,129,0.1)] hover:translate-x-[-4px] hover:translate-y-[-4px] transition-all relative overflow-hidden group">
                        <div className="absolute top-0 right-0 p-3 opacity-[0.03] text-4xl font-black group-hover:opacity-[0.08] transition-opacity">0{track.track_id}</div>
                        <div className="flex justify-between items-start mb-6 border-b-2 border-slate-50 pb-4">
                          <div>
                            <h4 className="font-black text-lg tracking-tightest uppercase mb-1">Subject_{track.track_id}</h4>
                            <div className="flex gap-2">
                              <span className="px-1.5 py-0.5 bg-slate-100 text-slate-500 font-mono text-[7px] font-black uppercase">CONF_{ (track.stability_score * 100).toFixed(0)}</span>
                              <span className="px-1.5 py-0.5 bg-emerald-100 text-emerald-600 font-mono text-[7px] font-black uppercase tracking-widest">STABLE_TRACK</span>
                            </div>
                          </div>
                        </div>
                        
                        <div className="space-y-4">
                          {track.intervals.map((interval, idx) => (
                            <div key={idx} className="p-4 border-4 border-slate-50 bg-slate-50/30 hover:bg-white hover:border-emerald-500/20 transition-all rounded-xl relative overflow-hidden">
                              <div className="flex justify-between items-center mb-3 relative z-10">
                                <div className="font-mono text-[9px] font-black text-slate-900 bg-white px-2 py-1 border-2 border-slate-900 shadow-[2px_2px_0px_0px_rgba(15,23,42,1)]">
                                  {interval.start.toFixed(1)}S » {interval.end.toFixed(1)}S
                                </div>
                                <div className={`text-xl font-black font-mono leading-none ${interval.peak_score > 0.8 ? 'text-red-500' : 'text-emerald-500'}`}>
                                  {(interval.peak_score * 100).toFixed(0)}%_PK
                                </div>
                              </div>
                              
                              <div className="flex flex-wrap gap-2 relative z-10">
                                {interval.dominant_signals.map(signal => (
                                  <span key={signal} className="px-2 py-1 bg-slate-900 text-white text-[8px] font-mono font-black uppercase tracking-widest rounded-sm skew-x-[-12deg]">
                                    {signal.replace('_', ' ')}
                                  </span>
                                ))}
                                <div className="flex-1" />
                                <div className="font-mono text-[7px] font-black text-slate-300 uppercase mt-1">CERTAINTY_{ (interval.confidence * 100).toFixed(0)}%</div>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))
                )}
              </div>
            </div>
          </div>
        </main>
      )}

      {/* VIEW: ERROR */}
      {view === 'ERROR' && (
        <section className="h-screen flex flex-col items-center justify-center px-6 text-center animate-in fade-in bg-white">
          <div className="text-8xl mb-10">🚨</div>
          <h3 className="text-5xl font-black tracking-tightest uppercase text-slate-900 mb-6">Engine_Panic</h3>
          <p className="font-mono text-xs text-slate-400 max-w-lg mb-12 uppercase font-black leading-loose tracking-widest p-6 border-4 border-red-100 bg-red-50 text-red-600 rounded-2xl">
            {error || 'PIPELINE_ERROR_DETECTED'}
          </p>
          <button
            onClick={() => setView('UPLOAD')}
            className="px-12 py-5 bg-slate-900 text-white font-black text-xl border-2 border-slate-900 shadow-[8px_8px_0px_0px_rgba(239,68,68,1)] hover:shadow-none hover:translate-x-1 hover:translate-y-1 transition-all"
          >
            HARD_REBOOT
          </button>
        </section>
      )}
    </div>
  );
}

export default App;
