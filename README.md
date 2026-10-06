# Causeway

**Datadog shows you what broke. Causeway shows you why.**

Causeway is a distributed-systems root cause analyzer. It ingests service
traces, builds a statistical causal graph between services using Granger
causality, and when an incident hits walks that graph backwards from the
anomalous services to point at the one that actually started the cascade,
instead of just listing everything that turned red at the same time.

> For the full write-up (motivation, interview narrative, demo script) see
> [CAUSEWAY_REVIEW.md](CAUSEWAY_REVIEW.md). This README covers what the
> project does, its current state, and the plan for what's left.

---

## How it works

```
Spans (real OTel traces, or synthetic data for now)
        │
        ▼
1. Ingestion            SpanRepository (SQLite)
        │
        ▼
2. Time series extraction   1-minute buckets per service:
                             latency p99 / error rate / throughput
        │
        ▼
3. Causal graph builder      Granger causality across every ordered
                              service pair × 3 metrics × N lags,
                              Bonferroni-corrected → networkx.DiGraph
        │
        ▼
4. Anomaly detection          Isolation Forest, trained per-service on
                               a normal-traffic baseline window
        │
        ▼
5. Root cause analysis        Backward walk from anomalous services
                               through the causal graph, scored by
                               path strength × timing alignment
        │
        ▼
6. Dashboard                  React + D3 causal graph, root cause panel,
                               service timeline, incident replay
```

## Current status

**Backend pipeline and dashboard complete.** The full pipeline runs
end-to-end on synthetic data, and the dashboard replays the planted incident
minute by minute:

| Layer | Module | Notes |
|---|---|---|
| Data models | [`causeway/models.py`](src/causeway/models.py) | `Span`, `ServiceTimeSeries`, `CausalEdge`, `MetricWindow`, `RootCauseReport`, ... |
| Storage | [`causeway/db/repository.py`](src/causeway/db/repository.py) | `SpanRepository` — SQLite-backed span store |
| Synthetic data | [`causeway/synthetic/generator.py`](src/causeway/synthetic/generator.py) | Generates normal traffic (with a real weak causal coupling between services) plus a planted cascading incident with known ground truth |
| Time series extraction | [`causeway/timeseries/extractor.py`](src/causeway/timeseries/extractor.py) | Buckets spans into 1-minute windows, interpolates gaps |
| Causal graph | [`causeway/causal/graph_builder.py`](src/causeway/causal/graph_builder.py) | `CausalGraphBuilder` — ADF stationarity check, Granger causality, Bonferroni correction |
| Anomaly detection | [`causeway/detection/anomaly.py`](src/causeway/detection/anomaly.py) | `IsolationForestDetector`, trained per service |
| Root cause analysis | [`causeway/analysis/root_cause.py`](src/causeway/analysis/root_cause.py) | `RootCauseAnalyzer` — backward graph walk + path scoring |
| Pipeline cache | [`causeway/pipeline.py`](src/causeway/pipeline.py) | `Pipeline` — builds the causal graph, detector, per-minute health timeline and incident list once per dataset instead of once per request |
| API | [`causeway/api/main.py`](src/causeway/api/main.py) | FastAPI app wiring the whole pipeline together; also serves the built dashboard |
| Dashboard | [`frontend/`](frontend/) | React + TypeScript + D3: force-directed causal graph, root cause panel, service metrics timeline, incident replay |

**Not built yet:**
- Real OpenTelemetry (OTLP) trace ingestion — currently only synthetic data via `POST /demo/seed`
- CI (GitHub Actions)
- Public demo / deployment

## Project plan

- [x] **Phase 1 — Backend pipeline.** Span model + SQLite storage, synthetic
      traffic/incident generator, time series extraction, Granger-causality
      graph builder with Bonferroni correction, Isolation Forest anomaly
      detection, backward-graph-walk root cause analyzer, FastAPI endpoints,
      unit + end-to-end tests.
- [ ] **Phase 2 — Real trace ingestion.** OpenTelemetry Collector → OTLP
      ingestion endpoint, replacing/augmenting the synthetic generator as the
      source of spans. Swap SQLite for TimescaleDB if volume warrants it.
- [x] **Phase 3 — Dashboard.** React app, D3 force-directed causal graph
      (edge thickness = F-statistic, label = lag), root cause panel with
      causal chain display, service metrics timeline, incident replay (play /
      scrub through time, `?t=<minutes>` deep links). Backed by a cached
      pipeline and new `/api/overview`, `/api/timeseries`, `/api/health` and
      `/api/incidents` endpoints.
