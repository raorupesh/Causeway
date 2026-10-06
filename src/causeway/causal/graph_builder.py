from __future__ import annotations

import logging
from itertools import product

import networkx as nx
import numpy as np
from statsmodels.tsa.stattools import adfuller, grangercausalitytests

from causeway.models import CausalEdge, ServiceTimeSeries

logger = logging.getLogger(__name__)

METRICS = ("latency_p99", "error_rate", "throughput")


class CausalGraphBuilder:
    """
    Tests every ordered pair of services for Granger causality and builds a
    directed graph of causal relationships.

    For N services: N*(N-1) pairs tested x 3 metrics x max_lag lags -
    potentially hundreds of statistical tests. Bonferroni correction is
    applied across all of them to control the false-positive rate.
    """

    def __init__(
        self,
        max_lag_minutes: int = 10,
        significance_level: float = 0.05,
        min_series_length: int = 60,
    ):
        self.max_lag = max_lag_minutes
        self.alpha = significance_level
        self.min_length = min_series_length

    def build(self, service_time_series: dict[str, ServiceTimeSeries]) -> nx.DiGraph:
        graph = nx.DiGraph()
        services = list(service_time_series.keys())

        for service in services:
            graph.add_node(service, label=service)

        n_pairs = max(len(services) * (len(services) - 1), 1)
        n_tests = n_pairs * len(METRICS) * self.max_lag
        bonferroni_alpha = self.alpha / n_tests

        for source, target in self._all_ordered_pairs(services):
            source_ts = service_time_series[source]
            target_ts = service_time_series[target]

            for metric in METRICS:
                source_series = getattr(source_ts, metric)
                target_series = getattr(target_ts, metric)

                edge = self._test_causality(
                    source, target, metric, source_series, target_series, bonferroni_alpha
                )
                if edge is None:
                    continue

                if graph.has_edge(source, target):
                    graph[source][target]["strength"] += edge.f_statistic
                    graph[source][target]["metrics"].append(metric)
                else:
                    graph.add_edge(
                        source,
                        target,
                        lag_minutes=edge.lag_minutes,
                        f_statistic=edge.f_statistic,
                        p_value=edge.p_value,
                        strength=edge.f_statistic,
                        metrics=[metric],
                    )

        return graph

    def _test_causality(
        self,
        source: str,
        target: str,
        metric: str,
        source_series: np.ndarray,
        target_series: np.ndarray,
        alpha: float,
    ) -> CausalEdge | None:
        s = self._make_stationary(source_series)
        t = self._make_stationary(target_series)

        min_len = min(len(s), len(t))
        if min_len < self.min_length:
            return None

        data = np.column_stack([t[:min_len], s[:min_len]])
        if np.allclose(data.std(axis=0), 0):
            return None

        try:
            results = grangercausalitytests(data, maxlag=self.max_lag)
        except Exception:
            logger.warning(
                "Granger test failed for %s->%s metric=%s", source, target, metric, exc_info=True
            )
            return None

        best: CausalEdge | None = None
        for lag, result in results.items():
            p_val = result[0]["ssr_ftest"][1]
            f_stat = result[0]["ssr_ftest"][0]

            if p_val < alpha and (best is None or p_val < best.p_value):
                best = CausalEdge(
                    source=source,
                    target=target,
                    metric=metric,
                    lag_minutes=int(lag),
                    p_value=float(p_val),
                    f_statistic=float(f_stat),
                )

        return best

    def _make_stationary(self, series: np.ndarray) -> np.ndarray:
        if len(series) < 3 or np.allclose(series, series[0]):
            return series
        try:
            is_stationary = adfuller(series, result_object=False)[1] < 0.05
        except Exception:
            is_stationary = True
        return series if is_stationary else np.diff(series)

    def _all_ordered_pairs(self, services: list[str]):
        for a, b in product(services, services):
            if a != b:
                yield (a, b)
