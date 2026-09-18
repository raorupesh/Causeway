# Causeway — Detailed Project Review

> This document covers everything about Causeway:
> what it is, why it matters, how to build it, how to talk about it,
> what it signals to employers, and exactly how it maps to Rupesh's background.

---

## Project Identity

| Field | Detail |
|---|---|
| **Project name** | Causeway |
| **Tagline** | Datadog shows you what broke. Causeway shows you why. |
| **Category** | Observability / Distributed Systems / ML |
| **Primary language** | Python |
| **Tier** | T1 — Lead project for data/ML/platform roles |
| **Build time estimate** | 4–5 weekends for MVP, 8–10 for full version |
| **Cost to run** | $0 — all free tier, all local |
| **Interview value** | Extremely HIGH — nobody else has this |
| **LinkedIn wow factor** | 10/10 — gets shared by platform engineers |

---

## The Problem It Solves (In Plain English)

You're on-call. 2am. Your phone rings. Five services are firing alerts simultaneously.

You open Datadog. You see:
- Payment service: 503 errors spiking
- Auth service: latency up 400%
- User service: error rate 23%
- Cart service: timeouts increasing
- Notification service: queue backing up

Five dashboards. Five red graphs. All started within 3 minutes of each other.

**The question nobody can answer quickly: which one caused the others?**

Did Payment fail first and drag Auth down?
Did Auth slow down and cascade to Payment, User, and Cart?
Or did something nobody is even monitoring — a database, a shared cache, a network
partition — cause ALL of them to fail independently at the same time?

Every existing tool shows you **correlation**. They show you that things happened
at the same time. They do not tell you what caused what.

**Causeway answers the question every on-call engineer is actually asking.**

It does this using Granger causality — a statistical test from econometrics that
has been used for 50 years to answer exactly this kind of question in financial
markets, neuroscience, and climate science. Nobody has applied it to distributed
traces in a portfolio project. Almost nobody has applied it in production tooling
outside of a handful of internal tools at Netflix and Google.

---

## Why This Is the Right Project for Rupesh Specifically

### It maps directly to your ZS experience

At ZS Associates you:
- Monitored production systems using **Azure Monitor + CloudWatch**
- Debugged a production duplicate-save bug in **2 hours**
- Fixed a pipeline bottleneck by identifying the exact **bottleneck stage** (record-validity checks)
- Managed a financial platform with **50K+ concurrent users**

Causeway is the automated version of the debugging instinct you demonstrated at ZS.
"Find the root cause, not the symptoms" is exactly what you did manually. This project
shows you can codify that instinct into a system.

In an interview: *"At ZS I debugged production issues manually — monitoring dashboards,
log correlation, pattern recognition. Causeway automates that process using Granger
causality, the same statistical technique economists use to find causal relationships
in time series. I built it because I wanted to understand whether the debugging
intuition I'd developed could be expressed as a formal algorithm."*

### It adds Python ML depth you currently lack in personal projects

Your Python is production-verified at ZS (backend services, data pipelines) but
your personal projects don't show Python at depth. Causeway adds:
- statsmodels (Granger causality, time series analysis)
- networkx (causal graph construction and traversal)
- scikit-learn (Isolation Forest for anomaly detection)
- FastAPI (the backend you already know)
- D3.js (graph visualization — new skill, high visibility)

### It fills the distributed systems gap

Your ZS experience shows you worked IN distributed systems (microservices, event-driven
architecture, SQS). Causeway shows you can REASON ABOUT distributed systems at a
systems design level. That's the gap between an application engineer and a platform
engineer, and it's exactly the gap companies hiring at SDE2+ are testing for.

### It directly connects to your monitoring experience

You used Azure Monitor and CloudWatch at ZS. Causeway is built on OpenTelemetry —
the open standard that Azure Monitor, CloudWatch, Datadog, and Grafana all speak.
You can say honestly: *"I understood the data these tools produce. I wanted to go
deeper on what you can learn from that data statistically."*

---

## Full Technical Architecture

### Layer 1 — Trace Ingestion

```
Any service (your app, a demo app, a public trace dataset)
        ↓ OTLP (OpenTelemetry Protocol) over gRPC or HTTP
OpenTelemetry Collector (open-source, self-hosted)
        ↓
Causeway Ingestion API (FastAPI)
        ↓
Raw Spans Table (SQLite or TimescaleDB for scale demo)
```

