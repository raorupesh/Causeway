from __future__ import annotations

import numpy as np

from causeway.pipeline import CRITICAL, DEGRADED, HEALTHY, classify_health


def test_single_anomalous_minute_is_only_degraded():
    status = classify_health(np.array([False, True, False]))
    assert status == [HEALTHY, DEGRADED, HEALTHY]


def test_sustained_anomaly_escalates_to_critical():
    status = classify_health(np.array([False, True, True, True, False]))
    assert status == [HEALTHY, DEGRADED, CRITICAL, CRITICAL, HEALTHY]


def test_anomaly_at_first_minute_is_degraded():
    assert classify_health(np.array([True]))[0] == DEGRADED
