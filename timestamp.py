"""Encode and decode 32-bit channel timestamp words (ODMR UDP 21.04.2026)."""

from __future__ import annotations

MARKER_100MS = 0x00000000
ZERO_SHIFT_NS = 0.185
TIMESTAMPS_PER_PACKET = 255  # bytes 4..1023 of the 1024-byte payload
# Hardware coarse field is 26 bits; values wrap instead of growing past uint32.
COARSE_MASK = 0x3FFFFFF
WORD_MASK = 0xFFFFFFFF
COARSE_WRAP_NS = (COARSE_MASK + 1) * 5.0  # ~335.544 ms

# Precomputed fine corrections in nanoseconds (channels 0/1).
_FINE_NS: tuple[float, ...] = tuple(
    round(i * 185 / 100) * 100 / 1000.0 for i in range(32)
)


def _quantize_fine_ch01(remainder_ns: float) -> int:
    best = 0
    best_err = abs(remainder_ns - _FINE_NS[0])
    for value in range(1, 32):
        err = abs(remainder_ns - _FINE_NS[value])
        if err < best_err:
            best = value
            best_err = err
    return best


# Integer remainder 0..4 ns -> fine index (valid when t_ns is an integer nanosecond).
_FINE_LUT_INT: tuple[int, ...] = tuple(_quantize_fine_ch01(float(r)) for r in range(5))


