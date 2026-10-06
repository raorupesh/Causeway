from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from causeway.api import main as main_module
from causeway.db.repository import SpanRepository


@pytest.fixture()
def client(tmp_path):
    main_module.repo = SpanRepository(db_path=str(tmp_path / "test_causeway.db"))
    return TestClient(main_module.app)


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    """One seeded dataset shared by every slow test in this module — seeding
    and building the causal graph is the expensive part."""
    db_path = tmp_path_factory.mktemp("seeded") / "test_causeway.db"
    main_module.repo = SpanRepository(db_path=str(db_path))
    client = TestClient(main_module.app)
    seed_response = client.post("/demo/seed")
    assert seed_response.status_code == 200
    return client, seed_response.json()


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_causal_graph_requires_seeded_data(client):
    response = client.get("/api/causal-graph")
    assert response.status_code == 400


def test_data_endpoints_require_seeded_data(client):
    for path in ("/api/timeseries", "/api/health", "/api/incidents", "/api/root-cause"):
        assert client.get(path).status_code == 400, path


def test_overview_reports_unseeded(client):
    assert client.get("/api/overview").json() == {"seeded": False}


@pytest.mark.slow
def test_seed_then_root_cause_identifies_the_planted_root(seeded):
    """End-to-end regression test for the full pipeline: synthetic traffic
    with a planted db-pool cascade should come back out the other end as
    ROOT_CAUSE_IDENTIFIED == db-pool, not INDEPENDENT_FAILURES."""
    client, seed = seeded
    assert seed["span_count"] > 0

    graph_response = client.get("/api/causal-graph")
    assert graph_response.status_code == 200
    edges = graph_response.json()["edges"]
    assert any(e["source"] == "db-pool" and e["target"] == "auth-service" for e in edges)

    root_cause_response = client.get("/api/root-cause")
    assert root_cause_response.status_code == 200
    body = root_cause_response.json()
    assert body["status"] == "ROOT_CAUSE_IDENTIFIED"
    assert body["root_cause"] == "db-pool"
    assert "notification-service" in body["anomalous_services"]


@pytest.mark.slow
def test_overview_describes_the_seeded_window(seeded):
    client, seed = seeded
    body = client.get("/api/overview").json()
    assert body["seeded"] is True
    assert body["graph_ready"] is True  # warmed by the seed background task
    assert set(body["services"]) == set(seed["services"])
    start = datetime.fromisoformat(body["window_start"])
    assert datetime.fromisoformat(body["baseline_end"]) - start == timedelta(
        hours=main_module.NORMAL_HOURS
    )


@pytest.mark.slow
def test_timeseries_range_and_health(seeded):
    client, seed = seeded
    incident = datetime.fromisoformat(seed["incident_time"])
    start = (incident - timedelta(minutes=30)).isoformat()
    end = (incident + timedelta(minutes=30)).isoformat()

    body = client.get("/api/timeseries", params={"start": start, "end": end}).json()
    assert 60 <= len(body["timestamps"]) <= 62
    db_pool = body["services"]["db-pool"]
    for key in ("latency_p99", "error_rate", "throughput", "anomaly_score", "health"):
        assert len(db_pool[key]) == len(body["timestamps"])
    # The planted incident should turn every service critical at some point.
    for service in seed["services"]:
        assert "critical" in body["services"][service]["health"], service

    single = client.get(
        "/api/services/cart-service/timeseries", params={"start": start, "end": end}
    ).json()
    assert single["health"] == body["services"]["cart-service"]["health"]
    assert client.get("/api/services/nope/timeseries").status_code == 404
    assert client.get("/api/timeseries", params={"start": end, "end": start}).status_code == 422


@pytest.mark.slow
def test_health_snapshot_during_incident(seeded):
    client, seed = seeded
    incident = datetime.fromisoformat(seed["incident_time"])
    at = (incident + timedelta(minutes=5)).isoformat()
    body = client.get("/api/health", params={"at": at}).json()
    assert body["services"]["db-pool"]["status"] == "critical"
    assert body["services"]["db-pool"]["anomaly_score"] < 0


@pytest.mark.slow
def test_incidents_detects_the_planted_cascade(seeded):
    client, seed = seeded
    incident = datetime.fromisoformat(seed["incident_time"])
    incidents = client.get("/api/incidents").json()["incidents"]
    assert incidents
    first = incidents[0]
    assert abs(datetime.fromisoformat(first["start"]) - incident) <= timedelta(minutes=2)
    assert set(seed["services"]) <= set(first["services"])
