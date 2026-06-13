"""Encode and decode 32-bit channel timestamp words (ODMR UDP 21.04.2026)."""

from __future__ import annotations

MARKER_100MS = 0x00000000
ZERO_SHIFT_NS = 0.185
TIMESTAMPS_PER_PACKET = 255  # bytes 4..1023 of the 1024-byte payload
# Hardware coarse field is 26 bits; values wrap instead of growing past uint32.
COARSE_MASK = 0x3FFFFFF
WORD_MASK = 0xFFFFFFFF

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

    coarse = int(t_ns // 5) & COARSE_MASK
    remainder_ns = t_ns - int(t_ns // 5) * 5.0
    fine = _quantize_fine_ch01(remainder_ns)

    word = ((coarse << 6) | fine) & WORD_MASK
    if word == MARKER_100MS:
        return encode_timestamp_ch01(ZERO_SHIFT_NS)
    return word


def encode_timestamp_ch2(t_ns: float, edge_bit: int) -> int:
    """Encode timestamp for trigger channel 2 (bit 5 is the edge flag)."""
    if t_ns <= 0:
        t_ns = ZERO_SHIFT_NS

    coarse = int(t_ns // 5) & COARSE_MASK
    bit5 = edge_bit & 1
    fine = 0x1F if bit5 else 0x00

    word = ((coarse << 6) | (bit5 << 5) | fine) & WORD_MASK
    if word == MARKER_100MS:
        return encode_timestamp_ch2(ZERO_SHIFT_NS, edge_bit)
    return word


def encode_word(channel: int, t_ns: float, edge_bit: int = 0) -> int:
    if channel in (0, 1):
        return encode_timestamp_ch01(t_ns)
    return encode_timestamp_ch2(t_ns, edge_bit)


class TimestampPacketStream:
    """Monotonic per-channel event stream packed into 255 words per UDP payload."""

    def __init__(
        self,
        channel: int,
        base_ns: float = 1000.0,
        event_step_ns: float = 100.0,
        edge_bit: int = 0,
        auto_toggle_edge: bool = False,
    ):
        if channel not in (0, 1, 2):
            raise ValueError("Channel must be 0, 1, or 2")
        self.channel = channel
        self._next_ns = base_ns
        self._event_step_ns = event_step_ns
        self._edge_bit = edge_bit & 1
        self._auto_toggle_edge = auto_toggle_edge and channel == 2
        self._pending_100ms_marker = False

    @property
    def auto_toggle_edge(self) -> bool:
        return self._auto_toggle_edge

    @property
    def event_step_ns(self) -> float:
        return self._event_step_ns

    def set_trigger_edge(self, edge_bit: int) -> None:
        self._edge_bit = edge_bit & 1

    def inject_100ms_marker(self) -> None:
        self._pending_100ms_marker = True

    def next_words(self, count: int = TIMESTAMPS_PER_PACKET) -> list[int]:
        if count < 1 or count > TIMESTAMPS_PER_PACKET:
            raise ValueError(f"count must be 1..{TIMESTAMPS_PER_PACKET}")

        words: list[int] = []
        for _ in range(count):
            if self._pending_100ms_marker:
                words.append(MARKER_100MS)
                self._next_ns += 100_000_000.0
                self._pending_100ms_marker = False
                continue

            words.append(encode_word(self.channel, self._next_ns, self._edge_bit))
            if self._auto_toggle_edge:
                self._edge_bit ^= 1
            self._next_ns += self._event_step_ns

        while len(words) < TIMESTAMPS_PER_PACKET:
            words.append(encode_word(self.channel, self._next_ns, self._edge_bit))
            if self._auto_toggle_edge:
                self._edge_bit ^= 1
            self._next_ns += self._event_step_ns

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
