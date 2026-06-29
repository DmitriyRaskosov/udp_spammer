"""Build 1024-byte UDP payloads for the lab board protocol (ODMR UDP 21.04.2026)."""

from __future__ import annotations

import os
import random
import struct
import sys
from array import array
from typing import Literal

from experiment_ini import CvOdmrExperiment
from timestamp import (
    COARSE_WRAP_NS,
    MARKER_100MS,
    TIMESTAMPS_PER_PACKET,
    ChannelTimestampState,
    SharedEventClock,
    TimestampPacketStream,
    encode_timestamp_ch01_fast,
    encode_timestamp_ch2_fast,
)

BodyMode = Literal["noise", "counter", "counter_fill", "timestamps"]


def build_legacy_body(mode: BodyMode, counter: int, size: int = 1012) -> bytes:
    if mode == "noise":
        return os.urandom(size)
    if mode == "counter":
        return struct.pack(">I", counter & 0xFFFFFFFF) + b"\x00" * (size - 4)
    if mode == "counter_fill":
        return bytes((counter + index) & 0xFF for index in range(size))
    raise ValueError(f"Unsupported legacy body mode: {mode}")


def build_timestamp_block(words: list[int]) -> bytes:
    if len(words) != TIMESTAMPS_PER_PACKET:
        raise ValueError(f"Expected {TIMESTAMPS_PER_PACKET} timestamp words, got {len(words)}")
    block = bytearray(TIMESTAMPS_PER_PACKET * 4)
    for index, word in enumerate(words):
        struct.pack_into(">I", block, index * 4, word & 0xFFFFFFFF)
    return bytes(block)


def pack_timestamp_payload(
    channel: int,
    counter: int,
    words: array,
    buffer: bytearray,
) -> memoryview:
    if len(words) != TIMESTAMPS_PER_PACKET:
        raise ValueError(f"Expected {TIMESTAMPS_PER_PACKET} timestamp words, got {len(words)}")
    if len(buffer) != 1024:
        raise ValueError(f"Payload buffer must be 1024 bytes, got {len(buffer)}")
    buffer[0] = channel & 0x0F
    buffer[1] = 0
    struct.pack_into(">H", buffer, 2, counter & 0xFFFF)
    if sys.byteorder == "little":
        words.byteswap()
    block = words.tobytes()
    if sys.byteorder == "little":
        words.byteswap()
    buffer[4 : 4 + TIMESTAMPS_PER_PACKET * 4] = block
    return memoryview(buffer)


def build_payload(
    channel: int,
    counter: int,
    *,
    timestamp_words: list[int] | None = None,
    ts1_word: int = 0,
    ts2_word: int = 0,
    body_mode: BodyMode = "timestamps",
) -> bytes:
    if channel not in (0, 1, 2):
        raise ValueError("Channel must be 0, 1, or 2")

    prefix = struct.pack(">BBH", channel & 0x0F, 0x00, counter & 0xFFFF)

    if body_mode == "timestamps":
        if timestamp_words is None:
            raise ValueError("timestamp_words required for timestamps body mode")
        payload = prefix + build_timestamp_block(timestamp_words)
    else:
        header = struct.pack(">II", ts1_word & 0xFFFFFFFF, ts2_word & 0xFFFFFFFF)
        body = build_legacy_body(body_mode, counter)
        payload = prefix + header + body

    if len(payload) != 1024:
        raise ValueError(f"Payload must be 1024 bytes, got {len(payload)}")
    return payload


