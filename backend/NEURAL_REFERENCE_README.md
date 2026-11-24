# CortexSignals software reference — Phase 1

Copy `neural_reference.py` and `test_neural_reference.py` into the existing `backend/` directory. No new dependencies are required.

## Run tests

From `backend/`:

```bash
python -m unittest -v test_neural_reference
python -m unittest discover -p 'test_*.py'
```

## Usage with the existing waveform and AD3 simulation

```python
from datasets import load_dataset
from waveforms import build_comparator_pattern
from neural_reference import generate_reference_events

source = load_dataset("separated")
thresholds_mv = {
    "P1": 5, "P2": 10, "P3": 20, "P4": 40,
    "N1": -5, "N2": -10, "N3": -20, "N4": -40,
}

# When you have a physical AD3 start response, use its *actual* sample count
# and sample_rate_hz, since the hardware divider may round the nominal rate.
playback_speed = 1.0
cycle_duration_ms = source["duration_ms"] / playback_speed
sample_count = 1024
pattern = build_comparator_pattern(
    source["amplitude_uv"], cycle_duration_ms, thresholds_mv,
    afe_gain=385.0, sample_count=sample_count, bias_v=1.6,
)
nominal_rate_hz = sample_count * 1000 / cycle_duration_ms
reference = generate_reference_events(
    pattern,
    sample_rate_hz=nominal_rate_hz,
    run_duration_ms=10_000,  # 10-second experiment
    packet_done_cycles=1,  # PLACEHOLDER! verify against packet sender RTL.
)
print(reference["event_count"])
print(reference["events"][:2])
print(reference["limitations"])
```

`events` have the same feature keys (`channel`, `timestamp_us`, `peak`, `trough`, `time_to_peak_us`, `flags_mask`, `flags`) as the UART decoder, plus reference-specific timing metadata and a synthetic `AA 02 ...` packet. **The synthetic `timestamp_us` has a local origin and must not be compared to FPGA absolute time until the clocks are aligned.**

## Actual RTL behavior implemented

- 50 MHz FPGA clock; 500 us quiet confirmation (25,000 clocks, plus the registered consumption edge).
- 2.5 ms event timeout; 100 us refractory after `packet_done`.
- Max active comparator threshold counts in `TRACK_EVENT` only; `QUIET_CONFIRMATION` does not update peak/trough.
- Dominant level chooses TTP; equal levels choose earliest maximum.
- Timeout, overlap, invalid-sequence, and saturation flags; 24-bit wrapped timestamp and 12-bit transmitted TTP.
- Continuous AD3 pattern repetition and optional post-stop low-signal drain.

## Important assumptions / missing RTL context

1. `packet_done_cycles=1` is only a **provisional simulation setting**. The true packet-generator/serial-transmit latency is unknown. This can affect observed event counts and refractory behavior.
2. FPGA comparator input synchronizer latency and starting clock phase are not known (`sync_latency_clocks=0` by default).
3. External `timeout_reached` and `refractory_done` are assumed inactive. The internal FSM timers are modeled.
4. `saturation_sync` is assumed low unless `saturation_words` is supplied.
5. Input is modeled as ideal digital comparators, not a physical calibrated AFE, DAC, hysteresis or propagation delays.
6. The model is independent of observed FPGA event packets; it does **not** calculate F1, time alignment, or validation PASS/FAIL in this phase.
7. The model only includes events whose assumed `packet_done` occurs before the end of the observation window. Set `drain_duration_ms` if FPGA collection continues after the AD3 outputs are stopped.

**Next step:** inspect the top-level module that connects `event_fsm.sv` to the UART packet sender and comparator synchronizers, then replace the placeholder packet acknowledgment and sync assumptions. After that, match these expected events against captured FPGA events.
