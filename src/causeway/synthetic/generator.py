from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import numpy as np

from causeway.models import Span


def _make_span(service: str, op: str, start: datetime, duration_ms: float, error: bool) -> Span:
    return Span(
        trace_id=str(uuid.uuid4()),
        span_id=str(uuid.uuid4()),
        parent_span_id=None,
        service_name=service,
        operation_name=op,
        start_time=start,
        end_time=start + timedelta(milliseconds=duration_ms),
        duration_ms=duration_ms,
        status_code=500 if error else 200,
        error=error,
        attributes={},
    )


def _build_latency_offsets(
    dependency_chain: list[str],
    total_minutes: int,
    rng: np.random.Generator,
    lag_minutes: int,
    phi: float,
    coupling: float,
    strength_ms: float,
) -> dict[str, np.ndarray]:
    """Latent per-minute latency offset for each service in a call chain.

    Each service's load is its own AR(1) process plus a fraction of the
    upstream service's load shifted forward by `lag_minutes` — this mirrors
    how latency actually propagates through a real call chain (A calls B
    calls C), and is what gives Granger causality genuine signal to detect
    in the "normal" baseline, not just during a planted incident.
    """
    upstream_load = np.zeros(total_minutes)
    offsets: dict[str, np.ndarray] = {}
    for service in dependency_chain:
        own_noise = rng.normal(0, 1.0, size=total_minutes)
        own_load = np.zeros(total_minutes)
        for t in range(1, total_minutes):
            own_load[t] = phi * own_load[t - 1] + own_noise[t]

        shifted_upstream = np.zeros(total_minutes)
        if lag_minutes < total_minutes:
            shifted_upstream[lag_minutes:] = upstream_load[:-lag_minutes]

        combined = own_load + coupling * shifted_upstream
        offsets[service] = combined * strength_ms
        upstream_load = combined

    return offsets


def generate_normal_traffic(
    services: list[str],
    hours: int,
    start: datetime,
    base_rps: float = 0.5,
    seed: int = 42,
    dependency_chain: list[str] | None = None,
    coupling_lag_minutes: int = 2,
) -> list[Span]:
    """Generate normal traffic across services for the given window.

    Latency is log-normal (p50 ~= 50ms), error rate is ~0.5%, and throughput
    follows a daily pattern (more traffic 9am-5pm).

    If `dependency_chain` is given, each service's latency baseline is
    weakly coupled to the previous service's in the list, lagged by
    `coupling_lag_minutes` — a real (if subtle) causal relationship that
    exists during normal operation, independent of any planted incident.
    """
    rng = np.random.default_rng(seed)
    spans: list[Span] = []

    total_minutes = hours * 60
    latency_offsets = (
        _build_latency_offsets(
            dependency_chain,
            total_minutes,
            rng,
            lag_minutes=coupling_lag_minutes,
            phi=0.9,
            coupling=0.6,
            strength_ms=25.0,
        )
        if dependency_chain
        else {}
    )

    for minute in range(total_minutes):
        bucket_time = start + timedelta(minutes=minute)
        daily_factor = 1.5 if 9 <= bucket_time.hour <= 17 else 0.6

        for service in services:
            n_requests = rng.poisson(base_rps * 60 * daily_factor)
            offset = latency_offsets[service][minute] if service in latency_offsets else 0.0
            base_latency_ms = max(50.0 + offset, 5.0)
            for _ in range(n_requests):
                offset_s = rng.uniform(0, 60)
                span_start = bucket_time + timedelta(seconds=offset_s)
                duration = float(rng.lognormal(mean=np.log(base_latency_ms), sigma=0.4))
                error = bool(rng.random() < 0.005)
                spans.append(_make_span(service, "handle_request", span_start, duration, error))

    return spans


def generate_incident(
    services: list[str],
    start_time: datetime,
    root_cause_service: str,
    downstream_chain: list[str],
    duration_minutes: int = 20,
    lag_minutes: int = 2,
    seed: int = 7,
) -> list[Span]:
    """Plant a cascading incident on top of normal traffic.

    root_cause_service degrades at start_time. Each service in
    downstream_chain follows in order, each `lag_minutes` after the previous
    one — a known-ground-truth causal chain that the pipeline should recover.
    """
    rng = np.random.default_rng(seed)
    spans: list[Span] = []

    chain = [root_cause_service, *downstream_chain]
    onset = {chain[i]: start_time + timedelta(minutes=lag_minutes * i) for i in range(len(chain))}

    for service in services:
        service_onset = onset.get(service)
        if service_onset is None:
            continue

        for minute in range(duration_minutes):
            bucket_time = service_onset + timedelta(minutes=minute)
            n_requests = rng.poisson(120)  # elevated traffic under retry storms
            for _ in range(n_requests):
                offset_s = rng.uniform(0, 60)
                span_start = bucket_time + timedelta(seconds=offset_s)
                duration = float(rng.lognormal(mean=np.log(400), sigma=0.6))
                error = bool(rng.random() < 0.35)
                spans.append(_make_span(service, "handle_request", span_start, duration, error))

    return spans