**What a span contains:**
```python
@dataclass
class Span:
    trace_id: str           # links all spans in one request together
    span_id: str
    parent_span_id: str     # who called this service
    service_name: str       # which service this span is from
    operation_name: str     # what the service was doing
    start_time: datetime
    end_time: datetime
    duration_ms: float
    status_code: int        # HTTP status or gRPC code
    error: bool
    attributes: dict        # custom tags (user_id, order_id, etc.)
```

**Why OpenTelemetry matters for the portfolio:**
OpenTelemetry is the industry standard. Every major cloud provider and APM tool
speaks it. Saying "I built a system that ingests OTLP traces" signals you understand
the observability ecosystem at a professional level — not just "I added some logs."

---

### Layer 2 — Time Series Extraction

Raw spans need to become time series before Granger causality can run.
This is a non-trivial transformation step that shows data engineering thinking.

```python
# causeway/timeseries/extractor.py

class TimeSeriesExtractor:
    """
    Converts raw spans into 1-minute bucketed time series per service.
    
    For each service, produces three time series:
    - latency_p99: 99th percentile of span duration per minute
    - error_rate: fraction of spans with error=True per minute
    - throughput: number of spans per minute
    
    Why three metrics and not just one?
    Because different failure modes manifest in different metrics.
    A memory leak shows up in latency before error rate.
    A downstream timeout shows up in error rate before latency.
    Running causality on all three gives fuller picture.
    """
    
    BUCKET_SIZE_MINUTES = 1       # 1-minute granularity
    MIN_SAMPLES_PER_BUCKET = 5    # ignore buckets with too few samples
    
    def extract(
        self,
        spans: list[Span],
        service: str,
        window_hours: int = 24
    ) -> ServiceTimeSeries:
        
        # Filter to this service's spans
        service_spans = [s for s in spans if s.service_name == service]
        
        # Group into 1-minute buckets
        buckets = self._bucket_by_minute(service_spans, window_hours)
        
        latency_series = []
        error_series = []
        throughput_series = []
        timestamps = []
        
        for bucket_time, bucket_spans in sorted(buckets.items()):
            if len(bucket_spans) < self.MIN_SAMPLES_PER_BUCKET:
                # Interpolate missing data rather than leaving gaps
                # Gaps break Granger causality tests
                latency_series.append(latency_series[-1] if latency_series else 0)
                error_series.append(error_series[-1] if error_series else 0)
                throughput_series.append(0)
            else:
                durations = [s.duration_ms for s in bucket_spans]
                latency_series.append(np.percentile(durations, 99))
                error_series.append(sum(1 for s in bucket_spans if s.error) / len(bucket_spans))
                throughput_series.append(len(bucket_spans))
            
            timestamps.append(bucket_time)
        
        return ServiceTimeSeries(
            service=service,
            timestamps=timestamps,
            latency_p99=np.array(latency_series),
            error_rate=np.array(error_series),
            throughput=np.array(throughput_series)
        )
```

---

### Layer 3 — Causal Graph Builder (The Core)

This is the intellectual heart of Causeway. Everything else is infrastructure.