- [ ] **Phase 4 — Demo polish.** README demo GIF, ARCHITECTURE.md, GitHub
      Actions CI, docker-compose, hosted demo.

## Tech stack

Python 3.12 · FastAPI · statsmodels (Granger causality, ADF test) ·
networkx (causal graph + traversal) · scikit-learn (Isolation Forest) ·
NumPy/pandas · SQLite · `uv` for dependency management · pytest.
Dashboard: React 19 · TypeScript · D3.js · Vite.

Planned: OpenTelemetry.

## Getting started

```bash
# install dependencies
uv sync

# run the API
uv run uvicorn causeway.api.main:app --reload

# seed synthetic demo data (normal traffic + a planted db-pool incident)
curl -X POST http://127.0.0.1:8000/demo/seed

# fetch the learned causal graph
curl http://127.0.0.1:8000/api/causal-graph

# ask for the root cause of the planted incident
curl http://127.0.0.1:8000/api/root-cause
```

### Dashboard

```bash
cd frontend
npm install

# development: hot reload on :5173, proxies /api and /demo to the API on :8000
npm run dev

# or build once and let the API serve it at http://127.0.0.1:8000/
npm run build
```

Open the dashboard, click **Generate demo data** (or POST `/demo/seed`), then
press play (or the space bar) to watch the cascade spread. Click or drag on the
timeline to scrub, use ← / → to step a minute (Shift for 10), click a node or
service to focus it, and hover an edge for its Granger statistics.
`?t=<minutes>` in the URL opens the replay at that offset from the incident,
e.g. `/?t=6`.

### Tests

```bash
uv run pytest                # fast tests only
uv run pytest -m slow        # includes the full pipeline / Granger causality run
uv run pytest -m ""          # everything
```

## API

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Liveness check |
| `/demo/seed` | POST | Generates and stores synthetic normal traffic plus a planted cascading incident (`db-pool` → `auth-service` → `payment-service` → `cart-service` → `notification-service`) |
| `/api/overview` | GET | Time window, baseline end, service list, and whether the causal graph has finished building (`{"seeded": false}` before seeding) |
| `/api/causal-graph` | GET | Causal graph learned from the baseline window: nodes/edges (lag, F-statistic, p-value, contributing metrics). Built once per dataset, then cached |
| `/api/root-cause` | GET | Root cause, confidence, and causal chain for the given `incident_time` (defaults to the end of the baseline window) |
| `/api/timeseries` | GET | Per-minute latency p99, error rate, throughput, anomaly score and health (`healthy` / `degraded` / `critical`) for every service; optional `start` / `end` |
| `/api/services/{service}/timeseries` | GET | Same, for one service |
| `/api/health` | GET | Every service's health at one minute (`at`, defaults to the latest) |
| `/api/incidents` | GET | Incidents detected after the baseline: runs where any service is critical, with short gaps merged |

Health comes from the Isolation Forest: a single anomalous minute is
`degraded` (that happens ~2% of the time in normal traffic), two or more
consecutive anomalous minutes are `critical`.

## Project layout

```
src/causeway/
├── api/            FastAPI app and routes
├── analysis/        Root cause analyzer
├── causal/           Granger-causality graph builder
├── db/                SQLite span repository
├── detection/         Isolation Forest anomaly detector
├── synthetic/          Synthetic traffic / incident generator
├── timeseries/          Span → time series extraction
├── pipeline.py          Cached pipeline: graph, detector, health, incidents
└── models.py            Shared dataclasses
tests/
frontend/
├── src/components/      CausalGraph, RootCausePanel, Timeline, ReplayControls
├── src/App.tsx          Data loading, replay state, layout
└── src/api.ts           Typed API client
```

## Known limitations

- **Granger causality is a statistical proxy for causality, not proof.** It
  tests whether a service's past values help predict another's future
  values — a good approximation for time-lagged propagation effects between
  services, not a philosophical guarantee.
- **Requires a training baseline.** The causal graph and anomaly detector are
  both fit on a window of "normal" traffic; a new service or a major
  architecture change needs that baseline rebuilt.
- **Doesn't catch novel failure modes.** A causal relationship that has never
  occurred in the baseline window won't appear in the graph — this is
  complementary to traditional alerting, not a replacement for it.
- **The root cause walk can name a healthy service.** Candidates are any
  ancestor of an anomalous service in the causal graph, whether or not that
  ancestor is anomalous itself, and confidence saturates at 99%. On the
  planted incident this gives the right answer; on a small single-service
  blip it can point at an upstream service that never misbehaved. Restricting
  candidates to anomalous services and adding the timing-alignment term are
  the next fixes.
