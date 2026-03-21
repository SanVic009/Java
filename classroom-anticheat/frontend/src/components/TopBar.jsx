import { Link } from 'react-router-dom';

export default function TopBar({ right, backToHome = false }) {
  return (
    <header className="sticky top-0 z-20 border-b border-indigo-100/80 bg-gradient-to-r from-white via-indigo-50/60 to-white backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        {backToHome ? (
          <Link
            to="/"
            className="text-sm font-semibold tracking-wide text-slate-600 transition-colors hover:text-indigo-700"
          >
            ← Back to Home
          </Link>
        ) : (
          <div className="text-sm font-semibold tracking-wide text-slate-700">Exam Integrity System</div>
        )}

        {right}
      </div>
    </header>
  );
}
