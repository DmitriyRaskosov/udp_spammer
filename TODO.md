# udp_lab_sim + odmr — plan and status

**Branch:** `home` in [odmr_test](https://github.com/DmitriyRaskosov/odmr_test) and udp_spammer.

---

## Architecture (production)

```
Windows  spammer  ──UDP 1066B──►  VM / stand
                                 packet_capture --analyze-stream
                                 → runs/.../pulses_grouped.txt
```

No `ch0_0.txt`, no `analyze.py` in production.

---

## Test matrix

| ID | Duration | Spammer (Windows) | Capture (VM) | ~Packets |
|----|----------|-------------------|--------------|----------|
| **T0** | ini-defined | `-CvOdmrProfile` | `run_stream.sh` | one sweep |
| **T1** | wall-clock stress | `-LongCvOdmr` | `run_soak.sh` | many sweeps |
| **T2** | 1 h | `-SoakOdmrPair -DurationSec 3600` | `run_soak.sh` SOAK=3600 | ~28M |
| **T3** | 10 h+ | same, longer | same | ~280M |

Rate: **~7843 packets/s** at 255 µs between ch0+ch2 pairs.

### Success criteria

```
enqueue failures: 0    kernel drops: 0
reorder late drops: 0  reorder gap skips: 0
bad pulse windows: 0
```

T0 also: `analyze groups: 36 (expected 36)`.

---

## Implementation phases

### P1 — odmr receiver soak (in progress)

- [x] `docs/LONG_EXPERIMENT.md`
- [x] `scripts/run_soak.sh` (`--soak`, `expected_groups=0`, log to `soak.log`)
- [x] `packet_capture --soak`
- [x] Periodic stats: pulses, groups, photon_peak, bad_win
- [ ] VM T2: 1 h `-SoakOdmrPair` joint test

### P2 — spammer long modes

- [x] `--duration SEC` for `--odmr-pair`
- [x] `--cv-odmr-loop` + `--duration` (repeat ini sweep; counter continuous across sweeps)
- [x] `spammer_odmr_compare.ps1`: `-SoakOdmrPair`, `-LongCvOdmr`, `-DurationSec`
- [ ] VM T1: 10 min `-LongCvOdmr` joint test

### P3 — lab / analyze hardening (later)

- [x] Production: one ini experiment, timing from t1..t5, capture auto-stop at expected_groups
- [ ] Frequency boundary marker in `analyze_stream`
- [ ] Optional shared ini duration estimate on VM startup log

---

## Commands cheat sheet

**T0 functional:**

```bash
# VM
bash scripts/run_stream.sh
```

```powershell
.\scripts\spammer_odmr_compare.ps1 -CvOdmrProfile -DstHost 192.168.1.9
```

**T1 — 10 min cv_odmr loop:**

```bash
SOAK_DURATION_SEC=600 RUN_LABEL=cv_odmr_10m bash scripts/run_soak.sh
```

```powershell
.\scripts\spammer_odmr_compare.ps1 -LongCvOdmr -DurationSec 600 -DstHost 192.168.1.9
```

**T1 smoke (1 / 3 / 5 min)** — same pair, match duration on both sides:

```bash
SOAK_DURATION_SEC=60 RUN_LABEL=cv_odmr_1m bash scripts/run_soak.sh
```

```powershell
.\scripts\spammer_odmr_compare.ps1 -LongCvOdmr -DurationSec 60 -DstHost 192.168.1.9
```

(`180` / `300` for 3 min / 5 min.) Success: `reorder late drops: 0`, `analyze groups` grows (~36 per sweep).

**T2 — 1 h dense soak:**

```bash
SOAK_DURATION_SEC=3600 RUN_LABEL=soak_1h bash scripts/run_soak.sh
```

```powershell
.\scripts\spammer_odmr_compare.ps1 -SoakOdmrPair -DurationSec 3600 -DstHost 192.168.1.9
```

---

## Done (T0)

- [x] Reorder: prime 0/1, gap skip on flush only, no MAX_GAP drops
- [x] Sparse padding fix in `parse_timestamps_raw`
- [x] `-CvOdmrProfile` end-to-end: 36/36 groups, 0 drops

---

## References

- odmr: `docs/LONG_EXPERIMENT.md`, `README.md`
- Protocol: `TECHNICAL.md`, `README.md`
