from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from causeway.api import main as main_module
from causeway.db.repository import SpanRepository


@pytest.fixture()
def client(tmp_path):
    main_module.repo = SpanRepository(db_path=str(tmp_path / "test_causeway.db"))
    return TestClient(main_module.app)


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_causal_graph_requires_seeded_data(client):
    response = client.get("/api/causal-graph")
    assert response.status_code == 400


@pytest.mark.slow
def test_seed_then_root_cause_identifies_the_planted_root(client):
    """End-to-end regression test for the full pipeline: synthetic traffic
    with a planted db-pool cascade should come back out the other end as
    ROOT_CAUSE_IDENTIFIED == db-pool, not INDEPENDENT_FAILURES."""
    seed_response = client.post("/demo/seed")
    assert seed_response.status_code == 200
    assert seed_response.json()["span_count"] > 0

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
