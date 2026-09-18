from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from causeway.causal.graph_builder import CausalGraphBuilder
from causeway.models import ServiceTimeSeries


def _coupled_series(n: int, lag: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Source is AR(1) noise; target is its own AR(1) noise plus a lagged
    copy of source -- a minimal case with a known, real Granger-causal
    direction (source -> target, not the reverse)."""
    rng = np.random.default_rng(seed)
    source = np.zeros(n)
    for t in range(1, n):
        source[t] = 0.5 * source[t - 1] + rng.normal(0, 1)

    target = np.zeros(n)
    shifted_source = np.zeros(n)
    shifted_source[lag:] = source[:-lag]
    for t in range(1, n):
        target[t] = 0.5 * target[t - 1] + rng.normal(0, 1) + 3.0 * shifted_source[t]

    return source, target


def _build_time_series(name: str, values: np.ndarray, start: datetime) -> ServiceTimeSeries:
    timestamps = [start + timedelta(minutes=i) for i in range(len(values))]
    zeros = np.zeros(len(values))
    return ServiceTimeSeries(
        service=name, timestamps=timestamps, latency_p99=values, error_rate=zeros, throughput=zeros
    )


def test_detects_known_lagged_causality_in_the_correct_direction_only():
    """Regression test for a bug where every Granger test silently failed
    (a TypeError from an incompatible statsmodels call was swallowed by a
    broad except-clause), so the causal graph always came back empty
    regardless of the underlying data."""
    start = datetime(2026, 1, 1, 0, 0)
    source, target = _coupled_series(n=200, lag=3, seed=42)

    series = {
        "upstream": _build_time_series("upstream", source, start),
        "downstream": _build_time_series("downstream", target, start),
    }

    graph = CausalGraphBuilder(max_lag_minutes=5, min_series_length=60).build(series)

    assert graph.has_edge("upstream", "downstream")
    assert not graph.has_edge("downstream", "upstream")

    edge = graph["upstream"]["downstream"]
    assert edge["p_value"] < 0.05
    assert isinstance(edge["lag_minutes"], int)
    assert isinstance(edge["f_statistic"], float)
    assert isinstance(edge["p_value"], float)


def test_independent_series_produce_no_edge():
    start = datetime(2026, 1, 1, 0, 0)
    rng = np.random.default_rng(7)
    a = rng.normal(50, 5, size=200)
    b = rng.normal(50, 5, size=200)

    series = {
        "a": _build_time_series("a", a, start),
        "b": _build_time_series("b", b, start),
    }

    graph = CausalGraphBuilder(max_lag_minutes=5, min_series_length=60).build(series)

    assert graph.number_of_edges() == 0