class PacketFactory:
    """Stateful packet builder for a single channel."""

    def __init__(
        self,
        channel: int,
        body_mode: BodyMode = "timestamps",
        ts_base_ns: float = 1000.0,
        ts2_offset_ns: float = 1_000_000.0,
        ts_step_ns: float = 100.0,
        event_step_ns: float = 100.0,
        events_per_packet: int = TIMESTAMPS_PER_PACKET,
        auto_toggle_edge: bool = False,
        marker_every_n_packets: int = 0,
        shared_counter: list[int] | None = None,
        shared_clock: SharedEventClock | None = None,
    ):
        self.channel = channel
        self.body_mode = body_mode
        self._shared_counter = shared_counter
        self._counter = 0
        self._edge_bit = 0
        self._events_per_packet = events_per_packet
        self._marker_every_n_packets = marker_every_n_packets
        self._packet_index = 0

        if body_mode == "timestamps":
            self._stream = TimestampPacketStream(
                channel=channel,
                base_ns=ts_base_ns,
                event_step_ns=event_step_ns,
                auto_toggle_edge=auto_toggle_edge,
                shared_clock=shared_clock,
            )
            self._legacy_timestamps = None
        else:
            self._stream = None
            self._legacy_timestamps = ChannelTimestampState(
                base_ns=ts_base_ns,
                offset_ns=ts2_offset_ns,
                step_ns=ts_step_ns,
            )

    @property
    def counter(self) -> int:
        if self._shared_counter is not None:
            return self._shared_counter[0]
        return self._counter

    def _current_counter(self) -> int:
        return self.counter

    def _advance_counter(self) -> None:
        if self._shared_counter is not None:
            self._shared_counter[0] = (self._shared_counter[0] + 1) & 0xFFFF
        else:
            self._counter = (self._counter + 1) & 0xFFFF

    def set_trigger_edge(self, edge_bit: int) -> None:
        self._edge_bit = edge_bit & 1
        if self._stream is not None:
            self._stream.set_trigger_edge(edge_bit)

    def inject_100ms_marker(self) -> None:
        target = self._stream or self._legacy_timestamps
        if target is not None:
            target.inject_100ms_marker()

    def next_payload(self) -> bytes:
        if self._marker_every_n_packets > 0 and self._packet_index > 0:
            if self._packet_index % self._marker_every_n_packets == 0:
                self.inject_100ms_marker()

        if self.body_mode == "timestamps":
            assert self._stream is not None
            edge_bit = self._edge_bit if self.channel == 2 else 0
            if self.channel == 2 and not self._stream.auto_toggle_edge:
                self._stream.set_trigger_edge(edge_bit)
            words = self._stream.next_words(self._events_per_packet)
            payload = build_payload(
                channel=self.channel,
                counter=self._current_counter(),
                timestamp_words=words,
                body_mode="timestamps",
            )
        else:
            assert self._legacy_timestamps is not None
            edge_bit = self._edge_bit if self.channel == 2 else 0
            ts1_word, ts2_word = self._legacy_timestamps.next_words(self.channel, edge_bit)
            payload = build_payload(
                channel=self.channel,
                counter=self._current_counter(),
                ts1_word=ts1_word,
                ts2_word=ts2_word,
                body_mode=self.body_mode,
            )

        self._advance_counter()
        self._packet_index += 1
        return payload


class DualChannelFactory:
    """Board-like ch0->ch1 pairs with a shared uint16 packet counter."""

    def __init__(
        self,
        body_mode: BodyMode = "timestamps",
        ts_base_ns: float = 1000.0,
        ts2_offset_ns: float = 1_000_000.0,
        ts_step_ns: float = 100.0,
        event_step_ns: float = 100.0,
        events_per_packet: int = TIMESTAMPS_PER_PACKET,
        marker_every_n_packets: int = 0,
    ):
        shared_counter = [0]
        factory_kwargs = dict(
            body_mode=body_mode,
            ts_base_ns=ts_base_ns,
            ts2_offset_ns=ts2_offset_ns,
            ts_step_ns=ts_step_ns,
            event_step_ns=event_step_ns,
            events_per_packet=events_per_packet,
            marker_every_n_packets=marker_every_n_packets,
            shared_counter=shared_counter,
        )
        self._ch0 = PacketFactory(channel=0, **factory_kwargs)
        self._ch1 = PacketFactory(channel=1, **factory_kwargs)
        self._shared_counter = shared_counter
        self._pairs_sent = 0

    @property
    def counter(self) -> int:
        return self._shared_counter[0]

    @property
    def pairs_sent(self) -> int:
        return self._pairs_sent

    def next_pair(self) -> tuple[bytes, bytes]:
        payload0 = self._ch0.next_payload()
        payload1 = self._ch1.next_payload()
        self._pairs_sent += 1
        return payload0, payload1


