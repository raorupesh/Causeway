from __future__ import annotations

from datetime import datetime

import networkx as nx

from causeway.detection.anomaly import IsolationForestDetector
from causeway.models import RootCauseCandidate, RootCauseReport, ServiceTimeSeries


class RootCauseAnalyzer:
    """
    Given a causal graph (built from normal traffic), the set of services
    currently behaving anomalously, and an incident time, identifies the
    most likely root cause: the anomalous service (or an ancestor of one)
    with no incoming causal edges of its own.

    Simplification vs. a fully timing-aware scorer: path score is the
    product of Granger F-statistics along the path. A timing-alignment bonus
    (does the propagation lag match when services actually started failing)
    is a natural extension but is left out of this MVP for time.
    """

    def __init__(self, anomaly_detector: IsolationForestDetector):
        self.detector = anomaly_detector

    def analyze(
        self,
        causal_graph: nx.DiGraph,
        current_metrics: dict[str, ServiceTimeSeries],
        incident_time: datetime,
    ) -> RootCauseReport:
        anomalous = self.detector.find_anomalous_services(current_metrics, incident_time)

        if not anomalous:
            return RootCauseReport(status="NO_ANOMALY")

        candidates: dict[str, RootCauseCandidate] = {}

        for service in anomalous:
            if service not in causal_graph:
                continue

            ancestors = nx.ancestors(causal_graph, service)
            for ancestor in ancestors:
                paths = list(nx.all_simple_paths(causal_graph, ancestor, service, cutoff=5))
                for path in paths:
                    score = self._score_path(causal_graph, path)
                    if ancestor not in candidates or candidates[ancestor].score < score:
                        candidates[ancestor] = RootCauseCandidate(
                            service=ancestor,
                            score=score,
                            path=path,
                            total_lag=self._total_lag(causal_graph, path),
                        )

        if not candidates:
            return RootCauseReport(
                status="INDEPENDENT_FAILURES",
                anomalous_services=anomalous,
                message="Multiple services failed independently — check shared infrastructure",
            )

        root_candidates = sorted(
            (c for c in candidates.values() if causal_graph.in_degree(c.service) == 0),
            key=lambda x: x.score,
            reverse=True,
        )
        if not root_candidates:
            root_candidates = sorted(candidates.values(), key=lambda x: x.score, reverse=True)

        root = root_candidates[0]

        return RootCauseReport(
            status="ROOT_CAUSE_IDENTIFIED",
            root_cause=root.service,
            confidence=min(0.99, root.score / 50),
            causal_chain=self._build_chain(causal_graph, root.path),
            anomalous_services=anomalous,
            total_propagation_minutes=root.total_lag,
            all_candidates=root_candidates[:5],
        )

    def _score_path(self, graph: nx.DiGraph, path: list[str]) -> float:
        strength = 1.0
        for i in range(len(path) - 1):
            edge = graph[path[i]][path[i + 1]]
            strength *= max(edge["f_statistic"], 1e-6)
        return strength

    def _total_lag(self, graph: nx.DiGraph, path: list[str]) -> int:
        return sum(graph[path[i]][path[i + 1]]["lag_minutes"] for i in range(len(path) - 1))

    def _build_chain(self, graph: nx.DiGraph, path: list[str]) -> list[dict]:
        chain = []
        for i in range(len(path) - 1):
            edge = graph[path[i]][path[i + 1]]
            chain.append(
                {
                    "source": path[i],
                    "target": path[i + 1],
                    "lag_minutes": edge["lag_minutes"],
                    "f_statistic": edge["f_statistic"],
                    "metrics": edge["metrics"],
                }
            )
        return chain
