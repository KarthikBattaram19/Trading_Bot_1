"""Latency instrumentation: P50 / P95 / P99 and time-to-first-token (TTFT)."""

from __future__ import annotations

import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Generator, Iterator

from backend.quality.config import get_thresholds


def _percentile(sorted_values: list[float], pct: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    weight = rank - low
    return sorted_values[low] * (1 - weight) + sorted_values[high] * weight


@dataclass
class LatencySample:
    operation: str
    total_ms: float
    ttft_ms: float | None = None
    success: bool = True


@dataclass
class LatencySnapshot:
    operation: str
    count: int
    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
    ttft_p50_ms: float | None
    ttft_p95_ms: float | None
    ttft_p99_ms: float | None
    mean_ms: float | None
    within_budget: bool
    budget_detail: str


@dataclass
class LatencyTracker:
    """Ring-buffer latency tracker for bot LLM / chat / decision calls."""

    max_samples: int = 2000
    _samples: deque[LatencySample] = field(default_factory=deque)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record(
        self,
        operation: str,
        total_ms: float,
        *,
        ttft_ms: float | None = None,
        success: bool = True,
    ) -> None:
        with self._lock:
            if len(self._samples) >= self.max_samples:
                self._samples.popleft()
            self._samples.append(
                LatencySample(
                    operation=operation,
                    total_ms=total_ms,
                    ttft_ms=ttft_ms,
                    success=success,
                )
            )

    @contextmanager
    def measure(self, operation: str) -> Generator["TimedCall", None, None]:
        timed = TimedCall(operation=operation, tracker=self)
        timed.start()
        try:
            yield timed
            timed.finish(success=timed.success)
        except Exception:
            timed.finish(success=False)
            raise

    def snapshot(self, operation: str | None = None) -> LatencySnapshot:
        thresholds = get_thresholds()
        with self._lock:
            samples = [
                s
                for s in self._samples
                if operation is None or s.operation == operation
            ]

        totals = sorted(s.total_ms for s in samples)
        ttfts = sorted(s.ttft_ms for s in samples if s.ttft_ms is not None)

        p50 = _percentile(totals, 50)
        p95 = _percentile(totals, 95)
        p99 = _percentile(totals, 99)
        ttft_p50 = _percentile(ttfts, 50)
        ttft_p95 = _percentile(ttfts, 95)
        ttft_p99 = _percentile(ttfts, 99)
        mean = sum(totals) / len(totals) if totals else None

        within = True
        details: list[str] = []
        if p50 is not None and p50 > thresholds.latency_p50_ms:
            within = False
            details.append(f"P50 {p50:.0f}ms > {thresholds.latency_p50_ms:.0f}ms")
        if p95 is not None and p95 > thresholds.latency_p95_ms:
            within = False
            details.append(f"P95 {p95:.0f}ms > {thresholds.latency_p95_ms:.0f}ms")
        if p99 is not None and p99 > thresholds.latency_p99_ms:
            within = False
            details.append(f"P99 {p99:.0f}ms > {thresholds.latency_p99_ms:.0f}ms")
        if ttft_p95 is not None and ttft_p95 > thresholds.ttft_p95_ms:
            within = False
            details.append(
                f"TTFT P95 {ttft_p95:.0f}ms > {thresholds.ttft_p95_ms:.0f}ms"
            )

        return LatencySnapshot(
            operation=operation or "all",
            count=len(samples),
            p50_ms=p50,
            p95_ms=p95,
            p99_ms=p99,
            ttft_p50_ms=ttft_p50,
            ttft_p95_ms=ttft_p95,
            ttft_p99_ms=ttft_p99,
            mean_ms=mean,
            within_budget=within if samples else True,
            budget_detail="; ".join(details) if details else "within budget",
        )

    def clear(self) -> None:
        with self._lock:
            self._samples.clear()

    def __iter__(self) -> Iterator[LatencySample]:
        with self._lock:
            return iter(list(self._samples))


@dataclass
class TimedCall:
    operation: str
    tracker: LatencyTracker
    _t0: float | None = None
    _ttft_ms: float | None = None
    _total_ms: float | None = None
    _finished: bool = False
    success: bool = True

    @property
    def ttft_ms(self) -> float | None:
        return self._ttft_ms

    @property
    def total_ms(self) -> float | None:
        return self._total_ms

    def start(self) -> None:
        self._t0 = time.perf_counter()

    def mark_first_token(self) -> None:
        if self._t0 is None or self._ttft_ms is not None:
            return
        self._ttft_ms = (time.perf_counter() - self._t0) * 1000.0

    def finish(self, *, success: bool | None = None) -> float:
        if self._finished or self._t0 is None:
            return self._total_ms or 0.0
        if success is not None:
            self.success = success
        total_ms = (time.perf_counter() - self._t0) * 1000.0
        self._total_ms = total_ms
        self.tracker.record(
            self.operation,
            total_ms,
            ttft_ms=self._ttft_ms,
            success=self.success,
        )
        self._finished = True
        return total_ms


_TRACKER = LatencyTracker()


def get_latency_tracker() -> LatencyTracker:
    return _TRACKER
