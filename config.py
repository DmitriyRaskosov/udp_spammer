"""Default configuration for the UDP lab equipment simulator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from timestamp import TIMESTAMPS_PER_PACKET

BodyMode = Literal["noise", "counter", "counter_fill", "timestamps"]
TimingMode = Literal["fixed", "random", "list"]


@dataclass
class SimulatorConfig:
    src_host: str = "192.168.10.10"
    dst_host: str = "192.168.10.2"
    port: int = 4660

    channel: int = 0
    body_mode: BodyMode = "timestamps"

    ts_base_ns: float = 1000.0
    ts2_offset_ns: float = 1_000_000.0
    ts_step_ns: float = 100.0

    event_step_ns: float = 100.0
    events_per_packet: int = TIMESTAMPS_PER_PACKET
    auto_toggle_edge: bool = False
    marker_every_n_packets: int = 0

    timing_mode: TimingMode = "random"
    fixed_interval_s: float = 255e-6
    random_min_s: float = 50e-6
    random_max_s: float = 300e-6
    interval_list_s: tuple[float, ...] = (
        50e-6,
        255e-6,
        500e-6,
        1e-3,
        100e-6,
        2e-3,
    )

    packet_count: int = 0
    bind_host: str = ""

    dual_channel: bool = False
    odmr_pair: bool = False
    pair_interval_s: float = 255e-6