class OdmrPairFactory:
    """ODMR capture path: ch0 photons + ch2 triggers, shared counter."""

    def __init__(
        self,
        body_mode: BodyMode = "timestamps",
        ts_base_ns: float = 1000.0,
        ts2_offset_ns: float = 1_000_000.0,
        ts_step_ns: float = 100.0,
        event_step_ns: float = 100.0,
        events_per_packet: int = TIMESTAMPS_PER_PACKET,
        marker_every_n_packets: int = 0,
    ):
        self._body_mode = body_mode
        self._events_per_packet = events_per_packet
        self._marker_every_n_packets = marker_every_n_packets
        self._packet_index = 0
        self._shared_counter = [0]
        self._edge_bit = 0
        self._pairs_sent = 0
        self._words0 = array("I", [0] * TIMESTAMPS_PER_PACKET)
        self._words2 = array("I", [0] * TIMESTAMPS_PER_PACKET)
        self._payload0 = bytearray(1024)
        self._payload2 = bytearray(1024)
        self._next_ns_int = int(ts_base_ns)
        self._step_ns_int = int(event_step_ns)
        self._wrap_at_ns_int = int(COARSE_WRAP_NS)
        self._pending_marker = False
        self._shared_clock = SharedEventClock(base_ns=ts_base_ns, event_step_ns=event_step_ns)

        if body_mode != "timestamps":
            shared_counter = self._shared_counter
            shared_clock = self._shared_clock
            factory_kwargs = dict(
                body_mode=body_mode,
                ts_base_ns=ts_base_ns,
                ts2_offset_ns=ts2_offset_ns,
                ts_step_ns=ts_step_ns,
                event_step_ns=event_step_ns,
                events_per_packet=events_per_packet,
                marker_every_n_packets=marker_every_n_packets,
                shared_counter=shared_counter,
                shared_clock=shared_clock,
            )
            self._photon = PacketFactory(channel=0, **factory_kwargs)
            self._trigger = PacketFactory(
                channel=2,
                auto_toggle_edge=True,
                **factory_kwargs,
            )
        else:
            self._photon = None
            self._trigger = None

    @property
    def counter(self) -> int:
        return self._shared_counter[0]

    @property
    def pairs_sent(self) -> int:
        return self._pairs_sent

    def _maybe_inject_marker(self) -> None:
        if self._marker_every_n_packets > 0 and self._packet_index > 0:
            if self._packet_index % self._marker_every_n_packets == 0:
                self._pending_marker = True

    def _fill_timestamp_pair(self) -> None:
        edge = self._edge_bit
        words0 = self._words0
        words2 = self._words2
        t_ns = self._next_ns_int
        step_ns = self._step_ns_int
        wrap_at = self._wrap_at_ns_int
        wrap_step = int(COARSE_WRAP_NS)
        marker_step = 100_000_000

        for index in range(TIMESTAMPS_PER_PACKET):
            if self._pending_marker:
                t_ns += marker_step
                self._pending_marker = False
                words0[index] = MARKER_100MS
                words2[index] = MARKER_100MS
                continue

            if t_ns >= wrap_at:
                wrap_at += wrap_step
                t_ns += marker_step
                words0[index] = MARKER_100MS
                words2[index] = MARKER_100MS
                continue

            words0[index] = encode_timestamp_ch01_fast(t_ns)
            words2[index] = encode_timestamp_ch2_fast(t_ns, edge)
            edge ^= 1
            t_ns += step_ns

        self._next_ns_int = t_ns
        self._wrap_at_ns_int = wrap_at
        self._edge_bit = edge

    def _next_pair_timestamps(self) -> tuple[bytes | memoryview, bytes | memoryview]:
        self._maybe_inject_marker()
        self._fill_timestamp_pair()

        counter0 = self._shared_counter[0]
        payload0 = pack_timestamp_payload(0, counter0, self._words0, self._payload0)
        self._shared_counter[0] = (counter0 + 1) & 0xFFFF

        counter2 = self._shared_counter[0]
        payload2 = pack_timestamp_payload(2, counter2, self._words2, self._payload2)
        self._shared_counter[0] = (counter2 + 1) & 0xFFFF

        self._packet_index += 1
        self._pairs_sent += 1
        return payload0, payload2

    def _next_pair_legacy(self) -> tuple[bytes, bytes]:
        assert self._photon is not None and self._trigger is not None
        clock_state = self._shared_clock.snapshot()
        payload0 = self._photon.next_payload()
        self._shared_clock.restore(clock_state)
        payload2 = self._trigger.next_payload()
        self._pairs_sent += 1
        return payload0, payload2

    def next_pair(self) -> tuple[bytes | memoryview, bytes | memoryview]:
        if self._body_mode == "timestamps":
            return self._next_pair_timestamps()
        return self._next_pair_legacy()


