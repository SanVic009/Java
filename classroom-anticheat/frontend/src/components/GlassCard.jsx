export default function GlassCard({ children, className = '' }) {
  return (
    <div
      className={`rounded-2xl border border-slate-200 bg-gradient-to-b from-white to-slate-50 shadow-[0_10px_32px_rgba(79,70,229,0.08)] ${className}`}
    >
      {children}
    </div>
  );
}