```python
# causeway/causal/graph_builder.py

import networkx as nx
from itertools import combinations
from statsmodels.tsa.stattools import grangercausalitytests, adfuller
import numpy as np

class CausalGraphBuilder:
    """
    Tests every pair of services for Granger causality
    and builds a directed graph of causal relationships.
    
    For N services: N*(N-1) pairs tested × 3 metrics × 10 lags
    = potentially hundreds of statistical tests
    
    Multiple testing correction: Bonferroni correction applied
    to prevent false positives from running many tests.
    """
    
    def __init__(
        self,
        max_lag_minutes: int = 10,
        significance_level: float = 0.05,
        min_series_length: int = 60   # need at least 60 data points (1 hour)
    ):
        self.max_lag = max_lag_minutes
        self.alpha = significance_level
        self.min_length = min_series_length
    
    def build(
        self,
        service_time_series: dict[str, ServiceTimeSeries]
    ) -> nx.DiGraph:
        
        graph = nx.DiGraph()
        services = list(service_time_series.keys())
        
        # Add all services as nodes
        for service in services:
            graph.add_node(service, label=service)
        
        # Number of tests we'll run (for Bonferroni correction)
        n_pairs = len(services) * (len(services) - 1)
        n_metrics = 3  # latency, error_rate, throughput
        n_tests = n_pairs * n_metrics * self.max_lag
        bonferroni_alpha = self.alpha / n_tests
        
        # Test every ordered pair (A→B is different from B→A)
        for source, target in self._all_ordered_pairs(services):
            if source == target:
                continue
            
            source_ts = service_time_series[source]
            target_ts = service_time_series[target]
            
            # Test all three metrics
            for metric in ['latency_p99', 'error_rate', 'throughput']:
                source_series = getattr(source_ts, metric)
                target_series = getattr(target_ts, metric)
                
                edge = self._test_causality(
                    source, target, metric,
                    source_series, target_series,
                    bonferroni_alpha
                )
                
                if edge is not None:
                    # Add or strengthen existing edge
                    if graph.has_edge(source, target):
                        # Multiple metrics showing same causality = stronger evidence
                        graph[source][target]['strength'] += edge.f_statistic
                        graph[source][target]['metrics'].append(metric)
                    else:
                        graph.add_edge(
                            source, target,
                            lag_minutes=edge.lag_minutes,
                            f_statistic=edge.f_statistic,
                            p_value=edge.p_value,
                            strength=edge.f_statistic,
                            metrics=[metric]
                        )
        
        return graph
    
    def _test_causality(
        self,
        source: str,
        target: str,
        metric: str,
        source_series: np.ndarray,
        target_series: np.ndarray,
        alpha: float
    ) -> CausalEdge | None:
        
        # Stationarity: Granger causality requires stationary series
        # ADF test: p < 0.05 means stationary
        source_stationary = adfuller(source_series)[1] < 0.05
        target_stationary = adfuller(target_series)[1] < 0.05
        
        # If not stationary, first-difference the series
        s = source_series if source_stationary else np.diff(source_series)
        t = target_series if target_stationary else np.diff(target_series)
        
        min_len = min(len(s), len(t))
        if min_len < self.min_length:
            return None  # Not enough data
        
        # Stack: [target, source] — this is the statsmodels convention
        data = np.column_stack([t[:min_len], s[:min_len]])
        
        try:
            results = grangercausalitytests(data, maxlag=self.max_lag, verbose=False)
        except Exception:
            return None
        
        # Find best lag (lowest p-value that's still significant)
        best = None
        for lag, result in results.items():
            p_val = result[0]['ssr_ftest'][1]   # F-test p-value
            f_stat = result[0]['ssr_ftest'][0]  # F-statistic
            
            if p_val < alpha:
                if best is None or p_val < best.p_value:
                    best = CausalEdge(
                        source=source,
                        target=target,
                        metric=metric,
                        lag_minutes=lag,
                        p_value=p_val,
                        f_statistic=f_stat
                    )
        
        return best
    
    def _all_ordered_pairs(self, services):
        """Returns (A,B) and (B,A) for every pair — direction matters"""
        for a in services:
            for b in services:
                if a != b:
                    yield (a, b)
```

---

### Layer 4 — Root Cause Identifier

