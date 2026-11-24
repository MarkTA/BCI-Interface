"""Waveform-derived isolation annotations for CortexSignals synthetic datasets.

This is an independent *source waveform* morphology check, not an FPGA
validation, analog calibration, or synchronized event correspondence check.
Annotations are never inferred from reported FPGA peak/trough levels.

Do not use these annotations for physical PCB measurements or as proof that
an FPGA event corresponds to a particular source spike.
"""
from __future__ import annotations

import csv
import io
import math
from typing import Any, Mapping, Sequence

ANNOTATOR_VERSION = '1.0.0'
# Enable only simple, known synthetic waveforms. Noisy, separated, or
# high-rate/ambiguous traces need explicit independent annotations.
SUPPORTED = frozenset({'positive_then_negative', 'negative_then_positive',
                       'small_spike', 'large_spike'})


def _read_source(data: bytes) -> tuple[list[float], list[float]]:
    reader = csv.DictReader(io.StringIO(data.decode('utf-8-sig')))
    if not reader.fieldnames or 'amplitude' not in reader.fieldnames or 'time' not in reader.fieldnames:
        raise ValueError('Ground-truth annotation requires time,amplitude CSV columns')
    times, amplitude = [], []
    for row in reader:
        times.append(float(row['time']))
        amplitude.append(float(row['amplitude']))
    if len(times) < 3 or not all(math.isfinite(x) for x in times + amplitude):
        raise ValueError('Insufficient or nonfinite waveform samples')
    if any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError('Source timestamps must increase')
    return times, amplitude


def infer_isolated_reference_indices(
    csv_bytes: bytes,
    dataset_name: str,
    reference_events: Sequence[Mapping[str, Any]],
    *,
    source_duration_ms: float,
    digital_cycle_duration_us: float,
    min_quiet_us: float = 500.0,
    merge_gap_us: float = 200.0,
) -> dict[str, Any]:
    """Find one distinct, quiet-separated spike per synthetic waveform cycle.

    Segmentation uses original CSV amplitudes only, with activity defined as
    >=1% of the source waveform peak. Any uncertain topology is rejected.
    Every expected event must lie inside a source spike interval (allowing a
    small quantization margin). Relative phase uses the *recorded* AD3 period.
    """
    response: dict[str, Any] = {
        'version': ANNOTATOR_VERSION, 'source': 'original_csv_morphology',
        'dataset': dataset_name, 'status': 'unavailable', 'reason': '',
        'isolated_reference_indices': [], 'per_cycle_spikes': None,
        'independent_of_fpga_packets': True,
        'hardware_acceptance_evidence': False,
    }
    if dataset_name not in SUPPORTED:
        response['reason'] = 'This waveform is not a vetted simple synthetic template.'
        return response
    if not (math.isfinite(source_duration_ms) and source_duration_ms > 0
            and math.isfinite(digital_cycle_duration_us) and digital_cycle_duration_us > 0):
        response['reason'] = 'Missing source or AD3 playback period.'
        return response
    try:
        times, amplitudes = _read_source(csv_bytes)
    except (ValueError, KeyError, UnicodeError, OverflowError) as exc:
        response['reason'] = f'Cannot independently segment waveform: {exc}'
        return response
    peak = max(abs(v) for v in amplitudes)
    if peak <= 0:
        response['reason'] = 'The source waveform contains no spike.'
        return response
    # Original generated dataset timestamps are in milliseconds.
    dt_us = source_duration_ms * 1000.0 / len(times)
    activity_floor = peak * 0.01
    active = [i for i, v in enumerate(amplitudes) if abs(v) >= activity_floor]
    if not active:
        response['reason'] = 'No source activity above the noise floor.'
        return response
    regions: list[list[int]] = []
    for index in active:
        if not regions or (index - regions[-1][-1]) * dt_us > merge_gap_us:
            regions.append([index])
        else:
            regions[-1].append(index)
    if len(regions) != 1:
        response['reason'] = f'Expected one isolated source spike per cycle; found {len(regions)} regions.'
        response['per_cycle_spikes'] = len(regions)
        return response
    first, last = regions[0][0] * dt_us, regions[0][-1] * dt_us
    period_source = source_duration_ms * 1000.0
    # Include the gap between the end of the current spike and the next cycle.
    quiet_before = first + (period_source - last)
    if quiet_before < min_quiet_us or first < min_quiet_us / 2 or period_source - last < min_quiet_us / 2:
        response['reason'] = 'Spike is too close to the cycle boundary or lacks a quiet interval.'
        return response
    # The reference is indexed by onset in the *digitally repeated* pattern.
    # Timestamps can be integer-microsecond quantized. Permit one AD3 sample
    # and modest edge discretization, but do not label a different phase.
    margin = max(2 * digital_cycle_duration_us / 1024.0, 15.0)
    indices = []
    for index, event in enumerate(reference_events):
        onset = event.get('relative_onset_us')
        if not isinstance(onset, (int, float)) or not math.isfinite(onset):
            response['reason'] = 'Reference events missing unwrapped onset timing.'
            return response
        phase = float(onset) % digital_cycle_duration_us
        # Check source-relative phase: playback may slightly alter the period.
        source_phase = phase / digital_cycle_duration_us * period_source
        if not first - margin <= source_phase <= last + margin:
            response['reason'] = 'Reference event falls outside the independently located source spike.'
            return response
        if event.get('flags_mask', 0) != 0:
            response['reason'] = 'Reference event has a timeout/overlap/invalid flag.'
            return response
        indices.append(index)
    response.update({
        'status': 'labeled', 'reason': 'Isolated source spike located independently in the original CSV; event correspondence remains exploratory without hardware sync.',
        'isolated_reference_indices': indices, 'per_cycle_spikes': 1,
        'activity_start_us': first, 'activity_end_us': last,
        'quiet_between_cycles_us': quiet_before,
        'activity_threshold_source_units': activity_floor,
    })
    return response
