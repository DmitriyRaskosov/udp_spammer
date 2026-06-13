"""Build 1024-byte UDP payloads for the lab board protocol (ODMR UDP 21.04.2026)."""

from __future__ import annotations

import os
import struct
from typing import Literal

from timestamp import (
    TIMESTAMPS_PER_PACKET,
    ChannelTimestampState,
    SharedEventClock,
    TimestampPacketStream,
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
        shared_counter = [0]
        shared_clock = SharedEventClock(base_ns=ts_base_ns, event_step_ns=event_step_ns)
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
        self._shared_clock = shared_clock
        self._shared_counter = shared_counter
        self._pairs_sent = 0

    @property
    def counter(self) -> int:
        return self._shared_counter[0]

    @property
    def pairs_sent(self) -> int:
        return self._pairs_sent

    def next_pair(self) -> tuple[bytes, bytes]:
        clock_state = self._shared_clock.snapshot()
        payload0 = self._photon.next_payload()
        self._shared_clock.restore(clock_state)
        payload2 = self._trigger.next_payload()
        self._pairs_sent += 1
        return payload0, payload2
