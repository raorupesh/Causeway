from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np


@dataclass
class Span:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    service_name: str
    operation_name: str
    start_time: datetime
    end_time: datetime
    duration_ms: float
    status_code: int
    error: bool
    attributes: dict = field(default_factory=dict)


@dataclass
class ServiceTimeSeries:
    service: str
    timestamps: list[datetime]
    latency_p99: np.ndarray
    error_rate: np.ndarray
    throughput: np.ndarray


@dataclass
class CausalEdge:
    source: str
    target: str
    metric: str
    lag_minutes: int
    p_value: float
    f_statistic: float


@dataclass
class MetricWindow:
    service: str
    timestamp: datetime
    latency_p99: float
    error_rate: float
    throughput: float
    prev_latency_p99: float = 0.0
    prev_error_rate: float = 0.0
    prev_throughput: float = 0.0


@dataclass
class AnomalyScore:
    service: str
    is_anomalous: bool
    score: float
    anomalous_features: list[str] = field(default_factory=list)


@dataclass
class RootCauseCandidate:
    service: str
    score: float
    path: list[str]
    total_lag: int


@dataclass
class RootCauseReport:
    status: str  # 'ROOT_CAUSE_IDENTIFIED' | 'NO_ANOMALY' | 'INDEPENDENT_FAILURES'
    root_cause: str | None = None
    confidence: float | None = None
    causal_chain: list[dict] = field(default_factory=list)
    anomalous_services: list[str] = field(default_factory=list)
    total_propagation_minutes: int | None = None
    all_candidates: list[RootCauseCandidate] = field(default_factory=list)
    message: str | None = None