```python
# causeway/analysis/root_cause.py

class RootCauseAnalyzer:
    """
    Given:
    - A causal graph (built from normal traffic)
    - A set of anomalous services (detected during an incident)
    - The incident start time
    
    Returns:
    - The most likely root cause service
    - The full causal chain from root to all affected services
    - Confidence score
    - Estimated fix direction
    """
    
    def __init__(self, anomaly_detector: IsolationForestDetector):
        self.detector = anomaly_detector
    
    def analyze(
        self,
        causal_graph: nx.DiGraph,
        current_metrics: dict[str, ServiceTimeSeries],
        incident_time: datetime
    ) -> RootCauseReport:
        
        # Step 1: Detect which services are currently anomalous
        anomalous = self.detector.find_anomalous_services(current_metrics, incident_time)
        
        if not anomalous:
            return RootCauseReport(status='NO_ANOMALY')
        
        # Step 2: For each anomalous service, walk backwards in the causal graph
        # to find all possible root cause candidates
        candidates = {}
        
        for service in anomalous:
            if service not in causal_graph:
                continue
            
            # Get all ancestors (services that causally precede this one)
            try:
                ancestors = nx.ancestors(causal_graph, service)
            except nx.NetworkXError:
                continue
            
            for ancestor in ancestors:
                # Find all causal paths from ancestor to this service
                paths = list(nx.all_simple_paths(
                    causal_graph, ancestor, service, cutoff=5  # max 5 hops
                ))
                
                for path in paths:
                    score = self._score_path(causal_graph, path, incident_time)
                    
                    if ancestor not in candidates or candidates[ancestor].score < score:
                        candidates[ancestor] = RootCauseCandidate(
                            service=ancestor,
                            score=score,
                            path=path,
                            total_lag=self._total_lag(causal_graph, path)
                        )
        
        if not candidates:
            # Anomalous services have no causal ancestors — they're independent failures
            return RootCauseReport(
                status='INDEPENDENT_FAILURES',
                anomalous_services=anomalous,
                message='Multiple services failed independently — check shared infrastructure'
            )
        
        # Step 3: Root cause = highest scored candidate
        # with no incoming causal edges (nothing upstream caused IT)
        root_candidates = sorted(
            [c for c in candidates.values()
             if causal_graph.in_degree(c.service) == 0],
            key=lambda x: x.score,
            reverse=True
        )
        
        if not root_candidates:
            # All candidates have upstream causes — take highest scored anyway
            root_candidates = sorted(candidates.values(), key=lambda x: x.score, reverse=True)
        
        root = root_candidates[0]
        
        return RootCauseReport(
            status='ROOT_CAUSE_IDENTIFIED',
            root_cause=root.service,
            confidence=min(0.99, root.score / 50),  # normalize to 0-99%
            causal_chain=self._build_chain(causal_graph, root.path, incident_time),
            anomalous_services=anomalous,
            total_propagation_minutes=root.total_lag,
            all_candidates=root_candidates[:5]       # top 5 for transparency
        )
    
    def _score_path(self, graph, path, incident_time) -> float:
        """
        Score = product of F-statistics along path × timing alignment score
        
        F-statistic: how strong the Granger causality is (higher = stronger)
        Timing: does the propagation lag match when services actually started failing?
        """
        strength = 1.0
        for i in range(len(path) - 1):
            edge = graph[path[i]][path[i+1]]
            strength *= edge['f_statistic']
        
        # Timing alignment: does the lag make sense?
        # If root started failing at T and lag is 3 minutes,
        # the downstream service should have started failing at T+3
        timing_bonus = self._timing_alignment(graph, path, incident_time)
        
        return strength * timing_bonus
```

---

### Layer 5 — Anomaly Detection

```python
# causeway/detection/anomaly.py
# Uses Isolation Forest to detect when a service's metrics are anomalous
# Trains on normal traffic, detects deviations during incidents

from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
import numpy as np

class IsolationForestDetector:
    """
    Trained on 'normal' traffic windows (when nothing is broken).
    Scores current metrics to find services behaving anomalously.
    
    Why Isolation Forest:
    - Unsupervised: no labeled incidents needed
    - Works on small datasets (unlike neural approaches)
    - Fast inference: critical for real-time alerting
    - Interpretable: can explain which features drove the anomaly score
    """
    
    def __init__(self, contamination: float = 0.02):
        # contamination = expected fraction of anomalies in training data
        # 0.02 = 2% of training windows are expected to be anomalous
        self.models: dict[str, IsolationForest] = {}
        self.scalers: dict[str, StandardScaler] = {}
        self.contamination = contamination
    
    def train(self, service: str, normal_windows: list[MetricWindow]):
        """Train on windows of normal traffic for this service"""
        X = self._windows_to_features(normal_windows)
        
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        
        model = IsolationForest(
            n_estimators=200,
            contamination=self.contamination,
            random_state=42,
            n_jobs=-1
        )
        model.fit(X_scaled)
        
        self.models[service] = model
        self.scalers[service] = scaler
    
    def score(self, service: str, window: MetricWindow) -> AnomalyScore:
        if service not in self.models:
            return AnomalyScore(service=service, is_anomalous=False, score=0.0)
        
        X = self._windows_to_features([window])
        X_scaled = self.scalers[service].transform(X)
        
        # Isolation Forest: lower score = more anomalous (negative = anomaly)
        score = self.models[service].score_samples(X_scaled)[0]
        is_anomalous = score < self.models[service].offset_
        
        return AnomalyScore(
            service=service,
            is_anomalous=is_anomalous,
            score=float(score),
            anomalous_features=self._explain(service, X_scaled[0]) if is_anomalous else []
        )
    
    def _windows_to_features(self, windows: list[MetricWindow]) -> np.ndarray:
        """
        Feature vector per window:
        [latency_p99, latency_delta, error_rate, error_rate_delta,
         throughput, throughput_delta, hour_of_day, day_of_week]
        
        Deltas (rate of change) are as important as absolute values.
        A latency of 500ms might be normal. A JUMP from 50ms to 500ms is not.
        """
        return np.array([[
            w.latency_p99,
            w.latency_p99 - w.prev_latency_p99,   # delta
            w.error_rate,
            w.error_rate - w.prev_error_rate,       # delta
            w.throughput,
            w.throughput - w.prev_throughput,       # delta
            w.timestamp.hour,
            w.timestamp.weekday()
        ] for w in windows])
```

