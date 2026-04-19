// SessionSummary — full-screen overlay, rendered when session_summary event arrives.

function ProbabilityBar({ value }) {
  const pct = Math.round(value * 100);
  const color =
    pct >= 50 ? "bg-red-400" :
    pct >= 25 ? "bg-amber-400" :
                "bg-slate-300";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-slate-200 print:w-20">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className={`text-xs font-bold tabular-nums ${
        pct >= 50 ? "text-red-500" : pct >= 25 ? "text-amber-500" : "text-slate-400"
      }`}>{pct}%</span>
    </div>
  );
}

function Differential({ rank, item }) {
  const pct = Math.round(item.probability * 100);
  const rankColor =
    rank === 1 ? "bg-red-100 text-red-600 border-red-200" :
    rank === 2 ? "bg-amber-100 text-amber-600 border-amber-200" :
                 "bg-slate-100 text-slate-500 border-slate-200";

  return (
    <div className="flex gap-4 rounded-xl border border-slate-100 bg-white p-4 shadow-sm print:border-slate-300 print:shadow-none">
      <div className={`flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full border text-xs font-bold ${rankColor}`}>
        {rank}
      </div>
      <div className="flex-1 min-w-0">
        <div className="mb-1.5 flex flex-wrap items-start justify-between gap-2">
          <p className="text-sm font-semibold text-slate-800">{item.diagnosis}</p>
          <ProbabilityBar value={item.probability} />
        </div>
        <p className="text-xs leading-relaxed text-slate-500">{item.reasoning}</p>
      </div>
    </div>
  );
}

function Chip({ label, color }) {
  const styles = {
    blue:   "bg-blue-50   text-blue-700   ring-blue-200",
    violet: "bg-violet-50 text-violet-700 ring-violet-200",
    slate:  "bg-slate-100 text-slate-600  ring-slate-200",
  };
  return (
    <span className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-medium ring-1 ring-inset ${styles[color] ?? styles.slate}`}>
      {label}
    </span>
  );
}

function SoapSection({ label, text }) {
  return (
    <div>
      <p className="mb-1 text-[10px] font-bold uppercase tracking-widest text-slate-400">{label}</p>
      <p className="text-sm leading-relaxed text-slate-700">{text}</p>
    </div>
  );
}

export default function SessionSummary({ summary, patient, onClose }) {
  if (!summary) return null;

  const sortedDiffs = [...summary.differentials].sort((a, b) => b.probability - a.probability);

  function handlePrint() {
    window.print();
  }

  return (
    /* Backdrop */
    <div className="animate-fade-in fixed inset-0 z-50 flex flex-col bg-slate-100 print:static print:bg-white">

      {/* ── Print header (hidden on screen) ───────────────────────────── */}
      <div className="hidden print:mb-6 print:block">
        <p className="text-xl font-bold text-slate-900">Doccy Co-pilot — Session Summary</p>
        {patient && (
          <p className="mt-1 text-sm text-slate-500">
            {patient.name}, Age {patient.age}
          </p>
        )}
        <hr className="mt-4 border-slate-300" />
      </div>

      {/* ── Screen header ─────────────────────────────────────────────── */}
      <header className="flex flex-shrink-0 items-center justify-between border-b border-slate-200 bg-white px-6 py-4 shadow-sm print:hidden">
        <div>
          <h1 className="text-base font-bold text-slate-900">Session Summary</h1>
          {patient && (
            <p className="text-xs text-slate-400">{patient.name} · Age {patient.age}</p>
          )}
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={handlePrint}
            className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 shadow-sm transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900"
          >
            <span className="text-sm leading-none">⎙</span>
            Print
          </button>
          <button
            onClick={onClose}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 shadow-sm transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900"
          >
            ✕ Close
          </button>
        </div>
      </header>

      {/* ── Body ─────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-6 py-6 print:overflow-visible print:px-0 print:py-0">
        <div className="mx-auto max-w-4xl space-y-6">

          {/* ── Row 1: Differentials + Key findings ─────────────────── */}
          <div className="grid grid-cols-1 gap-5 md:grid-cols-3 print:grid-cols-1">

            {/* Differentials (2/3 width) */}
            <div className="md:col-span-2 print:col-span-1">
              <div className="mb-3 flex items-center gap-2">
                <h2 className="text-xs font-bold uppercase tracking-widest text-slate-400">
                  Differential Diagnoses
                </h2>
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-400">
                  {sortedDiffs.length}
                </span>
              </div>
              <div className="flex flex-col gap-2.5">
                {sortedDiffs.map((d, i) => (
                  <Differential key={i} rank={i + 1} item={d} />
                ))}
              </div>
            </div>

            {/* Key findings (1/3 width) */}
            <div>
              <h2 className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-400">
                Key Findings
              </h2>
              <div className="rounded-xl border border-slate-100 bg-white p-4 shadow-sm print:border-slate-300 print:shadow-none">
                <ul className="space-y-2.5">
                  {summary.keyFindings.map((f, i) => (
                    <li key={i} className="flex items-start gap-2.5">
                      <span className="mt-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-slate-400" />
                      <span className="text-xs leading-relaxed text-slate-600">{f}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>

          {/* ── Row 2: Labs + Imaging chips ─────────────────────────── */}
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 print:grid-cols-1">
            <div className="rounded-xl border border-slate-100 bg-white p-4 shadow-sm print:border-slate-300 print:shadow-none">
              <h2 className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-400">
                Suggested Labs
              </h2>
              <div className="flex flex-wrap gap-2">
                {summary.suggestedLabs.map((l) => (
                  <Chip key={l} label={l} color="blue" />
                ))}
              </div>
            </div>

            <div className="rounded-xl border border-slate-100 bg-white p-4 shadow-sm print:border-slate-300 print:shadow-none">
              <h2 className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-400">
                Suggested Imaging
              </h2>
              <div className="flex flex-wrap gap-2">
                {summary.suggestedImaging.map((i) => (
                  <Chip key={i} label={i} color="violet" />
                ))}
              </div>
            </div>
          </div>

          {/* ── Row 3: SOAP note ─────────────────────────────────────── */}
          <div className="rounded-xl border border-slate-100 bg-white p-5 shadow-sm print:border-slate-300 print:shadow-none">
            <h2 className="mb-4 text-xs font-bold uppercase tracking-widest text-slate-400">
              SOAP Note
            </h2>
            <div className="grid grid-cols-1 gap-x-8 gap-y-5 sm:grid-cols-2 print:grid-cols-1">
              <SoapSection label="Subjective"  text={summary.soapNote.subjective}  />
              <SoapSection label="Objective"   text={summary.soapNote.objective}   />
              <SoapSection label="Assessment"  text={summary.soapNote.assessment}  />
              <SoapSection label="Plan"        text={summary.soapNote.plan}        />
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}
