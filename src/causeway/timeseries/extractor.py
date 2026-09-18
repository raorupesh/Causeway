from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

import numpy as np

from causeway.models import Span, ServiceTimeSeries


class TimeSeriesExtractor:
    """
    Converts raw spans into fixed-size (default 1-minute) bucketed time
    series per service.

    For each service, produces three time series:
    - latency_p99: 99th percentile of span duration per bucket
    - error_rate: fraction of spans with error=True per bucket
    - throughput: number of spans per bucket

    Buckets with too few samples are filled by carrying forward the previous
    value (rather than leaving gaps) because gaps break the Granger
    causality tests downstream.
    """

    BUCKET_SIZE_MINUTES = 1
    MIN_SAMPLES_PER_BUCKET = 5

    def extract(
        self,
        spans: list[Span],
        service: str,
        window_start: datetime,
        window_hours: int = 24,
    ) -> ServiceTimeSeries:
        service_spans = [s for s in spans if s.service_name == service]
        buckets = self._bucket_by_minute(service_spans, window_start, window_hours)

        latency_series: list[float] = []
        error_series: list[float] = []
        throughput_series: list[float] = []
        timestamps: list[datetime] = []

        n_buckets = (window_hours * 60) // self.BUCKET_SIZE_MINUTES
        for i in range(n_buckets):
            bucket_time = window_start + timedelta(minutes=i * self.BUCKET_SIZE_MINUTES)
            bucket_spans = buckets.get(bucket_time, [])

            if len(bucket_spans) < self.MIN_SAMPLES_PER_BUCKET:
                latency_series.append(latency_series[-1] if latency_series else 0.0)
                error_series.append(error_series[-1] if error_series else 0.0)
                throughput_series.append(0.0)
            else:
                durations = [s.duration_ms for s in bucket_spans]
                latency_series.append(float(np.percentile(durations, 99)))
                error_series.append(sum(1 for s in bucket_spans if s.error) / len(bucket_spans))
                throughput_series.append(float(len(bucket_spans)))

            timestamps.append(bucket_time)

        return ServiceTimeSeries(
            service=service,
            timestamps=timestamps,
            latency_p99=np.array(latency_series),
            error_rate=np.array(error_series),
            throughput=np.array(throughput_series),
        )

    def _bucket_by_minute(
        self,
        spans: list[Span],
        window_start: datetime,
        window_hours: int,
    ) -> dict[datetime, list[Span]]:
        buckets: dict[datetime, list[Span]] = defaultdict(list)
        window_end = window_start + timedelta(hours=window_hours)

        for span in spans:
            if not (window_start <= span.start_time < window_end):
                continue
            minutes_since_start = int((span.start_time - window_start).total_seconds() // 60)
            bucket_time = window_start + timedelta(minutes=minutes_since_start)
            buckets[bucket_time].append(span)

        return buckets
