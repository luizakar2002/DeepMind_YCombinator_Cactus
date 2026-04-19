import ctypes
import json
import logging
import re
import sys
import time
from pathlib import Path
from threading import Lock, RLock

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "cactus" / "python"))
from src.downloads import ensure_model
from src.cactus import (
    _lib, _enc, TokenCallback,          # low-level C bindings for fast PCM path
    cactus_init, cactus_destroy,
    cactus_reset, cactus_log_set_level,
)

# Shared lock — serialises ALL cactus_* calls (inference + ANE VAD) on the
# single model handle.  VAD holds it for ~10-20ms; inference holds it for
# the full decode duration.  Export so audio.py can import it.
model_lock: Lock = Lock()

from pipeline.audio import audio_to_wav_bytes

logger = logging.getLogger(__name__)

MODEL        = "google/gemma-4-E2B-it"
_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "extraction.txt"
_DIFF_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "differential_local.txt"
_MAX_TOKENS  = 120   # tight cap — fewer tokens = faster sequential decode
_DIFF_MAX_TOKENS = 200
_TARGET_PEAK = 0.8   # normalise all audio to this amplitude

_model_handle = None
_model_init_lock = RLock()   # guards _ensure_model against concurrent init


def _build_differential_prompt(patient=None) -> str:
    template = _DIFF_PROMPT_PATH.read_text() if _DIFF_PROMPT_PATH.exists() else (
        'Return ONLY JSON: {"differentials":[],"urgency":"routine"}'
    )
    if patient:
        meds      = ", ".join(f"{m.name} {m.dose}" for m in patient.medications)
        diagnoses = ", ".join(patient.diagnoses)
        allergies = ", ".join(a.substance for a in patient.allergies)
        context   = f"Diagnoses: {diagnoses}. Medications: {meds}. Allergies: {allergies}."
    else:
        context = "No patient record."
    return template.replace("{patient_context}", context)


def _build_system_prompt(patient=None) -> str:
    template = _PROMPT_PATH.read_text() if _PROMPT_PATH.exists() else (
        'Return ONLY JSON: {"transcript":"","symptoms":[],"drugs_mentioned":[],"body_parts":[],"red_flags":[]}'
    )
    if patient:
        meds      = ", ".join(f"{m.name} {m.dose}" for m in patient.medications)
        diagnoses = ", ".join(patient.diagnoses)
        allergies = ", ".join(a.substance for a in patient.allergies)
        context   = f"Diagnoses: {diagnoses}. Medications: {meds}. Allergies: {allergies}."
    else:
        context = "No patient record."
    return template.replace("{patient_context}", context)


def _ensure_model():
    global _model_handle
    if _model_handle is not None:          # fast path — no lock needed
        return _model_handle
    with _model_init_lock:                 # serialise concurrent callers
        if _model_handle is None:          # re-check inside lock
            logger.info(f"Loading Cactus model: {MODEL}")
            weights = ensure_model(MODEL)
            _model_handle = cactus_init(str(weights), None, False)
            cactus_log_set_level(4)
            logger.info("Cactus model ready.")
    return _model_handle


def unload_model():
    global _model_handle
    if _model_handle is not None:
        cactus_destroy(_model_handle)
        _model_handle = None


_EMPTY = {"symptoms": [], "drugs_mentioned": [], "body_parts": [], "red_flags": []}


def _parse_entities(raw: str) -> dict:
    from json_repair import repair_json
    clean = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
    m = re.search(r"\{.*\}", clean, re.DOTALL)
    if m:
        clean = m.group(0)
    try:
        return json.loads(repair_json(clean))
    except Exception:
        logger.warning(f"Could not parse model output: {raw[:120]!r}")
        return dict(_EMPTY)


def merge_entities(accumulated: dict, new: dict) -> dict:
    """Merge a fresh extraction into the running session total, deduplicating."""
    # symptoms — handle both string and object shapes
    seen_syms: set[str] = set()
    for s in accumulated.get("symptoms", []):
        seen_syms.add((s if isinstance(s, str) else s.get("text", "")).lower())
    for s in new.get("symptoms", []):
        text = (s if isinstance(s, str) else s.get("text", "")).lower()
        if text and text not in seen_syms:
            accumulated.setdefault("symptoms", []).append(s)
            seen_syms.add(text)

    # drugs
    seen_drugs = {d.lower() for d in accumulated.get("drugs_mentioned", [])}
    for d in new.get("drugs_mentioned", []):
        if isinstance(d, str) and d and d.lower() not in seen_drugs:
            accumulated.setdefault("drugs_mentioned", []).append(d)
            seen_drugs.add(d.lower())

    # body_parts
    def _part_key(p): return (p if isinstance(p, str) else p.get("text", "")).lower()
    seen_parts = {_part_key(p) for p in accumulated.get("body_parts", [])}
    for p in new.get("body_parts", []):
        k = _part_key(p)
        if k and k not in seen_parts:
            accumulated.setdefault("body_parts", []).append(p)
            seen_parts.add(k)

    # timeline (legacy field — kept for compat)
    if new.get("timeline"):
        accumulated["timeline"] = new["timeline"]

    # red_flags
    seen_flags = {f.lower() for f in accumulated.get("red_flags", [])}
    for f in new.get("red_flags", []):
        if isinstance(f, str) and f and f.lower() not in seen_flags:
            accumulated.setdefault("red_flags", []).append(f)
            seen_flags.add(f.lower())

    return accumulated


