#!/usr/bin/env python3
"""UDP packet generator simulating the lab board at 192.168.10.10."""

from __future__ import annotations

import argparse
import socket
import sys
import time

from config import SimulatorConfig
from packet import CvOdmrPairFactory, DualChannelFactory, OdmrPairFactory, PacketFactory
from experiment_ini import load_cv_odmr_ini
from timing import IntervalGenerator, wait_until
from timestamp import TIMESTAMPS_PER_PACKET

ODMR_PROGRESS_EVERY = 20_000


def packet_prefix_counter(payload: bytes) -> int:
    """uint16 packet counter from prefix bytes 2..3 (big-endian)."""
    return int.from_bytes(payload[2:4], "big")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synthesize UDP packets for lab board protocol testing.",
    )
    parser.add_argument("--src-host", default="192.168.10.10", help="Source IP shown in packets")
    parser.add_argument("--dst-host", default="192.168.10.2", help="Destination IP")
    parser.add_argument("--port", type=int, default=4660, help="UDP port on both sides")
    parser.add_argument("--bind-host", default="", help="Optional local bind IP")
    parser.add_argument("--channel", type=int, choices=(0, 1, 2), default=0, help="Channel 0/1/2 (ignored with --dual-channel)")
    parser.add_argument(
        "--dual-channel",
        action="store_true",
        help="Alternate ch0->ch1 like the board (0 us within pair, --interval between pairs)",
    )
    parser.add_argument(
        "--odmr-pair",
        action="store_true",
        help="Alternate ch0->ch2 for ODMR (photon + trigger, 0 us within pair, --interval between pairs)",
    )
    parser.add_argument(
        "--cv-odmr-profile",
        action="store_true",
        help="cv_odmr experiment blocks from --experiment-ini (sparse random photons, one pulse per pair)",
    )
    parser.add_argument(
        "--experiment-ini",
        default="cv_odmr.ini",
        help="cv_odmr.ini for --cv-odmr-profile (repeats + Rigol sweep)",
    )
    parser.add_argument(
        "--body-mode",
        choices=("timestamps", "noise", "counter", "counter_fill"),
        default="timestamps",
        help="timestamps=odmr-compatible (bytes 4..1023); legacy modes fill bytes 12..1023",
    )
    parser.add_argument("--count", type=int, default=0, help="Packets to send, 0 = infinite")
    parser.add_argument("--ts-base-ns", type=float, default=1000.0, help="Initial event time in ns")
    parser.add_argument(
        "--ts2-offset-ns",
        type=float,
        default=1_000_000.0,
        help="Legacy modes only: initial ts2 - ts1 offset in ns",
    )
    parser.add_argument(
        "--ts-step-ns",
        type=float,
        default=100.0,
        help="Legacy modes only: timestamp step per packet",
    )
    parser.add_argument(
        "--event-step-ns",
        type=float,
        default=100.0,
        help="timestamps mode: step between events inside a packet (ns)",
    )
    parser.add_argument(
        "--events-per-packet",
        type=int,
        default=TIMESTAMPS_PER_PACKET,
        help=f"timestamps mode: explicit events before pad (1..{TIMESTAMPS_PER_PACKET}, pad to 255)",
    )
    parser.add_argument(
        "--auto-toggle-edge",
        action="store_true",
        help="Channel 2: toggle trigger edge bit on each event (pairs for analyze.py)",
    )
    parser.add_argument(
        "--marker-every-n-packets",
        type=int,
        default=0,
        help="Insert +100 ms marker (word 0) every N packets; 0=disabled",
    )
    parser.add_argument(
        "--timing",
        choices=("fixed", "random", "list"),
        default="random",
        help="Inter-packet delay mode",
    )
    parser.add_argument("--interval", type=float, default=255e-6, help="Fixed delay in seconds")
    parser.add_argument("--random-min", type=float, default=50e-6, help="Random delay lower bound")
    parser.add_argument("--random-max", type=float, default=300e-6, help="Random delay upper bound")
    parser.add_argument(
        "--interval-list",
        default="50e-6,255e-6,500e-6,1e-3,100e-6,2e-3",
        help="Comma-separated delays for list timing mode",
    )
    parser.add_argument(
        "--trigger-edge",
        type=int,
        choices=(0, 1),
        default=0,
        help="Channel 2 only when --auto-toggle-edge is off",
    )
    return parser.parse_args()


