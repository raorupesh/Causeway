from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from causeway.models import AnomalyScore, MetricWindow, ServiceTimeSeries


class IsolationForestDetector:
    """
    Trained per-service on windows of normal traffic. Scores current metric
    windows to find services behaving anomalously.

    Isolation Forest is unsupervised (no labeled incidents needed), works on
    small datasets, and is fast enough for interactive use.
    """

    def __init__(self, contamination: float = 0.02):
        self.models: dict[str, IsolationForest] = {}
        self.scalers: dict[str, StandardScaler] = {}
        self.contamination = contamination

    def train(self, service: str, normal_windows: list[MetricWindow]) -> None:
        X = self._windows_to_features(normal_windows)

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        model = IsolationForest(
            n_estimators=200,
            contamination=self.contamination,
            random_state=42,
            n_jobs=-1,
        )
        model.fit(X_scaled)

        self.models[service] = model
        self.scalers[service] = scaler

    def score(self, service: str, window: MetricWindow) -> AnomalyScore:
        if service not in self.models:
            return AnomalyScore(service=service, is_anomalous=False, score=0.0)

        X = self._windows_to_features([window])
        X_scaled = self.scalers[service].transform(X)

        model = self.models[service]
        score = float(model.score_samples(X_scaled)[0])
        is_anomalous = bool(model.predict(X_scaled)[0] == -1)

        return AnomalyScore(
            service=service,
            is_anomalous=is_anomalous,
            score=score,
            anomalous_features=self._explain(window) if is_anomalous else [],
        )

    def score_series(self, ts: ServiceTimeSeries) -> tuple[np.ndarray, np.ndarray]:
        """Score every window of a time series in one vectorized pass.

        Returns (decision, is_anomalous) arrays aligned with ts.timestamps.
        decision is IsolationForest's decision_function: negative means
        anomalous, and values just above zero are borderline. The first
        window has no previous value, so it reuses itself as "previous".
        """
        n = len(ts.timestamps)
        if ts.service not in self.models or n == 0:
            return np.zeros(n), np.zeros(n, dtype=bool)

        def prev(a: np.ndarray) -> np.ndarray:
            return np.concatenate([a[:1], a[:-1]])

        X = np.column_stack(
            [
                ts.latency_p99,
                ts.latency_p99 - prev(ts.latency_p99),
                ts.error_rate,
                ts.error_rate - prev(ts.error_rate),
                ts.throughput,
                ts.throughput - prev(ts.throughput),
                [t.hour for t in ts.timestamps],
                [t.weekday() for t in ts.timestamps],
            ]
        )
        X_scaled = self.scalers[ts.service].transform(X)
        decision = self.models[ts.service].decision_function(X_scaled)
        return decision, decision < 0

    def find_anomalous_services(
        self,
        current_metrics: dict[str, ServiceTimeSeries],
        incident_time: datetime,
        lookahead_minutes: int = 15,
    ) -> list[str]:
        """Return services with at least one anomalous window in
        [incident_time, incident_time + lookahead_minutes].

        A single point-in-time check would miss services whose onset lags
        behind the incident start (as happens in a cascading failure), so
        this scans forward instead of only checking the nearest window.
        """
        anomalous = []
        for service, ts in current_metrics.items():
            windows = self._windows_in_range(service, ts, incident_time, lookahead_minutes)
            if any(self.score(service, w).is_anomalous for w in windows):
                anomalous.append(service)
        return anomalous

    def _windows_in_range(
        self,
        service: str,
        ts: ServiceTimeSeries,
        incident_time: datetime,
        lookahead_minutes: int,
    ) -> list[MetricWindow]:
        range_end = incident_time + timedelta(minutes=lookahead_minutes)
        windows = []
        for i in range(1, len(ts.timestamps)):
            if not (incident_time <= ts.timestamps[i] <= range_end):
                continue
            windows.append(
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
            )
        return windows

    def _windows_to_features(self, windows: list[MetricWindow]) -> np.ndarray:
        """
        Feature vector per window:
        [latency_p99, latency_delta, error_rate, error_rate_delta,
         throughput, throughput_delta, hour_of_day, day_of_week]

        Deltas (rate of change) matter as much as absolute values — a
        latency of 500ms might be normal, a jump from 50ms to 500ms is not.
        """
        return np.array(
            [
                [
                    w.latency_p99,
                    w.latency_p99 - w.prev_latency_p99,
                    w.error_rate,
                    w.error_rate - w.prev_error_rate,
                    w.throughput,
                    w.throughput - w.prev_throughput,
                    w.timestamp.hour,
                    w.timestamp.weekday(),
                ]
                for w in windows
            ]
        )

    def _explain(self, window: MetricWindow) -> list[str]:
        features = []
        if window.prev_latency_p99 > 0 and window.latency_p99 > window.prev_latency_p99 * 2:
            features.append("latency_p99")
        if window.error_rate > window.prev_error_rate + 0.05:
            features.append("error_rate")
        if window.prev_throughput > 0 and window.throughput < window.prev_throughput * 0.5:
            features.append("throughput")
        return features
