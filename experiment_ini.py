"""Minimal cv_odmr.ini reader for the UDP spammer (no external deps)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CvOdmrExperiment:
    repeats_per_freq: int = 1000
    t1_ns: int = 50_000
    t2_ns: int = 500_000
    t4_ns: int = 10_000
    t5_ns: int = 50_000
    start_freq_hz: float = 2855e6
    stop_freq_hz: float = 2890e6
    freq_step_hz: float = 1e6

    @property
    def expected_groups(self) -> int:
        if self.freq_step_hz <= 0 or self.stop_freq_hz <= self.start_freq_hz:
            return 0
        return int(round((self.stop_freq_hz - self.start_freq_hz) / self.freq_step_hz)) + 1

    @property
    def freq_count(self) -> int:
        return self.expected_groups

    @property
    def start_freq_mhz(self) -> float:
        return self.start_freq_hz / 1e6

    @property
    def freq_step_khz(self) -> float:
        return self.freq_step_hz / 1e3

    @property
    def total_pulse_pairs(self) -> int:
        return self.expected_groups * self.repeats_per_freq * 2

    @property
    def total_udp_packets(self) -> int:
        return self.total_pulse_pairs * 2

    @property
    def point_duration_ns(self) -> int:
        """Time on one Rigol frequency: repeats × (t1+t2+t4) + t5."""
        return self.repeats_per_freq * (self.t1_ns + self.t2_ns + self.t4_ns) + self.t5_ns

    @property
    def pair_interval_s(self) -> float:
        """Pause between ch0+ch2 UDP pairs within one frequency (even/odd share inner loop)."""
        return (self.t1_ns + self.t2_ns + self.t4_ns) / (2 * 1e9)

    @property
    def freq_step_pause_s(self) -> float:
        """Extra pause when advancing to the next frequency (t5)."""
        return self.t5_ns / 1e9

    def estimated_duration_s(self) -> float:
        """Wall-clock estimate for one full experiment (single sweep)."""
        if self.expected_groups <= 0:
            return 0.0
        return self.expected_groups * self.point_duration_ns / 1e9


_EXPR_RE = re.compile(r"^\s*([A-Za-z0-9_]+)\s*=\s*(.+?)\s*(?:;.*)?$")


def _eval_expr(raw: str) -> float:
    text = raw.strip()
    for op in ("*", "/", "+", "-"):
        if op in text:
            left, right = text.split(op, 1)
            a = float(left.strip())
            b = float(right.strip())
            if op == "*":
                return a * b
            if op == "/":
                return a / b
            if op == "+":
                return a + b
            return a - b
    return float(text)


def _parse_int(raw: str, default: int) -> int:
    try:
        return int(_eval_expr(raw))
    except (TypeError, ValueError):
        return default


def load_cv_odmr_ini(path: str | Path) -> CvOdmrExperiment:
    ini_path = Path(path)
    general: dict[str, str] = {}
    rigol: dict[str, str] = {}
    section = None

    for line in ini_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip().lower()
            continue
        match = _EXPR_RE.match(stripped)
        if not match:
            continue
        key, value = match.group(1).strip().lower(), match.group(2).strip()
        if section == "general":
            general[key] = value
        elif section == "rigol":
            rigol[key] = value

    repeats = _parse_int(general.get("number_of_repeats", "1000"), 1000)
    t1 = _parse_int(general.get("t1", "50000"), 50_000)
    t2 = _parse_int(general.get("t2", "500000"), 500_000)
    t4 = _parse_int(general.get("t4", "10000"), 10_000)
    t5 = _parse_int(general.get("t5", "50000"), 50_000)
    start = _eval_expr(rigol.get("start_freq", "2855 * 1E6"))
    stop = _eval_expr(rigol.get("stop_freq", "2890 * 1E6"))
    step = _eval_expr(rigol.get("freq_step", "1000 * 1E3"))
    return CvOdmrExperiment(
        repeats_per_freq=repeats,
        t1_ns=t1,
        t2_ns=t2,
        t4_ns=t4,
        t5_ns=t5,
        start_freq_hz=start,
        stop_freq_hz=stop,
        freq_step_hz=step,
    )
