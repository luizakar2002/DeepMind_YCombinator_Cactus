"""
cactus_router.py
─────────────────────────────────────────────────────────────────────────────
7-Layer Intelligent Routing Module
Routes medical consultation requests between on-device (Cactus/Gemma 4)
and cloud inference based on uncertainty, complexity, and context signals.


do you see the /models/pipeline/7layerrouting.py file and its content. I wrote it separately and tested with ollama, now just forget ollama, and use the 7 layer logic to implement routing pipeline for the backend working with gemma 4 


USAGE (by your co-founder):
─────────────────────────────
    from cactus_router import ConsultationRouter, RoutingContext

    router = ConsultationRouter()

    # On each utterance from the consultation:
    decision = router.route(RoutingContext(
        prompt        = transcribed_text,
        speaker       = "doctor",          # or "patient"
        audio_conf    = 0.91,              # from Cactus VAD
        cactus_conf   = 0.87,              # from Cactus completion confidence field
        logprobs      = [...],             # from Cactus completion logprobs
        turn          = 4,                 # conversation turn index
        ehr_loaded    = True,
    ))

    if decision.use_cloud:
        # call cloud API
    else:
        # use cactus_complete() result already in decision.local_response

WINDOWS DEV MODE (your environment):
─────────────────────────────────────
    router = ConsultationRouter(dev_mode=True)
    # Uses Ollama instead of Cactus. Everything else is identical.
─────────────────────────────────────────────────────────────────────────────
"""

import time
import numpy as np
import requests
from dataclasses import dataclass, field
from enum import Enum
from concurrent.futures import ThreadPoolExecutor
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Tuneable thresholds — adjust these as you gather real consultation data
# ─────────────────────────────────────────────────────────────────────────────

class Thresholds:
    # Layer 1 — static heuristics
    MAX_PROMPT_WORDS        = 80      # hard cap before even trying on-device
    MIN_AUDIO_CONFIDENCE    = 0.60    # below → transcription too noisy

    # Layer 2 — Cactus native confidence (production only)
    MIN_CACTUS_CONFIDENCE   = 0.72    # below → escalate immediately

    # Layer 3 — varentropy math gate
    RISK_LAMBDA             = 2.0     # penalty weight on variance
    RISK_CEILING            = 4.0     # escalate above this
    ENTROPY_CEILING         = 2.8     # escalate above this (raw entropy)

    # Layer 4 — latency gate
    LATENCY_CEILING_MS      = 3000    # on-device too slow → cloud next time

    # Layer 5 — conversation context
    MAX_LOCAL_TURNS         = 30      # KV cache pressure ceiling
    HIGH_RISK_KEYWORDS      = [       # medical red flags → always cloud
        "chest pain", "difficulty breathing", "suicidal",
        "overdose", "unconscious", "severe bleeding",
        "stroke", "heart attack", "anaphylaxis",
    ]

    # Layer 6 — resource gate
    MAX_RAM_MB              = 6000    # if Cactus reports high RAM → cloud


# ─────────────────────────────────────────────────────────────────────────────
# Data types
# ─────────────────────────────────────────────────────────────────────────────

class Destination(Enum):
    ON_DEVICE = "on_device"
    CLOUD     = "cloud"
    SKIP      = "skip"       # silence / empty segment


@dataclass
class RoutingContext:
    """
    Everything the router needs to make a decision.
    Your co-founder populates this after each Cactus transcription.
    """
    prompt:          str
    speaker:         str   = "unknown"    # "doctor" | "patient"
    audio_conf:      float = 1.0          # from cactus_vad confidence
    cactus_conf:     float = 1.0          # from cactus_complete 'confidence' field
    logprobs:        list  = field(default_factory=list)  # from cactus_complete
    ram_usage_mb:    float = 0.0          # from cactus_complete 'ram_usage_mb'
    last_latency_ms: float = 0.0          # latency of previous on-device call
    turn:            int   = 0            # conversation turn index
    ehr_loaded:      bool  = False        # was EHR prefilled into KV cache
    force_cloud:     bool  = False        # manual override


