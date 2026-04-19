import { useState, useEffect, useRef, useCallback } from "react";

const MOCK_MODE = false;
const WS_URL = "ws://localhost:8000/ws";

// ── Mock event sequences ──────────────────────────────────────────────────────

const MOCK_EVENTS = [
  {
    delay: 300,
    event: {
      type: "session_start",
      patient_name: "Jane Doe",
      age: 54,
      conditions: ["Type 2 Diabetes", "Hypertension"],
      medications: ["Metformin 1000mg", "Lisinopril 10mg"],
      allergies: ["Penicillin"],
    },
  },
  {
    delay: 1200,
    event: {
      type: "transcript",
      speaker: "doctor",
      text: "Good morning Jane. What brings you in today?",
      timestamp_ms: Date.now(),
    },
  },
  {
    delay: 2500,
    event: {
      type: "transcript",
      speaker: "patient",
      text: "I've been having chest pain and shortness of breath for the past two days.",
      timestamp_ms: Date.now() + 1300,
    },
  },
  {
    delay: 3000,
    event: {
      type: "entity",
      category: "symptom",
      text: "chest pain",
      detail: "onset 2 days ago",
      timestamp_ms: Date.now() + 1800,
    },
  },
  {
    delay: 3200,
    event: {
      type: "entity",
      category: "symptom",
      text: "shortness of breath",
      detail: "onset 2 days ago",
      timestamp_ms: Date.now() + 2000,
    },
  },
  {
    delay: 3500,
    event: {
      type: "entity",
      category: "duration",
      text: "two days",
      detail: "symptom duration",
      timestamp_ms: Date.now() + 2300,
    },
  },
  {
    delay: 4000,
    event: {
      type: "routing",
      status: "cloud",
      reason: "Complex cardiac presentation detected",
      confidence_score: 0.87,
    },
  },
  {
    delay: 4500,
    event: {
      type: "alert",
      id: "alert-001",
      level: "warning",
      title: "Cardiac Symptom Cluster",
      body: "Patient reports chest pain + dyspnea with history of hypertension. Consider ECG.",
      source: "cloud",
      suggested_action: "Order 12-lead ECG immediately",
      timestamp_ms: Date.now() + 3300,
    },
  },
  {
    delay: 5500,
    event: {
      type: "drug_interaction",
      id: "ddi-001",
      drug_mentioned: "Ibuprofen",
      interacts_with: "Lisinopril",
      severity: "moderate",
      detail:
        "NSAIDs can reduce the antihypertensive effect of ACE inhibitors and may impair renal function.",
      timestamp_ms: Date.now() + 4300,
    },
  },
  {
    delay: 6500,
    event: {
      type: "contradiction",
      id: "con-001",
      field: "allergies",
      patient_stated: "No known drug allergies",
      ehr_value: "Penicillin allergy on file",
      title: "Allergy Discrepancy",
      body: "Patient denies allergies but EHR records Penicillin allergy.",
      timestamp_ms: Date.now() + 5300,
    },
  },
  {
    delay: 9000,
    event: {
      type: "alert",
      id: "alert-002",
      level: "critical",
      title: "Possible ACS",
      body: "Symptom profile consistent with Acute Coronary Syndrome. Immediate evaluation required.",
      source: "cloud",
      suggested_action: "Activate cardiac protocol",
      timestamp_ms: Date.now() + 7800,
    },
  },
  {
    delay: 7500,
    event: {
      type: "command_response",
      id: "cmd-001",
      query: "What's the typical first-line workup for chest pain with dyspnea?",
      response:
        "For chest pain with dyspnea, the standard first-line workup includes a 12-lead ECG (within 10 min of arrival), troponin I or T at 0h and 3h, chest X-ray, oxygen saturation, and basic metabolic panel. If PE is suspected, add D-dimer. Risk-stratify using HEART score or TIMI.",
      source: "cloud",
      timestamp_ms: Date.now() + 6300,
    },
  },
  {
    delay: 10500,
    event: {
      type: "command_response",
      id: "cmd-002",
      query: "Is Metformin safe to continue if ACS is confirmed?",
      response:
        "Metformin should be held if ACS is confirmed and the patient is haemodynamically unstable, requires contrast imaging, or has deteriorating renal function. It can generally be resumed 48h after contrast exposure once creatinine is stable. Insulin is the preferred agent for in-hospital glucose control in ACS.",
      source: "local",
      timestamp_ms: Date.now() + 9100,
    },
  },
  {
    delay: 12000,
    event: {
      type: "session_summary",
      differentials: [
        {
          diagnosis: "Unstable Angina / NSTEMI",
          probability: 0.62,
          reasoning: "Chest pain, dyspnea, hypertension, age > 50",
        },
        {
          diagnosis: "Pulmonary Embolism",
          probability: 0.18,
          reasoning: "Dyspnea and chest pain without clear cardiac cause",
        },
        {
          diagnosis: "Musculoskeletal chest pain",
          probability: 0.1,
          reasoning: "Possible if reproducible on palpation",
        },
      ],
      suggested_labs: ["Troponin I/T", "BNP", "CBC", "BMP", "D-dimer"],
      suggested_imaging: ["12-lead ECG", "Chest X-ray", "Echo if troponin elevated"],
      key_findings: [
        "Chest pain x2 days",
        "Shortness of breath",
        "Known hypertension",
        "Allergy documentation discrepancy",
        "Potential NSAID + ACE inhibitor interaction",
      ],
      soap_note: {
        subjective:
          "54yo F with HTN and T2DM presenting with 2-day history of chest pain and shortness of breath.",
        objective: "Vitals pending. Allergy discrepancy noted.",
        assessment: "Rule out ACS. Differential includes PE, MSK pain.",
        plan: "ECG, troponin, chest X-ray. Clarify allergy history. Avoid NSAIDs.",
      },
    },
  },
];

