"""Statistics helpers for round time measurement."""

from __future__ import annotations

import statistics
from typing import Iterable, Tuple


def mean_std(values: Iterable[float]) -> Tuple[float, float, int]:
    data = list(values)
    if not data:
        return 0.0, 0.0, 0
    mean_val = statistics.mean(data)
    if len(data) < 2:
        return mean_val, 0.0, len(data)
    return mean_val, statistics.stdev(data), len(data)