@dataclass
class RoutingDecision:
    """
    What the router returns. Your co-founder reads .use_cloud to branch.
    """
    destination:      Destination
    use_cloud:        bool
    reason:           str            # human-readable explanation
    layer:            int            # which layer made the call (1-7)
    metrics:          dict           # varentropy scores + signals
    latency_ms:       float          # time spent in router itself
    local_response:   str = ""       # populated if on-device inference ran


# ─────────────────────────────────────────────────────────────────────────────
# Varentropy math (Layer 3)
# ─────────────────────────────────────────────────────────────────────────────

def _varentropy(logprobs: list, risk_lambda: float = Thresholds.RISK_LAMBDA) -> dict:
    """
    Core uncertainty math.

    entropy    = average uncertainty across all tokens
    varentropy = variance of that uncertainty — catches oscillation
    risk       = entropy_mean + λ * varentropy
                 (normalized by log(n) so long responses don't auto-escalate)

    Why normalization matters:
      A 50-token response accumulates more raw variance than a 5-token one
      even if the model is equally confident throughout. Dividing by log(n+1)
      makes the score comparable across utterances of different lengths.
    """
    if not logprobs:
        return {"entropy": 0, "varentropy": 0, "risk": 0, "n_tokens": 0}

    lp       = np.array(logprobs, dtype=np.float64)
    probs    = np.exp(lp)
    neg_lp   = -lp

    entropy  = float(-np.sum(probs * lp))
    varentr  = float(np.var(neg_lp))
    ev       = float(np.mean(neg_lp))
    raw_risk = ev + (risk_lambda * varentr)

    # Normalize for response length
    norm_factor = np.log(len(logprobs) + 1)
    risk = raw_risk / norm_factor if norm_factor > 0 else raw_risk

    return {
        "entropy":    round(entropy, 4),
        "varentropy": round(varentr, 4),
        "ev":         round(ev, 4),
        "risk":       round(risk, 4),
        "n_tokens":   len(logprobs),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Dev-mode Ollama backend (Windows)
# ─────────────────────────────────────────────────────────────────────────────

def _ollama_infer(prompt: str, model: str = "gemma3:4b") -> tuple[str, list, float]:
    """
    Windows dev only. Returns (response_text, logprobs, latency_ms).
    In production, your co-founder uses cactus_complete() instead.
    """
    t0 = time.perf_counter()
    resp = requests.post(
        "http://localhost:11434/api/generate",
        json={"model": model, "prompt": prompt, "stream": False, "logprobs": True},
        timeout=60,
    ).json()
    latency_ms = (time.perf_counter() - t0) * 1000

    text     = resp.get("response", "")
    logprobs = [t["logprob"] for t in resp.get("logprobs", [])]
    return text, logprobs, latency_ms


# ─────────────────────────────────────────────────────────────────────────────
# The 7-layer router
# ─────────────────────────────────────────────────────────────────────────────

class ConsultationRouter:
    """
    7-layer routing engine for medical consultation inference.

    Layer 1 — Static heuristics      (no model call, <1ms)
    Layer 2 — Cactus confidence gate  (production: native signal; dev: skipped)
    Layer 3 — Varentropy math gate    (runs on logprobs from inference)
    Layer 4 — Latency gate            (is on-device fast enough?)
    Layer 5 — Conversation context    (turn depth, red flags, EHR state)
    Layer 6 — Resource gate           (RAM, thermal pressure)
    Layer 7 — Cloud fallback          (final destination if escalated)
    """

    def __init__(
        self,
        dev_mode:    bool  = False,         # True = use Ollama on Windows
        ollama_model: str  = "gemma3:4b",
        risk_lambda: float = Thresholds.RISK_LAMBDA,
        verbose:     bool  = True,
    ):
        self.dev_mode     = dev_mode
        self.ollama_model = ollama_model
        self.risk_lambda  = risk_lambda
        self.verbose      = verbose
        self.executor     = ThreadPoolExecutor(max_workers=2)
        self._history: list[RoutingDecision] = []

        mode = "DEV (Ollama)" if dev_mode else "PRODUCTION (Cactus)"
        self._log(f"ConsultationRouter ready | mode={mode} | λ={risk_lambda}")

    # ── public interface ──────────────────────────────────────────────────────

    def route(self, ctx: RoutingContext) -> RoutingDecision:
        """
        Main entry point. Call this on every transcribed utterance.
        Returns a RoutingDecision — check .use_cloud to branch.
        """
        t_start = time.perf_counter()
        self._log(f"\n{'─'*60}")
        self._log(f"[{ctx.speaker.upper()}] \"{ctx.prompt[:70]}\"")

        decision = self._run_layers(ctx, t_start)
        self._history.append(decision)

        self._log(f"→ {decision.destination.value.upper()} "
                  f"(layer {decision.layer}) | {decision.reason} "
                  f"| router: {decision.latency_ms:.1f}ms")
        return decision

    def summary(self) -> dict:
        """Returns routing stats for the current session."""
        total     = len(self._history)
        on_device = sum(1 for d in self._history if d.destination == Destination.ON_DEVICE)
        cloud     = sum(1 for d in self._history if d.destination == Destination.CLOUD)
        skipped   = sum(1 for d in self._history if d.destination == Destination.SKIP)
        return {
            "total": total, "on_device": on_device,
            "cloud": cloud, "skipped": skipped,
            "cloud_rate": round(cloud / max(total, 1), 2),
        }

    # ── layers ────────────────────────────────────────────────────────────────

    def _run_layers(self, ctx: RoutingContext, t_start: float) -> RoutingDecision:

        def decision(dest, reason, layer, metrics=None, response=""):
            return RoutingDecision(
                destination=dest,
                use_cloud=(dest == Destination.CLOUD),
                reason=reason,
                layer=layer,
                metrics=metrics or {},
                latency_ms=round((time.perf_counter() - t_start) * 1000, 2),
                local_response=response,
            )

        # ── Layer 1: Static heuristics ────────────────────────────────────────
        # Fast, free, no model call. Catches obvious cases immediately.
        self._log("[L1] Static heuristics...")

        if not ctx.prompt.strip():
            return decision(Destination.SKIP, "empty segment (VAD silence)", 1)

        if ctx.force_cloud:
            return decision(Destination.CLOUD, "manual override", 1)

        if ctx.audio_conf < Thresholds.MIN_AUDIO_CONFIDENCE:
            return decision(Destination.CLOUD,
                f"audio confidence {ctx.audio_conf:.2f} too low", 1)

        word_count = len(ctx.prompt.split())
        if word_count > Thresholds.MAX_PROMPT_WORDS:
            return decision(Destination.CLOUD,
                f"prompt too long ({word_count} words)", 1)

        # ── Layer 2: Cactus native confidence ─────────────────────────────────
        # Production: Cactus returns a 'confidence' float with every completion.
        # Dev mode: skipped (Ollama doesn't have this field).
        self._log("[L2] Cactus confidence gate...")

        if not self.dev_mode and ctx.cactus_conf < Thresholds.MIN_CACTUS_CONFIDENCE:
            return decision(Destination.CLOUD,
                f"Cactus confidence {ctx.cactus_conf:.2f} below threshold", 2)

        # ── Layer 3: Varentropy math gate ─────────────────────────────────────
        # Run inference (dev: Ollama, prod: already ran via Cactus).
        # Analyze logprobs for uncertainty and oscillation.
        self._log("[L3] Varentropy math gate...")

        if self.dev_mode:
            # Dev: run Ollama here to get logprobs
            try:
                local_response, logprobs, infer_ms = _ollama_infer(
                    ctx.prompt, self.ollama_model
                )
                self._log(f"     Ollama: {infer_ms:.0f}ms | {len(logprobs)} tokens")
            except requests.exceptions.ConnectionError:
                return decision(Destination.CLOUD, "Ollama unavailable", 3)
        else:
            # Production: logprobs already provided by co-founder from cactus_complete()
            local_response = ""
            logprobs       = ctx.logprobs
            infer_ms       = ctx.last_latency_ms

        # Compute varentropy in parallel (non-blocking for the main thread)
        future  = self.executor.submit(_varentropy, logprobs, self.risk_lambda)
        metrics = future.result()
        self._log(f"     entropy={metrics['entropy']} | "
                  f"varentropy={metrics['varentropy']} | "
                  f"risk={metrics['risk']} | tokens={metrics['n_tokens']}")

        if metrics["risk"] > Thresholds.RISK_CEILING:
            return decision(Destination.CLOUD,
                f"risk {metrics['risk']} > {Thresholds.RISK_CEILING}", 3, metrics)

        if metrics["entropy"] > Thresholds.ENTROPY_CEILING:
            return decision(Destination.CLOUD,
                f"entropy {metrics['entropy']} > {Thresholds.ENTROPY_CEILING}", 3, metrics)

        # ── Layer 4: Latency gate ─────────────────────────────────────────────
        # If the previous on-device call was too slow, route next one to cloud.
        # Prevents the doctor from waiting mid-consultation.
        self._log("[L4] Latency gate...")

        if infer_ms > Thresholds.LATENCY_CEILING_MS:
            return decision(Destination.CLOUD,
                f"on-device latency {infer_ms:.0f}ms too high", 4, metrics)

        # ── Layer 5: Conversation context ─────────────────────────────────────
        # Medical red flags always go to cloud regardless of confidence.
        # Deep conversations pressure the KV cache.
        self._log("[L5] Conversation context...")

        prompt_lower = ctx.prompt.lower()
        for flag in Thresholds.HIGH_RISK_KEYWORDS:
            if flag in prompt_lower:
                return decision(Destination.CLOUD,
                    f"medical red flag: '{flag}'", 5, metrics)

        if ctx.turn > Thresholds.MAX_LOCAL_TURNS:
            return decision(Destination.CLOUD,
                f"turn {ctx.turn} exceeds KV cache limit", 5, metrics)

        if not ctx.ehr_loaded and ctx.turn > 5:
            # EHR not loaded but conversation is getting deep — cloud has more context
            return decision(Destination.CLOUD,
                "EHR not loaded and conversation is deep", 5, metrics)

        # ── Layer 6: Resource gate ────────────────────────────────────────────
        # Cactus reports RAM usage per completion. If device is under pressure,
        # route to cloud before it crashes or throttles.
        self._log("[L6] Resource gate...")

        if ctx.ram_usage_mb > Thresholds.MAX_RAM_MB:
            return decision(Destination.CLOUD,
                f"RAM {ctx.ram_usage_mb:.0f}MB exceeds ceiling", 6, metrics)

        # ── Layer 7: On-device confirmed ──────────────────────────────────────
        # All gates passed. Stay on-device.
        self._log("[L7] All gates passed → on-device ✓")
        return decision(
            Destination.ON_DEVICE,
            "all layers passed",
            7, metrics,
            response=local_response,
        )

    def _log(self, msg: str):
        if self.verbose:
            print(msg)


# ─────────────────────────────────────────────────────────────────────────────
# Test — runs on Windows with Ollama
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    router = ConsultationRouter(dev_mode=True, verbose=True)

    test_cases = [
        RoutingContext("", speaker="doctor"),                              # L1: empty
        RoutingContext("What brings you in today?",                        # L7: on-device
                       speaker="doctor", audio_conf=0.95, turn=1, ehr_loaded=True),
        RoutingContext("I have chest pain and difficulty breathing",        # L5: red flag
                       speaker="patient", audio_conf=0.90, turn=2, ehr_loaded=True),
        RoutingContext("My knee hurts a little",                            # L7: on-device
                       speaker="patient", audio_conf=0.88, turn=3, ehr_loaded=True),
        RoutingContext("Tell me everything",                                 # L1: low audio
                       speaker="patient", audio_conf=0.30, turn=4),
        RoutingContext("What is 2+2?",                                      # L7: on-device
                       speaker="doctor", audio_conf=0.99, turn=5, ehr_loaded=True),
    ]

    for ctx in test_cases:
        result = router.route(ctx)
        print(f"   RESULT: {result.destination.value} | layer={result.layer} "
              f"| {result.reason}\n")

    print("\n" + "="*60)
    print("SESSION SUMMARY:", router.summary())