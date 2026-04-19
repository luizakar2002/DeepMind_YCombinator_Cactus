import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path

import google.generativeai as genai

logger = logging.getLogger(__name__)

_PROMPT_PATH  = Path(__file__).parent.parent / "prompts" / "differential.txt"
_GEMINI_MODEL = "gemini-2.5-flash"
_client_ready = False

# ── Circuit breaker — backs off when Gemini quota is exhausted ────────────────
_circuit_open_until: float = 0.0   # epoch seconds; 0 = closed (normal)
_BACKOFF_SECONDS = 120             # stay open for 2 min after a 429


def _circuit_is_open() -> bool:
    return time.time() < _circuit_open_until


def _trip_circuit(retry_after_s: float = _BACKOFF_SECONDS):
    global _circuit_open_until
    _circuit_open_until = time.time() + retry_after_s
    logger.warning(
        f"[CLOUD] Circuit breaker OPEN — Gemini quota exhausted. "
        f"Cloud calls suppressed for {retry_after_s:.0f}s."
    )


def _ensure_client():
    global _client_ready
    if not _client_ready:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY environment variable not set")
        genai.configure(api_key=api_key)
        _client_ready = True


def _anonymise_patient_context(patient) -> str:
    """Build clinical context with no PII — name, DOB, and ID are excluded."""
    if not patient:
        return "No patient record loaded."
    meds = ", ".join(f"{m.name} {m.dose}" for m in patient.medications)
    labs = ", ".join(
        f"{l.test} {l.value}{l.unit} [{l.flag}]"
        for l in patient.lab_results if l.flag
    )
    return (
        f"Age: {patient.age}, Sex: {patient.sex}. "
        f"Diagnoses: {', '.join(patient.diagnoses)}. "
        f"Medications: {meds}. "
        f"Allergies: {', '.join(a.substance for a in patient.allergies)}. "
        f"Flagged labs: {labs or 'none'}. "
        f"Chief complaint: {patient.chief_complaint}"
    )


def _build_prompt(session_entities: dict, patient, latest_transcript: str) -> str:
    template = _PROMPT_PATH.read_text()
    return (
        template
        .replace("{patient_context}", _anonymise_patient_context(patient))
        .replace("{session_entities}", json.dumps(session_entities, indent=2))
        .replace("{latest_transcript}", latest_transcript or "(none)")
    )


def _parse_response(raw: str) -> dict:
    from json_repair import repair_json
    clean = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
    match = re.search(r"\{.*\}", clean, re.DOTALL)
    if match:
        clean = match.group(0)
    return json.loads(repair_json(clean))


def _call_gemini_blocking(session_entities: dict, patient, latest_transcript: str) -> dict:
    """Pure blocking call — always run via run_in_executor, never directly."""
    if _circuit_is_open():
        logger.info("[CLOUD] Circuit open — skipping Gemini call.")
        return {"urgency": "routine", "skipped": "quota_backoff"}

    _ensure_client()
    prompt = _build_prompt(session_entities, patient, latest_transcript)
    model = genai.GenerativeModel(_GEMINI_MODEL)
    try:
        response = model.generate_content(prompt)
    except Exception as exc:
        msg = str(exc)
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
            # Parse retry_after from error message if available
            import re as _re
            m = _re.search(r"retry in (\d+(?:\.\d+)?)", msg)
            backoff = float(m.group(1)) + 10 if m else _BACKOFF_SECONDS
            _trip_circuit(backoff)
        raise
    logger.info(f"Gemini raw: {response.text[:300]}")
    return _parse_response(response.text)


_SUMMARY_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "summary.txt"


def _build_summary_prompt(session_entities: dict, patient, alerts: list[dict]) -> str:
    template = _SUMMARY_PROMPT_PATH.read_text()
    alerts_text = (
        "\n".join(f"- [{a.get('level','?').upper()}] {a.get('message','')}" for a in alerts)
        or "None raised."
    )
    return (
        template
        .replace("{patient_context}", _anonymise_patient_context(patient))
        .replace("{session_entities}", json.dumps(session_entities, indent=2))
        .replace("{alerts_summary}", alerts_text)
    )


def _call_summary_blocking(session_entities: dict, patient, alerts: list[dict]) -> dict:
    if _circuit_is_open():
        return {"error": "Gemini quota exhausted — summary unavailable during backoff."}
    _ensure_client()
    prompt = _build_summary_prompt(session_entities, patient, alerts)
    model = genai.GenerativeModel(_GEMINI_MODEL)
    try:
        response = model.generate_content(prompt)
    except Exception as exc:
        msg = str(exc)
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
            _trip_circuit()
        raise
    logger.info(f"Gemini summary raw: {response.text[:300]}")
    return _parse_response(response.text)


async def call_gemini_summary_async(
    session_entities: dict,
    patient,
    alerts: list[dict],
) -> dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, _call_summary_blocking, session_entities, patient, alerts
    )


async def call_gemini_async(
    session_entities: dict,
    patient,
    latest_transcript: str,
) -> dict:
    """Non-blocking wrapper — safe to fire with create_task."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, _call_gemini_blocking, session_entities, patient, latest_transcript
    )
