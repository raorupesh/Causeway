from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from causeway.analysis.root_cause import RootCauseAnalyzer
from causeway.causal.graph_builder import CausalGraphBuilder
from causeway.db.repository import SpanRepository
from causeway.detection.anomaly import IsolationForestDetector
from causeway.models import MetricWindow, ServiceTimeSeries
from causeway.synthetic.generator import generate_incident, generate_normal_traffic
from causeway.timeseries.extractor import TimeSeriesExtractor

app = FastAPI(title="Causeway")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

repo = SpanRepository()
extractor = TimeSeriesExtractor()

DEMO_SERVICES = ["db-pool", "auth-service", "payment-service", "cart-service", "notification-service"]
TOTAL_HOURS = 24
NORMAL_HOURS = 22  # portion of the window used as the causal-graph / anomaly-detector baseline


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/demo/seed")
def seed_demo_data():
    """Generate synthetic normal traffic plus a planted cascading incident
    and store it, so the pipeline can be exercised without a real tracing
    backend."""
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    window_start = now_utc - timedelta(hours=TOTAL_HOURS)
    incident_time = window_start + timedelta(hours=NORMAL_HOURS)

    spans = generate_normal_traffic(
        DEMO_SERVICES, hours=TOTAL_HOURS, start=window_start, dependency_chain=DEMO_SERVICES
    )
    spans += generate_incident(
        DEMO_SERVICES,
        start_time=incident_time,
        root_cause_service="db-pool",
        downstream_chain=["auth-service", "payment-service", "cart-service", "notification-service"],
    )

    repo.reset()
    repo.insert_spans(spans)

    return {
        "services": DEMO_SERVICES,
        "window_start": window_start.isoformat(),
        "incident_time": incident_time.isoformat(),
        "span_count": len(spans),
    }


def _all_series() -> tuple[dict[str, ServiceTimeSeries], datetime]:
    services = repo.get_services()
    if not services:
        raise HTTPException(400, "No data ingested yet — POST /demo/seed first")

    spans = repo.get_spans()
    window_start = min(s.start_time for s in spans)
    series = {s: extractor.extract(spans, s, window_start, TOTAL_HOURS) for s in services}
    return series, window_start


def _slice(ts: ServiceTimeSeries, end_idx: int) -> ServiceTimeSeries:
    return ServiceTimeSeries(
        service=ts.service,
        timestamps=ts.timestamps[:end_idx],
        latency_p99=ts.latency_p99[:end_idx],
        error_rate=ts.error_rate[:end_idx],
        throughput=ts.throughput[:end_idx],
    )


def _build_normal_series(series: dict[str, ServiceTimeSeries]) -> dict[str, ServiceTimeSeries]:
    normal_idx = NORMAL_HOURS * 60
    return {s: _slice(ts, normal_idx) for s, ts in series.items()}


def _train_detector(normal_series: dict[str, ServiceTimeSeries]) -> IsolationForestDetector:
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


@app.get("/api/causal-graph")
def get_causal_graph():
    series, _ = _all_series()
    normal_series = _build_normal_series(series)

    graph = CausalGraphBuilder().build(normal_series)
    return {
        "nodes": list(graph.nodes),
        "edges": [{"source": u, "target": v, **data} for u, v, data in graph.edges(data=True)],
    }


@app.get("/api/root-cause")
def get_root_cause(incident_time: str | None = None):
    series, window_start = _all_series()
    normal_series = _build_normal_series(series)

    graph = CausalGraphBuilder().build(normal_series)
    detector = _train_detector(normal_series)

    incident_dt = (
        datetime.fromisoformat(incident_time)
        if incident_time
        else window_start + timedelta(hours=NORMAL_HOURS)
    )

    report = RootCauseAnalyzer(detector).analyze(graph, series, incident_dt)

    return {
        "status": report.status,
        "root_cause": report.root_cause,
        "confidence": report.confidence,
        "causal_chain": report.causal_chain,
        "anomalous_services": report.anomalous_services,
        "total_propagation_minutes": report.total_propagation_minutes,
        "message": report.message,
    }
