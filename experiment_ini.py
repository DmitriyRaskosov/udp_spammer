"""Minimal cv_odmr.ini reader for the UDP spammer (no external deps)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CvOdmrExperiment:
    repeats_per_freq: int = 1000
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

    repeats = int(general.get("number_of_repeats", "1000"))
    start = _eval_expr(rigol.get("start_freq", "2855 * 1E6"))
    stop = _eval_expr(rigol.get("stop_freq", "2890 * 1E6"))
    step = _eval_expr(rigol.get("freq_step", "1000 * 1E3"))
    return CvOdmrExperiment(
        repeats_per_freq=repeats,
        start_freq_hz=start,
        stop_freq_hz=stop,
        freq_step_hz=step,
    )