def build_config(args: argparse.Namespace) -> SimulatorConfig:
    interval_list = tuple(float(item.strip()) for item in args.interval_list.split(",") if item.strip())
    events = max(1, min(args.events_per_packet, TIMESTAMPS_PER_PACKET))
    return SimulatorConfig(
        src_host=args.src_host,
        dst_host=args.dst_host,
        port=args.port,
        channel=args.channel,
        body_mode=args.body_mode,
        ts_base_ns=args.ts_base_ns,
        ts2_offset_ns=args.ts2_offset_ns,
        ts_step_ns=args.ts_step_ns,
        event_step_ns=args.event_step_ns,
        events_per_packet=events,
        auto_toggle_edge=args.auto_toggle_edge,
        marker_every_n_packets=max(0, args.marker_every_n_packets),
        timing_mode=args.timing,
        fixed_interval_s=args.interval,
        random_min_s=args.random_min,
        random_max_s=args.random_max,
        interval_list_s=interval_list,
        packet_count=args.count,
        bind_host=args.bind_host,
        dual_channel=args.dual_channel,
        odmr_pair=args.odmr_pair,
        cv_odmr_profile=args.cv_odmr_profile,
        experiment_ini=args.experiment_ini,
        pair_interval_s=args.interval,
    )


def create_socket(config: SimulatorConfig) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if config.bind_host:
        sock.bind((config.bind_host, 0))
    return sock


def run_dual(config: SimulatorConfig) -> int:
    factory = DualChannelFactory(
        body_mode=config.body_mode,
        ts_base_ns=config.ts_base_ns,
        ts2_offset_ns=config.ts2_offset_ns,
        ts_step_ns=config.ts_step_ns,
        event_step_ns=config.event_step_ns,
        events_per_packet=config.events_per_packet,
        marker_every_n_packets=config.marker_every_n_packets,
    )
    destination = (config.dst_host, config.port)
    sent = 0

    print(
        "UDP lab simulator (dual channel)\n"
        f"  destination: {config.dst_host}:{config.port}\n"
        f"  pattern: ch0->ch1 (0 us) -> pause {config.pair_interval_s * 1e6:.0f} us -> ...\n"
        f"  body mode: {config.body_mode}\n"
        f"  payload size: 1024 bytes\n"
        f"  shared counter start: 0\n"
    )
    if config.body_mode == "timestamps":
        print(
            f"  events per packet: {config.events_per_packet} (padded to {TIMESTAMPS_PER_PACKET})\n"
            f"  event step: {config.event_step_ns} ns"
        )

    sock = create_socket(config)
    try:
        next_pair_at = time.perf_counter()
        while config.packet_count == 0 or sent < config.packet_count:
            wait_until(next_pair_at)
            payload0, payload1 = factory.next_pair()
            for payload in (payload0, payload1):
                if len(payload) != 1024:
                    raise RuntimeError(f"Unexpected payload size: {len(payload)}")
                if config.packet_count != 0 and sent >= config.packet_count:
                    break
                sock.sendto(payload, destination)
                sent += 1
                if sent <= 4 or sent % 200 == 0:
                    print(
                        f"sent #{sent}: ch={payload[0] & 0x0F} "
                        f"counter={packet_prefix_counter(payload)} "
                        f"prefix={payload[:4].hex()}"
                    )
            if config.packet_count != 0 and sent >= config.packet_count:
                break
            next_pair_at += config.pair_interval_s
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        sock.close()

    print(f"Total packets sent: {sent} ({factory.pairs_sent} pairs)")
    return 0


