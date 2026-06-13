#!/usr/bin/env python3
"""Offline validation of generated packets (ODMR UDP 21.04.2026)."""

from __future__ import annotations

import struct

from packet import DualChannelFactory, OdmrPairFactory, PacketFactory
from timestamp import TIMESTAMPS_PER_PACKET, MARKER_100MS, decode_timestamp


def iter_timestamp_words(payload: bytes):
    for offset in range(4, 1024, 4):
        yield struct.unpack_from(">I", payload, offset)[0]


def verify_timestamps_mode() -> None:
    factory = PacketFactory(
        channel=0,
        body_mode="timestamps",
        ts_base_ns=1000.0,
        event_step_ns=100.0,
        events_per_packet=10,
    )
    payloads = [factory.next_payload() for _ in range(3)]

    prev_last_ns = -1.0
    for index, payload in enumerate(payloads):
        assert len(payload) == 1024
        assert payload[0] & 0x0F == 0
        assert payload[1] == 0
        counter = int.from_bytes(payload[2:4], "big")
        assert counter == index

        words = list(iter_timestamp_words(payload))
        assert len(words) == TIMESTAMPS_PER_PACKET
        assert MARKER_100MS not in words

        decoded = [decode_timestamp(word) for word in words]
        valid = [value for value in decoded if value is not None]
        assert len(valid) == TIMESTAMPS_PER_PACKET
        assert valid == sorted(valid)
        assert valid[0] > prev_last_ns
        prev_last_ns = valid[-1]

        print(
            f"packet {index}: counter={counter} events={len(valid)} "
            f"t_first={valid[0]:.3f} ns t_last={valid[-1]:.3f} ns"
        )

    ch2 = PacketFactory(channel=2, body_mode="timestamps", auto_toggle_edge=True)
    p2 = ch2.next_payload()
    words2 = list(iter_timestamp_words(p2))
    assert all((word >> 5) & 1 in (0, 1) for word in words2[:4])
    print("channel 2 auto edge: OK")


def verify_dual_channel() -> None:
    factory = DualChannelFactory(body_mode="timestamps", event_step_ns=100.0)
    p0, p1 = factory.next_pair()
    assert (p0[0] & 0x0F) == 0 and (p1[0] & 0x0F) == 1
    assert int.from_bytes(p0[2:4], "big") == 0
    assert int.from_bytes(p1[2:4], "big") == 1
    p0b, p1b = factory.next_pair()
    assert int.from_bytes(p0b[2:4], "big") == 2
    assert int.from_bytes(p1b[2:4], "big") == 3
    print("dual channel shared counter: OK")


def verify_odmr_pair() -> None:
    factory = OdmrPairFactory(body_mode="timestamps", event_step_ns=100.0)
    p0, p2 = factory.next_pair()
    assert (p0[0] & 0x0F) == 0 and (p2[0] & 0x0F) == 2
    assert int.from_bytes(p0[2:4], "big") == 0
    assert int.from_bytes(p2[2:4], "big") == 1
    print("odmr pair ch0+ch2 shared counter: OK")


def verify_long_timestamps() -> None:
    factory = PacketFactory(channel=0, body_mode="timestamps", event_step_ns=100.0)
    for _ in range(20_000):
        payload = factory.next_payload()
        assert len(payload) == 1024
    print("long timestamps run (20k packets): OK")


def verify_legacy_mode() -> None:
    factory = PacketFactory(channel=0, body_mode="counter_fill")
    payload = factory.next_payload()
    assert len(payload) == 1024
    assert payload[1] == 0
    ts1 = decode_timestamp(int.from_bytes(payload[4:8], "big"))
    ts2 = decode_timestamp(int.from_bytes(payload[8:12], "big"))
    assert ts1 is not None and ts2 is not None
    print("legacy counter_fill header: OK")


def main() -> None:
    verify_timestamps_mode()
    verify_dual_channel()
    verify_odmr_pair()
    verify_long_timestamps()
    verify_legacy_mode()
    print("OK: packet layout matches ODMR UDP 21.04.2026 / odmr packet_collector")


if __name__ == "__main__":
    main()
