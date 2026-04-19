"""
Pipeline telemetry — collects per-chunk timing and cloud/local routing stats.
Single module-level singleton; reset via stats.reset().
"""
import time
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class PipelineStats:
    chunks_total: int = 0
    chunks_local_only: int = 0
    chunks_escalated: int = 0
    escalation_reasons: dict = field(default_factory=lambda: defaultdict(int))

    # All durations in milliseconds
    queue_wait_ms: list = field(default_factory=list)      # time chunk sat in queue (true latency signal)
    inference_ms: list = field(default_factory=list)       # _run_extraction wall time
    dispatch_ms: list = field(default_factory=list)        # broadcasts + rule checks
    cloud_ms: list = field(default_factory=list)           # Gemini round-trip
    chunks_dropped: int = 0

    session_start: float = field(default_factory=time.time)

    # ── Recording helpers ─────────────────────────────────────────────────────

    def chunk_arrived(self, queue_wait: float = 0.0):
        """Call at the top of the pipeline loop, before inference."""
        self.queue_wait_ms.append(queue_wait)

    def record_inference(self, started: float):
        self.inference_ms.append((time.time() - started) * 1000)

    def record_dispatch(self, started: float):
        self.dispatch_ms.append((time.time() - started) * 1000)

    def record_cloud(self, started: float):
        self.cloud_ms.append((time.time() - started) * 1000)

    def record_routing(self, escalated: bool, reason: str = ""):
        self.chunks_total += 1
        if escalated:
            self.chunks_escalated += 1
            self.escalation_reasons[reason] += 1
        else:
            self.chunks_local_only += 1

    def reset(self):
        self.__init__()

    # ── Summary ───────────────────────────────────────────────────────────────

    def summary(self) -> dict:
        def _avg(lst): return round(sum(lst) / len(lst)) if lst else None
        def _p95(lst):
            if not lst: return None
            s = sorted(lst)
            return round(s[min(int(len(s) * 0.95), len(s) - 1)])
        def _last(lst, n=5): return [round(v) for v in lst[-n:]]

        cloud_ratio = (
            round(self.chunks_escalated / self.chunks_total * 100, 1)
            if self.chunks_total else 0.0
        )
        uptime_s = round(time.time() - self.session_start)

        return {
            "uptime_s": uptime_s,
            "routing": {
                "chunks_total": self.chunks_total,
                "chunks_dropped": self.chunks_dropped,
                "local_only": self.chunks_local_only,
                "escalated_cloud": self.chunks_escalated,
                "cloud_pct": cloud_ratio,
                "reasons": dict(self.escalation_reasons),
            },
            "timing_ms": {
                "queue_wait": {"avg": _avg(self.queue_wait_ms), "p95": _p95(self.queue_wait_ms), "last": _last(self.queue_wait_ms)},
                "inference":  {"avg": _avg(self.inference_ms),  "p95": _p95(self.inference_ms),  "last": _last(self.inference_ms)},
                "dispatch":   {"avg": _avg(self.dispatch_ms),   "p95": _p95(self.dispatch_ms),   "last": _last(self.dispatch_ms)},
                "cloud":      {"avg": _avg(self.cloud_ms),      "p95": _p95(self.cloud_ms),      "last": _last(self.cloud_ms)},
                "end_to_end": {
                    "avg": _avg([q + i for q, i in zip(self.queue_wait_ms, self.inference_ms)]),
                    "p95": _p95([q + i for q, i in zip(self.queue_wait_ms, self.inference_ms)]),
                },
            },
            "sample_counts": {
                "queue_wait": len(self.queue_wait_ms),
                "inference": len(self.inference_ms),
                "dispatch": len(self.dispatch_ms),
                "cloud": len(self.cloud_ms),
            },
        }


stats = PipelineStats()
