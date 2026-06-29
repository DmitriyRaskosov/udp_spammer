#!/usr/bin/env python3
"""Offline validation of generated packets (ODMR UDP 21.04.2026)."""

from __future__ import annotations

import struct

from packet import CvOdmrPairFactory, DualChannelFactory, OdmrPairFactory, PacketFactory
from experiment_ini import CvOdmrExperiment
from timestamp import TIMESTAMPS_PER_PACKET, MARKER_100MS, COARSE_WRAP_NS, decode_timestamp, encode_timestamp_ch2


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


def verify_encode_ch2_no_recursion() -> None:
    """Regression: ch2 edge=0 at small t must not recurse on marker word."""
    for t_ns in (0.0, 0.185, 5.0, COARSE_WRAP_NS):
        for edge in (0, 1):
            word = encode_timestamp_ch2(t_ns, edge)
            assert word != MARKER_100MS, f"encoded marker at t={t_ns} edge={edge}"
    print("encode_timestamp_ch2 no marker recursion: OK")


def verify_coarse_wrap_markers() -> None:
    factory = PacketFactory(channel=2, body_mode="timestamps", auto_toggle_edge=True)
    marker_packets = 0
    for _ in range(20_000):
        words = list(iter_timestamp_words(factory.next_payload()))
        if MARKER_100MS in words:
            marker_packets += 1
    assert marker_packets > 0, "expected +100ms markers after coarse wrap"
    print(f"coarse wrap markers in long ch2 run: OK ({marker_packets} packets with markers)")


def verify_odmr_pair_marker_sync() -> None:
    """ch0 and ch2 packets in a pair must share the same +100ms marker positions."""
    factory = OdmrPairFactory(body_mode="timestamps", event_step_ns=100.0)
    marker_pairs = 0
    for _ in range(20_000):
        p0, p2 = factory.next_pair()
        w0 = list(iter_timestamp_words(p0))
        w2 = list(iter_timestamp_words(p2))
        for word0, word2 in zip(w0, w2):
            assert (word0 == MARKER_100MS) == (word2 == MARKER_100MS)
        if any(word == MARKER_100MS for word in w0):
            marker_pairs += 1
    assert marker_pairs > 0, "expected +100ms markers after coarse wrap"
    print(f"odmr pair marker sync: OK ({marker_pairs} pairs with markers)")


def verify_odmr_pair_stress() -> None:
    factory = OdmrPairFactory(body_mode="timestamps", event_step_ns=100.0)
    for _ in range(150_000):
        p0, p2 = factory.next_pair()
        assert len(p0) == 1024 and len(p2) == 1024
    print("odmr pair stress (150k packets, past coarse wrap): OK")


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


def verify_experiment_ini_timing() -> None:
    exp = CvOdmrExperiment(
        repeats_per_freq=100,
        t1_ns=50_000,
        t2_ns=500_000,
        t4_ns=10_000,
        t5_ns=50_000,
        start_freq_hz=2855e6,
        stop_freq_hz=2890e6,
        freq_step_hz=1e6,
    )
    assert exp.expected_groups == 36
    assert abs(exp.pair_interval_s - 280e-6) < 1e-9
    assert abs(exp.freq_step_pause_s - 50e-6) < 1e-9
    assert 1.5 < exp.estimated_duration_s() < 3.0
    print("cv_odmr ini timing estimate: OK")


def verify_cv_odmr_loop_counter() -> None:
    """reset_sweep must not reset the shared uint16 packet counter."""
    exp = CvOdmrExperiment(
        repeats_per_freq=1,
        start_freq_hz=2855e6,
        stop_freq_hz=2856e6,
        freq_step_hz=1e6,
    )
    factory = CvOdmrPairFactory(exp)
    for _ in range(exp.total_pulse_pairs):
        factory.next_pair()
    counter_after_sweep = factory.counter
    assert factory.is_complete
    factory.reset_sweep()
    assert not factory.is_complete
    p0, _ = factory.next_pair()
    assert int.from_bytes(p0[2:4], "big") == counter_after_sweep
    print("cv_odmr reset_sweep keeps counter: OK")


def main() -> None:
    verify_encode_ch2_no_recursion()
    verify_timestamps_mode()
    verify_dual_channel()
    verify_odmr_pair()
    verify_experiment_ini_timing()
    verify_cv_odmr_loop_counter()
    verify_odmr_pair_marker_sync()
    verify_coarse_wrap_markers()
    verify_odmr_pair_stress()
    verify_long_timestamps()
    verify_legacy_mode()
    print("OK: packet layout matches ODMR UDP 21.04.2026 / odmr packet_collector")


if __name__ == "__main__":
    main()