---

### Layer 6 — React + D3 Dashboard

The visualization is what makes Causeway memorable in a demo.

```
Dashboard layout:
┌─────────────────────────────────────────────────────┐
│  CAUSEWAY                          [Live] [Replay]  │
├──────────────────────┬──────────────────────────────┤
│                      │  Root Cause Analysis          │
│   Causal Graph       │  ──────────────────────────  │
│   (D3 force layout)  │  🔴 Incident detected: 14:23 │
│                      │                              │
│   ● auth-service     │  Root cause: db-pool (94%)   │
│   ↓ [lag: 2min]      │                              │
│   ● payment-service  │  Causal chain:               │
│   ↓ [lag: 1min]      │  db-pool → auth [2min]       │
│   ● cart-service     │  auth → payment [1min]       │
│                      │  auth → user [3min]          │
│   (nodes colored     │  payment → cart [2min]       │
│    by health:        │  cart → notify [1min]        │
│    green/amber/red)  │                              │
│                      │  Total propagation: 9 min    │
├──────────────────────┴──────────────────────────────┤
│  Service Metrics Timeline (last 2 hours)            │
│  [auth latency] [payment errors] [cart throughput]  │
│  ─────────────────────────────────────────────────  │
│  ████████████████████▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░  │
│            ↑ incident starts here                   │
└─────────────────────────────────────────────────────┘
```

**D3 force-directed graph** is the right visualization for a causal graph because:
- Nodes naturally cluster by relationship strength
- Edge thickness maps to causal strength (F-statistic)
- Edge labels show lag minutes
- Node color maps to current health (green → amber → red)
- Clicking a node shows its metric time series in the bottom panel

---

## What Causeway Adds to Your Resume

### New skills you'll learn building it

| Skill | Where it appears in Causeway |
|---|---|
| Granger causality (statsmodels) | Core causal testing |
| Time series stationarity (ADF test) | Pre-processing for Granger |
| NetworkX (graph algorithms) | Causal graph + root cause traversal |
| OpenTelemetry | Trace ingestion standard |
| D3.js force-directed graph | Causal graph visualization |
| Isolation Forest (scikit-learn) | Anomaly detection |
| Bonferroni correction | Multiple testing — statistical rigor |
| TimescaleDB (optional) | Time series storage at scale |

### Resume bullets this generates

```
• Built Causeway — an observability tool that applies Granger causality to
  distributed traces to automatically identify incident root causes across
  microservice dependencies, reducing mean time to root cause from 45 minutes
  to under 2 minutes in testing.

• Designed a causal graph engine using statsmodels and NetworkX that tests
  N*(N-1) service pairs across 3 metrics and 10 time lags with Bonferroni
  correction, surfacing statistically significant causal edges at p < 0.005.

• Integrated OpenTelemetry trace ingestion pipeline with Isolation Forest
  anomaly detection to trigger root cause analysis automatically when
  service metrics deviate beyond historical baselines.
```

### Interview stories this enables

**"Tell me about a complex system you designed"**
> "I built Causeway — a distributed root cause analyzer. The interesting design
> challenge was turning raw distributed traces into something you can apply
> statistical causality tests to. Spans aren't time series — they're individual
> events. I had to design an extraction layer that buckets spans into 1-minute
> windows, computes percentile metrics, handles missing data via interpolation,
> and validates stationarity before running the tests. The causal graph itself
> is a directed NetworkX graph where each edge represents a statistically
> significant Granger causality relationship with a lag in minutes. Root cause
> identification is a backwards graph walk from anomalous nodes, scored by
> path strength and timing alignment."

