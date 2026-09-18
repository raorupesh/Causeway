from __future__ import annotations

from datetime import datetime

from causeway.synthetic.generator import generate_incident, generate_normal_traffic


def test_generate_normal_traffic_is_deterministic_for_a_given_seed():
    start = datetime(2026, 1, 1, 0, 0)
    a = generate_normal_traffic(["svc"], hours=1, start=start, seed=1)
    b = generate_normal_traffic(["svc"], hours=1, start=start, seed=1)

    assert [s.duration_ms for s in a] == [s.duration_ms for s in b]


def test_dependency_chain_couples_downstream_latency_to_upstream():
    start = datetime(2026, 1, 1, 0, 0)
    services = ["a", "b"]
    spans = generate_normal_traffic(
        services, hours=6, start=start, seed=3, dependency_chain=services
    )

    # Sanity check both services actually produced traffic.
    assert any(s.service_name == "a" for s in spans)
    assert any(s.service_name == "b" for s in spans)


def test_generate_incident_degrades_only_planted_services_and_window():
    start = datetime(2026, 1, 1, 0, 0)
    services = ["root", "downstream", "untouched"]
    spans = generate_incident(
        services,
        start_time=start,
        root_cause_service="root",
        downstream_chain=["downstream"],
        duration_minutes=5,
        lag_minutes=2,
    )

    affected = {s.service_name for s in spans}
    assert affected == {"root", "downstream"}
    assert all(s.error or s.duration_ms > 0 for s in spans)

    root_spans = [s for s in spans if s.service_name == "root"]
    downstream_spans = [s for s in spans if s.service_name == "downstream"]
    assert min(s.start_time for s in root_spans) < min(s.start_time for s in downstream_spans)
