import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";

// Normalize backend patient shape → what the UI expects
function normalizePatient(p) {
  return {
    id: p.id,
    name: p.name,
    age: p.age,
    conditions: p.diagnoses ?? p.conditions ?? [],
    medications: (p.medications ?? []).map((m) =>
      typeof m === "string" ? m : `${m.name} ${m.dose}`
    ),
    allergies: (p.allergies ?? []).map((a) =>
      typeof a === "string" ? a : a.substance
    ),
  };
}

async function fetchPatients() {
  const res = await fetch("http://localhost:8000/patients");
  if (!res.ok) throw new Error(`Failed to fetch patients (${res.status})`);
  const data = await res.json();
  return data.map(normalizePatient);
}

async function startSession(patientId) {
  const res = await fetch(
    `http://localhost:8000/session/start?patient_id=${encodeURIComponent(patientId)}`,
    { method: "POST" }
  );
  if (!res.ok) throw new Error(`Failed to start session (${res.status})`);
  return res.json(); // { session_id, patient_id, state }
}

function ConditionPill({ label }) {
  return (
    <span className="inline-block rounded-full bg-slate-700 px-2 py-0.5 text-xs text-slate-300">
      {label}
    </span>
  );
}

function AllergyBadge({ label }) {
  return (
    <span className="inline-block rounded-full bg-red-900/60 px-2 py-0.5 text-xs text-red-300">
      {label}
    </span>
  );
}

function PatientCard({ patient, onSelect, loading }) {
  return (
    <button
      onClick={() => onSelect(patient)}
      disabled={loading}
      className="group relative w-full rounded-xl border border-slate-700 bg-slate-900 p-5 text-left transition-all duration-150 hover:border-brand-500 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
    >
      {/* Header */}
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <p className="text-base font-semibold text-slate-100 group-hover:text-white">
            {patient.name}
          </p>
          <p className="text-sm text-slate-400">Age {patient.age}</p>
        </div>
        <span className="mt-0.5 flex-shrink-0 rounded-full bg-brand-700/30 px-2.5 py-0.5 text-xs font-medium text-brand-500">
          #{patient.id}
        </span>
      </div>

      {/* Conditions */}
      {patient.conditions?.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1">
          {patient.conditions.map((c) => (
            <ConditionPill key={c} label={c} />
          ))}
        </div>
      )}

      {/* Allergies */}
      {patient.allergies?.length > 0 && (
        <div className="flex flex-wrap gap-1">
          <span className="text-xs text-slate-500">Allergies:</span>
          {patient.allergies.map((a) => (
            <AllergyBadge key={a} label={a} />
          ))}
        </div>
      )}

      {/* Arrow indicator */}
      <div className="absolute right-4 top-1/2 -translate-y-1/2 text-slate-600 transition-colors group-hover:text-brand-500">
        →
      </div>
    </button>
  );
}

export default function PatientSelect() {
  const navigate = useNavigate();
  const [patients, setPatients] = useState([]);
  const [loadingPatients, setLoadingPatients] = useState(true);
  const [fetchError, setFetchError] = useState(null);
  const [startingId, setStartingId] = useState(null);
  const [startError, setStartError] = useState(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoadingPatients(true);
    setFetchError(null);

    fetchPatients()
      .then((data) => {
        if (!cancelled) setPatients(data);
      })
      .catch((err) => {
        if (!cancelled) setFetchError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoadingPatients(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSelect(patient) {
    setStartingId(patient.id);
    setStartError(null);
    try {
      const { session_id } = await startSession(patient.id);
      navigate("/session", { state: { patient, sessionId: session_id } });
    } catch (err) {
      setStartError(err.message);
      setStartingId(null);
    }
  }

  const filtered = patients.filter((p) =>
    p.name.toLowerCase().includes(query.toLowerCase())
  );

  return (
    <div className="min-h-screen bg-slate-950 px-4 py-12">
      <div className="mx-auto max-w-2xl">
        {/* Logo / header */}
        <div className="mb-10 text-center">
          <h1 className="text-3xl font-bold tracking-tight text-white">
            Doccy <span className="text-brand-500">Co-pilot</span>
          </h1>
          <p className="mt-2 text-sm text-slate-400">
            Select a patient to begin the clinical session
          </p>
        </div>

        {/* Search */}
        <div className="relative mb-6">
          <span className="absolute inset-y-0 left-3 flex items-center text-slate-500 select-none pointer-events-none">
            ⌕
          </span>
          <input
            type="text"
            placeholder="Search patients…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-full rounded-lg border border-slate-700 bg-slate-900 py-2.5 pl-9 pr-4 text-sm text-slate-100 placeholder-slate-500 outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
          />
        </div>

        {/* States */}
        {loadingPatients && (
          <div className="flex items-center justify-center gap-2 py-20 text-slate-500">
            <span className="animate-spin">⟳</span>
            <span className="text-sm">Loading patients…</span>
          </div>
        )}

        {fetchError && (
          <div className="rounded-lg border border-red-800 bg-red-950/40 p-4 text-sm text-red-400">
            <span className="font-medium">Failed to load patients:</span> {fetchError}
            <button
              onClick={() => window.location.reload()}
              className="ml-3 underline hover:text-red-300"
            >
              Retry
            </button>
          </div>
        )}

        {startError && (
          <div className="mb-4 rounded-lg border border-amber-800 bg-amber-950/40 p-3 text-sm text-amber-400">
            Could not start session: {startError}
          </div>
        )}

        {!loadingPatients && !fetchError && filtered.length === 0 && (
          <p className="py-20 text-center text-sm text-slate-500">
            {query ? `No patients match "${query}"` : "No patients found."}
          </p>
        )}

        {/* Patient list */}
        <div className="flex flex-col gap-3">
          {filtered.map((patient) => (
            <PatientCard
              key={patient.id}
              patient={patient}
              onSelect={handleSelect}
              loading={startingId === patient.id}
            />
          ))}
        </div>

      </div>
    </div>
  );
}
