import { useEffect, useRef, useState, useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useDoccy } from "../hooks/useDoccy";
import SessionSummary from "../components/SessionSummary";

// ── Skeleton loader ───────────────────────────────────────────────────────────

function Skeleton({ className }) {
  return <div className={`animate-skeleton rounded bg-slate-100 ${className}`} />;
}

function PanelSkeleton() {
  return (
    <div className="flex flex-col gap-4 p-5">
      <Skeleton className="h-3 w-1/3" />
      <div className="flex gap-3">
        <Skeleton className="h-7 w-7 flex-shrink-0 rounded-full" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-3 w-1/4" />
          <Skeleton className="h-10 w-3/4 rounded-2xl" />
        </div>
      </div>
      <div className="flex flex-row-reverse gap-3">
        <Skeleton className="h-7 w-7 flex-shrink-0 rounded-full" />
        <div className="flex-1 space-y-2 flex flex-col items-end">
          <Skeleton className="h-3 w-1/4" />
          <Skeleton className="h-14 w-4/5 rounded-2xl" />
        </div>
      </div>
      <div className="flex gap-3">
        <Skeleton className="h-7 w-7 flex-shrink-0 rounded-full" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-3 w-1/4" />
          <Skeleton className="h-8 w-2/3 rounded-2xl" />
        </div>
      </div>
    </div>
  );
}

// ── Connection banner ─────────────────────────────────────────────────────────

function ReconnectingBanner() {
  return (
    <div className="flex animate-fade-in items-center justify-center gap-2 bg-amber-500 px-4 py-1.5 text-xs font-medium text-white">
      <span className="animate-spin leading-none">⟳</span>
      Connection lost — reconnecting…
    </div>
  );
}

// ── Header ────────────────────────────────────────────────────────────────────

const URGENCY_CONFIG = {
  routine:  { dot: "bg-slate-500",   label: "Routine",  text: "text-slate-400",  ping: "" },
  elevated: { dot: "bg-amber-400",   label: "Elevated", text: "text-amber-400",  ping: "bg-amber-400" },
  urgent:   { dot: "bg-red-500",     label: "Urgent",   text: "text-red-400",    ping: "bg-red-500" },
};

