from __future__ import annotations

from datetime import datetime, timedelta

from causeway.models import Span
from causeway.timeseries.extractor import TimeSeriesExtractor


def _span(service: str, start: datetime, duration_ms: float, error: bool = False) -> Span:
    return Span(
        trace_id="t",
        span_id="s",
        parent_span_id=None,
        service_name=service,
        operation_name="op",
        start_time=start,
        end_time=start + timedelta(milliseconds=duration_ms),
        duration_ms=duration_ms,
        status_code=500 if error else 200,
        error=error,
    )


def test_bucket_with_enough_samples_computes_real_metrics():
    window_start = datetime(2026, 1, 1, 0, 0)
    spans = [
        _span("svc", window_start + timedelta(seconds=i * 5), duration_ms=100 + i, error=(i == 0))
        for i in range(10)
    ]

    ts = TimeSeriesExtractor().extract(spans, "svc", window_start, window_hours=1)

    assert ts.timestamps[0] == window_start
    assert ts.throughput[0] == 10
    assert ts.error_rate[0] == 0.1
    assert ts.latency_p99[0] > 100


def test_sparse_bucket_carries_forward_previous_value_instead_of_gap():
    window_start = datetime(2026, 1, 1, 0, 0)
    # Minute 0: enough samples for a real reading.
    spans = [_span("svc", window_start + timedelta(seconds=i), duration_ms=200) for i in range(10)]
    # Minute 1: too few samples (below MIN_SAMPLES_PER_BUCKET) -> should carry forward.
    spans.append(_span("svc", window_start + timedelta(minutes=1, seconds=1), duration_ms=999))

    ts = TimeSeriesExtractor().extract(spans, "svc", window_start, window_hours=1)

    assert ts.latency_p99[0] == ts.latency_p99[1]
    assert ts.throughput[1] == 0


def test_ignores_spans_outside_window_and_other_services():
    window_start = datetime(2026, 1, 1, 0, 0)
    spans = [
        _span("svc", window_start - timedelta(minutes=5), duration_ms=100),
        _span("other-service", window_start, duration_ms=100),
    ]

    ts = TimeSeriesExtractor().extract(spans, "svc", window_start, window_hours=1)

    assert all(t == 0 for t in ts.throughput)


def test_output_length_matches_requested_window():
    window_start = datetime(2026, 1, 1, 0, 0)
    ts = TimeSeriesExtractor().extract([], "svc", window_start, window_hours=2)

    assert len(ts.timestamps) == 2 * 60
    assert len(ts.latency_p99) == 2 * 60