def encode_timestamp_ch01_fast(t_ns_int: int) -> int:
    coarse = (t_ns_int // 5) & COARSE_MASK
    fine = _FINE_LUT_INT[t_ns_int % 5]
    return ((coarse << 6) | fine) & WORD_MASK


def encode_timestamp_ch2_fast(t_ns_int: int, edge_bit: int) -> int:
    bit5 = edge_bit & 1
    coarse = (t_ns_int // 5) & COARSE_MASK
    fine = 0x1F if bit5 else 0x00
    return ((coarse << 6) | (bit5 << 5) | fine) & WORD_MASK


def decode_timestamp(word: int) -> float | None:
    """Return timestamp in nanoseconds, or None for the +100 ms marker."""
    if word == MARKER_100MS:
        return None

    coarse = (word >> 6) & 0x3FFFFFF
    fine = word & 0x1F
    fine_ps = round(fine * 185 / 100) * 100
    return coarse * 5.0 + fine_ps / 1000.0


def encode_timestamp_ch01(t_ns: float) -> int:
    """Encode timestamp for detector channels 0 and 1 (bit 5 is always 0)."""
    if t_ns <= 0:
        t_ns = ZERO_SHIFT_NS

    t_ns = float(t_ns)
    for _ in range(32):
        coarse = int(t_ns // 5) & COARSE_MASK
        remainder_ns = t_ns - int(t_ns // 5) * 5.0
        fine = _quantize_fine_ch01(remainder_ns)
        word = ((coarse << 6) | fine) & WORD_MASK
        if word != MARKER_100MS:
            return word
        t_ns += ZERO_SHIFT_NS

    return 0x01


def encode_timestamp_ch2(t_ns: float, edge_bit: int) -> int:
    """Encode timestamp for trigger channel 2 (bit 5 is the edge flag)."""
    if t_ns <= 0:
        t_ns = ZERO_SHIFT_NS

    bit5 = edge_bit & 1
    t_ns = float(t_ns)
    for _ in range(32):
        coarse = int(t_ns // 5) & COARSE_MASK
        fine = 0x1F if bit5 else 0x00
        word = ((coarse << 6) | (bit5 << 5) | fine) & WORD_MASK
        if word != MARKER_100MS:
            return word
        t_ns += ZERO_SHIFT_NS

    return ((bit5 << 5) | (0x1F if bit5 else 0x01)) & WORD_MASK


def encode_word(channel: int, t_ns: float, edge_bit: int = 0) -> int:
    if channel in (0, 1):
        return encode_timestamp_ch01(t_ns)
    return encode_timestamp_ch2(t_ns, edge_bit)


class SharedEventClock:
    """Shared monotonic timeline for multi-channel packet generation."""

    def __init__(self, base_ns: float = 1000.0, event_step_ns: float = 100.0):
        self._next_ns = base_ns
        self._event_step_ns = event_step_ns
        self._pending_100ms_marker = False
        self._coarse_wrap_at_ns = COARSE_WRAP_NS

    def snapshot(self) -> tuple[float, float, bool, float]:
        return (
            self._next_ns,
            self._coarse_wrap_at_ns,
            self._pending_100ms_marker,
            self._event_step_ns,
        )

    def restore(self, state: tuple[float, float, bool, float]) -> None:
        self._next_ns, self._coarse_wrap_at_ns, self._pending_100ms_marker, self._event_step_ns = state

    def inject_100ms_marker(self) -> None:
        self._pending_100ms_marker = True

    def append_marker(self, words: list[int]) -> None:
        words.append(MARKER_100MS)
        self._next_ns += 100_000_000.0
        self._pending_100ms_marker = False

    def needs_coarse_wrap_marker(self) -> bool:
        return self._next_ns >= self._coarse_wrap_at_ns

    def emit_coarse_wrap_marker(self, words: list[int]) -> None:
        self._coarse_wrap_at_ns += COARSE_WRAP_NS
        self.append_marker(words)

    def advance_after_event(self) -> None:
        self._next_ns += self._event_step_ns


class TimestampPacketStream:
    """Monotonic per-channel event stream packed into 255 words per UDP payload."""

    def __init__(
        self,
        channel: int,
        base_ns: float = 1000.0,
        event_step_ns: float = 100.0,
        edge_bit: int = 0,
        auto_toggle_edge: bool = False,
        shared_clock: SharedEventClock | None = None,
    ):
        if channel not in (0, 1, 2):
            raise ValueError("Channel must be 0, 1, or 2")
        self.channel = channel
        self._clock = shared_clock or SharedEventClock(base_ns, event_step_ns)
        self._edge_bit = edge_bit & 1
        self._auto_toggle_edge = auto_toggle_edge and channel == 2

    @property
    def auto_toggle_edge(self) -> bool:
        return self._auto_toggle_edge

    @property
    def event_step_ns(self) -> float:
        return self._clock._event_step_ns

    @property
    def shared_clock(self) -> SharedEventClock:
        return self._clock

    def set_trigger_edge(self, edge_bit: int) -> None:
        self._edge_bit = edge_bit & 1

    def inject_100ms_marker(self) -> None:
        self._clock.inject_100ms_marker()

    def _append_event(self, words: list[int]) -> None:
        clock = self._clock
        if clock._pending_100ms_marker:
            clock.append_marker(words)
            return

        if clock.needs_coarse_wrap_marker():
            clock.emit_coarse_wrap_marker(words)
            return

        words.append(encode_word(self.channel, clock._next_ns, self._edge_bit))
        if self._auto_toggle_edge:
            self._edge_bit ^= 1
        clock.advance_after_event()

    def next_words(self, count: int = TIMESTAMPS_PER_PACKET) -> list[int]:
        if count < 1 or count > TIMESTAMPS_PER_PACKET:
            raise ValueError(f"count must be 1..{TIMESTAMPS_PER_PACKET}")

        words: list[int] = []
        while len(words) < TIMESTAMPS_PER_PACKET:
            self._append_event(words)

        return words


class ChannelTimestampState:
    """Legacy dual-stream helper used by non-timestamp body modes."""

    def __init__(self, base_ns: float, offset_ns: float = 0.0, step_ns: float = 100.0):
        self._ts1_ns = base_ns
        self._ts2_ns = base_ns + offset_ns
        self._step_ns = step_ns
        self._pending_100ms_marker = False

    @property
    def step_ns(self) -> float:
        return self._step_ns

    def inject_100ms_marker(self) -> None:
        self._pending_100ms_marker = True

    def next_words(self, channel: int, edge_bit: int = 0) -> tuple[int, int]:
        if self._pending_100ms_marker:
            self._ts1_ns += 100_000_000.0
            self._ts2_ns += 100_000_000.0
            self._pending_100ms_marker = False
            return MARKER_100MS, MARKER_100MS

        if channel in (0, 1):
            word1 = encode_timestamp_ch01(self._ts1_ns)
            word2 = encode_timestamp_ch01(self._ts2_ns)
        else:
            word1 = encode_timestamp_ch2(self._ts1_ns, edge_bit)
            word2 = encode_timestamp_ch2(self._ts2_ns, edge_bit)

        self._ts1_ns += self._step_ns
        self._ts2_ns += self._step_ns
        return word1, word2
