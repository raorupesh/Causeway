from __future__ import annotations

from datetime import datetime

import networkx as nx

from causeway.analysis.root_cause import RootCauseAnalyzer


class _StubDetector:
    """Reports a fixed set of services as anomalous, so root-cause path
    selection can be tested independent of Isolation Forest statistics."""

    def __init__(self, anomalous: list[str]):
        self._anomalous = anomalous

    def find_anomalous_services(self, current_metrics, incident_time):
        return self._anomalous


def _chain_graph() -> nx.DiGraph:
    graph = nx.DiGraph()
    edges = [
        ("db-pool", "auth-service", 2, 10.0),
        ("auth-service", "payment-service", 1, 8.0),
        ("payment-service", "cart-service", 2, 6.0),
    ]
    for source, target, lag, f_stat in edges:
        graph.add_edge(
            source,
            target,
            lag_minutes=lag,
            f_statistic=f_stat,
            p_value=0.001,
            strength=f_stat,
            metrics=["latency_p99"],
        )
    return graph


def test_identifies_upstream_root_cause_for_a_downstream_anomaly():
    graph = _chain_graph()
    detector = _StubDetector(["cart-service"])

    report = RootCauseAnalyzer(detector).analyze(graph, current_metrics={}, incident_time=datetime(2026, 1, 1))

    assert report.status == "ROOT_CAUSE_IDENTIFIED"
    assert report.root_cause == "db-pool"
    assert [step["source"] for step in report.causal_chain] == ["db-pool", "auth-service", "payment-service"]
    assert report.total_propagation_minutes == 5


def test_no_anomaly_when_detector_finds_nothing():
    graph = _chain_graph()
    detector = _StubDetector([])

    report = RootCauseAnalyzer(detector).analyze(graph, current_metrics={}, incident_time=datetime(2026, 1, 1))

    assert report.status == "NO_ANOMALY"
    assert report.root_cause is None


def test_independent_failures_when_anomalous_services_have_no_common_ancestor():
    graph = nx.DiGraph()
    graph.add_node("isolated-a")
    graph.add_node("isolated-b")
    detector = _StubDetector(["isolated-a", "isolated-b"])

    report = RootCauseAnalyzer(detector).analyze(graph, current_metrics={}, incident_time=datetime(2026, 1, 1))

    assert report.status == "INDEPENDENT_FAILURES"
    assert set(report.anomalous_services) == {"isolated-a", "isolated-b"}