def run_odmr_pair(config: SimulatorConfig) -> int:
    factory = OdmrPairFactory(
        body_mode=config.body_mode,
        ts_base_ns=config.ts_base_ns,
        ts2_offset_ns=config.ts2_offset_ns,
        ts_step_ns=config.ts_step_ns,
        event_step_ns=config.event_step_ns,
        events_per_packet=config.events_per_packet,
        marker_every_n_packets=config.marker_every_n_packets,
    )
    destination = (config.dst_host, config.port)
    sent = 0

    print(
        "UDP lab simulator (ODMR pair: ch0 + ch2)\n"
        f"  destination: {config.dst_host}:{config.port}\n"
        f"  pattern: ch0->ch2 (0 us) -> pause {config.pair_interval_s * 1e6:.0f} us -> ...\n"
        f"  body mode: {config.body_mode}\n"
        f"  ch2 auto-toggle-edge: on\n"
        f"  payload size: 1024 bytes\n"
        f"  shared counter start: 0\n"
    )
    if config.body_mode == "timestamps":
        print(
            f"  events per packet: {config.events_per_packet} (padded to {TIMESTAMPS_PER_PACKET})\n"
            f"  event step: {config.event_step_ns} ns"
        )

    sock = create_socket(config)
    try:
        next_pair_at = time.perf_counter()
        while config.packet_count == 0 or sent < config.packet_count:
            wait_until(next_pair_at)
            payload0, payload2 = factory.next_pair()
            for payload in (payload0, payload2):
                if len(payload) != 1024:
                    raise RuntimeError(f"Unexpected payload size: {len(payload)}")
                if config.packet_count != 0 and sent >= config.packet_count:
                    break
                sock.sendto(payload, destination)
                sent += 1
                if sent <= 4 or sent % ODMR_PROGRESS_EVERY == 0:
                    print(
                        f"sent #{sent}: ch={payload[0] & 0x0F} "
                        f"counter={packet_prefix_counter(payload)} "
                        f"prefix={payload[:4].hex()}"
                    )
            if config.packet_count != 0 and sent >= config.packet_count:
                break
            next_pair_at += config.pair_interval_s
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        sock.close()

    print(f"Total packets sent: {sent} ({factory.pairs_sent} pairs)")
    return 0


def run_cv_odmr_profile(config: SimulatorConfig) -> int:
    experiment = load_cv_odmr_ini(config.experiment_ini)
    factory = CvOdmrPairFactory(experiment)
    destination = (config.dst_host, config.port)
    sent = 0
    target_pairs = experiment.total_pulse_pairs
    target_packets = experiment.total_udp_packets
    if config.packet_count > 0:
        target_packets = min(config.packet_count, target_packets)

    print(
        "UDP lab simulator (cv_odmr profile: ch0 + ch2)\n"
        f"  destination: {config.dst_host}:{config.port}\n"
        f"  ini: {config.experiment_ini}\n"
        f"  expected_groups: {experiment.expected_groups} "
        f"({experiment.start_freq_mhz:.3f} MHz, step {experiment.freq_step_khz:.3f} kHz)\n"
        f"  repeats_per_freq: {experiment.repeats_per_freq}\n"
        f"  pulse pairs: {target_pairs} -> UDP packets: {target_packets}\n"
        f"  pause between pairs: {config.pair_interval_s * 1e6:.0f} us\n"
        f"  photons: random sparse (70-170 ns, occasional up to 500 ns)\n"
    )

    sock = create_socket(config)
    try:
        next_pair_at = time.perf_counter()
        while not factory.is_complete and (config.packet_count == 0 or sent < config.packet_count):
            wait_until(next_pair_at)
            payload0, payload2 = factory.next_pair()
            for payload in (payload0, payload2):
                if config.packet_count != 0 and sent >= config.packet_count:
                    break
                sock.sendto(payload, destination)
                sent += 1
                if sent <= 4 or sent % ODMR_PROGRESS_EVERY == 0:
                    print(
                        f"sent #{sent}: ch={payload[0] & 0x0F} "
                        f"counter={packet_prefix_counter(payload)} "
                        f"prefix={payload[:4].hex()}"
                    )
            if config.packet_count != 0 and sent >= config.packet_count:
                break
            next_pair_at += config.pair_interval_s
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        sock.close()

    print(
        f"Total packets sent: {sent} ({factory.pairs_sent} pulse pairs, "
        f"freq blocks completed: {factory.pairs_sent // max(1, experiment.repeats_per_freq * 2)})"
    )
    return 0


