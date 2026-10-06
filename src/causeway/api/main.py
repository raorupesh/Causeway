from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from causeway.db.repository import SpanRepository
from causeway.pipeline import NoDataError, Pipeline, SeriesBundle
from causeway.synthetic.generator import generate_incident, generate_normal_traffic

app = FastAPI(title="Causeway")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

repo = SpanRepository()

DEMO_SERVICES = ["db-pool", "auth-service", "payment-service", "cart-service", "notification-service"]
TOTAL_HOURS = 24
NORMAL_HOURS = 22  # portion of the window used as the causal-graph / anomaly-detector baseline

_pipeline: Pipeline | None = None


def get_pipeline() -> Pipeline:
    """The pipeline cache is tied to the current repo, so swapping `repo`
    (as the tests do) or reseeding always starts from a fresh cache."""
    global _pipeline
    if _pipeline is None or _pipeline.repo is not repo:
        _pipeline = Pipeline(repo, total_hours=TOTAL_HOURS, normal_hours=NORMAL_HOURS)
    return _pipeline


@app.exception_handler(NoDataError)
def _no_data_handler(_: Request, exc: NoDataError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


def _parse_time(value: str, name: str) -> datetime:
    """Parse an ISO timestamp into naive UTC (the representation spans use)."""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(422, f"{name} must be an ISO-8601 timestamp")
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _range(bundle: SeriesBundle, start: str | None, end: str | None) -> tuple[int, int]:
    start_idx = bundle.index_of(_parse_time(start, "start")) if start else 0
    end_idx = (
        bundle.index_of(_parse_time(end, "end")) + 1 if end else len(bundle.timestamps)
    )
    if end_idx <= start_idx:
        raise HTTPException(422, "end must be after start")
    return start_idx, end_idx


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/demo/seed")
def seed_demo_data(background_tasks: BackgroundTasks):
    """Generate synthetic normal traffic plus a planted cascading incident
    and store it, so the pipeline can be exercised without a real tracing
    backend. The causal graph is then precomputed in the background."""
    global _pipeline
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

    _pipeline = None
    background_tasks.add_task(get_pipeline().warm)

    return {
        "services": DEMO_SERVICES,
        "window_start": window_start.isoformat(),
        "incident_time": incident_time.isoformat(),
        "span_count": len(spans),
    }


@app.get("/api/overview")
def get_overview():
    """Everything the dashboard needs to lay out its time axis, plus whether
    the (slow) causal graph has finished building yet."""
    if not repo.get_services():
        return {"seeded": False}

    pipeline = get_pipeline()
    bundle = pipeline.bundle()
    return {
        "seeded": True,
        "services": sorted(bundle.series),
        "window_start": bundle.window_start.isoformat(),
        "window_end": bundle.window_end.isoformat(),
        "baseline_end": pipeline.baseline_end.isoformat(),
        "default_incident_time": pipeline.baseline_end.isoformat(),
        "bucket_minutes": 1,
        "graph_ready": pipeline.is_ready("graph"),
    }


@app.get("/api/causal-graph")
def get_causal_graph():
    graph = get_pipeline().graph()
    return {
        "nodes": list(graph.nodes),
        "edges": [{"source": u, "target": v, **data} for u, v, data in graph.edges(data=True)],
    }


@app.get("/api/root-cause")
def get_root_cause(incident_time: str | None = None):
    pipeline = get_pipeline()
    incident_dt = (
        _parse_time(incident_time, "incident_time") if incident_time else pipeline.baseline_end
    )
    report = pipeline.root_cause(incident_dt)

    return {
        "status": report.status,
        "incident_time": incident_dt.isoformat(),
        "root_cause": report.root_cause,
        "confidence": report.confidence,
        "causal_chain": report.causal_chain,
        "anomalous_services": report.anomalous_services,
        "total_propagation_minutes": report.total_propagation_minutes,
        "message": report.message,
    }


def _service_payload(pipeline: Pipeline, service: str, start_idx: int, end_idx: int) -> dict:
    ts = pipeline.bundle().series[service]
    health = pipeline.health()
    return {
        "latency_p99": [round(float(v), 2) for v in ts.latency_p99[start_idx:end_idx]],
        "error_rate": [round(float(v), 4) for v in ts.error_rate[start_idx:end_idx]],
        "throughput": [float(v) for v in ts.throughput[start_idx:end_idx]],
        "anomaly_score": [
            round(float(v), 4) for v in health.decision[service][start_idx:end_idx]
        ],
        "health": health.status[service][start_idx:end_idx],
    }


@app.get("/api/timeseries")
def get_timeseries(start: str | None = None, end: str | None = None):
    """Per-minute metrics and health for every service in [start, end].

    anomaly_score is the Isolation Forest decision function: negative is
    anomalous. health is healthy / degraded / critical."""
    pipeline = get_pipeline()
    bundle = pipeline.bundle()
    start_idx, end_idx = _range(bundle, start, end)
    return {
        "timestamps": [t.isoformat() for t in bundle.timestamps[start_idx:end_idx]],
        "services": {
            s: _service_payload(pipeline, s, start_idx, end_idx) for s in sorted(bundle.series)
        },
    }


@app.get("/api/services/{service}/timeseries")
def get_service_timeseries(service: str, start: str | None = None, end: str | None = None):
    pipeline = get_pipeline()
    bundle = pipeline.bundle()
    if service not in bundle.series:
        raise HTTPException(404, f"Unknown service: {service}")
    start_idx, end_idx = _range(bundle, start, end)
    return {
        "service": service,
        "timestamps": [t.isoformat() for t in bundle.timestamps[start_idx:end_idx]],
        **_service_payload(pipeline, service, start_idx, end_idx),
    }


@app.get("/api/health")
def get_health(at: str | None = None):
    """Health of every service at a single point in time (defaults to the
    latest minute). The dashboard uses this to color graph nodes."""
    pipeline = get_pipeline()
    bundle = pipeline.bundle()
    idx = bundle.index_of(_parse_time(at, "at")) if at else len(bundle.timestamps) - 1
    health = pipeline.health()
    return {
        "at": bundle.timestamps[idx].isoformat(),
        "services": {
            s: {
                "status": health.status[s][idx],
                "anomaly_score": round(float(health.decision[s][idx]), 4),
            }
            for s in sorted(bundle.series)
        },
    }


@app.get("/api/incidents")
def get_incidents():
    """Incidents detected after the baseline window: stretches where at
    least one service is critical."""
    return {
        "incidents": [
            {"start": i.start.isoformat(), "end": i.end.isoformat(), "services": i.services}
            for i in get_pipeline().incidents()
        ]
    }


# Serve the built dashboard (frontend/dist) from the same origin when present,
# so `uvicorn causeway.api.main:app` alone is enough for a demo.
_frontend_dist = Path(
    os.environ.get(
        "CAUSEWAY_FRONTEND_DIST", Path(__file__).resolve().parents[3] / "frontend" / "dist"
    )
)
if _frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="frontend")
