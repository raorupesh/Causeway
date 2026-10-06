from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, TypeVar

import networkx as nx
import numpy as np

from causeway.analysis.root_cause import RootCauseAnalyzer
from causeway.causal.graph_builder import CausalGraphBuilder
from causeway.db.repository import SpanRepository
from causeway.detection.anomaly import IsolationForestDetector
from causeway.models import MetricWindow, RootCauseReport, ServiceTimeSeries
from causeway.timeseries.extractor import TimeSeriesExtractor

T = TypeVar("T")

HEALTHY = "healthy"
DEGRADED = "degraded"
CRITICAL = "critical"


class NoDataError(Exception):
    pass


@dataclass
class SeriesBundle:
    series: dict[str, ServiceTimeSeries]
    window_start: datetime
    timestamps: list[datetime]

    @property
    def window_end(self) -> datetime:
        return self.timestamps[-1] + timedelta(minutes=1)

    def index_of(self, t: datetime) -> int:
        """Index of the 1-minute bucket containing t, clamped to the window."""
        idx = int((t - self.window_start).total_seconds() // 60)
        return max(0, min(idx, len(self.timestamps) - 1))


@dataclass
class HealthTimeline:
    """Per-service, per-minute health derived from the anomaly detector.

    A single anomalous minute is common even in normal traffic (the detector
    is fit with 2% contamination), so one anomalous minute is only DEGRADED;
    two or more consecutive anomalous minutes are CRITICAL.
    """

    status: dict[str, list[str]]
    decision: dict[str, np.ndarray]


@dataclass
class Incident:
    start: datetime
    end: datetime
    services: list[str]


def slice_series(ts: ServiceTimeSeries, end_idx: int) -> ServiceTimeSeries:
    return ServiceTimeSeries(
        service=ts.service,
        timestamps=ts.timestamps[:end_idx],
        latency_p99=ts.latency_p99[:end_idx],
        error_rate=ts.error_rate[:end_idx],
        throughput=ts.throughput[:end_idx],
    )


def train_detector(normal_series: dict[str, ServiceTimeSeries]) -> IsolationForestDetector:
    detector = IsolationForestDetector()
    for service, ts in normal_series.items():
        windows = [
            MetricWindow(
                service=service,
                timestamp=ts.timestamps[i],
                latency_p99=float(ts.latency_p99[i]),
                error_rate=float(ts.error_rate[i]),
                throughput=float(ts.throughput[i]),
                prev_latency_p99=float(ts.latency_p99[i - 1]),
                prev_error_rate=float(ts.error_rate[i - 1]),
                prev_throughput=float(ts.throughput[i - 1]),
            )
            for i in range(1, len(ts.timestamps))
        ]
        if windows:
            detector.train(service, windows)
    return detector


def classify_health(is_anomalous: np.ndarray) -> list[str]:
    status = []
    for i, anomalous in enumerate(is_anomalous):
        if not anomalous:
            status.append(HEALTHY)
        elif i > 0 and is_anomalous[i - 1]:
            status.append(CRITICAL)
        else:
            status.append(DEGRADED)
    return status


class Pipeline:
    """
    Lazily computes and caches every derived artifact (time series, causal
    graph, anomaly detector, health timeline, root cause reports) for the
    spans currently in a repository.

    The causal graph is the expensive step (hundreds of Granger tests), so
    it is built once per dataset instead of once per request. Each artifact
    has its own lock, so a slow graph build does not block cheap requests
    like time series or health.
    """

    def __init__(
        self,
        repo: SpanRepository,
        total_hours: int,
        normal_hours: int,
        extractor: TimeSeriesExtractor | None = None,
    ):
        self.repo = repo
        self.total_hours = total_hours
        self.normal_hours = normal_hours
        self.extractor = extractor or TimeSeriesExtractor()
        self._cache: dict[object, object] = {}
        self._locks: dict[object, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _cached(self, key: object, compute: Callable[[], T]) -> T:
        if key in self._cache:
            return self._cache[key]  # type: ignore[return-value]
        with self._locks_guard:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            if key not in self._cache:
                self._cache[key] = compute()
        return self._cache[key]  # type: ignore[return-value]

    def is_ready(self, key: str) -> bool:
        return key in self._cache

    # -- artifacts --------------------------------------------------------

    def bundle(self) -> SeriesBundle:
        return self._cached("bundle", self._compute_bundle)

    def _compute_bundle(self) -> SeriesBundle:
        services = self.repo.get_services()
        if not services:
            raise NoDataError("No data ingested yet — POST /demo/seed first")
        spans = self.repo.get_spans()
        window_start = min(s.start_time for s in spans)
        series = {
            s: self.extractor.extract(spans, s, window_start, self.total_hours) for s in services
        }
        timestamps = next(iter(series.values())).timestamps
        return SeriesBundle(series=series, window_start=window_start, timestamps=timestamps)

    @property
    def baseline_end(self) -> datetime:
        return self.bundle().window_start + timedelta(hours=self.normal_hours)

    def normal_series(self) -> dict[str, ServiceTimeSeries]:
        normal_idx = self.normal_hours * 60
        return {s: slice_series(ts, normal_idx) for s, ts in self.bundle().series.items()}

    def graph(self) -> nx.DiGraph:
        return self._cached("graph", lambda: CausalGraphBuilder().build(self.normal_series()))

    def detector(self) -> IsolationForestDetector:
        return self._cached("detector", lambda: train_detector(self.normal_series()))

    def health(self) -> HealthTimeline:
        return self._cached("health", self._compute_health)

    def _compute_health(self) -> HealthTimeline:
        detector = self.detector()
        status: dict[str, list[str]] = {}
        decision: dict[str, np.ndarray] = {}
        for service, ts in self.bundle().series.items():
            d, anomalous = detector.score_series(ts)
            decision[service] = d
            status[service] = classify_health(anomalous)
        return HealthTimeline(status=status, decision=decision)

    def incidents(self, merge_gap_minutes: int = 5) -> list[Incident]:
        return self._cached("incidents", lambda: self._compute_incidents(merge_gap_minutes))

    def _compute_incidents(self, merge_gap_minutes: int) -> list[Incident]:
        """Contiguous stretches after the baseline where any service is
        CRITICAL, with short healthy gaps merged into one incident."""
        bundle = self.bundle()
        health = self.health()
        start_idx = bundle.index_of(self.baseline_end)

        incidents: list[Incident] = []
        current: tuple[int, int, set[str]] | None = None
        for i in range(start_idx, len(bundle.timestamps)):
            critical = {s for s, st in health.status.items() if st[i] == CRITICAL}
            if not critical:
                continue
            if current and i - current[1] <= merge_gap_minutes:
                current = (current[0], i, current[2] | critical)
            else:
                if current:
                    incidents.append(self._make_incident(bundle, current))
                current = (i, i, critical)
        if current:
            incidents.append(self._make_incident(bundle, current))
        return incidents

    def _make_incident(self, bundle: SeriesBundle, run: tuple[int, int, set[str]]) -> Incident:
        start_idx, end_idx, services = run
        # Back up to the first anomalous (DEGRADED) minute that led into the
        # critical run, so the incident starts at onset, not confirmation.
        health = self.health()
        while start_idx > 0 and any(
            health.status[s][start_idx - 1] != HEALTHY for s in services
        ):
            start_idx -= 1
        return Incident(
            start=bundle.timestamps[start_idx],
            end=bundle.timestamps[end_idx] + timedelta(minutes=1),
            services=sorted(services),
        )

    def root_cause(self, incident_time: datetime) -> RootCauseReport:
        return self._cached(
            ("root_cause", incident_time),
            lambda: RootCauseAnalyzer(self.detector()).analyze(
                self.graph(), self.bundle().series, incident_time
            ),
        )

    def warm(self) -> None:
        """Precompute everything, e.g. in a background task after seeding."""
        try:
            self.health()
            self.graph()
        except NoDataError:
            pass