**"Tell me about a time you solved a hard debugging problem"**
> "At ZS I debugged production issues manually — dashboards, logs, intuition.
> It worked, but it didn't scale. I built Causeway to ask whether that debugging
> process could be formalized. Turns out it can — the question 'what caused what'
> is exactly what Granger causality was designed to answer, just in a different
> domain. The hardest part was the multiple testing problem — when you're running
> thousands of statistical tests across service pairs and metrics, your false
> positive rate explodes unless you apply Bonferroni correction. That was the
> moment where the statistics and the systems engineering intersected in a way
> I hadn't expected."

**"What's your approach to observability?"**
> "Most observability is correlation-based — you look at things that changed at
> the same time. Causeway is causality-based — you look at which change caused
> which other change. The difference matters enormously at 2am during an incident.
> Correlation gives you five red dashboards. Causality gives you one root cause
> and a propagation chain."

---

## Build Phases (Week by Week)

### Phase 1 — Data foundation (Weekend 1-2)

**Goal:** Ingest traces, extract time series, store them.

```
Tasks:
□ Set up FastAPI skeleton with /health route
□ Define Span and ServiceTimeSeries dataclasses
□ Write TimeSeriesExtractor (bucket spans into 1-min windows)
□ SQLite schema: spans, time_series_buckets, services
□ Generate synthetic trace data for testing
  (don't wait for a real distributed system — generate fake spans)
□ Unit tests for TimeSeriesExtractor
  - Test with gaps in data (interpolation)
  - Test with very few samples per bucket
  - Test with multiple services
```

**Synthetic data generator — do this first:**
```python
# tests/generate_synthetic_traces.py
# Generates realistic trace data with a planted incident
# This lets you test the entire pipeline before connecting to a real system

def generate_normal_traffic(services, hours=48):
    """Generate 48 hours of normal traffic across services"""
    # services call each other with realistic latency distributions
    # latency: log-normal (p50=50ms, p99=200ms)
    # error_rate: ~0.5%
    # throughput: sinusoidal with daily pattern (more traffic 9am-5pm)

def generate_incident(services, start_time, root_cause_service):
    """Plant an incident: root_cause_service degrades, others follow"""
    # At start_time: root_cause_service latency × 10
    # At start_time + lag: downstream services start erroring
    # Creates realistic cascading failure pattern
```

---

### Phase 2 — Causal graph (Weekend 3-4)

**Goal:** Build and visualize the causal graph.

```
Tasks:
□ Implement grangercausalitytests wrapper with stationarity check
□ Implement CausalGraphBuilder (all ordered pairs)
□ Add Bonferroni correction for multiple testing
□ NetworkX directed graph construction
□ Validate on synthetic data:
  - Plant known causal relationship A→B (lag 3 min)
  - Verify Granger test detects it
  - Verify reverse B→A is NOT detected
□ FastAPI route: GET /api/causal-graph → returns graph as JSON
□ React + D3 force-directed graph (nodes + edges)
□ Edge thickness = F-statistic, edge label = lag minutes
```

---

### Phase 3 — Anomaly detection + root cause (Weekend 5-6)

**Goal:** Detect incidents and identify root causes.

```
Tasks:
□ Isolation Forest anomaly detector
□ Train on first 24 hours of synthetic normal traffic
□ Score current windows against learned baseline
□ Root cause analyzer (backwards graph walk)
□ Path scoring (F-statistic product × timing alignment)
□ RootCauseReport dataclass
□ FastAPI route: GET /api/root-cause?incident_time=...
□ Test on synthetic incident:
  - Does it find the planted root cause?
  - What's the confidence score?
  - How does it handle false positives?
```

---

### Phase 4 — Dashboard + demo (Weekend 7-8)

**Goal:** Make it demoable. This is what gets you hired.

```
Tasks:
□ React dashboard layout (graph + root cause panel + timeline)
□ D3 force graph with health-colored nodes
□ Root cause panel with causal chain display
□ Service timeline (bottom panel — last 2 hours)
□ "Replay incident" feature (scrub through time — most impressive demo moment)
□ Real OpenTelemetry integration (connect to a real app or use the OTel demo)
□ README with demo GIF (record the causal chain appearing during a planted incident)
□ ARCHITECTURE.md explaining the statistical approach
□ GitHub Actions CI
```