// ── State shape helpers ───────────────────────────────────────────────────────

function applyEvent(event, setters) {
  const { setAlerts, setEntities, setTranscript, setRouting, setSessionData, setCommandResponses, setDifferentials, setUrgency, setSuggestedQuestions } = setters;

  switch (event.type) {
    case "session_start":
      setSessionData({
        patientName: event.patient_name,
        age: event.age,
        conditions: event.conditions ?? [],
        medications: event.medications ?? [],
        allergies: event.allergies ?? [],
        flaggedLabs: event.flagged_labs ?? [],
        summary: null,
        contradictions: [],
        drugInteractions: [],
      });
      break;

    case "transcript":
      setTranscript((prev) => [
        ...prev,
        { speaker: event.speaker, text: event.text, timestamp_ms: event.timestamp_ms },
      ]);
      break;

    case "entity":
      setEntities((prev) => [
        ...prev,
        {
          category: event.category,
          text: event.text,
          detail: event.detail,
          timestamp_ms: event.timestamp_ms,
        },
      ]);
      break;

    // Backend batch entity events — flatten dict into individual entity items
    case "entities":
    case "session_entities": {
      const data = event.data ?? {};
      const ts = event.timestamp_ms ?? Date.now();
      const incoming = [];

      // symptoms are objects {text, duration, severity}
      for (const item of (data.symptoms ?? [])) {
        const text = typeof item === "string" ? item : item?.text;
        if (!text) continue;
        const detail = [item?.duration, item?.severity].filter(Boolean).join(", ") || null;
        incoming.push({ category: "symptom", text, detail, timestamp_ms: ts });
      }

      // drugs_mentioned, body_parts, red_flags are plain strings
      for (const item of (data.drugs_mentioned ?? [])) {
        if (typeof item === "string" && item) incoming.push({ category: "drug", text: item, detail: null, timestamp_ms: ts });
      }
      for (const item of (data.body_parts ?? [])) {
        const text = typeof item === "string" ? item : item?.text;
        if (text) incoming.push({ category: "body_part", text, detail: null, timestamp_ms: ts });
      }
      for (const item of (data.red_flags ?? [])) {
        if (typeof item === "string" && item) incoming.push({ category: "red_flag", text: item, detail: null, timestamp_ms: ts });
      }
      if (data.timeline) {
        incoming.push({ category: "duration", text: data.timeline, detail: null, timestamp_ms: ts });
      }

      if (event.type === "session_entities") {
        setEntities(incoming);
      } else {
        setEntities((prev) => {
          const existing = new Set(prev.map((e) => `${e.category}:${e.text}`));
          return [...prev, ...incoming.filter((e) => !existing.has(`${e.category}:${e.text}`))];
        });
      }
      break;
    }

    case "routing":
      setRouting({ status: event.status, reason: event.reason, confidenceScore: event.confidence_score });
      break;

    case "alert":
      // Cloud differentials arrive as alert events with source="cloud" and body=JSON string.
      // Route them to the differentials panel instead of the generic alerts list.
      if (event.source === "cloud" && event.title === "Cloud Differential") {
        let items = [];
        try { items = JSON.parse(event.body); } catch (_) {}
        if (Array.isArray(items) && items.length > 0) {
          const urgency = event.level ?? "routine";
          const question = event.suggested_question ?? null;
          setUrgency(urgency);
          setDifferentials([{
            id: event.id ?? `cloud-${Date.now()}`,
            source: "cloud",
            urgency,
            reason: event.escalation_reason,
            differentials: items,
            suggestedQuestion: question,
            timestamp: Date.now(),
          }]);
          if (question) {
            setSuggestedQuestions((prev) =>
              prev.some((q) => q.text === question)
                ? prev
                : [...prev, { id: `q-${Date.now()}`, text: question, asked: false }]
            );
          }
        }
        break;
      }
      setAlerts((prev) => {
        const exists = prev.some((a) => a.id === event.id);
        if (exists) return prev;
        return [
          ...prev,
          {
            id: event.id,
            level: event.level,
            title: event.title,
            body: event.body,
            source: event.source,
            suggestedAction: event.suggested_action,
            timestamp_ms: event.timestamp_ms,
          },
        ];
      });
      break;

    case "local_differential": {
      const urgency = event.level ?? event.data?.urgency ?? "routine";
      const question = event.data?.suggested_question ?? null;
      setUrgency(urgency);
      setDifferentials([{
        id: `local-${Date.now()}`,
        source: "on_device",
        urgency,
        reason: null,
        differentials: event.data?.differentials ?? [],
        suggestedQuestion: question,
        timestamp: Date.now(),
      }]);
      if (question) {
        setSuggestedQuestions((prev) =>
          prev.some((q) => q.text === question)
            ? prev
            : [...prev, { id: `q-${Date.now()}`, text: question, asked: false }]
        );
      }
      break;
    }

    case "contradiction":
      setSessionData((prev) =>
        prev
          ? {
              ...prev,
              contradictions: [
                ...(prev.contradictions ?? []),
                {
                  id: event.id ?? `contra-${Date.now()}`,
                  type: event.type,
                  level: event.level,
                  message: event.message,
                  detail: event.detail,
                  timestamp_ms: event.timestamp_ms ?? Date.now(),
                },
              ],
            }
          : prev
      );
      break;

    case "drug_interaction":
      setSessionData((prev) =>
        prev
          ? {
              ...prev,
              drugInteractions: [
                ...(prev.drugInteractions ?? []),
                {
                  id: event.id ?? `ddi-${Date.now()}`,
                  level: event.level,
                  message: event.message,
                  detail: event.detail,
                  timestamp_ms: event.timestamp_ms ?? Date.now(),
                },
              ],
            }
          : prev
      );
      break;

    case "session_summary":
      setSessionData((prev) =>
        prev
          ? {
              ...prev,
              summary: {
                differentials: event.differentials,
                suggestedLabs: event.suggested_labs,
                suggestedImaging: event.suggested_imaging,
                keyFindings: event.key_findings,
                soapNote: event.soap_note,
              },
            }
          : prev
      );
      break;

    case "command_response":
      setCommandResponses((prev) => {
        const exists = prev.some((r) => r.id === event.id);
        if (exists) return prev;
        return [
          ...prev,
          {
            id: event.id,
            query: event.query,
            response: event.response,
            source: event.source,
            timestamp_ms: event.timestamp_ms,
          },
        ];
      });
      break;

    case "ping":
    case "stats":
      break; // handled externally if needed — no-op here

    default:
      console.warn("[useDoccy] Unknown event type:", event.type);
  }
}

