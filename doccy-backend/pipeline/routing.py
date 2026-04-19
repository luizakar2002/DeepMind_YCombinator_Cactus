"""
7-Layer Intelligent Routing — Cactus/Gemma 4 production version.

Adapted from 7layerrouting.py with Ollama dev-mode removed.
All inference signals come from the live Cactus pipeline.

Layer 1 — Static heuristics      (prompt length, force flags)
Layer 2 — Heuristic confidence    (entity richness proxy for cactus_conf)
Layer 3 — Varentropy math gate    (synthetic logprobs from confidence score)
Layer 4 — Conversation context    (red flags, turn depth, EHR state)
Layer 5 — Resource gate           (RAM — skipped until cactus exposes it)
Layer 6 — On-device confirmed
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

logger = logging.getLogger(__name__)


# ── Tuneable thresholds ───────────────────────────────────────────────────────

class Thresholds:
    # Layer 1
    MAX_PROMPT_WORDS      = 80
    # Layer 2 — confidence derived from entity heuristic (0-1)
    MIN_CACTUS_CONF       = 0.72
    # Layer 3 — varentropy (computed from synthetic logprob proxy)
    RISK_LAMBDA           = 2.0
    RISK_CEILING          = 4.0
    ENTROPY_CEILING       = 2.8
    # Layer 4 — context
    MAX_LOCAL_TURNS       = 30
    HIGH_RISK_KEYWORDS    = [
        "chest pain", "difficulty breathing", "suicidal",
        "overdose", "unconscious", "severe bleeding",
        "stroke", "heart attack", "anaphylaxis",
    ]
    # Layer 6 — resource (RAM not yet exposed by cactus_complete)
    MAX_RAM_MB            = 6000


# ── Data types ────────────────────────────────────────────────────────────────

class Destination(Enum):
    ON_DEVICE = "on_device"
    CLOUD     = "cloud"
    SKIP      = "skip"


@dataclass
class RoutingContext:
    prompt:       str
    entities:     dict
    chunk_index:  int  = 0
    ehr_loaded:   bool = True
    force_cloud:  bool = False


@dataclass
class RoutingDecision:
    destination:  Destination
    use_cloud:    bool
    reason:       str
    layer:        int
    metrics:      dict = field(default_factory=dict)


# ── Varentropy math (Layer 3) ─────────────────────────────────────────────────

def _varentropy(logprobs: list, risk_lambda: float = Thresholds.RISK_LAMBDA) -> dict:
    """
    entropy    = average uncertainty across tokens
    varentropy = variance of per-token uncertainty (catches oscillation)
    risk       = entropy_mean + λ × varentropy, normalised by log(n+1)
    """
    if not logprobs:
        return {"entropy": 0.0, "varentropy": 0.0, "risk": 0.0, "n_tokens": 0}

    lp      = np.array(logprobs, dtype=np.float64)
    probs   = np.exp(lp)
    neg_lp  = -lp

    entropy  = float(-np.sum(probs * lp))
    varentr  = float(np.var(neg_lp))
    ev       = float(np.mean(neg_lp))
    raw_risk = ev + risk_lambda * varentr

    norm   = float(np.log(len(logprobs) + 1))
    risk   = raw_risk / norm if norm > 0 else raw_risk

    return {
        "entropy":    round(entropy, 4),
        "varentropy": round(varentr, 4),
        "risk":       round(risk, 4),
        "n_tokens":   len(logprobs),
    }


def _confidence_score(entities: dict) -> float:
    """
    Heuristic 0-1 confidence derived from Gemma 4 entity extraction richness.
    Substitutes for the native cactus_conf field (not yet exposed by the C API).
    """
    score    = 1.0
    symptoms = entities.get("symptoms", [])

    if not symptoms:
        score -= 0.4

    for s in symptoms:
        if not isinstance(s, dict):
            score -= 0.1
            continue
        text = s.get("text", "")
        if len(text.split()) == 1 and text.lower() in {"feeling", "pain", "hurt", "bad", "sick"}:
            score -= 0.2
        if s.get("duration") is None:
            score -= 0.05
        if s.get("severity") is None:
            score -= 0.05

    if entities.get("drugs_mentioned"):
        score += 0.05
    if entities.get("timeline"):
        score += 0.05

    return max(0.0, min(1.0, score))


def _synthetic_logprobs(confidence: float, n_tokens: int = 12) -> list[float]:
    """
    Converts a scalar confidence into a list of synthetic log-probabilities
    so the varentropy formula has something to work with.

    High confidence → logprobs clustered near 0 (certain).
    Low confidence  → logprobs spread out and more negative (uncertain).
    """
    mean_lp  = float(np.log(max(confidence, 1e-5)))
    variance = (1.0 - confidence) * 0.5
    rng      = np.random.default_rng(seed=42)
    return list(rng.normal(mean_lp, max(variance, 1e-4), n_tokens))


# ── 7-layer router ────────────────────────────────────────────────────────────

class ConsultationRouter:

    def __init__(self, risk_lambda: float = Thresholds.RISK_LAMBDA):
        self.risk_lambda = risk_lambda
        self._history: list[RoutingDecision] = []

    def route(self, ctx: RoutingContext) -> RoutingDecision:
        t_start = time.perf_counter()
        decision = self._run_layers(ctx)
        self._history.append(decision)
        elapsed = (time.perf_counter() - t_start) * 1000
        logger.info(
            f"[ROUTING] L{decision.layer} → {decision.destination.value.upper()} "
            f"| {decision.reason} | router={elapsed:.1f}ms"
        )
        return decision

    def summary(self) -> dict:
        total     = len(self._history)
        on_device = sum(1 for d in self._history if d.destination == Destination.ON_DEVICE)
        cloud     = sum(1 for d in self._history if d.destination == Destination.CLOUD)
        skipped   = sum(1 for d in self._history if d.destination == Destination.SKIP)
        return {
            "total": total, "on_device": on_device,
            "cloud": cloud, "skipped": skipped,
            "cloud_rate": round(cloud / max(total, 1), 2),
        }

    def _run_layers(self, ctx: RoutingContext) -> RoutingDecision:

        def _decide(dest, reason, layer, metrics=None):
            return RoutingDecision(
                destination=dest,
                use_cloud=(dest == Destination.CLOUD),
                reason=reason,
                layer=layer,
                metrics=metrics or {},
            )

        # ── Layer 1: Static heuristics ────────────────────────────────────────
        prompt = ctx.prompt.strip()

        if not prompt:
            return _decide(Destination.SKIP, "empty_segment", 1)

        if ctx.force_cloud:
            return _decide(Destination.CLOUD, "manual_override", 1)

        word_count = len(prompt.split())
        if word_count > Thresholds.MAX_PROMPT_WORDS:
            return _decide(Destination.CLOUD, f"prompt_too_long({word_count}_words)", 1)

        # ── Layer 2: Heuristic confidence gate ────────────────────────────────
        conf = _confidence_score(ctx.entities)
        if conf < Thresholds.MIN_CACTUS_CONF:
            return _decide(Destination.CLOUD, f"low_confidence({conf:.2f})", 2)

        # ── Layer 3: Varentropy math gate ─────────────────────────────────────
        logprobs = _synthetic_logprobs(conf)
        metrics  = _varentropy(logprobs, self.risk_lambda)

        if metrics["risk"] > Thresholds.RISK_CEILING:
            return _decide(Destination.CLOUD,
                f"varentropy_risk({metrics['risk']:.2f})", 3, metrics)

        if metrics["entropy"] > Thresholds.ENTROPY_CEILING:
            return _decide(Destination.CLOUD,
                f"varentropy_entropy({metrics['entropy']:.2f})", 3, metrics)

        # ── Layer 4: Conversation context ─────────────────────────────────────
        # Red flags in transcript
        prompt_lower = prompt.lower()
        for flag in Thresholds.HIGH_RISK_KEYWORDS:
            if flag in prompt_lower:
                return _decide(Destination.CLOUD, f"red_flag:'{flag}'", 4, metrics)

        # Red flags extracted by Gemma 4
        if ctx.entities.get("red_flags"):
            flags = ctx.entities["red_flags"]
            return _decide(Destination.CLOUD,
                f"red_flags_detected:{flags[:2]}", 4, metrics)

        if ctx.chunk_index > Thresholds.MAX_LOCAL_TURNS:
            return _decide(Destination.CLOUD,
                f"turn_{ctx.chunk_index}_exceeds_kv_limit", 4, metrics)

        if not ctx.ehr_loaded and ctx.chunk_index > 5:
            return _decide(Destination.CLOUD,
                "ehr_not_loaded_conversation_deep", 4, metrics)

        # ── Layer 5: Resource gate (RAM not yet exposed — layer passes) ────────
        # When cactus_complete exposes ram_usage_mb, add check here.

        # ── Layer 6: On-device confirmed ──────────────────────────────────────
        return _decide(Destination.ON_DEVICE, "all_layers_passed", 6, metrics)


# ── Module-level singleton ────────────────────────────────────────────────────

_router = ConsultationRouter()


# ── Public API (called by main.py) ────────────────────────────────────────────

def should_escalate(
    entities:    dict,
    chunk_index: int,
    transcript:  str  = "",
    ehr_loaded:  bool = True,
) -> tuple[bool, str]:
    """Returns (escalate: bool, reason: str)."""
    ctx = RoutingContext(
        prompt=transcript,
        entities=entities,
        chunk_index=chunk_index,
        ehr_loaded=ehr_loaded,
    )
    decision = _router.route(ctx)
    return decision.use_cloud, decision.reason


def routing_summary() -> dict:
    """Session-level cloud vs on-device breakdown — broadcast via /stats."""
    return _router.summary()
