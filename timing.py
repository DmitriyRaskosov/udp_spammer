"""Irregular inter-packet delay generators."""

from __future__ import annotations

import random
import time
from typing import Iterator

from config import SimulatorConfig


class IntervalGenerator:
    def __init__(self, config: SimulatorConfig):
        self._config = config
        self._list_index = 0

    def next_interval(self) -> float:
        mode = self._config.timing_mode
        if mode == "fixed":
            return self._config.fixed_interval_s
        if mode == "random":
            return random.uniform(self._config.random_min_s, self._config.random_max_s)
        if mode == "list":
            values = self._config.interval_list_s
            if not values:
                return 0.0
            interval = values[self._list_index % len(values)]
            self._list_index += 1
            return interval
        raise ValueError(f"Unsupported timing mode: {mode}")


def wait_until(deadline: float) -> None:
    while True:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            return
        if remaining > 0.002:
            time.sleep(remaining * 0.5)
        else:
            time.sleep(0)