def run(config: SimulatorConfig, trigger_edge: int = 0) -> int:
    factory = PacketFactory(
        channel=config.channel,
        body_mode=config.body_mode,
        ts_base_ns=config.ts_base_ns,
        ts2_offset_ns=config.ts2_offset_ns,
        ts_step_ns=config.ts_step_ns,
        event_step_ns=config.event_step_ns,
        events_per_packet=config.events_per_packet,
        auto_toggle_edge=config.auto_toggle_edge,
        marker_every_n_packets=config.marker_every_n_packets,
    )
    if config.channel == 2:
        factory.set_trigger_edge(trigger_edge)

    intervals = IntervalGenerator(config)
    destination = (config.dst_host, config.port)
    sent = 0

    print(
        "UDP lab simulator\n"
        f"  destination: {config.dst_host}:{config.port}\n"
        f"  channel: {config.channel}\n"
        f"  body mode: {config.body_mode}\n"
        f"  timing: {config.timing_mode}\n"
        f"  payload size: 1024 bytes\n"
        f"  counter start: 0\n"
    )
    if config.body_mode == "timestamps":
        print(
            f"  events per packet: {config.events_per_packet} (padded to {TIMESTAMPS_PER_PACKET})\n"
            f"  event step: {config.event_step_ns} ns\n"
            f"  ts base: {config.ts_base_ns} ns"
        )
        if config.channel == 2:
            print(f"  auto toggle edge: {config.auto_toggle_edge}")
        if config.marker_every_n_packets:
            print(f"  +100 ms marker every: {config.marker_every_n_packets} packets")
    else:
        print(
            f"  ts base: {config.ts_base_ns} ns, ts2 offset: {config.ts2_offset_ns} ns, "
            f"step: {config.ts_step_ns} ns"
        )
    if config.src_host != "192.168.10.10":
        print(f"  note: src-host {config.src_host} is informational; OS chooses the real source IP")

    sock = create_socket(config)
    try:
        next_send_at = time.perf_counter()
        while config.packet_count == 0 or sent < config.packet_count:
            payload = factory.next_payload()
            if len(payload) != 1024:
                raise RuntimeError(f"Unexpected payload size: {len(payload)}")

            wait_until(next_send_at)
            sock.sendto(payload, destination)
            sent += 1

            if sent <= 3 or sent % 100 == 0:
                ts0 = int.from_bytes(payload[4:8], "big")
                print(
                    f"sent #{sent}: ch={payload[0] & 0x0F} "
                    f"counter={packet_prefix_counter(payload)} "
                    f"ts[0]=0x{ts0:08x} prefix={payload[:4].hex()}"
                )

            next_send_at = time.perf_counter() + intervals.next_interval()
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        sock.close()

    print(f"Total packets sent: {sent}")
    return 0


def main() -> int:
    args = parse_args()
    config = build_config(args)
    if config.odmr_pair and config.dual_channel:
        print("error: --odmr-pair and --dual-channel are mutually exclusive", file=sys.stderr)
        return 2
    if config.cv_odmr_profile and (config.odmr_pair or config.dual_channel):
        print("error: --cv-odmr-profile cannot be combined with --odmr-pair or --dual-channel", file=sys.stderr)
        return 2
    if config.cv_odmr_profile:
        return run_cv_odmr_profile(config)
    if config.odmr_pair:
        if config.channel != 0:
            print("note: --odmr-pair sends ch0 and ch2; --channel is ignored", file=sys.stderr)
        return run_odmr_pair(config)
    if config.dual_channel:
        if config.channel != 0:
            print("note: --dual-channel sends ch0 and ch1; --channel is ignored", file=sys.stderr)
        return run_dual(config)
    return run(config, trigger_edge=args.trigger_edge)


if __name__ == "__main__":
    sys.exit(main())