# ── Audio preparation ─────────────────────────────────────────────────────────

# Gemma 4's audio encoder uses a fixed 40ms frame duration at 16kHz.
# Any buffer whose length is not a multiple of 640 samples causes the encoder
# to stall on an internal tensor alignment pass before prefill even starts —
# this is the source of the observed 11,000ms spikes on short VAD chunks.
_FRAME_SAMPLES = 640          # 40ms × 16,000Hz = 640 samples per encoder frame
_TARGET_PEAK   = 0.8          # normalise every chunk to this amplitude


def _align_to_frame_boundary(audio: np.ndarray) -> tuple[np.ndarray, int]:
    """
    Pad audio with digital silence so len(audio) is an exact multiple of
    _FRAME_SAMPLES (640).  Returns (padded_audio, samples_added).

    Examples at 16kHz:
      670ms = 10,720 samples → ceil to 10,880 (17 × 640, = 680ms) → +160 samples
      1,340ms = 21,440 → already 21,440 / 640 = 33.5 → ceil to 21,760 (+320)
      1,280ms = 20,480 → 20,480 / 640 = 32.0 → exact, no pad needed
    """
    remainder = len(audio) % _FRAME_SAMPLES
    if remainder == 0:
        return audio, 0
    pad = _FRAME_SAMPLES - remainder
    return np.concatenate([audio, np.zeros(pad, dtype=np.float32)]), pad


def _prepare_audio(audio: np.ndarray) -> tuple[np.ndarray, float, float, int]:
    """
    1. Normalise amplitude to _TARGET_PEAK (both up and down — fixes quiet mic).
    2. Align to the nearest 40ms frame boundary so Gemma 4's audio encoder
       never hits an alignment stall.
    Returns (audio, original_dur_s, original_peak, pad_samples_added).
    """
    peak = float(np.max(np.abs(audio)))
    dur  = len(audio) / 16000

    if peak < 1e-6:
        # Pure silence — still needs alignment so the encoder doesn't stall
        audio, pad = _align_to_frame_boundary(audio)
        return audio, dur, peak, pad

    # Normalise to target peak (boost quiet audio, attenuate hot-mic)
    audio = audio * (_TARGET_PEAK / peak)

    # Align to 40ms boundary
    audio, pad = _align_to_frame_boundary(audio)
    return audio, dur, peak, pad


# ── Fast C-level completion (avoids Python list unpacking) ────────────────────

def _cactus_complete_fast(model, messages_json: str, options_json: str, wav_bytes: bytes) -> str:
    """
    Calls _lib.cactus_complete directly using from_buffer_copy for the PCM
    array — one C memcpy instead of iterating 60,000 Python integers.
    """
    buf     = ctypes.create_string_buffer(65536)
    cb      = TokenCallback()   # no streaming callback
    n       = len(wav_bytes)
    pcm_arr = (ctypes.c_uint8 * n).from_buffer_copy(wav_bytes)
    pcm_ptr = ctypes.cast(pcm_arr, ctypes.POINTER(ctypes.c_uint8))

    rc = _lib.cactus_complete(
        model,
        _enc(messages_json),
        buf, len(buf),
        _enc(options_json),
        None,           # tools_json
        cb, None,       # callback + user_data
        pcm_ptr, n,
    )
    if rc < 0:
        from src.cactus import cactus_get_last_error
        raise RuntimeError(cactus_get_last_error() or "cactus_complete failed")
    return buf.value.decode("utf-8", errors="ignore")


# ── Main extraction function ──────────────────────────────────────────────────