class CvOdmrPairFactory:
    """cv_odmr experiment: sparse random photons, one pulse window per UDP pair."""

    def __init__(
        self,
        experiment: CvOdmrExperiment,
        *,
        ts_base_ns: float = 1000.0,
        pulse_min_ns: int = 500,
        pulse_max_ns: int = 5000,
        photon_min: int = 0,
        photon_max: int = 40,
        photon_step_min_ns: int = 70,
        photon_step_max_ns: int = 170,
        photon_step_rare_max_ns: int = 500,
        photon_step_rare_prob: float = 0.08,
        freq_gap_marker: bool = False,
        seed: int | None = None,
    ):
        self._experiment = experiment
        self._pulse_min_ns = pulse_min_ns
        self._pulse_max_ns = pulse_max_ns
        self._photon_min = photon_min
        self._photon_max = photon_max
        self._photon_step_min_ns = photon_step_min_ns
        self._photon_step_max_ns = photon_step_max_ns
        self._photon_step_rare_max_ns = photon_step_rare_max_ns
        self._photon_step_rare_prob = photon_step_rare_prob
        self._freq_gap_marker = freq_gap_marker
        self._rng = random.Random(seed)

        self._shared_counter = [0]
        self._words0 = array("I", [0] * TIMESTAMPS_PER_PACKET)
        self._words2 = array("I", [0] * TIMESTAMPS_PER_PACKET)
        self._payload0 = bytearray(1024)
        self._payload2 = bytearray(1024)
        self._next_ns_int = int(ts_base_ns)
        self._edge_bit = 0
        self._pairs_sent = 0
        self._freq_index = 0
        self._pulse_in_freq = 0

    @property
    def counter(self) -> int:
        return self._shared_counter[0]

    @property
    def pairs_sent(self) -> int:
        return self._pairs_sent

    @property
    def is_complete(self) -> bool:
        return self._freq_index >= self._experiment.expected_groups

    def reset_sweep(self) -> None:
        """Start the next ini sweep; shared packet counter keeps incrementing."""
        self._freq_index = 0
        self._pulse_in_freq = 0

    def _photon_step_ns(self) -> int:
        if self._rng.random() < self._photon_step_rare_prob:
            return self._rng.randint(self._photon_step_min_ns, self._photon_step_rare_max_ns)
        return self._rng.randint(self._photon_step_min_ns, self._photon_step_max_ns)

    def _clear_words(self) -> None:
        for index in range(TIMESTAMPS_PER_PACKET):
            self._words0[index] = 0
            self._words2[index] = 0

    def _fill_single_pulse(self) -> None:
        self._clear_words()

        if self._freq_gap_marker and self._pulse_in_freq == 0 and self._freq_index > 0:
            self._next_ns_int += 100_000_000
            self._words0[0] = MARKER_100MS
            self._words2[0] = MARKER_100MS
            return

        pulse_len = self._rng.randint(self._pulse_min_ns, self._pulse_max_ns)
        t0 = self._next_ns_int
        t_end = t0 + pulse_len

        self._words2[0] = encode_timestamp_ch2_fast(t0, self._edge_bit)
        self._words2[1] = encode_timestamp_ch2_fast(t_end, self._edge_bit ^ 1)
        self._edge_bit ^= 1

        photon_count = self._rng.randint(self._photon_min, self._photon_max)
        t_photon = t0 + self._rng.randint(20, max(21, pulse_len // 3))
        photon_index = 0
        for _ in range(photon_count):
            if t_photon >= t_end or photon_index >= TIMESTAMPS_PER_PACKET:
                break
            self._words0[photon_index] = encode_timestamp_ch01_fast(t_photon)
            photon_index += 1
            t_photon += self._photon_step_ns()

        self._next_ns_int = t_end + self._rng.randint(50, 250)

    def next_pair(self) -> tuple[bytes | memoryview, bytes | memoryview]:
        if self.is_complete:
            raise StopIteration("cv_odmr experiment complete")

        self._fill_single_pulse()

        counter0 = self._shared_counter[0]
        payload0 = pack_timestamp_payload(0, counter0, self._words0, self._payload0)
        self._shared_counter[0] = (counter0 + 1) & 0xFFFF

        counter2 = self._shared_counter[0]
        payload2 = pack_timestamp_payload(2, counter2, self._words2, self._payload2)
        self._shared_counter[0] = (counter2 + 1) & 0xFFFF

        self._pairs_sent += 1
        self._pulse_in_freq += 1
        pulses_per_freq = self._experiment.repeats_per_freq * 2
        if self._pulse_in_freq >= pulses_per_freq:
            self._pulse_in_freq = 0
            self._freq_index += 1

        return payload0, payload2
