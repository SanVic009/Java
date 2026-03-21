import { Link } from 'react-router-dom';
import PageContainer from '../components/PageContainer';
import TopBar from '../components/TopBar';

const features = [
  {
    title: 'Institution-Ready Workflow',
    detail: 'Simple upload and review process designed for invigilators and integrity committees.',
  },
  {
    title: 'Offline-First Analysis',
    detail: 'Your footage stays inside your own environment and analysis server.',
  },
  {
    title: 'Human-In-The-Loop',
    detail: 'Suspicious intervals are surfaced for review; no automatic judgment is made.',
  },
];

export default function HomePage() {
  return (
    <PageContainer>
      <TopBar
        right={
          <Link
            to="/upload"
            className="rounded-lg bg-[#6366f1] px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-[#5558e8]"
          >
            Open Upload
          </Link>
        }
      />

      <main className="mx-auto grid max-w-6xl gap-14 px-6 pb-16 pt-14 lg:grid-cols-[1.35fr_1fr] lg:items-center">
        <section>
          <span className="inline-flex rounded-full border border-indigo-200 bg-gradient-to-r from-indigo-50 to-violet-50 px-4 py-2 text-sm font-medium text-[#6366f1]">
            AI-Powered Exam Monitoring
          </span>

          <h1 className="mt-8 max-w-4xl text-[44px] font-bold leading-[1.08] tracking-tight text-slate-900 md:text-[72px]">
            Catch Dishonesty. Protect Integrity.
          </h1>

          <p className="mt-8 max-w-3xl text-[17px] leading-relaxed text-slate-600">
            Upload your exam footage and let the system automatically surface suspicious behavior for human review — privately, offline, and without bias.
          </p>

          <div className="mt-12 flex flex-col gap-4 sm:flex-row">
            <Link
              to="/upload"
              className="inline-flex items-center justify-center rounded-xl bg-gradient-to-r from-[#6366f1] to-[#7c5cff] px-8 py-4 text-base font-semibold text-white shadow-[0_8px_20px_rgba(99,102,241,0.35)] transition-colors hover:from-[#5558e8] hover:to-[#6d4df7]"
            >
              Analyze Video
            </Link>
            <Link
              to="/upload"
              className="inline-flex items-center justify-center rounded-xl border border-slate-300 bg-white px-8 py-4 text-base font-semibold text-slate-700 transition-colors hover:border-indigo-300 hover:bg-indigo-50/40 hover:text-slate-900"
            >
              See How It Works
            </Link>
          </div>
        </section>

        <aside className="rounded-2xl border border-indigo-100 bg-gradient-to-b from-white to-indigo-50/35 p-6 shadow-[0_10px_34px_rgba(99,102,241,0.1)]">
          <div className="mb-5 text-sm font-semibold text-slate-500">Why institutions choose this system</div>
          <div className="space-y-4">
            {features.map((feature, index) => (
              <div
                key={feature.title}
                className={`rounded-xl border p-4 ${
                  index === 0
                    ? 'border-indigo-200 bg-indigo-50/70'
                    : index === 1
                      ? 'border-violet-200 bg-violet-50/70'
                      : 'border-teal-200 bg-teal-50/70'
                }`}
              >
                <h3 className="text-sm font-semibold text-slate-900">{feature.title}</h3>
                <p className="mt-1 text-sm leading-relaxed text-slate-600">{feature.detail}</p>
              </div>
            ))}
          </div>
        </aside>
      </main>
    </PageContainer>
  );
}