function UrgencyPill({ urgency }) {
  const cfg = URGENCY_CONFIG[urgency] ?? URGENCY_CONFIG.routine;
  return (
    <div className="flex items-center gap-1.5 rounded-lg border border-slate-800 bg-slate-900 px-3 py-1.5">
      <span className="relative flex h-2 w-2 flex-shrink-0">
        {cfg.ping && <span className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 ${cfg.ping}`} />}
        <span className={`relative inline-flex h-2 w-2 rounded-full ${cfg.dot}`} />
      </span>
      <span className={`text-xs font-semibold ${cfg.text}`}>{cfg.label}</span>
    </div>
  );
}

function SessionTimer({ elapsed, active }) {
  if (!active) return null;
  const m = String(Math.floor(elapsed / 60)).padStart(2, "0");
  const s = String(elapsed % 60).padStart(2, "0");
  return (
    <span className="hidden tabular-nums text-xs text-slate-500 sm:block">{m}:{s}</span>
  );
}

function Header({ patient, routing, isConnected, summaryReady, onSummary, urgency, elapsed, sessionActive }) {
  const navigate = useNavigate();

  return (
    <header className="flex h-14 flex-shrink-0 items-center justify-between border-b border-slate-800 bg-slate-950 px-4 md:px-6">
      {/* Left: brand + patient */}
      <div className="flex min-w-0 items-center gap-3">
        <span className="flex-shrink-0 text-base font-semibold tracking-tight text-white">
          Doccy <span className="text-brand-500">Co-pilot</span>
        </span>
        {patient && (
          <>
            <span className="hidden text-slate-600 sm:block">/</span>
            <div className="hidden min-w-0 items-center gap-2 sm:flex">
              <span className="truncate text-sm font-medium text-slate-200">{patient.name}</span>
              <span className="hidden text-xs text-slate-500 md:block">Age {patient.age}</span>
              {patient.allergies?.length > 0 && (
                <span className="hidden rounded-full bg-red-900/50 px-2 py-0.5 text-xs font-medium text-red-400 lg:block">
                  ⚠ {patient.allergies.join(", ")}
                </span>
              )}
            </div>
          </>
        )}
      </div>

      {/* Right: indicators + actions */}
      <div className="flex flex-shrink-0 items-center gap-2 md:gap-3">
        <SessionTimer elapsed={elapsed} active={sessionActive} />
        <UrgencyPill urgency={urgency} />
        <div className="hidden md:block">
          <RoutingIndicator routing={routing} />
        </div>
        <ConnectionDot isConnected={isConnected} />

        <button
          onClick={onSummary}
          disabled={!summaryReady}
          className={`relative rounded-md px-2.5 py-1.5 text-xs font-medium transition md:px-3 ${
            summaryReady
              ? "border border-sky-600 bg-sky-600 text-white hover:bg-sky-500"
              : "border border-slate-700 bg-slate-900 text-slate-600 cursor-not-allowed"
          }`}
        >
          {summaryReady && (
            <span className="absolute -right-1 -top-1 flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-sky-400 opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-sky-400" />
            </span>
          )}
          Summary
        </button>

        <button
          onClick={() => navigate("/")}
          className="rounded-md border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-xs font-medium text-slate-300 transition hover:border-slate-600 hover:text-white md:px-3"
        >
          <span className="hidden sm:inline">End Session</span>
          <span className="sm:hidden">✕</span>
        </button>
      </div>
    </header>
  );
}

function RoutingIndicator({ routing }) {
  const idle    = !routing;
  const isCloud = routing?.status === "cloud";

  const dot        = idle ? "bg-slate-600" : isCloud ? "bg-sky-400" : "bg-emerald-400";
  const ping       = idle ? ""             : isCloud ? "bg-sky-400" : "bg-emerald-400";
  const label      = idle ? "—"           : isCloud ? "Cloud AI"   : "Local AI";
  const labelColor = idle ? "text-slate-500" : isCloud ? "text-sky-400" : "text-emerald-400";
  const icon       = isCloud ? "☁" : idle ? null : "⚡";
  const pct        = routing ? Math.round(routing.confidenceScore * 100) : null;
  const barColor   = isCloud ? "bg-sky-400" : "bg-emerald-400";

  return (
    <div className="group relative">
      <div className="flex cursor-default items-center gap-2 rounded-lg border border-slate-800 bg-slate-900 px-3 py-1.5 transition-colors group-hover:border-slate-700 group-hover:bg-slate-800">
        <span className="relative flex h-2 w-2 flex-shrink-0">
          {!idle && <span className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-50 ${ping}`} />}
          <span className={`relative inline-flex h-2 w-2 rounded-full ${dot}`} />
        </span>
        <span className="flex items-center gap-1">
          {icon && <span className="text-[11px] leading-none opacity-70">{icon}</span>}
          <span className={`text-xs font-semibold ${labelColor}`}>{label}</span>
        </span>
        {pct != null && <span className="text-[10px] text-slate-500 tabular-nums">{pct}%</span>}
      </div>

      {routing && (
        <div className="pointer-events-none absolute right-0 top-full z-50 mt-2 w-64 origin-top-right scale-95 opacity-0 transition-all duration-150 group-hover:scale-100 group-hover:opacity-100">
          <div className="absolute -top-1.5 right-4 h-3 w-3 rotate-45 rounded-sm border-l border-t border-slate-700 bg-slate-900" />
          <div className="relative overflow-hidden rounded-xl border border-slate-700 bg-slate-900 p-4 shadow-2xl">
            <div className="mb-3 flex items-center gap-2">
              <span className="relative flex h-2.5 w-2.5 flex-shrink-0">
                <span className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-40 ${ping}`} />
                <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${dot}`} />
              </span>
              <span className={`text-sm font-bold ${labelColor}`}>
                {icon} {isCloud ? "Cloud inference" : "Local inference"}
              </span>
            </div>
            <p className="mb-3 text-xs leading-relaxed text-slate-300">{routing.reason}</p>
            <div>
              <div className="mb-1.5 flex items-center justify-between">
                <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">Confidence</span>
                <span className={`text-xs font-bold tabular-nums ${labelColor}`}>{pct}%</span>
              </div>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
                <div className={`h-full rounded-full transition-all duration-700 ${barColor}`} style={{ width: `${pct}%` }} />
              </div>
            </div>
            <div className="mt-3 border-t border-slate-800 pt-3">
              <p className="text-[10px] leading-relaxed text-slate-600">
                {isCloud
                  ? "Routed to cloud model — complex pattern detected, latency may increase."
                  : "Running on-device — low latency, data stays local."}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ConnectionDot({ isConnected }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="relative flex h-2 w-2">
        {isConnected && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-teal-400 opacity-60" />}
        <span className={`relative inline-flex h-2 w-2 rounded-full ${isConnected ? "bg-teal-400" : "bg-slate-600"}`} />
      </span>
      <span className={`hidden text-xs sm:block ${isConnected ? "text-teal-500" : "text-slate-600"}`}>
        {isConnected ? "Live" : "Offline"}
      </span>
    </div>
  );
}

// ── Mobile tab bar ────────────────────────────────────────────────────────────

function TabBar({ activeTab, onTab, alertCount }) {
  return (
    <div className="flex flex-shrink-0 border-b border-slate-200 bg-white lg:hidden">
      {[
        { id: "clinical", label: "Differentials" },
        { id: "alerts",   label: `Alerts${alertCount > 0 ? ` (${alertCount})` : ""}` },
      ].map(({ id, label }) => (
        <button
          key={id}
          onClick={() => onTab(id)}
          className={`flex-1 py-2.5 text-xs font-semibold uppercase tracking-widest transition ${
            activeTab === id
              ? "border-b-2 border-brand-500 text-brand-600"
              : "text-slate-400 hover:text-slate-600"
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

// ── Transcript panel ──────────────────────────────────────────────────────────

function TranscriptLine({ entry }) {
  const isDoctor = entry.speaker === "doctor";
  return (
    <div className={`flex animate-slide-in gap-3 ${isDoctor ? "" : "flex-row-reverse"}`}>
      <div className={`mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full text-[10px] font-bold uppercase ${
        isDoctor ? "bg-brand-100 text-brand-700" : "bg-slate-100 text-slate-500"
      }`}>
        {isDoctor ? "Dr" : "Pt"}
      </div>
      <div className={`max-w-[78%] ${isDoctor ? "" : "flex flex-col items-end"}`}>
        <span className={`mb-1 block text-[10px] font-semibold uppercase tracking-wider ${
          isDoctor ? "text-brand-600" : "text-slate-400"
        }`}>
          {isDoctor ? "Doctor" : "Patient"}
        </span>
        <p className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
          isDoctor
            ? "rounded-tl-sm bg-brand-50 text-slate-800"
            : "rounded-tr-sm bg-slate-100 text-slate-700"
        }`}>
          {entry.text}
        </p>
      </div>
    </div>
  );
}

function TranscriptPanel({ transcript, loading }) {
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [transcript]);

  return (
    <section className="flex flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-shrink-0 items-center justify-between border-b border-slate-100 px-5 py-3">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400">Transcript</h2>
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-400">
          {transcript.length} {transcript.length === 1 ? "line" : "lines"}
        </span>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <PanelSkeleton />
        ) : transcript.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-slate-100 text-lg text-slate-300 select-none">♪</div>
            <p className="text-sm font-medium text-slate-400">Waiting for audio…</p>
            <p className="text-xs text-slate-300">Conversation will appear here in real time</p>
          </div>
        ) : (
          <div className="flex flex-col gap-5 px-5 py-5">
            {transcript.map((entry, i) => (
              <TranscriptLine key={i} entry={entry} />
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>
    </section>
  );
}

// ── Command response card ─────────────────────────────────────────────────────

const SOURCE_STYLE = {
  cloud: { label: "Cloud AI", color: "text-sky-500",     dot: "bg-sky-400"     },
  local: { label: "Local AI",  color: "text-emerald-500", dot: "bg-emerald-400" },
};

function CommandResponseCard({ response }) {
  const src = SOURCE_STYLE[response.source] ?? SOURCE_STYLE.local;
  return (
    <div className="animate-slide-in overflow-hidden rounded-xl border border-slate-200 bg-gradient-to-br from-slate-900 to-slate-800 shadow-lg">
      <div className="border-b border-slate-700/60 px-4 py-3">
        <p className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-slate-500">Query</p>
        <p className="text-xs italic leading-relaxed text-slate-400">"{response.query}"</p>
      </div>
      <div className="px-4 py-3">
        <div className="mb-2.5 flex items-center gap-2">
          <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-slate-700 text-[11px]">✦</div>
          <span className={`text-[10px] font-bold uppercase tracking-widest ${src.color}`}>{src.label}</span>
          <span className="relative ml-0.5 flex h-1.5 w-1.5">
            <span className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-50 ${src.dot}`} />
            <span className={`relative inline-flex h-1.5 w-1.5 rounded-full ${src.dot}`} />
          </span>
        </div>
        <p className="text-sm leading-relaxed text-slate-200">{response.response}</p>
      </div>
    </div>
  );
}

// ── Alerts panel ──────────────────────────────────────────────────────────────

const LEVEL_STYLE = {
  critical: { border: "border-red-400",   badge: "bg-red-100   text-red-700",   icon: "🔴" },
  warning:  { border: "border-amber-400", badge: "bg-amber-100 text-amber-700", icon: "🟡" },
  info:     { border: "border-blue-300",  badge: "bg-blue-50   text-blue-700",  icon: "🔵" },
};

const CONTRADICTION_STYLE = { border: "border-orange-400", badge: "bg-orange-100 text-orange-700", icon: "⚠" };

const DDI_SEVERITY_STYLE = {
  severe:   { border: "border-red-400",   badge: "bg-red-100   text-red-700",   icon: "💊" },
  moderate: { border: "border-amber-400", badge: "bg-amber-100 text-amber-700", icon: "💊" },
  mild:     { border: "border-slate-300", badge: "bg-slate-100 text-slate-600", icon: "💊" },
};

// ── Differential diagnosis card ───────────────────────────────────────────────

const LIKELIHOOD_STYLE = {
  high:   "bg-red-100 text-red-700 ring-red-200",
  medium: "bg-amber-100 text-amber-700 ring-amber-200",
  low:    "bg-slate-100 text-slate-500 ring-slate-200",
};

const URGENCY_BORDER = {
  urgent:   "border-red-400",
  elevated: "border-amber-400",
  routine:  "border-sky-300",
};

const SOURCE_BADGE = {
  cloud:     { label: "Cloud AI",    color: "text-sky-500",     dot: "bg-sky-400"     },
  on_device: { label: "On-Device AI", color: "text-emerald-500", dot: "bg-emerald-400" },
};

function DifferentialCard({ diff }) {
  const src     = SOURCE_BADGE[diff.source] ?? SOURCE_BADGE.on_device;
  const border  = URGENCY_BORDER[diff.urgency] ?? URGENCY_BORDER.routine;
  const items   = diff.differentials ?? [];

  return (
    <div className={`animate-slide-in rounded-lg border-l-4 bg-white px-4 py-3 shadow-sm ring-1 ring-slate-100 ${border}`}>
      <div className="mb-2 flex items-center gap-2">
        <span className="select-none text-sm leading-none">🧬</span>
        <span className="rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider bg-slate-100 text-slate-600">
          Differential
        </span>
        <span className={`ml-auto flex items-center gap-1 text-[10px] font-semibold ${src.color}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${src.dot}`} />
          {src.label}
        </span>
      </div>
      <p className="mb-2 text-sm font-semibold text-slate-800">Second Opinion</p>
      <div className="flex flex-col gap-1.5">
        {items.map((item, i) => (
          <div key={i} className="flex items-start gap-2 rounded-md bg-slate-50 px-2.5 py-2">
            <span className="mt-px text-[10px] font-bold text-slate-400 tabular-nums w-3">{i + 1}.</span>
            <div className="flex-1 min-w-0">
              <div className="flex flex-wrap items-center gap-1.5 mb-0.5">
                <span className="text-xs font-semibold text-slate-800">{item.diagnosis}</span>
                {item.likelihood && (
                  <span className={`rounded-full px-1.5 py-0.5 text-[9px] font-bold uppercase ring-1 ring-inset ${LIKELIHOOD_STYLE[item.likelihood] ?? LIKELIHOOD_STYLE.low}`}>
                    {item.likelihood}
                  </span>
                )}
                {item.icd10 && (
                  <span className="rounded px-1.5 py-0.5 font-mono text-[9px] bg-slate-800 text-slate-300">
                    {item.icd10}
                  </span>
                )}
              </div>
              {item.rationale && (
                <p className="text-[11px] leading-relaxed text-slate-500">{item.rationale}</p>
              )}
            </div>
          </div>
        ))}
      </div>
      {diff.reason && (
        <p className="mt-2 text-[10px] text-slate-400">Triggered by: {diff.reason}</p>
      )}
    </div>
  );
}

function AlertCard({ style, badge, title, body, meta, action }) {
  return (
    <div className={`animate-slide-in rounded-lg border-l-4 bg-white px-4 py-3 shadow-sm ring-1 ring-slate-100 ${style.border}`}>
      <div className="mb-1.5 flex items-center gap-2">
        <span className="select-none text-sm leading-none">{style.icon}</span>
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider ${style.badge}`}>{badge}</span>
        {meta && <span className="ml-auto text-[10px] text-slate-400">{meta}</span>}
      </div>
      <p className="text-sm font-semibold text-slate-800">{title}</p>
      {body && <p className="mt-1 text-xs leading-relaxed text-slate-500">{body}</p>}
      {action && (
        <div className="mt-2 flex items-start gap-1.5 rounded-md bg-slate-50 px-2.5 py-1.5">
          <span className="mt-px select-none text-[10px] text-slate-400">→</span>
          <p className="text-xs font-medium text-slate-600">{action}</p>
        </div>
      )}
    </div>
  );
}

function buildCards(alerts, sessionData) {
  const cards = [];
  for (const a of alerts) {
    cards.push({ id: a.id, ts: a.timestamp_ms, style: LEVEL_STYLE[a.level] ?? LEVEL_STYLE.info, badge: a.level, title: a.title, body: a.body, meta: a.source, action: a.suggestedAction });
  }
  for (const c of (sessionData?.contradictions ?? [])) {
    const typeLabels = {
      allergy_conflict:       "Allergy Conflict",
      undisclosed_drug:       "Undisclosed Drug",
      lab_correlation:        "Lab Correlation",
      ehr_drug_not_mentioned: "EHR Drug Not Mentioned",
    };
    const title = typeLabels[c.type] ?? "Contradiction";
    const style = c.level === "critical" ? LEVEL_STYLE.critical
                : c.level === "warning"  ? LEVEL_STYLE.warning
                : CONTRADICTION_STYLE;
    cards.push({ id: c.id, ts: c.timestamp_ms, style, badge: title, title: c.message, body: null, meta: null, action: null });
  }
  for (const d of (sessionData?.drugInteractions ?? [])) {
    const style = d.level === "critical" ? DDI_SEVERITY_STYLE.severe
                : d.level === "warning"  ? DDI_SEVERITY_STYLE.moderate
                : DDI_SEVERITY_STYLE.mild;
    const drugA = d.detail?.mentioned_drug ?? "";
    const drugB = d.detail?.ehr_drug ?? "";
    const title = drugA && drugB ? `${drugA} + ${drugB}` : "Drug Interaction";
    cards.push({ id: d.id, ts: d.timestamp_ms, style, badge: `DDI · ${d.level ?? "info"}`, title, body: d.message, meta: null, action: null });
  }
  return cards.sort((a, b) => b.ts - a.ts);
}

// ── Differentials panel (main left column) ───────────────────────────────────

function DifferentialsPanel({ differentials, suggestedQuestions, onDismissQuestion, loading }) {
  const sortedDiffs = [...differentials].sort((a, b) => b.timestamp - a.timestamp);
  const pendingQuestions = (suggestedQuestions ?? []).filter((q) => !q.asked);
  const askedQuestions   = (suggestedQuestions ?? []).filter((q) => q.asked);

  return (
    <section className="flex flex-col overflow-hidden rounded-xl border border-slate-200 bg-slate-50 shadow-sm">
      <div className="flex flex-shrink-0 items-center justify-between border-b border-slate-100 bg-white px-5 py-3">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400">Differential Diagnosis</h2>
      </div>
      <div className="flex flex-1 flex-col gap-2.5 overflow-y-auto p-3">
        {loading ? (
          <div className="flex flex-col gap-3 pt-1">
            {[1, 2].map((n) => (
              <div key={n} className="animate-skeleton rounded-lg border border-slate-200 bg-white p-4 space-y-2">
                <Skeleton className="h-3 w-1/3" />
                <Skeleton className="h-3 w-2/3" />
                <Skeleton className="h-3 w-1/2" />
              </div>
            ))}
          </div>
        ) : sortedDiffs.length === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-1.5 py-10 text-center">
            <div className="mb-1 text-2xl text-slate-200 select-none">🧬</div>
            <p className="text-sm font-medium text-slate-400">No differentials yet</p>
            <p className="text-xs text-slate-300">Appears after 3+ symptoms are detected</p>
          </div>
        ) : (
          sortedDiffs.map((d) => <DifferentialCard key={d.id} diff={d} />)
        )}

        {/* Questions to Ask */}
        {(pendingQuestions.length > 0 || askedQuestions.length > 0) && (
          <div className="mt-1 rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
            <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-2.5">
              <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">Questions to Ask</span>
              {pendingQuestions.length > 0 && (
                <span className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[9px] font-bold text-amber-700">{pendingQuestions.length}</span>
              )}
            </div>
            <div className="flex flex-col divide-y divide-slate-50">
              {pendingQuestions.map((q) => (
                <div key={q.id} className="flex items-start gap-2.5 px-4 py-2.5">
                  <button
                    onClick={() => onDismissQuestion(q.id)}
                    className="mt-0.5 flex h-4 w-4 flex-shrink-0 items-center justify-center rounded border border-slate-300 text-transparent hover:border-emerald-400 hover:bg-emerald-50 hover:text-emerald-500 transition-colors"
                    title="Mark as asked"
                  >
                    <svg className="h-2.5 w-2.5" viewBox="0 0 10 10" fill="none"><path d="M2 5l2 2 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
                  </button>
                  <p className="text-xs leading-relaxed text-slate-700">{q.text}</p>
                </div>
              ))}
              {askedQuestions.map((q) => (
                <div key={q.id} className="flex items-start gap-2.5 px-4 py-2.5 opacity-40">
                  <span className="mt-0.5 flex h-4 w-4 flex-shrink-0 items-center justify-center rounded border border-emerald-400 bg-emerald-50 text-emerald-500">
                    <svg className="h-2.5 w-2.5" viewBox="0 0 10 10" fill="none"><path d="M2 5l2 2 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
                  </span>
                  <p className="text-xs leading-relaxed text-slate-500 line-through">{q.text}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

// ── Right sidebar: entities + alerts stacked ──────────────────────────────────

const ENTITY_STYLE = {
  symptom:   { label: "Symptoms",    dot: "bg-red-400",    tag: "bg-red-50   text-red-700   ring-red-200"   },
  drug:      { label: "Drugs",       dot: "bg-blue-400",   tag: "bg-blue-50  text-blue-700  ring-blue-200"  },
  body_part: { label: "Body Parts",  dot: "bg-green-400",  tag: "bg-green-50 text-green-700 ring-green-200" },
  red_flag:  { label: "Red Flags",   dot: "bg-red-600",    tag: "bg-red-100  text-red-800   ring-red-300"   },
  duration:  { label: "Duration",    dot: "bg-slate-400",  tag: "bg-slate-100 text-slate-600 ring-slate-200"},
};

function EntityTag({ entity, style }) {
  return (
    <span title={entity.detail || undefined} className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${style.tag}`}>
      {entity.text}
    </span>
  );
}

const LAB_FLAG_STYLE = {
  HIGH:     "bg-red-50 text-red-700 ring-red-200",
  LOW:      "bg-amber-50 text-amber-700 ring-amber-200",
  CRITICAL: "bg-red-100 text-red-800 ring-red-300 animate-pulse",
};

function LabsCard({ labs }) {
  if (!labs || labs.length === 0) return null;
  return (
    <div className="flex-shrink-0 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400">Flagged Labs</h2>
        <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-600">{labs.length}</span>
      </div>
      <div className="flex flex-wrap gap-2 p-4">
        {labs.map((l, i) => {
          const style = LAB_FLAG_STYLE[l.flag] ?? LAB_FLAG_STYLE.HIGH;
          return (
            <span key={i} className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${style}`}>
              <span className="font-semibold">{l.test}</span>
              <span className="opacity-70">{l.value}{l.unit ? ` ${l.unit}` : ""}</span>
              <span className="font-bold">{l.flag === "LOW" ? "↓" : "↑"}</span>
            </span>
          );
        })}
      </div>
    </div>
  );
}

function SidebarPanel({ entities, alerts, sessionData, commandResponses, flaggedLabs, loading }) {
  const byCategory = Object.fromEntries(Object.keys(ENTITY_STYLE).map((k) => [k, []]));
  for (const e of entities) {
    if (byCategory[e.category]) byCategory[e.category].push(e);
  }
  const hasEntities = entities.length > 0;

  const cards = buildCards(alerts, sessionData);
  const sortedResponses = [...commandResponses].sort((a, b) => b.timestamp_ms - a.timestamp_ms);
  const totalCount = cards.length;
  const alertsEmpty = totalCount === 0 && sortedResponses.length === 0;

  return (
    <section className="flex flex-col gap-3 overflow-hidden">
      {/* ── Flagged labs ── */}
      <LabsCard labs={flaggedLabs} />

      {/* ── Detected entities ── */}
      <div className="flex-shrink-0 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400">Detected Entities</h2>
          {hasEntities && (
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-400">{entities.length}</span>
          )}
        </div>
        <div className="p-4">
          {loading ? (
            <div className="space-y-3">
              {[1, 2].map((n) => <Skeleton key={n} className="h-3 w-2/3" />)}
            </div>
          ) : !hasEntities ? (
            <p className="text-xs italic text-slate-300">Listening for clinical entities…</p>
          ) : (
            <div className="flex flex-col gap-3">
              {Object.entries(ENTITY_STYLE).map(([key, style]) => {
                const items = byCategory[key];
                if (items.length === 0) return null;
                return (
                  <div key={key}>
                    <div className="mb-1.5 flex items-center gap-1.5">
                      <span className={`h-1.5 w-1.5 flex-shrink-0 rounded-full ${style.dot}`} />
                      <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">{style.label}</span>
                      <span className="text-[10px] text-slate-300">{items.length}</span>
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {items.map((e, i) => <EntityTag key={i} entity={e} style={style} />)}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* ── Alerts ── */}
      <div className="flex flex-1 flex-col overflow-hidden rounded-xl border border-slate-200 bg-slate-50 shadow-sm">
        <div className="flex flex-shrink-0 items-center justify-between border-b border-slate-100 bg-white px-4 py-3">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400">Alerts</h2>
          {totalCount > 0 ? (
            <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-600">{totalCount} active</span>
          ) : (
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-400">0 active</span>
          )}
        </div>
        <div className="flex flex-1 flex-col gap-2 overflow-y-auto p-3">
          {loading ? (
            <div className="flex flex-col gap-3 pt-1">
              {[1, 2].map((n) => (
                <div key={n} className="animate-skeleton rounded-lg border-l-4 border-slate-200 bg-white p-3 space-y-2">
                  <Skeleton className="h-3 w-1/3" />
                  <Skeleton className="h-3 w-2/3" />
                </div>
              ))}
            </div>
          ) : alertsEmpty ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-1 py-6 text-center">
              <div className="mb-1 text-xl text-slate-200 select-none">✓</div>
              <p className="text-xs font-medium text-slate-400">No alerts yet</p>
            </div>
          ) : (
            <>
              {cards.map((c) => (
                <AlertCard key={c.id} style={c.style} badge={c.badge} title={c.title} body={c.body} meta={c.meta} action={c.action} />
              ))}
              {sortedResponses.length > 0 && (
                <>
                  {cards.length > 0 && (
                    <div className="flex items-center gap-2 py-1">
                      <div className="h-px flex-1 bg-slate-200" />
                      <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">Assistant</span>
                      <div className="h-px flex-1 bg-slate-200" />
                    </div>
                  )}
                  {sortedResponses.map((r) => <CommandResponseCard key={r.id} response={r} />)}
                </>
              )}
            </>
          )}
        </div>
      </div>
    </section>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

// ── Transcript bar ────────────────────────────────────────────────────────────

function TranscriptBar({ transcript }) {
  const last = transcript[transcript.length - 1];
  if (!last) return null;
  return (
    <div className="flex-shrink-0 bg-slate-900/30 backdrop-blur-sm px-5 py-2">
      <p className="truncate text-xs italic text-slate-200/80">
        {last.speaker && <span className="not-italic font-medium text-slate-300/60 mr-1.5">{last.speaker}:</span>}
        {last.text}
      </p>
    </div>
  );
}

export default function Session() {
  const { state } = useLocation();
  const patient = state?.patient ?? null;
  const sessionId = state?.sessionId ?? "demo-session";
  const { transcript, alerts, entities, routing, sessionData, commandResponses, differentials, urgency, suggestedQuestions, setSuggestedQuestions, isConnected, reconnecting } = useDoccy(sessionId);
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [activeTab, setActiveTab] = useState("clinical");
  const [elapsed, setElapsed] = useState(0);

  // Start timer when session_start is received
  useEffect(() => {
    if (!sessionData) return;
    const t = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [!!sessionData]);  // eslint-disable-line react-hooks/exhaustive-deps

  const dismissQuestion = useCallback((id) => {
    setSuggestedQuestions((prev) => prev.map((q) => q.id === id ? { ...q, asked: true } : q));
  }, [setSuggestedQuestions]);

  const summaryReady   = !!sessionData?.summary;
  const sessionLoading = !sessionData && isConnected;
  const alertCount     = buildCards(alerts, sessionData).length;

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-slate-100">
      <Header
        patient={patient}
        routing={routing}
        isConnected={isConnected}
        summaryReady={summaryReady}
        onSummary={() => setSummaryOpen(true)}
        urgency={urgency}
        elapsed={elapsed}
        sessionActive={!!sessionData}
      />

      {reconnecting && <ReconnectingBanner />}

      {summaryOpen && (
        <SessionSummary
          summary={sessionData.summary}
          patient={patient}
          onClose={() => setSummaryOpen(false)}
        />
      )}

      {/* Mobile tab bar */}
      <TabBar activeTab={activeTab} onTab={setActiveTab} alertCount={alertCount} />

      {/* Transcript ticker */}
      <TranscriptBar transcript={transcript} />

      {/* Main panels */}
      <main className="flex flex-1 gap-4 overflow-hidden p-3 md:p-4">
        {/* Differentials — full width on mobile, 70% on lg */}
        <div className={`flex-col overflow-hidden ${activeTab === "clinical" ? "flex flex-1" : "hidden"} lg:flex lg:flex-[7]`}>
          <DifferentialsPanel
            differentials={differentials}
            suggestedQuestions={suggestedQuestions}
            onDismissQuestion={dismissQuestion}
            loading={sessionLoading}
          />
        </div>

        {/* Sidebar: entities + alerts — full width on mobile, 30% on lg */}
        <div className={`flex-col overflow-hidden ${activeTab === "alerts" ? "flex flex-1" : "hidden"} lg:flex lg:flex-[3]`}>
          <SidebarPanel
            entities={entities}
            alerts={alerts}
            sessionData={sessionData}
            commandResponses={commandResponses}
            flaggedLabs={sessionData?.flaggedLabs ?? []}
            loading={sessionLoading}
          />
        </div>
      </main>
    </div>
  );
}
