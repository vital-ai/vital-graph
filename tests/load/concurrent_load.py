"""Read + write + jobs, concurrently. `issues/171` Part 2.

Every timing conclusion in this repository has been drawn from a QUIET database,
and the production problem was never quiet: `issues/161` measured ~110s of
background analytics inside a three-minute window while queries were being
timed. During the work that produced this file, an apparent 2x regression and an
apparent 6x improvement BOTH turned out to be contention or cache state rather
than code.

A benchmark that only ever runs alone cannot answer the question this repository
actually has, which is a CONCURRENCY question: does rebuild work hold locks or
CPU while application queries wait.

WHAT IS ASSERTED, in order of importance:

  1. ZERO timeouts and zero cancelled statements. Non-negotiable — a timeout is
     the production symptom, not a slow percentile.
  2. p99, not the mean. The mean hides exactly the queue-behind-a-rebuild case
     this exists to find: 99 fast queries and one 55s query is a good mean and a
     production incident.
  3. A hard ceiling no single query may cross.
  4. Writes keep making progress. A read workload that starves ingest is not a
     pass; it is the same failure pointed the other way.

The harness reports rather than asserts, so a caller decides the thresholds and
a diagnostic run can print the picture without failing.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, List, Optional


@dataclass
class Sample:
    label: str
    ms: float
    ok: bool
    error: str = ""

    @property
    def timed_out(self) -> bool:
        e = self.error.lower()
        return ("timeout" in e or "cancel" in e or "querycanceled" in e)


@dataclass
class LoadResult:
    samples: List[Sample] = field(default_factory=list)
    writes: int = 0
    write_errors: int = 0
    seconds: float = 0.0

    def latencies(self, label: Optional[str] = None) -> List[float]:
        return sorted(s.ms for s in self.samples
                      if s.ok and (label is None or s.label == label))

    def pct(self, p: float, label: Optional[str] = None) -> float:
        xs = self.latencies(label)
        if not xs:
            return 0.0
        # Nearest-rank. With small n an interpolated percentile invents a value
        # between two measurements, and this is used as a pass/fail bound.
        k = max(0, min(len(xs) - 1, int(round(p / 100.0 * len(xs))) - 1))
        return xs[k]

    @property
    def timeouts(self) -> List[Sample]:
        return [s for s in self.samples if s.timed_out]

    @property
    def failures(self) -> List[Sample]:
        return [s for s in self.samples if not s.ok]

    def summary(self) -> Dict[str, object]:
        return {
            "queries": len(self.samples),
            "ok": len(self.samples) - len(self.failures),
            "timeouts": len(self.timeouts),
            "failures": len(self.failures) - len(self.timeouts),
            "p50_ms": round(self.pct(50), 1),
            "p99_ms": round(self.pct(99), 1),
            "max_ms": round(max((s.ms for s in self.samples), default=0.0), 1),
            "writes": self.writes,
            "write_errors": self.write_errors,
            "seconds": round(self.seconds, 1),
        }

    def by_label(self) -> Dict[str, Dict[str, float]]:
        out: Dict[str, Dict[str, float]] = {}
        for label in sorted({s.label for s in self.samples}):
            xs = self.latencies(label)
            out[label] = {
                "n": len(xs),
                "p50_ms": round(self.pct(50, label), 1),
                "p99_ms": round(self.pct(99, label), 1),
                "max_ms": round(max(xs, default=0.0), 1),
                "timeouts": len([s for s in self.timeouts if s.label == label]),
            }
        return out


async def _reader(name: str, fn: Callable[[], Awaitable], stop: asyncio.Event,
                  out: List[Sample], pace_s: float) -> None:
    while not stop.is_set():
        t0 = time.monotonic()
        try:
            await fn()
            out.append(Sample(name, (time.monotonic() - t0) * 1000, True))
        except Exception as exc:
            out.append(Sample(name, (time.monotonic() - t0) * 1000, False,
                              f"{type(exc).__name__}: {exc}"))
        if pace_s:
            await asyncio.sleep(pace_s)


async def _writer(fn: Callable[[], Awaitable], stop: asyncio.Event,
                  res: LoadResult, pace_s: float) -> None:
    while not stop.is_set():
        try:
            await fn()
            res.writes += 1
        except Exception:
            res.write_errors += 1
        if pace_s:
            await asyncio.sleep(pace_s)


async def run_load(*, readers: Dict[str, Callable[[], Awaitable]],
                   writer: Optional[Callable[[], Awaitable]] = None,
                   jobs: Optional[List[Callable[[], Awaitable]]] = None,
                   duration_s: float = 60.0,
                   read_concurrency: int = 4,
                   read_pace_s: float = 0.0,
                   write_pace_s: float = 0.05) -> LoadResult:
    """Run readers, a writer and the jobs together for `duration_s`.

    `jobs` are run ONCE EACH, concurrently with the workload, rather than on a
    schedule: the question is what a maintenance cycle or an analytics pass does
    to latency while it runs, and a job that finishes early has already answered
    it. A job that raises is not a failure of the load test — it is recorded by
    the caller, because a job dying under load is itself a finding.
    """
    res = LoadResult()
    stop = asyncio.Event()
    tasks: List[asyncio.Task] = []
    t0 = time.monotonic()

    for name, fn in readers.items():
        for _ in range(read_concurrency):
            tasks.append(asyncio.create_task(
                _reader(name, fn, stop, res.samples, read_pace_s)))
    if writer is not None:
        tasks.append(asyncio.create_task(
            _writer(writer, stop, res, write_pace_s)))

    job_tasks = [asyncio.create_task(j()) for j in (jobs or [])]

    try:
        # READERS RUN UNTIL THE JOBS FINISH, not for `duration_s` alone.
        #
        # The first version slept `duration_s` and then stopped everything. On
        # the 53M-quad space that measured 45s of load against jobs that ran for
        # 134s — so roughly two thirds of the job execution had NO queries
        # observing it, and the run reported a clean p99 for a window that was
        # mostly quiet. A contention test that stops before the contention ends
        # measures the recovery, not the event.
        #
        # `duration_s` is therefore a MINIMUM. A run with no jobs is unchanged.
        await asyncio.sleep(duration_s)
        if job_tasks:
            await asyncio.gather(*job_tasks, return_exceptions=True)
    finally:
        stop.set()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(*job_tasks, return_exceptions=True)
        res.seconds = time.monotonic() - t0
    return res