// ── Hook ─────────────────────────────────────────────────────────────────────

export function useDoccy(sessionId = "demo-session") {
  const [alerts, setAlerts] = useState([]);
  const [entities, setEntities] = useState([]);
  const [transcript, setTranscript] = useState([]);
  const [routing, setRouting] = useState(null);
  const [sessionData, setSessionData] = useState(null);
  const [commandResponses, setCommandResponses] = useState([]);
  const [differentials, setDifferentials] = useState([]);
  const [urgency, setUrgency] = useState("routine");
  const [suggestedQuestions, setSuggestedQuestions] = useState([]);
  const [isConnected, setIsConnected] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);

  const wsRef = useRef(null);
  const timersRef = useRef([]);

  const setters = { setAlerts, setEntities, setTranscript, setRouting, setSessionData, setCommandResponses, setDifferentials, setUrgency, setSuggestedQuestions };

  const dispatch = useCallback(
    (event) => applyEvent(event, setters),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  // ── Mock mode ───────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!MOCK_MODE) return;

    setIsConnected(true);

    MOCK_EVENTS.forEach(({ delay, event }) => {
      const id = setTimeout(() => dispatch(event), delay);
      timersRef.current.push(id);
    });

    return () => {
      timersRef.current.forEach(clearTimeout);
      timersRef.current = [];
      setIsConnected(false);
    };
  }, [dispatch]);

  // ── Live WebSocket mode ─────────────────────────────────────────────────────
  useEffect(() => {
    if (MOCK_MODE) return;

    let active = true;
    let ws;
    let reconnectTimer;
    let attempt = 0;

    function scheduleReconnect() {
      // Exponential backoff: 1s → 2s → 4s → 8s → cap at 15s
      const delay = Math.min(1000 * 2 ** attempt, 15000);
      attempt += 1;
      reconnectTimer = setTimeout(connect, delay);
    }

    function connect() {
      if (!active) return;

      // Don't open a second socket if one is already connecting/open
      if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) {
        return;
      }

      try {
        ws = new WebSocket(WS_URL);
      } catch (err) {
        console.error("[useDoccy] WebSocket constructor failed:", err);
        if (active) scheduleReconnect();
        return;
      }

      wsRef.current = ws;

      ws.onopen = () => {
        if (!active) { ws.close(); return; }
        attempt = 0; // reset backoff on successful connect
        setIsConnected(true);
        setReconnecting(false);
      };

      ws.onmessage = (msg) => {
        if (!active) return;
        try {
          const raw = JSON.parse(msg.data);
          // Prefer raw.event (explicit WS event name) over raw.type (internal backend field
          // that leaks through **dict spreads and would override the intended event route).
          const event = { ...raw, type: raw.event ?? raw.type };
          dispatch(event);
        } catch (err) {
          console.error("[useDoccy] Failed to parse message:", err);
        }
      };

      ws.onclose = (ev) => {
        if (!active) return;
        setIsConnected(false);
        setReconnecting(true);
        // 1000 = normal close (e.g. server restart after /session/end) — still reconnect
        console.info(`[useDoccy] WS closed (code ${ev.code}), reconnecting in ${Math.min(1000 * 2 ** attempt, 15000)}ms`);
        scheduleReconnect();
      };

      ws.onerror = () => {
        // onerror is always followed by onclose — let onclose drive reconnect
        if (ws.readyState !== WebSocket.CLOSED) ws.close();
      };
    }

    connect();

    return () => {
      active = false;
      clearTimeout(reconnectTimer);
      if (ws) {
        ws.onclose = null; // prevent reconnect loop during cleanup
        ws.onerror = null;
        ws.close();
      }
    };
  }, [dispatch, sessionId]);

  return { alerts, entities, transcript, routing, sessionData, commandResponses, differentials, urgency, suggestedQuestions, setSuggestedQuestions, isConnected, reconnecting };
}