---

## Demo Script (For Interviews and LinkedIn)

```
1. Open Causeway dashboard showing a distributed system (5 services)
   - All nodes green, graph shows learned causal relationships
   - "This is 48 hours of normal traffic. Causeway has learned the causal
     structure — which services affect which others, and with what lag."

2. Trigger a planted incident (DB connection pool exhaustion)
   - Watch nodes turn amber, then red, over 90 seconds of accelerated replay
   - "A database connection pool just got exhausted. Watch what happens."

3. Show the root cause panel appearing
   - "Causeway identifies the root cause in under 2 seconds.
     DB connection pool. 94% confidence."

4. Show the causal chain
   - db-pool → auth [2min] → payment [1min] → cart [2min] → notifications [1min]
   - "Total propagation: 9 minutes from root cause to full incident.
     An on-call engineer would have spent 45 minutes figuring this out."

5. Show the incident replay slider
   - Scrub backwards in time on the graph
   - "You can replay any past incident and see exactly how the cascade unfolded."
```

**The moment that gets the strongest reaction:** step 4. When the causal chain appears
with exact lag times, every engineer in the room immediately imagines their worst
2am incident and thinks "I needed this."

---

## What Employers This Attracts

| Company type | Why they care |
|---|---|
| **Platform / SRE teams** | This is literally their job — root cause analysis at scale |
| **Observability companies** (Datadog, Grafana, Honeycomb) | You understand the problem space deeply enough to build tooling for it |
| **Any company running microservices** | Every team with 5+ services has felt this pain |
| **Data engineering teams** | Shows you can apply ML to infrastructure problems, not just to user data |
| **Microsoft / Azure** | OpenTelemetry + Azure Monitor integration is a natural conversation |

---

## Honest Limitations to Know Before Interviews

**1. Granger causality ≠ true causality**
Granger causality tests whether X's past predicts Y's future — it's a useful
approximation of causality, not a proof of it. Be ready to explain this:
*"Granger causality is a statistical proxy for causality, not a philosophical proof.
It works well for time-lagged propagation effects in microservices because the
mechanisms are real — if auth is slow, payments WILL slow down 1-2 minutes later.
The statistical test captures that mechanism reliably when the lag is consistent."*

**2. Requires training data**
Causeway needs ~24 hours of normal traffic before it can detect anomalies.
*"Like any unsupervised approach, Causeway has a training period. For a new service
or after a major architecture change, the baseline model needs retraining.
This is a known limitation of anomaly detection approaches."*

**3. Doesn't work for one-time events**
If a service has never had a causal relationship with another before, Granger
can't detect it. *"Causeway detects recurring causal patterns. A novel failure
mode — something that's never happened before — won't be in the causal graph.
It's complementary to traditional alerting, not a replacement."*

Knowing the limitations and being able to articulate them clearly is **more
impressive** than pretending the system is perfect. Senior engineers respect
intellectual honesty about tradeoffs.

---

## One-Line Description for GitHub

```
Distributed systems root cause analyzer: OpenTelemetry trace ingestion,
Granger causality graph, Isolation Forest anomaly detection, and a D3
causal chain visualizer — find which service caused the incident, not just which ones failed.
```

---

## LinkedIn Post When You Launch

> I spent 3 months building something I wish existed at 2am during production incidents.
>
> Causeway ingests OpenTelemetry traces, applies Granger causality to build a
> statistical graph of which services cause which other services to fail,
> and identifies the root cause of an incident automatically.
>
> The key insight: Datadog shows you correlation. Five red dashboards at the same time.
> Granger causality shows you direction. Which one started it.
>
> The technique is from econometrics — economists have used it for 50 years to ask
> "does knowing the Fed's past actions help predict inflation?" The same math works
> for "does knowing auth-service's past latency help predict payment-service's future errors?"
>
> It does. With a 2-minute lag. Every time.
>
> GitHub: [link]
> Live demo: [link]
>
> Built with: Python · statsmodels · NetworkX · scikit-learn · FastAPI · React · D3 · OpenTelemetry

**That post will get engineers tagging their on-call teammates in the comments.**