def _run_extraction(audio: np.ndarray, system_prompt: str) -> tuple[str, dict]:
    """Blocking — always run via loop.run_in_executor, never directly."""

    t_total = time.perf_counter()

    # 1. Model handle (cached — effectively free after first call)
    t0 = time.perf_counter()
    model = _ensure_model()
    model_ms = (time.perf_counter() - t0) * 1000

    # 2. Audio normalization + 40ms frame alignment (before acquiring lock)
    t0 = time.perf_counter()
    audio, dur, peak, pad_samples = _prepare_audio(audio)
    prep_ms = (time.perf_counter() - t0) * 1000

    aligned_dur = len(audio) / 16000
    frames      = len(audio) // _FRAME_SAMPLES
    logger.info(
        f"[PREP] {dur*1000:.0f}ms → {aligned_dur*1000:.0f}ms "
        f"(+{pad_samples} samples, {frames} × 40ms frames)  "
        f"peak {peak:.3f} → {_TARGET_PEAK:.1f}"
    )

    # 3. WAV encode — float32 → 16-bit PCM WAV bytes (before lock — pure CPU)
    t0 = time.perf_counter()
    wav_bytes = audio_to_wav_bytes(audio)
    wav_ms = (time.perf_counter() - t0) * 1000

    # 4. Acquire model lock — serialises with ANE VAD calls in audio.py.
    #    Lock is held from reset through end of decode; VAD waits at most
    #    ~20ms before inference starts and ~decode_time while it runs.
    # 5. Build messages + options (matches what speculative prefill used)
    messages = json.dumps([
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": "Extract clinical entities from this audio snippet."},
    ])
    options = json.dumps({
        "max_tokens":  _MAX_TOKENS,
        "no_think":    True,    # suppress chain-of-thought tokens
        "temperature": 0.0,     # greedy decode — deterministic + fastest
    })

    model_lock.acquire()
    try:
        t0 = time.perf_counter()
        cactus_reset(model)
        reset_ms = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        raw_json = _cactus_complete_fast(model, messages, options, wav_bytes)
        infer_ms = (time.perf_counter() - t0) * 1000
    finally:
        model_lock.release()

    # raw_json is the buffer content; cactus wraps it as {"response":"..."}
    try:
        response = json.loads(raw_json).get("response", raw_json)
    except Exception:
        response = raw_json

    # 6. JSON parse
    t0 = time.perf_counter()
    entities = _parse_entities(response)
    parse_ms = (time.perf_counter() - t0) * 1000

    transcript_text = entities.pop("transcript", "") or ""
    total_ms = (time.perf_counter() - t_total) * 1000

    logger.info(
        f"[INFERENCE BREAKDOWN] "
        f"model={model_ms:.0f}ms  reset={reset_ms:.0f}ms  "
        f"prep={prep_ms:.0f}ms  wav={wav_ms:.0f}ms  "
        f"cactus={infer_ms:.0f}ms  parse={parse_ms:.0f}ms  "
        f"TOTAL={total_ms:.0f}ms"
    )
    logger.info(f"[RESPONSE] {response[:200]!r}")

    return transcript_text, entities


# ── On-device text-only differential diagnosis ────────────────────────────────

def _run_differential_text(session_entities: dict, diff_prompt: str) -> dict:
    """
    Blocking text-only differential — run via loop.run_in_executor, never directly.
    Uses the high-level cactus_complete() wrapper with pcm_data=None (no audio).
    Shares model_lock with audio extraction — serializes automatically.
    """
    from src.cactus import cactus_complete as _cactus_complete_hl

    t0    = time.perf_counter()
    model = _ensure_model()

    messages = json.dumps([
        {"role": "system", "content": diff_prompt},
        {"role": "user",   "content": f"Symptoms: {json.dumps(session_entities.get('symptoms', []))}. "
                                      f"Drugs: {json.dumps(session_entities.get('drugs_mentioned', []))}. "
                                      f"Red flags: {json.dumps(session_entities.get('red_flags', []))}. "
                                      "Give differential."},
    ])
    options = json.dumps({
        "max_tokens":  _DIFF_MAX_TOKENS,
        "no_think":    True,
        "temperature": 0.0,
    })

    with model_lock:
        cactus_reset(model)
        raw = _cactus_complete_hl(model, messages, options, None, None, pcm_data=None)

    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.info(f"[LOCAL DIFF] completed in {elapsed_ms:.0f}ms")

    try:
        response = json.loads(raw).get("response", raw)
    except Exception:
        response = raw

    logger.info(f"[LOCAL DIFF] raw response: {response[:200]!r}")

    from json_repair import repair_json
    clean = re.sub(r"```(?:json)?", "", response).replace("```", "").strip()
    m = re.search(r"\{.*\}", clean, re.DOTALL)
    if m:
        clean = m.group(0)
    try:
        return json.loads(repair_json(clean))
    except Exception:
        return {"differentials": [], "urgency": "routine"}
